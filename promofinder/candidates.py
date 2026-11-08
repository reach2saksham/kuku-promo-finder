"""Generate and score promo candidates with rules only (stage 1, free, deterministic).

Three shapes:
  single         one continuous 20-60s stretch of one episode
  flash_forward  the episode's peak moment first (2-6s), then the build-up that leads to it
  premise        a setup from the first episodes + the title's promised twist from later on
  bridge         an episode's final cliffhanger + the next episode's opening, cut before it resolves
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from .parse import Beat, Episode, sec_to_ts
from .features import (beat_hook, beat_cliff, delivery_heat, CONTEXT_DEPENDENT_OPENERS, PAST_REFS, RELATION_WORDS)

MIN_LEN, MAX_LEN = 20.0, 60.0
HOOK_WINDOW = 3.0


@dataclass
class Segment:
    episode: int
    start: float
    end: float
    first_beat: str
    last_beat: str

    def to_dict(self):
        d = asdict(self)
        d["start_ts"], d["end_ts"] = sec_to_ts(self.start), sec_to_ts(self.end)
        d["duration"] = round(self.end - self.start, 2)
        return d


@dataclass
class Promo:
    id: str
    kind: str
    segments: list[Segment]
    hook: str = ""
    hook_beat: str = ""
    cliffhanger: str = ""
    cliff_beat: str = ""
    why: str = ""
    scores: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    heuristic_score: float = 0.0
    llm: dict = field(default_factory=dict)
    final_score: float = 0.0
    qc: dict = field(default_factory=dict)
    rank: int = 0

    @property
    def duration(self) -> float:
        return sum(s.end - s.start for s in self.segments)

    @property
    def episodes(self) -> list[int]:
        out = []
        for s in self.segments:
            if s.episode not in out:
                out.append(s.episode)
        return out

    def to_dict(self):
        d = asdict(self)
        d["segments"] = [s.to_dict() for s in self.segments]
        d["duration"] = round(self.duration, 2)
        d["episodes"] = self.episodes
        return d


# ----------------------------------------------------------------------------------------
class EpisodeIndex:
    """Pre-computes per-beat scores and legal cut points for one episode."""

    def __init__(self, ep: Episode):
        self.ep = ep
        self.beats = ep.beats
        self.hook = {b.id: beat_hook(b) for b in self.beats}
        self.cliff = {b.id: beat_cliff(b) for b in self.beats}
        self.lines = [b for b in self.beats if b.kind == "dialogue"]
        self.by_id = {b.id: b for b in self.beats}
        # Legal cut points: never cut in the middle of a spoken line.
        self.starts = sorted({b.start for b in self.beats if not self._inside_line(b.start)})
        self.ends = sorted({b.end for b in self.beats if not self._inside_line(b.end)} | {ep.duration})

    def _inside_line(self, t: float) -> bool:
        return any(l.start + 0.05 < t < l.end - 0.05 for l in self.lines)

    def beats_in(self, s: float, e: float) -> list[Beat]:
        return [b for b in self.beats if b.start >= s - 1e-6 and b.end <= e + 0.3]

    # --- component scores ----------------------------------------------------------------
    def hook_at(self, s: float) -> tuple[float, Beat | None, list[str]]:
        best, bb, why = 0.0, None, []
        for b in self.beats:
            if s - 1e-6 <= b.start <= s + HOOK_WINDOW:
                sc, r = self.hook[b.id]
                lag = b.start - s
                if lag > 1.5:   # a line that only starts at 2.9s barely lands inside the 3s window
                    sc *= 1 - 0.4 * (lag - 1.5) / 1.5
                if sc > best:
                    best, bb, why = sc, b, r
        # dead air: nothing said in the first 3 seconds
        first_line = next((l for l in self.lines if l.start >= s - 1e-6), None)
        if first_line is None or first_line.start > s + HOOK_WINDOW:
            best *= 0.75
            why = why + ["no line in first 3s"]
        return best, bb, why

    def cliff_at(self, e: float) -> tuple[float, Beat | None, list[str]]:
        tail = [b for b in self.beats if e - 4.0 <= b.end <= e + 0.3]
        best, bb, why = 0.0, None, []
        last_line = next((l for l in reversed(self.lines) if l.end <= e + 0.3), None)
        for b in tail:
            sc, r = self.cliff[b.id]
            if b is last_line:
                sc *= 1.15
            # the last thing seen/heard before the cut matters most: a strong line followed by
            # 4s of silent footage is a weaker cut than ending right on it
            sc *= max(0.6, 1 - 0.1 * max(0.0, e - b.end))
            if sc > best:
                best, bb, why = sc, b, r
        if last_line is not None and (bb is None or bb.kind != "dialogue") and last_line.end >= e - 6:
            # report the last spoken line as the cliffhanger text even if a visual carried the score
            ls, lr = self.cliff[last_line.id]
            if ls >= best * 0.6:
                bb = last_line
        if e >= self.ep.duration - 1.0:
            best += 0.25
            why = why + ["episode's own cliffhanger ending"]
        # anything after the cut that resolves the tension makes the cut stronger if it's left out,
        # but if the window ends long after the last line it trails off
        if last_line is not None and e - last_line.end > 7:
            best -= 0.15
            why = why + ["trails off after last line"]
        return max(0.0, min(1.0, best)), bb, why

    def lines_in(self, s: float, e: float):
        return [l for l in self.lines if s - 1e-6 <= l.start and l.end <= e + 0.3]

    def energy(self, s: float, e: float) -> tuple[float, float]:
        """(dialogue coverage 0..1, mean delivery heat 0..1)"""
        lines = [l for l in self.lines if s - 1e-6 <= l.start and l.end <= e + 0.3]
        if not lines or e <= s:
            return 0.0, 0.0
        covered, cur_s, cur_e = 0.0, None, None
        for l in sorted(lines, key=lambda x: x.start):
            if cur_e is None or l.start > cur_e:
                if cur_e is not None:
                    covered += cur_e - cur_s
                cur_s, cur_e = l.start, l.end
            else:
                cur_e = max(cur_e, l.end)
        covered += cur_e - cur_s
        heat = sum(delivery_heat(l)[0] for l in lines) / len(lines)
        return min(1.0, covered / (e - s) / 0.6), heat


def standalone(lines: list[Beat], first_start: float) -> tuple[float, list[str]]:
    """Can a stranger follow these lines (all segments, in play order)?"""
    sc, why = 0.8, []
    if not lines:
        return 0.2, ["no dialogue"]
    if CONTEXT_DEPENDENT_OPENERS.match(lines[0].text):
        sc -= 0.25
        why.append(f'opens mid-thought ("{lines[0].text[:30]}")')
    early = lines[:4]
    pr = sum(1 for l in early if PAST_REFS.search(l.text))
    if pr:
        sc -= min(0.3, 0.12 * pr)
        why.append("leans on earlier events")
    if any(RELATION_WORDS.search(l.text) for l in lines):
        sc += 0.12
        why.append("relationships are named on screen")
    speakers = {re.sub(r"^(LADY|LORD|THE|SIR)\s+", "", l.speaker) for l in lines}
    if len(speakers) > 4:
        sc -= 0.15
        why.append(f"{len(speakers)} speakers - hard to follow")
    if len(speakers) == 1:
        sc -= 0.1
        why.append("monologue")
    return max(0.0, min(1.0, sc)), why


def _length_factor(d: float) -> float:
    if 25 <= d <= 45:
        return 1.0
    if 20 <= d <= 60:
        return 0.94
    return 0.0


def combine(hook: float, cliff: float, stand: float, cover: float, heat: float, dur: float) -> float:
    base = 0.32 * hook + 0.32 * cliff + 0.20 * stand + 0.16 * (0.6 * cover + 0.4 * heat)
    return round(base * _length_factor(dur), 4)


def speaker_label(name: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in name.split())


def _beat_label(b: Beat | None) -> str:
    if b is None:
        return ""
    if b.kind == "dialogue":
        return f'{speaker_label(b.speaker)}: "{b.text}"'
    return f"[{b.kind}] {b.text}"


def score_promo(p: Promo, idx: dict[int, EpisodeIndex]) -> Promo:
    first, last = p.segments[0], p.segments[-1]
    i0, i1 = idx[first.episode], idx[last.episode]
    h, hb, hw = i0.hook_at(first.start)
    c, cb, cw = i1.cliff_at(last.end)
    lines = [l for sg in p.segments for l in idx[sg.episode].lines_in(sg.start, sg.end)]
    st, sw = standalone(lines, first.start)
    cov = heat = 0.0
    for sg in p.segments:
        a, b = idx[sg.episode].energy(sg.start, sg.end)
        w = (sg.end - sg.start) / max(1e-6, p.duration)
        cov += a * w
        heat += b * w
    score = combine(h, c, st, cov, heat, p.duration)
    if len(p.segments) > 1:
        score -= 0.02 * (len(p.segments) - 1)   # every extra cut is editor time and a chance to confuse
    p.scores = {"hook": round(h, 3), "cliffhanger": round(c, 3), "standalone": round(st, 3),
                "dialogue_coverage": round(cov, 3), "intensity": round(heat, 3)}
    p.heuristic_score = round(score, 4)
    p.hook, p.hook_beat = _beat_label(hb), hb.id if hb else ""
    p.cliffhanger, p.cliff_beat = _beat_label(cb), cb.id if cb else ""
    p.reasons = [f"hook: {r}" for r in hw] + [f"cliff: {r}" for r in cw] + [f"standalone: {r}" for r in sw]
    return p


def _seg(ix: EpisodeIndex, s: float, e: float) -> Segment:
    inside = ix.beats_in(s, e)
    return Segment(ix.ep.number, round(s, 2), round(e, 2), inside[0].id if inside else "", inside[-1].id if inside else "")


# ----------------------------------------------------------------------------------------
def single_windows(ix: EpisodeIndex, keep: int = 4) -> list[Promo]:
    # prune start/end points first so the search stays cheap at catalogue scale
    starts = [s for s in ix.starts if ix.hook_at(s)[0] >= 0.3] or ix.starts
    ends = [e for e in ix.ends if ix.cliff_at(e)[0] >= 0.3] or ix.ends
    scored = []
    for s in starts:
        for e in ends:
            d = e - s
            if MIN_LEN <= d <= MAX_LEN:
                p = Promo(id="", kind="single", segments=[_seg(ix, s, e)])
                scored.append(score_promo(p, idx={ix.ep.number: ix}))
    return nms(scored, keep)


def overlap(a: Promo, b: Promo) -> float:
    tot = 0.0
    for x in a.segments:
        for y in b.segments:
            if x.episode == y.episode:
                tot += max(0.0, min(x.end, y.end) - max(x.start, y.start))
    return tot / max(1e-6, min(a.duration, b.duration))


def nms(cands: list[Promo], keep: int, max_overlap: float = 0.35) -> list[Promo]:
    out: list[Promo] = []
    for p in sorted(cands, key=lambda x: -x.heuristic_score):
        if all(overlap(p, q) <= max_overlap for q in out):
            out.append(p)
        if len(out) >= keep:
            break
    return out


def flash_forwards(ix: EpisodeIndex, keep: int = 1) -> list[Promo]:
    """Peak moment first, then rewind to the build-up that leads into it."""
    peaks = sorted((b for b in ix.beats if b.kind in ("dialogue", "action") and ix.hook[b.id][0] >= 0.6),
                   key=lambda b: -ix.hook[b.id][0])[:4]
    out = []
    for pk in peaks:
        ps = max((t for t in ix.starts if t <= pk.start + 1e-6), default=None)
        pe = min((t for t in ix.ends if t >= pk.end - 1e-6), default=None)
        if ps is None or pe is None or not (1.5 <= pe - ps <= 7):
            continue
        for s in ix.starts:
            seg2_end = ps   # stop right where the peak begins: the viewer has seen it coming, not how it ends
            d = (pe - ps) + (seg2_end - s)
            # ps is a legal start, so it is also a legal cut (no line is mid-way there)
            if seg2_end - s >= 12 and MIN_LEN <= d <= MAX_LEN:
                p = Promo(id="", kind="flash_forward", segments=[_seg(ix, ps, pe), _seg(ix, s, seg2_end)])
                p = score_promo(p, {ix.ep.number: ix})
                p.scores["cliffhanger"] = round(min(1.0, p.scores["cliffhanger"] + 0.2), 3)  # the peak is promised, not shown resolved
                p.heuristic_score = round(p.heuristic_score + 0.32 * 0.2 * _length_factor(p.duration), 4)
                p.reasons.append("cliff: cuts back just before the peak the viewer already glimpsed")
                out.append(p)
    return nms(out, keep)


def bridges(prev: EpisodeIndex, nxt: EpisodeIndex, keep: int = 1) -> list[Promo]:
    """Ep N's closing cliffhanger + Ep N+1's first beats, cut on the next unresolved moment."""
    out = []
    tail_starts = [s for s in prev.starts if 8 <= prev.ep.duration - s <= 30]
    head_ends = [e for e in nxt.ends if 6 <= e <= 30]
    for s in tail_starts:
        for e in head_ends:
            d = (prev.ep.duration - s) + e
            if MIN_LEN <= d <= MAX_LEN:
                p = Promo(id="", kind="bridge", segments=[_seg(prev, s, prev.ep.duration), _seg(nxt, 0.0, e)])
                out.append(score_promo(p, {prev.ep.number: prev, nxt.ep.number: nxt}))
    return nms(out, keep)


STOP = {"i", "a", "the", "he", "she", "was", "is", "my", "me", "of", "to", "and", "her", "his", "an", "in", "on", "by", "for", "with", "who"}


def premise_trailers(title: str, idx: dict[int, EpisodeIndex], singles: list[Promo], keep: int = 2) -> list[Promo]:
    """Microdrama titles state the hook ("...He was a Duke"). Pair an early setup with the
    later line that pays off the title, cut right as the twist lands."""
    terms = [w for w in re.findall(r"[a-z']+", title.lower()) if w not in STOP and len(w) > 2]
    if not terms:
        return []
    eps = sorted(idx)
    early = [p for p in singles if p.kind == "single" and p.segments[0].episode <= eps[min(2, len(eps) - 1)]]
    early = sorted(early, key=lambda p: -p.heuristic_score)[:3]
    twist_lines = []
    for n in eps[3:]:
        ix = idx[n]
        for l in ix.lines:
            hits = [t for t in terms if re.search(rf"\b{re.escape(t)}", l.text.lower())]
            if hits:
                twist_lines.append((len(hits) + ix.hook[l.id][0] + ix.cliff[l.id][0], ix, l))
    twist_lines = sorted(twist_lines, key=lambda x: -x[0])[:5]
    out = []
    for setup in early:
        sg = setup.segments[0]
        ix0 = idx[sg.episode]
        for _, ix, line in twist_lines:
            te = min((t for t in ix.ends if t >= line.end - 1e-6), default=None)
            if te is None:
                continue
            for ts in [t for t in ix.starts if 5 <= te - t <= 22]:
                # trim the setup so the total fits
                room = MAX_LEN - (te - ts)
                for se in [e for e in ix0.ends if sg.start + 10 <= e <= min(sg.end, sg.start + room)][-3:]:
                    d = (se - sg.start) + (te - ts)
                    if MIN_LEN <= d <= MAX_LEN:
                        p = Promo(id="", kind="premise", segments=[_seg(ix0, sg.start, se), _seg(ix, ts, te)])
                        p = score_promo(p, idx)
                        p.reasons.append(f"premise: pays off the title ({', '.join(t for t in terms if t in line.text.lower())})")
                        p.heuristic_score = round(p.heuristic_score + 0.03, 4)
                        out.append(p)
    return nms(out, keep, max_overlap=0.2)


def generate(title: str, episodes: list[Episode], per_episode: int = 3) -> tuple[list[Promo], dict[int, EpisodeIndex]]:
    idx = {e.number: EpisodeIndex(e) for e in episodes}
    allp: list[Promo] = []
    singles: list[Promo] = []
    nums = sorted(idx)
    for n in nums:
        s = single_windows(idx[n], keep=per_episode)
        singles += s
        allp += s
        allp += flash_forwards(idx[n], keep=1)
    for a, b in zip(nums, nums[1:]):
        if b == a + 1:
            allp += bridges(idx[a], idx[b], keep=1)
    allp += premise_trailers(title, idx, singles)
    for i, p in enumerate(sorted(allp, key=lambda p: (p.segments[0].episode, p.segments[0].start))):
        p.id = f"P{i + 1:03d}"
    return allp, idx
