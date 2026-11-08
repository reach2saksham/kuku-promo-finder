"""Parse Kuku-style microdrama screenplays into a flat, timestamped beat list.

Input: a folder or .zip of episode .txt files. Each beat in the file looks like

    **LADY ASHFORD (Outraged, Accusing):**
    Start: (00:46.80) | End: (00:50.00)
    "You knew this before I walked through those doors!"

Kinds: CAMERA, ACTION, SOUND FX, or a character name (= DIALOGUE).
Everything downstream works on these Beat objects, never on raw text, so a
new screenplay format only needs a new parser.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

TS = r"(\d{1,2}):(\d{2}(?:\.\d+)?)"
RE_BEAT_HEAD = re.compile(r"^\*\*(?P<head>.+?):\*\*\s*$")
RE_BEAT_TIME = re.compile(rf"^Start:\s*\({TS}\)\s*\|\s*End:\s*\({TS}\)\s*$")
RE_EP_NUM = re.compile(r"^EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", re.I)
RE_LOGLINE = re.compile(r"^EPISODE LOGLINE:\s*(.*)$", re.I)
RE_CONT = re.compile(r"^CONTINUITY NOTES:\s*(.*)$", re.I)
RE_SCENE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
RE_SCENE_HEADING = re.compile(r"^SCENE HEADING:\s*(.*)$", re.I)
RE_SPEAKER = re.compile(r"^(?P<name>[^()]+?)\s*(?:\((?P<p1>[^)]*)\))?\s*(?:\((?P<p2>[^)]*)\))?$")

NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx", "SOUND": "sfx", "MUSIC": "sfx"}


def ts_to_sec(m: str, s: str) -> float:
    return int(m) * 60 + float(s)


def sec_to_ts(x: float) -> str:
    x = max(0.0, x)
    m = int(x // 60)
    return f"{m:02d}:{x - m * 60:05.2f}"


@dataclass
class Beat:
    id: str              # e.g. "E07-B042" - stable handle the LLM must use instead of inventing timestamps
    episode: int
    idx: int
    kind: str            # camera | action | sfx | dialogue
    start: float
    end: float
    text: str
    speaker: str = ""    # dialogue only (normalised, e.g. "ASHFORD")
    delivery: str = ""   # parenthetical, e.g. "Outraged, Accusing"
    offscreen: bool = False
    scene: int = 1
    scene_heading: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Episode:
    number: int
    title: str
    logline: str
    continuity: str
    beats: list[Beat] = field(default_factory=list)
    source: str = ""

    @property
    def duration(self) -> float:
        return max((b.end for b in self.beats), default=0.0)

    def dialogue(self):
        return [b for b in self.beats if b.kind == "dialogue"]


def _norm_speaker(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip().upper())
    # "LADY ASHFORD" and "ASHFORD" are the same person; strip honorifics
    # for matching but keep the raw label in text output.
    return name


def parse_episode_text(text: str, source: str = "") -> Episode:
    lines = [l.rstrip("\n").rstrip("\r") for l in text.splitlines()]
    num, logline, cont = 0, "", ""
    scene, heading = 1, ""
    beats: list[Beat] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if m := RE_EP_NUM.match(line):
            num = int(m.group(1))
        elif m := RE_LOGLINE.match(line):
            logline = m.group(1).strip()
        elif m := RE_CONT.match(line):
            cont = m.group(1).strip()
        elif m := RE_SCENE.match(line):
            scene = int(m.group(1))
        elif m := RE_SCENE_HEADING.match(line):
            heading = m.group(1).strip()
        elif m := RE_BEAT_HEAD.match(line):
            head = m.group("head").strip()
            # next non-empty line should be the timing line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            tm = RE_BEAT_TIME.match(lines[j].strip()) if j < len(lines) else None
            if not tm:
                i += 1
                continue
            start, end = ts_to_sec(tm.group(1), tm.group(2)), ts_to_sec(tm.group(3), tm.group(4))
            # body = following lines until blank line or next beat header
            body = []
            k = j + 1
            while k < len(lines):
                s = lines[k].strip()
                if not s:
                    if body:
                        break
                    k += 1
                    continue
                if RE_BEAT_HEAD.match(s) or RE_SCENE.match(s) or s.startswith("--- SCRIPT"):
                    break
                body.append(s)
                k += 1
            body_text = " ".join(body).strip()
            key = head.upper()
            if key in NON_DIALOGUE:
                kind, speaker, delivery, off = NON_DIALOGUE[key], "", "", False
            else:
                kind = "dialogue"
                sm = RE_SPEAKER.match(head)
                name = sm.group("name") if sm else head
                parens = [p for p in ((sm.group("p1"), sm.group("p2")) if sm else ()) if p]
                off = any(p.strip().upper() in {"O.S.", "V.O.", "O.C.", "OFF-SCREEN"} for p in parens)
                delivery = ", ".join(p for p in parens if p.strip().upper() not in {"O.S.", "V.O.", "O.C.", "OFF-SCREEN", "CONT'D"})
                speaker = _norm_speaker(name)
                body_text = body_text.strip().strip('"').strip("“”").strip()
            beats.append(Beat(id="", episode=num, idx=0, kind=kind, start=start, end=end, text=body_text,
                              speaker=speaker, delivery=delivery, offscreen=off, scene=scene, scene_heading=heading))
            i = k
            continue
        i += 1
    beats.sort(key=lambda b: (b.start, b.end))
    for n, b in enumerate(beats):
        b.episode = num
        b.idx = n
        b.id = f"E{num:02d}-B{n:03d}"
    return Episode(number=num, title=f"Episode {num}", logline=logline, continuity=cont, beats=beats, source=source)


def load_show(path: str | Path) -> tuple[str, list[Episode]]:
    """Load every episode from a folder or a .zip. Returns (show_title, episodes sorted by number)."""
    path = Path(path)
    texts: list[tuple[str, str]] = []
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith(".txt") and not n.startswith("__MACOSX"):
                    texts.append((n, z.read(n).decode("utf-8", errors="replace")))
        names = [n for n, _ in texts]
        title = Path(names[0]).parent.name if names and Path(names[0]).parent.name else path.stem
    elif path.is_dir():
        for f in sorted(path.rglob("*.txt")):
            texts.append((str(f), f.read_text(encoding="utf-8", errors="replace")))
        title = path.name
    elif path.is_file():
        texts.append((str(path), path.read_text(encoding="utf-8", errors="replace")))
        title = path.stem
    else:
        raise FileNotFoundError(path)
    eps = [parse_episode_text(t, src) for src, t in texts]
    eps = [e for e in eps if e.beats]
    eps.sort(key=lambda e: e.number)
    title = re.sub(r"-scripts.*$", "", title).strip()
    return title, eps
