"""End-to-end run: screenplay folder/zip -> ranked, checked promo list.

  1 parse      screenplay -> timestamped beats                          (code)
  2 generate   every legal 20-60s window + montage shapes, rule-scored  (code, ~2s for 50 episodes)
  3 shortlist  best per episode + best overall                          (code)
  4 judge      LLM scores the shortlist, may trim, writes the "why"     (model, optional)
  5 QC         hard rules + warnings                                    (code)
  6 rank       "post first" list: diverse, early-funnel, QC-clean       (code)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .parse import load_show, sec_to_ts
from .candidates import generate, score_promo, nms, overlap, _seg, Promo, MIN_LEN, MAX_LEN, speaker_label
from .llm import Model, build_judge_prompt, parse_json, validate_judgement, LLMError, PROMPT_VERSION
from .qc import run_qc


def heuristic_why(p: Promo) -> str:
    hook_r = next((r.split(": ", 1)[1] for r in p.reasons if r.startswith("hook:") and "no line" not in r), "")
    cliff_r = next((r.split(": ", 1)[1] for r in p.reasons if r.startswith("cliff:") and "trails" not in r), "")
    stand = "relationships are spelled out, so a cold viewer can follow" if any("relationships are named" in r for r in p.reasons) \
        else "a cold viewer may need a beat to place the characters"
    shape = {"single": "", "flash_forward": "Shows the peak first, then rewinds to how it happened. ",
             "bridge": "Carries one episode's cliffhanger into the next. ",
             "premise": "Sells the whole premise: the setup, then the twist the title promises. "}[p.kind]
    return f"{shape}Opens strong ({hook_r or 'early conflict'}) and cuts on an open question ({cliff_r or 'unresolved beat'}); {stand}."


def shortlist(promos: list[Promo], n: int) -> list[Promo]:
    by_ep: dict[int, list[Promo]] = {}
    for p in promos:
        by_ep.setdefault(p.segments[0].episode, []).append(p)
    picked = [max(v, key=lambda p: p.heuristic_score) for v in by_ep.values()]
    rest = sorted((p for p in promos if p not in picked), key=lambda p: -p.heuristic_score)
    picked += rest[: max(0, n - len(picked))]
    return sorted(picked, key=lambda p: -p.heuristic_score)[:max(n, 1)]


def _apply_trim(p: Promo, j: dict, idx) -> str | None:
    if len(p.segments) != 1 or not (j.get("suggested_start_beat") or j.get("suggested_end_beat")):
        return None
    sg = p.segments[0]
    ix = idx[sg.episode]
    s, e = sg.start, sg.end
    if j.get("suggested_start_beat") in ix.by_id:
        t = ix.by_id[j["suggested_start_beat"]].start
        s = max((x for x in ix.starts if x <= t + 1e-6), default=s)
    if j.get("suggested_end_beat") in ix.by_id:
        t = ix.by_id[j["suggested_end_beat"]].end
        e = min((x for x in ix.ends if x >= t - 1e-6), default=e)
    if (s, e) == (sg.start, sg.end):
        return None
    if not (MIN_LEN <= e - s <= MAX_LEN):
        return f"model trim rejected: would be {e - s:.1f}s"
    old = f"{sec_to_ts(sg.start)}-{sec_to_ts(sg.end)}"
    p.segments = [_seg(ix, s, e)]
    score_promo(p, {sg.episode: ix})
    return f"model trimmed {old} -> {sec_to_ts(s)}-{sec_to_ts(e)}"


def judge(promos: list[Promo], idx, title: str, model: Model, llm_weight: float, export_dir: Path | None, log) -> dict:
    stats = {"judged": 0, "rejected_fields": 0, "errors": 0, "trims": 0, "exported": 0}
    for i, p in enumerate(promos, 1):
        prompt, allowed = build_judge_prompt(p, idx, title)
        if export_dir is not None:
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / f"{model.key(prompt)}.txt").write_text(prompt, encoding="utf-8")
            stats["exported"] += 1
            continue
        try:
            raw = parse_json(model.complete(prompt))
        except (LLMError, json.JSONDecodeError) as e:
            stats["errors"] += 1
            p.llm = {"error": str(e)[:200]}
            log(f"  [{i}/{len(promos)}] {p.id} model error: {str(e)[:120]}")
            continue
        clean, rejected = validate_judgement(raw, p, allowed)
        stats["rejected_fields"] += len(rejected)
        clean["rejected"] = rejected
        p.llm = clean
        note = _apply_trim(p, clean, idx)
        if note:
            p.llm["trim"] = note
            stats["trims"] += "rejected" not in note
        if "overall" in clean:
            stats["judged"] += 1
            p.final_score = round((1 - llm_weight) * p.heuristic_score + llm_weight * clean["overall"] / 10, 4)
            if clean.get("why"):
                p.why = clean["why"]
            # the model's hook/cliff pick replaces the rules' pick only when it passed validation AND still
            # sits where it should in the (possibly trimmed) clip: hook in the first 3s, cliff in the last 6s
            first, last = p.segments[0], p.segments[-1]
            for side, attr in (("hook", "hook"), ("cliff", "cliffhanger")):
                if f"{side}_beat" in clean:
                    b = next(ix.by_id[clean[f"{side}_beat"]] for ix in idx.values() if clean[f"{side}_beat"] in ix.by_id)
                    sg = first if side == "hook" else last
                    placed = b.episode == sg.episode and (
                        sg.start - 0.01 <= b.start <= sg.start + 3.0 if side == "hook" else sg.end - 6.0 <= b.end <= sg.end + 0.3)
                    if not placed:
                        p.llm.setdefault("ignored", []).append(f"{side} beat {b.id} not at the {'start' if side == 'hook' else 'end'} of the final cut")
                        continue
                    setattr(p, attr, f'{speaker_label(b.speaker)}: "{b.text}"' if b.kind == "dialogue" else f"[{b.kind}] {b.text}")
                    setattr(p, f"{side}_beat", b.id)
        log(f"  [{i}/{len(promos)}] {p.id} overall={clean.get('overall')} rejected={len(rejected)}")
    return stats


def funnel_factor(p: Promo, n_eps: int) -> float:
    """Viewers who tap a promo start at episode 1. Earlier promos pay off sooner and spoil less."""
    e = min(p.episodes)
    return 1.0 + 0.12 * max(0.0, 1 - (e - 1) / max(1, 0.6 * n_eps))


def post_first(promos: list[Promo], n_eps: int, k: int = 10) -> list[Promo]:
    pool = [p for p in promos if p.qc.get("status") != "FAIL"]
    judged = any(p.llm.get("overall") is not None for p in pool)
    if judged:
        pool = [p for p in pool if p.llm.get("overall") is not None]
    pool.sort(key=lambda p: -(p.final_score * funnel_factor(p, n_eps) * (0.93 if p.qc["status"] == "REVIEW" else 1.0)))
    out, used_eps = [], set()
    for p in pool:
        if any(overlap(p, q) > 0.2 for q in out):
            continue
        if used_eps & set(p.episodes):
            continue
        out.append(p)
        used_eps |= set(p.episodes)
        if len(out) == k:
            break
    return out


def run(input_path: str, out_dir: str = "outputs", model_spec: str = "none", shortlist_n: int = 60,
        per_episode: int = 3, llm_weight: float = 0.6, rpm: float = 0, export_prompts: bool = False,
        cache_dir: str = ".cache/llm", log=print, api_key: str | None = None, base_url: str | None = None) -> dict:
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    title, eps = load_show(input_path)
    log(f"Loaded '{title}': {len(eps)} episodes, {sum(len(e.beats) for e in eps)} beats")
    promos, idx = generate(title, eps, per_episode=per_episode)
    log(f"Generated {len(promos)} candidate promos (rules) in {time.time() - t0:.1f}s")
    for p in promos:
        p.final_score = p.heuristic_score
        p.why = heuristic_why(p)

    model = Model(model_spec, cache_dir=cache_dir, rpm=rpm, api_key=api_key, base_url=base_url)
    llm_stats = {}
    sl = shortlist(promos, shortlist_n)
    if model.enabled or export_prompts:
        log(f"Judging shortlist of {len(sl)} with {model.spec}" if not export_prompts else f"Exporting {len(sl)} judge prompts")
        llm_stats = judge(sl, idx, title, model, llm_weight, out / "prompts" if export_prompts else None, log)
        for p in sl:
            if p.llm.get("overall") is None and "error" not in p.llm:
                p.why = heuristic_why(p)
    run_qc(promos, idx)
    picks = post_first(promos, len(eps))
    for r, p in enumerate(picks, 1):
        p.rank = r
    meta = {
        "show": title, "episodes": len(eps), "beats": sum(len(e.beats) for e in eps),
        "candidates": len(promos), "shortlist": len(sl), "model": model.spec, "prompt_version": PROMPT_VERSION,
        "llm_weight": llm_weight if model.enabled else 0, "llm_stats": llm_stats,
        "llm_calls": model.calls, "llm_cache_hits": model.cache_hits,
        "tokens_in": model.tokens_in, "tokens_out": model.tokens_out,
        "qc": {s: sum(1 for p in promos if p.qc["status"] == s) for s in ("PASS", "REVIEW", "FAIL")},
        "seconds": round(time.time() - t0, 1), "input": str(input_path),
    }
    from .render import write_all
    write_all(out, title, eps, idx, promos, picks, meta)
    log(f"Done in {meta['seconds']}s -> {out.resolve()}")
    return {"title": title, "promos": promos, "picks": picks, "meta": meta, "idx": idx}
