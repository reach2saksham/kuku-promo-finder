"""Write the outputs an editor / marketer actually uses."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .parse import sec_to_ts
from .candidates import speaker_label


def transcript(p, idx) -> list[str]:
    out = []
    for n, sg in enumerate(p.segments):
        if n:
            out.append("--- CUT ---")
        for b in idx[sg.episode].beats_in(sg.start, sg.end):
            who = speaker_label(b.speaker) + (f" ({b.delivery})" if b.delivery else "") if b.kind == "dialogue" else b.kind.upper()
            out.append(f"E{sg.episode:02d} {sec_to_ts(b.start)} {who}: {b.text}")
    return out


def seg_str(p) -> str:
    return " + ".join(f"E{s.episode} {sec_to_ts(s.start)}-{sec_to_ts(s.end)}" for s in p.segments)


def write_all(out: Path, title, eps, idx, promos, picks, meta):
    ordered = sorted(promos, key=lambda p: (p.rank == 0, p.rank, -p.final_score))
    # JSON: everything, for other tools
    data = {"meta": meta, "post_first": [p.id for p in picks],
            "promos": [{**p.to_dict(), "transcript": transcript(p, idx)} for p in ordered]}
    (out / "promos.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # CSV: one row per promo, one column per segment field - opens in Sheets for an editor
    with open(out / "promos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["post_first_rank", "id", "shape", "episodes", "segments", "duration_s",
                    "seg1_episode", "seg1_start", "seg1_end", "seg2_episode", "seg2_start", "seg2_end",
                    "hook", "cliffhanger", "why_it_works", "final_score", "rules_score", "model_overall",
                    "hook_s", "cliff_s", "standalone_s", "qc_status", "qc_flags"])
        for p in ordered:
            s = p.segments
            g = lambda i, a: (getattr(s[i], a) if i < len(s) else "")
            w.writerow([p.rank or "", p.id, p.kind, ",".join(map(str, p.episodes)), seg_str(p), round(p.duration, 1),
                        g(0, "episode"), sec_to_ts(s[0].start), sec_to_ts(s[0].end),
                        g(1, "episode"), sec_to_ts(s[1].start) if len(s) > 1 else "", sec_to_ts(s[1].end) if len(s) > 1 else "",
                        p.hook, p.cliffhanger, p.why, p.final_score, p.heuristic_score, p.llm.get("overall", ""),
                        p.scores.get("hook"), p.scores.get("cliffhanger"), p.scores.get("standalone"),
                        p.qc.get("status"), " | ".join(p.qc.get("flags", []))])

    # Markdown report
    L = [f"# Promo picks - {title}", "",
         f"{meta['episodes']} episodes, {meta['beats']} script beats -> {meta['candidates']} candidate promos. "
         f"Model: `{meta['model']}`. QC: {meta['qc']['PASS']} pass / {meta['qc']['REVIEW']} review / {meta['qc']['FAIL']} fail. "
         f"Run time {meta['seconds']}s.", "",
         "## Post these first", "",
         "Ranked by score, nudged toward early episodes (a viewer who taps lands on episode 1, so early promos pay off sooner and spoil less), "
         "one promo per episode so the feed doesn't repeat itself.", ""]
    for p in picks:
        L += [f"### {p.rank}. {p.id} - {seg_str(p)} ({p.duration:.0f}s, {p.kind})",
              f"- **Hook:** {p.hook}", f"- **Cliffhanger:** {p.cliffhanger}", f"- **Why it works:** {p.why}",
              f"- **Scores:** final {p.final_score:.2f} (rules {p.heuristic_score:.2f}"
              + (f", model {p.llm['overall']:.0f}/10" if p.llm.get("overall") is not None else "") + f") - QC **{p.qc['status']}**"
              + (": " + "; ".join(p.qc["flags"]) if p.qc["flags"] else ""), ""]
        if p.llm.get("trim"):
            L.append(f"- _{p.llm['trim']}_\n")
    L += ["## All promos by episode", "", "| Ep | ID | Shape | Segments | Len | Hook | Cliffhanger | Score | QC |", "|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(promos, key=lambda p: (p.segments[0].episode, -p.final_score)):
        cut = lambda s: s.replace("|", "/")[:70]
        L.append(f"| {p.segments[0].episode} | {p.id} | {p.kind} | {seg_str(p)} | {p.duration:.0f}s | {cut(p.hook)} | {cut(p.cliffhanger)} | {p.final_score:.2f} | {p.qc['status']} |")
    covered = {e for p in promos for e in p.episodes}
    missing = [e.number for e in eps if e.number not in covered]
    L += ["", f"Episodes with no promo: {missing or 'none'}"]
    (out / "report.md").write_text("\n".join(L), encoding="utf-8")

    # QC report
    from collections import Counter
    flags = Counter()
    for p in promos:
        for f_ in p.qc["flags"]:
            flags[f_.split(":")[0].split("(")[0].split('"')[0].strip()[:60]] += 1
    Q = ["# Automatic QC", "", f"PASS {meta['qc']['PASS']} / REVIEW {meta['qc']['REVIEW']} / FAIL {meta['qc']['FAIL']} of {len(promos)}", "",
         "## Most common flags", ""] + [f"- {n} x {f_}" for f_, n in flags.most_common(20)]
    if meta.get("llm_stats"):
        Q += ["", "## Model layer", "", f"```\n{json.dumps(meta['llm_stats'], indent=2)}\n```",
              "", "Rejected model fields (cited a beat or quote that is not in the script):", ""]
        for p in promos:
            if p.llm.get("rejected"):
                Q.append(f"- {p.id}: {', '.join(p.llm['rejected'])}")
    Q += ["", "## FAIL", ""] + [f"- {p.id} {seg_str(p)}: {'; '.join(p.qc['flags'])}" for p in promos if p.qc["status"] == "FAIL"]
    (out / "qc_report.md").write_text("\n".join(Q), encoding="utf-8")

    # HTML viewer: self-contained, no server needed
    def card(p):
        tr = "".join(f"<div class='{'cut' if t.startswith('---') else 'ln'}'>{html.escape(t)}</div>" for t in transcript(p, idx))
        flags = "".join(f"<li>{html.escape(f_)}</li>" for f_ in p.qc["flags"])
        model = f" &middot; model {p.llm['overall']:.0f}/10" if p.llm.get("overall") is not None else ""
        return (f"<details class='c {p.qc['status']}' {'open' if p.rank and p.rank <= 3 else ''}><summary>"
                f"<b>{'#' + str(p.rank) + ' ' if p.rank else ''}{p.id}</b> <span class='k'>{p.kind}</span> {html.escape(seg_str(p))} "
                f"<span class='d'>{p.duration:.0f}s &middot; score {p.final_score:.2f}{model}</span> <span class='q'>{p.qc['status']}</span></summary>"
                f"<p><b>Hook:</b> {html.escape(p.hook)}</p><p><b>Cliffhanger:</b> {html.escape(p.cliffhanger)}</p>"
                f"<p><b>Why:</b> {html.escape(p.why)}</p>{'<ul>' + flags + '</ul>' if flags else ''}"
                f"<div class='tr'>{tr}</div></details>")
    picks_html = "".join(card(p) for p in picks)
    rest_html = "".join(card(p) for p in sorted(promos, key=lambda p: (p.segments[0].episode, -p.final_score)) if not p.rank)
    H = f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>Promos - {html.escape(title)}</title>
<style>body{{font:14px/1.45 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1b1b1f}}
h1{{font-size:22px}} .m{{color:#555}} details.c{{border:1px solid #ddd;border-radius:8px;margin:8px 0;padding:8px 12px}}
summary{{cursor:pointer}} .k{{background:#eef;padding:1px 6px;border-radius:4px;font-size:12px}} .d{{color:#666}}
.q{{float:right;font-size:12px;font-weight:600}} .PASS .q{{color:#17803d}} .REVIEW .q{{color:#b26b00}} .FAIL .q{{color:#b3261e}}
.tr{{font:12px/1.4 ui-monospace,monospace;background:#fafafa;border-radius:6px;padding:8px;max-height:340px;overflow:auto}}
.cut{{color:#b3261e;margin:4px 0}} ul{{color:#8a5a00;margin:4px 0}}</style></head><body>
<h1>Promo picks &mdash; {html.escape(title)}</h1>
<p class='m'>{meta['episodes']} episodes &middot; {meta['candidates']} candidates &middot; model <code>{html.escape(meta['model'])}</code> &middot;
QC {meta['qc']['PASS']} pass / {meta['qc']['REVIEW']} review / {meta['qc']['FAIL']} fail</p>
<h2>Post these first</h2>{picks_html}<h2>All other candidates (by episode)</h2>{rest_html}</body></html>"""
    (out / "report.html").write_text(H, encoding="utf-8")
