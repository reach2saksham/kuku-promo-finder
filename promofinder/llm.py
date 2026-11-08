"""Model layer (stage 2): an LLM judges the shortlist. Swappable with one string.

    --model none                                  rules only (default, free, offline)
    --model gemini:gemini-3.8-flash               GEMINI_API_KEY   (free tier is enough)
    --model openai:gpt-4o-mini                    OPENAI_API_KEY   (+ OPENAI_BASE_URL for any
                                                  OpenAI-compatible API: Groq, OpenRouter, vLLM, a
                                                  company gateway...)
    --model anthropic:claude-haiku-5-5            ANTHROPIC_API_KEY
    --model ollama:llama3.1                       local Ollama, no key
    --model replay:path/to/responses              answers saved earlier (offline re-runs, demos)

Standard library only (urllib), so nothing to install. Every call is cached on
disk by a hash of (model, prompt): re-runs are free and identical.

Anti-hallucination: the model never writes timestamps. It may only cite beat IDs
that exist in the clip it was shown, and every quote it gives is checked against
the script text. Anything that fails a check is thrown away and the rules-based
values are kept.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
import urllib.request
import urllib.error
from difflib import SequenceMatcher
from pathlib import Path


def load_env(path: str = ".env") -> None:
    """Read KEY=value lines from a .env file (if there is one) into os.environ.
    Variables already set in the shell win. Keeps API keys out of commands and out of git."""
    f = Path(path)
    if not f.is_file():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


PROMPT_VERSION = "judge-v1"


class LLMError(RuntimeError):
    pass


# ----------------------------------------------------------------------------------------
def _post(url: str, payload: dict, headers: dict, timeout: int = 300) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(min(60, 4 * 2 ** attempt))
                continue
            raise LLMError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            # network blips and slow "thinking" models: retry, then give up cleanly so the
            # pipeline keeps the rules-based values for this candidate instead of crashing
            if attempt < 2:
                time.sleep(3)
                continue
            raise LLMError(f"{type(e).__name__}: {e}") from e
    raise LLMError("unreachable")


class Model:
    def __init__(self, spec: str, cache_dir: str | Path = ".cache/llm", rpm: float = 0, temperature: float = 0.2,
                 api_key: str | None = None, base_url: str | None = None):
        self.spec = spec or "none"
        self.api_key, self.base_url = api_key, base_url   # override env vars (used by the web app)
        self.provider, _, self.name = self.spec.partition(":")
        self.cache = Path(cache_dir)
        self.rpm = rpm
        self.temperature = temperature
        self._last = 0.0
        self.calls = self.cache_hits = 0
        self.tokens_in = self.tokens_out = 0
        if self.provider not in {"none", "gemini", "openai", "anthropic", "ollama", "replay"}:
            raise ValueError(f"unknown provider '{self.provider}'")

    @property
    def enabled(self) -> bool:
        return self.provider != "none"

    def key(self, prompt: str) -> str:
        return hashlib.sha256(f"{PROMPT_VERSION}\n{prompt}".encode()).hexdigest()[:20]

    def complete(self, prompt: str) -> str:
        k = self.key(prompt)
        if self.provider == "replay":
            f = Path(self.name) / f"{k}.json"
            if not f.exists():
                raise LLMError(f"no saved answer for prompt {k} in {self.name}")
            return f.read_text(encoding="utf-8")
        cf = self.cache / self.spec.replace(":", "_").replace("/", "_") / f"{k}.json"
        if cf.exists():
            self.cache_hits += 1
            return cf.read_text(encoding="utf-8")
        if self.rpm:
            wait = 60.0 / self.rpm - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
        self._last = time.time()
        text = getattr(self, f"_{self.provider}")(prompt)
        self.calls += 1
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(text, encoding="utf-8")
        return text

    # --- providers -------------------------------------------------------------------------
    def _gemini(self, prompt: str) -> str:
        key = self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError("set GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.name}:generateContent"
        r = _post(url, {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json"}},
                  {"x-goog-api-key": key})
        u = r.get("usageMetadata", {})
        self.tokens_in += u.get("promptTokenCount", 0)
        self.tokens_out += u.get("candidatesTokenCount", 0)
        try:
            return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected Gemini response: {str(r)[:300]}") from e

    def _openai(self, prompt: str) -> str:
        base = (self.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        r = _post(f"{base}/chat/completions",
                  {"model": self.name, "temperature": self.temperature,
                   "messages": [{"role": "user", "content": prompt}],
                   "response_format": {"type": "json_object"}},
                  {"Authorization": f"Bearer {key}"} if key else {})
        u = r.get("usage", {})
        self.tokens_in += u.get("prompt_tokens", 0)
        self.tokens_out += u.get("completion_tokens", 0)
        return r["choices"][0]["message"]["content"]

    def _anthropic(self, prompt: str) -> str:
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("set ANTHROPIC_API_KEY")
        r = _post("https://api.anthropic.com/v1/messages",
                  {"model": self.name, "max_tokens": 1500, "temperature": self.temperature,
                   "messages": [{"role": "user", "content": prompt}]},
                  {"x-api-key": key, "anthropic-version": "2023-06-01"})
        u = r.get("usage", {})
        self.tokens_in += u.get("input_tokens", 0)
        self.tokens_out += u.get("output_tokens", 0)
        return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")

    def _ollama(self, prompt: str) -> str:
        host = (self.base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        r = _post(f"{host}/api/chat", {"model": self.name, "stream": False, "format": "json",
                                       "options": {"temperature": self.temperature},
                                       "messages": [{"role": "user", "content": prompt}]}, {})
        return r["message"]["content"]


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise LLMError("model did not return JSON")
        return json.loads(m.group(0))


# ----------------------------------------------------------------------------------------
JUDGE_PROMPT = """You are a performance-marketing editor for a vertical microdrama app (think short-form romance/revenge series sold through TikTok, Instagram Reels and YouTube Shorts ads).

You are judging ONE candidate promo: a 20-60 second clip cut from the show itself, shown cold to a stranger scrolling their feed. No music, captions or edits will be added. A great promo:
1. HOOK - something in the first 3 seconds stops the scroll (a slap, a reveal, a shocking or humiliating line).
2. CLIFFHANGER - it cuts at an unresolved moment so the viewer must install the app to see what happens.
3. STANDALONE - a stranger who never saw the show understands who wants what, from these lines alone.

Show: "{title}"
Context for YOU only (the viewer does not get this): {context}

The clip, in play order. Each line is [beat id] (time in episode) KIND: text. Segments are separated by a cut.
{clip}

Beats just outside the clip (you may move the start or end onto one of these, or inside the clip, if it makes a better promo):
{nearby}

Rules:
- Only cite beat ids that appear above. Never invent timestamps, lines or events.
- "hook_quote" and "cliff_quote" must be copied exactly from the text of the beat you cite.
- Keep any suggested trim between 20 and 60 seconds and do not start or end in the middle of a spoken line. Use null if the cut is already right.
- Be a harsh judge: 10 means you would put ad money behind it today; 5 means usable filler; 2 means it would not work.

Return only JSON:
{{"hook_score": 1-10, "cliffhanger_score": 1-10, "standalone_score": 1-10, "overall": 1-10,
 "hook_beat": "<beat id>", "hook_quote": "<exact text>",
 "cliff_beat": "<beat id>", "cliff_quote": "<exact text>",
 "why": "<one line a marketing lead would read: why this promo works, or why not>",
 "suggested_start_beat": "<beat id or null>", "suggested_end_beat": "<beat id or null>",
 "problems": ["<short issue>", "..."]}}
"""


def _fmt_beat(b) -> str:
    from .parse import sec_to_ts
    who = f"{b.speaker}" + (f" ({b.delivery})" if b.delivery else "") if b.kind == "dialogue" else b.kind.upper()
    return f"[{b.id}] ({sec_to_ts(b.start)}-{sec_to_ts(b.end)}) {who}: {b.text}"


def build_judge_prompt(promo, idx, title: str, nearby_n: int = 6) -> tuple[str, dict]:
    clip_lines, nearby, allowed = [], [], {}
    for n, sg in enumerate(promo.segments):
        ix = idx[sg.episode]
        if n:
            clip_lines.append("--- CUT ---")
        clip_lines.append(f"(Segment {n + 1}: Episode {sg.episode})")
        for b in ix.beats_in(sg.start, sg.end):
            clip_lines.append(_fmt_beat(b))
            allowed[b.id] = b
    if len(promo.segments) == 1:
        sg = promo.segments[0]
        ix = idx[sg.episode]
        inside = ix.beats_in(sg.start, sg.end)
        if inside:
            i0, i1 = inside[0].idx, inside[-1].idx
            before = ix.beats[max(0, i0 - nearby_n):i0]
            after = ix.beats[i1 + 1:i1 + 1 + nearby_n]
            nearby = ["(before the clip)"] + [_fmt_beat(b) for b in before] + ["(after the clip)"] + [_fmt_beat(b) for b in after]
            for b in before + after:
                allowed[b.id] = b
    ctx = " | ".join(f"Ep {e}: {idx[e].ep.logline}" for e in promo.episodes)
    prompt = JUDGE_PROMPT.format(title=title, context=ctx, clip="\n".join(clip_lines),
                                 nearby="\n".join(nearby) if nearby else "(none - multi-segment promo, trims not allowed)")
    return prompt, allowed


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def quote_ok(quote: str, beat_text: str) -> bool:
    q, t = _norm(quote), _norm(beat_text)
    if not q:
        return False
    return q in t or SequenceMatcher(None, q, t).ratio() >= 0.85


def validate_judgement(raw: dict, promo, allowed: dict) -> tuple[dict, list[str]]:
    """Return (clean judgement, list of rejected fields)."""
    rejected = []
    clean = {}
    for k in ("hook_score", "cliffhanger_score", "standalone_score", "overall"):
        try:
            v = float(raw.get(k))
            if not 1 <= v <= 10:
                raise ValueError
            clean[k] = v
        except (TypeError, ValueError):
            rejected.append(k)
    for side in ("hook", "cliff"):
        bid, q = raw.get(f"{side}_beat"), raw.get(f"{side}_quote") or ""
        if bid in allowed and quote_ok(q, allowed[bid].text):
            clean[f"{side}_beat"], clean[f"{side}_quote"] = bid, allowed[bid].text
        else:
            rejected.append(f"{side}_beat/quote ({bid}: '{q[:40]}')")
    clean["why"] = str(raw.get("why") or "").strip()[:300]
    clean["problems"] = [str(p)[:160] for p in (raw.get("problems") or [])][:5]
    for side in ("start", "end"):
        bid = raw.get(f"suggested_{side}_beat")
        if bid in (None, "", "null"):
            continue
        if bid in allowed and len(promo.segments) == 1:
            clean[f"suggested_{side}_beat"] = bid
        else:
            rejected.append(f"suggested_{side}_beat ({bid})")
    return clean, rejected
