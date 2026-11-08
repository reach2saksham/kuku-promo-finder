"""Automatic quality checks (stage 3). Each promo gets PASS / REVIEW / FAIL plus flags.

FAIL   breaks a hard rule from the brief (length, cutting mid-line, bad timestamps), so it's never shown as a pick
REVIEW something an editor should look at before posting
PASS   nothing found (which is not the same as "good" - see the human spot-check in the report)
"""
from __future__ import annotations

import re
from .candidates import Promo, EpisodeIndex, MIN_LEN, MAX_LEN
from .features import RESOLUTION, CONTEXT_DEPENDENT_OPENERS


def _all_speakers(idx: dict[int, EpisodeIndex]) -> set[str]:
    """Proper names of speaking characters. A word that also shows up in lower case anywhere in the
    scripts ("mother", "duchess", "guard") is a role, not a name, so it is dropped."""
    lower_words = set()
    for ix in idx.values():
        for b in ix.beats:
            lower_words.update(re.findall(r"(?<![A-Za-z])[a-z]{4,}(?![A-Za-z])", b.text))
    names = set()
    for ix in idx.values():
        for l in ix.lines:
            for part in re.split(r"[\s']+", l.speaker):
                if len(part) > 3 and part.isalpha() and part.lower() not in lower_words:
                    names.add(part.title())
    return names


def check(p: Promo, idx: dict[int, EpisodeIndex], n_episodes: int, known_names: set[str]) -> dict:
    hard, warn, info = [], [], []
    # --- hard rules ------------------------------------------------------------------------
    if not (MIN_LEN - 0.01 <= p.duration <= MAX_LEN + 0.01):
        hard.append(f"length {p.duration:.1f}s is outside 20-60s")
    for sg in p.segments:
        ix = idx.get(sg.episode)
        if ix is None or sg.start < 0 or sg.end > ix.ep.duration + 0.01 or sg.end <= sg.start:
            hard.append(f"segment E{sg.episode} {sg.start}-{sg.end} is not inside the episode")
            continue
        if ix._inside_line(sg.start):
            hard.append(f"E{sg.episode} starts in the middle of a spoken line")
        if ix._inside_line(sg.end):
            hard.append(f"E{sg.episode} ends in the middle of a spoken line")
    if p.llm.get("overall") is not None and p.llm["overall"] <= 3:
        hard.append(f"model judged it unusable ({p.llm['overall']:.0f}/10)")
    if hard:
        return {"status": "FAIL", "flags": hard + warn + info}

    first, last = p.segments[0], p.segments[-1]
    i0, i1 = idx[first.episode], idx[last.episode]
    lines = [l for sg in p.segments for l in idx[sg.episode].lines_in(sg.start, sg.end)]
    beats = [b for sg in p.segments for b in idx[sg.episode].beats_in(sg.start, sg.end)]

    # --- hook ------------------------------------------------------------------------------
    if p.scores.get("hook", 0) < 0.45:
        warn.append("weak hook: nothing strong in the first 3 seconds")
    first_content = next((b for b in beats if b.kind != "camera"), None)
    if first_content and first_content.start - first.start > 2.0:
        warn.append(f"{first_content.start - first.start:.1f}s before anything is said or happens")
    if lines and CONTEXT_DEPENDENT_OPENERS.match(lines[0].text):
        warn.append(f'first line opens mid-thought: "{lines[0].text[:40]}"')

    # --- cliffhanger -----------------------------------------------------------------------
    tail = [b for b in i1.beats_in(max(last.start, last.end - 5), last.end)]
    for b in tail:
        for pat in RESOLUTION:
            if re.search(pat, b.text.lower()):
                warn.append(f'ending may feel resolved ("{b.text[:45]}")')
                break
    if p.scores.get("cliffhanger", 0) < 0.45:
        warn.append("weak cliffhanger: the cut point does not leave a clear open question")
    cliff_b = i1.by_id.get(p.cliff_beat) if p.cliff_beat else None
    if cliff_b is not None and cliff_b.kind == "camera":
        info.append("cliffhanger is visual only - confirm it reads in the actual footage")

    # --- standalone ------------------------------------------------------------------------
    present = {w.title() for l in lines for w in l.speaker.split()}
    shown_text = " ".join(b.text for b in beats if b.kind != "dialogue")
    for name in sorted(known_names):
        said = any(re.search(rf"\b{name}\b", l.text) for l in lines)
        if said and name not in present and not re.search(rf"\b{name}\b", shown_text):
            warn.append(f"mentions {name}, who never appears in the clip")
    speakers = {l.speaker for l in lines}
    if len(speakers) > 4:
        warn.append(f"{len(speakers)} different speakers in under a minute")
    if not lines:
        warn.append("no dialogue at all")
    for pr in p.llm.get("problems", []):
        if re.search(r"confus|context|unclear|hard to follow|doesn.t make sense|who is", pr, re.I):
            warn.append(f"model: {pr}")
            break

    # --- placement / funnel ----------------------------------------------------------------
    late = max(p.episodes) / max(1, n_episodes)
    if n_episodes >= 5 and late >= 0.7:
        info.append(f"from episode {max(p.episodes)} of {n_episodes}: may spoil later arcs; viewer reaches it only after a long run")
    if len(p.segments) > 1:
        info.append(f"{len(p.segments)} segments - needs an editor to join cuts")

    status = "REVIEW" if warn else "PASS"
    return {"status": status, "flags": warn + info}


def run_qc(promos: list[Promo], idx: dict[int, EpisodeIndex]) -> None:
    names = _all_speakers(idx)
    n = max(idx) if idx else 1
    for p in promos:
        p.qc = check(p, idx, n, names)
