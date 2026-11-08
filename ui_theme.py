"""Visual theme for the web UI (app.py). Presentation only: no pipeline logic here.

Monochrome night look: black page with a grey halftone texture (pure CSS), a narrow
centred column, white double-framed panels, a speech bubble under a square pixel avatar,
tiny orange accents. Source Serif 4 for headings, Inter for everything you read or tap.
The upload screen fits one page with no scrolling; results get a wider column.
"""
from __future__ import annotations

import base64
import html

import streamlit as st

ORANGE = "#FF7A2F"
WHITE = "#FFFFFF"


def _pixel_svg(rows: list[str], colors: dict[str, str]) -> str:
    """Turn a text grid into a crisp SVG data URI."""
    h, w = len(rows), max(len(r) for r in rows)
    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1" height="1" fill="{colors[c]}"/>'
        for y, row in enumerate(rows) for x, c in enumerate(row) if c in colors
    )
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'shape-rendering="crispEdges">{rects}</svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


CLAPPER = _pixel_svg([
    "................",
    ".##############.",
    ".#oo..oo..oo..#.",
    ".##############.",
    "................",
    ".##############.",
    ".#............#.",
    ".#....##......#.",
    ".#....####....#.",
    ".#....######..#.",
    ".#....####....#.",
    ".#....##......#.",
    ".#............#.",
    ".##############.",
    "................",
    "................",
], {"#": WHITE, "o": ORANGE})

CSS = f"""
:root {{
  font-weight:400;
  --panel:linear-gradient(180deg, rgba(48,50,55,.92), rgba(30,31,35,.92));
  --row:rgba(38,40,44,.88); --hair:rgba(255,255,255,.07); --soft:rgba(255,255,255,.2);
  --white:#fff; --muted:#A3A7AD; --orange:{ORANGE};
  --serif:'Source Serif 4', Georgia, 'Times New Roman', serif;
  --gutter:clamp(1rem, 4vw, 1.5rem); --read:.97rem; --read-lh:1.6;
}}
::selection {{ background:var(--orange); color:#000; }}

/* ---------- halftone backdrop ---------- */
.stApp {{ background:#000 !important; }}
.stApp::before {{
  content:""; position:fixed; inset:0; pointer-events:none;
  background-image:
    radial-gradient(circle, transparent 0.85px, #000 1.35px),
    radial-gradient(38% 34% at 28% 32%, rgba(255,255,255,.30), transparent 72%),
    radial-gradient(34% 42% at 72% 58%, rgba(255,255,255,.24), transparent 72%),
    radial-gradient(30% 28% at 48% 88%, rgba(255,255,255,.18), transparent 72%),
    radial-gradient(42% 30% at 88% 14%, rgba(255,255,255,.16), transparent 72%);
  background-size: 3px 3px, 170% 170%, 150% 150%, 190% 190%, 160% 160%;
  background-position: 0 0, 0% 0%, 100% 100%, 50% 100%, 100% 0%;
  animation: smoke 38s ease-in-out infinite alternate;
}}
@keyframes smoke {{
  0%   {{ background-position: 0 0, 0% 0%,   100% 100%, 50% 100%, 100% 0%; }}
  50%  {{ background-position: 0 0, 60% 30%, 40% 70%,   10% 40%,  30% 60%; }}
  100% {{ background-position: 0 0, 100% 80%, 0% 20%,   90% 10%,  0% 100%; }}
}}
@media (prefers-reduced-motion: reduce) {{ .stApp::before {{ animation:none; }} }}
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {{ background:transparent !important; }}
[data-testid="stDecoration"], [data-testid="stAppDeployButton"], [data-testid="stSkillsNudge"] {{ display:none !important; }}
[data-testid="stMainBlockContainer"] {{
  max-width:720px; padding-left:var(--gutter) !important; padding-right:var(--gutter) !important;
  padding-top:clamp(3.75rem, 9vh, 4.5rem) !important; padding-bottom:3rem !important;
}}
[data-testid="stMainBlockContainer"]:has(.pf-results) {{ max-width:980px; }}
* {{ scrollbar-width:thin; scrollbar-color:#2F3135 transparent; }}
/* invisible elements still cost a 16px gap each in Streamlit's stack */
[data-testid="stElementContainer"]:has(.pf-status) {{ position:absolute; }}

/* ---------- double frame: white line, gap, white line ---------- */
.pf-avatar {{
  display:grid; place-items:center; background:#000; flex:none;
  border:1px solid var(--white); box-shadow: inset 0 0 0 3px #000, inset 0 0 0 4px rgba(255,255,255,.9);
}}
.pf-avatar img {{ width:52%; image-rendering:pixelated; }}

/* ---------- hero ---------- */
.pf-hero {{ position:relative; container:hero / inline-size; }}
.pf-hero-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:.75rem; }}
.pf-hero-top .pf-avatar {{ width:56px; height:56px; }}
.pf-chips {{ display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.45rem; min-width:0; }}
.pf-chip {{
  font-size:.75rem; font-weight:500; color:var(--white); padding:.28rem .6rem; border:1px solid var(--soft); border-radius:6px;
  background:rgba(20,21,24,.7); max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}}
.pf-chip i {{ display:inline-block; width:6px; height:6px; background:var(--orange); margin-right:.4rem; vertical-align:1px; }}
.pf-bubble {{
  position:relative; margin-top:20px; padding:.95rem 1.25rem 1rem; background:var(--panel);
  border:1px solid var(--white); border-radius:6px;
  box-shadow: inset 0 0 0 3px #2B2D31, inset 0 0 0 4px rgba(255,255,255,.85);
  font-size:var(--read); line-height:var(--read-lh); color:var(--white);
}}
.pf-bubble::before, .pf-bubble::after {{
  content:""; position:absolute; top:-15px; left:12px; width:34px; height:15px;
  clip-path: polygon(0 0, 100% 100%, 46% 100%);
}}
.pf-bubble::before {{ background:var(--white); }}
.pf-bubble::after {{ top:-13px; left:14px; width:30px; height:14px; background:#303237; }}
.pf-bubble p {{ margin:0 0 .55rem; }}
.pf-bubble p:last-child {{ margin:0; }}
.pf-cursor {{ display:inline-block; width:.5em; height:1em; background:var(--orange); vertical-align:-.12em; margin-left:.2em; animation:blink 1s steps(1) infinite; }}
@keyframes blink {{ 50% {{ opacity:0; }} }}
@container hero (max-width:480px) {{ .pf-bubble {{ padding:.8rem 1rem .85rem; }} }}

.pf-h {{ font-family:var(--serif); font-weight:600; font-size:1.3rem; line-height:1.25; color:var(--white); margin:0 0 .4rem; }}
.pf-p {{ font-size:var(--read); line-height:var(--read-lh); color:#D7D9DC; margin:0; }}
.pf-gap {{ margin-top:1rem; }}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"], [data-testid="stSidebarContent"] {{ background:#050505 !important; }}
[data-testid="stSidebar"] {{ border-right:1px solid var(--hair); }}
[data-testid="stSidebarUserContent"] {{ padding-top:0 !important; padding-bottom:1rem !important; }}
.pf-brand {{ display:flex; align-items:center; gap:.75rem; margin:0 0 .4rem; }}
.pf-brand .pf-avatar {{ width:46px; height:46px; }}
.pf-brand b {{ display:block; font-family:var(--serif); font-weight:600; font-size:1.2rem; line-height:1.2; color:var(--white); }}
.pf-brand small {{ font-size:.78rem; color:var(--muted); }}
.pf-label {{ font-size:.75rem; font-weight:500; letter-spacing:.04em; color:var(--muted); margin:.2rem 0 .1rem; }}
.pf-note {{
  margin-top:.2rem; padding:.7rem .8rem; font-size:.8rem; line-height:1.45; color:#D7D9DC;
  background:rgba(255,255,255,.04); border:1px solid var(--hair); border-radius:6px;
}}
.pf-note i {{ display:inline-block; width:6px; height:6px; background:var(--orange); margin-right:.45rem; vertical-align:1px; }}
[data-testid="stWidgetLabel"] p {{ font-size:.78rem !important; font-weight:500; color:#B4B8BE !important; }}
[data-testid="stTextInputRootElement"] input::placeholder {{ color:#7D8187; opacity:1; }}
[data-baseweb="select"] > div, [data-baseweb="input"], [data-testid="stNumberInputContainer"] {{
  background:var(--row) !important; border-color:var(--hair) !important; border-radius:6px !important;
}}

/* ---------- upload ---------- */
[data-testid="stFileUploaderDropzone"] {{
  background:var(--row) !important; border:1px solid var(--soft) !important; border-radius:6px !important; padding:.75rem 1rem !important;
}}
[data-testid="stFileUploaderDropzone"] button {{ background:var(--white) !important; color:#000 !important; border:0 !important; font-weight:500; }}
[data-testid="stFileUploaderDropzone"] button:hover {{ background:#E4E5E7 !important; }}
[data-testid="stFileUploaderDropzone"] button * {{ color:#000 !important; fill:#000 !important; }}
.st-key-find_promos button {{ background:var(--white) !important; color:#000 !important; border:0 !important; padding:.65rem 0 !important; }}
.st-key-find_promos button:hover {{ background:#E4E5E7 !important; }}
.st-key-find_promos button p {{ color:#000 !important; font-weight:600; }}
.st-key-download button {{
  background:#000 !important; color:var(--white) !important; border:1px solid var(--white) !important;
  box-shadow: inset 0 0 0 3px #000, inset 0 0 0 4px rgba(255,255,255,.85) !important; padding:.6rem 1.2rem !important;
}}
.st-key-download button:hover {{ background:#141414 !important; }}
.st-key-download button p {{ font-weight:500; }}
[data-testid="stCode"] pre, [data-testid="stCodeBlock"] pre {{ max-width:100%; background:rgba(0,0,0,.55) !important; border:1px solid var(--hair); border-radius:6px; }}

/* ---------- results ---------- */
.pf-stats {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(135px, 1fr)); gap:0; background:var(--row); border:1px solid var(--hair); border-radius:6px; overflow:hidden; }}
.pf-stat {{ padding:.75rem 1rem; border-right:1px solid var(--hair); border-bottom:1px solid var(--hair); margin:0 -1px -1px 0; min-width:0; }}
.pf-stat b {{ display:block; font-family:var(--serif); font-size:1.45rem; font-weight:600; line-height:1.2; color:var(--white); white-space:nowrap; }}
.pf-stat span {{ display:block; margin-top:.15rem; font-size:.76rem; line-height:1.3; color:var(--muted); }}

[data-testid="stExpander"] details {{ border:1px solid var(--soft) !important; border-radius:6px !important; background:var(--row); }}
[data-testid="stExpander"] summary p {{ font-size:.92rem; font-weight:500; color:var(--white); overflow-wrap:anywhere; }}
[data-testid="stExpander"] summary:hover {{ background:rgba(255,255,255,.045); }}

.pf-pick {{ display:grid; grid-template-columns:6rem minmax(0, 1fr); gap:.5rem .75rem; font-size:.93rem; line-height:1.5; color:var(--white); }}
.pf-pick dt {{ font-size:.76rem; font-weight:500; letter-spacing:.04em; color:var(--muted); padding-top:.15rem; }}
.pf-pick dd {{ margin:0; min-width:0; overflow-wrap:anywhere; }}
.pf-tags {{ display:flex; flex-wrap:wrap; gap:.4rem; }}
.pf-tag {{
  display:inline-flex; align-items:center; gap:.45rem; max-width:100%; padding:.25rem .55rem; font-size:.78rem; font-weight:500; line-height:1.35;
  border:1px solid currentColor; border-radius:6px; background:rgba(0,0,0,.4); overflow-wrap:anywhere;
}}
.pf-tag i {{ width:7px; height:7px; display:inline-block; flex:none; }}
.pf-tag.ok {{ color:var(--white); }} .pf-tag.ok i {{ background:#5BE08C; }}
.pf-tag.warn {{ color:var(--orange); }} .pf-tag.warn i {{ background:var(--orange); }}

/* ---------- corner status ---------- */
.pf-status {{
  position:fixed; right:22px; bottom:22px; z-index:50; pointer-events:none; width:98px; height:74px;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:.4rem;
  background:#000; border:1px solid var(--white);
  box-shadow: inset 0 0 0 3px #000, inset 0 0 0 4px rgba(255,255,255,.85);
  font-size:.7rem; color:var(--white); text-align:center; line-height:1.05;
}}
.pf-status img {{ width:22px; image-rendering:pixelated; }}
.pf-status i {{ display:inline-block; width:5px; height:5px; background:var(--orange); margin-right:.3rem; vertical-align:1px; animation:blink 1.4s steps(1) infinite; }}
@media (max-width:1320px) {{ .pf-status {{ display:none; }} }}
@media (max-width:1560px) {{ .stApp:has(.pf-results) .pf-status {{ display:none; }} }}

/* ---------- upload screen: one page, no scrolling ----------
   :has(.pf-hero) is only true before the first run. Each step down in height drops the
   least important thing first; nothing is ever clipped. */
[data-testid="stMainBlockContainer"]:has(.pf-hero) {{
  padding-top:clamp(1.5rem, calc((100dvh - 500px) / 2), 12rem) !important; padding-bottom:1rem !important;
}}
@media (max-width:768px) {{
  [data-testid="stHeader"] {{ background:rgba(0,0,0,.88) !important; backdrop-filter:blur(6px); }}
  .stApp:has(.pf-hero) [data-testid="stHeader"] {{ background:transparent !important; backdrop-filter:none; }}
  [data-testid="stMainBlockContainer"]:has(.pf-hero) {{ padding-top:max(3rem, calc((100dvh - 520px) / 2)) !important; }}
}}
/* phones can't reach a path on this machine, so that box goes */
@media (max-width:600px) {{
  .st-key-local_path {{ display:none; }}
  .pf-pick {{ grid-template-columns:minmax(0, 1fr); gap:.1rem; }}
  .pf-pick dd {{ margin-bottom:.5rem; }}
}}
@media (max-height:640px) {{
  .pf-bubble p + p {{ display:none; }}
  .pf-bubble p {{ margin:0; }}
  .stApp:has(.pf-hero) .pf-p {{ display:none; }}
}}
/* phone in landscape */
@media (max-height:480px) {{
  [data-testid="stMainBlockContainer"]:has(.pf-hero) {{ padding-top:.75rem !important; padding-bottom:.25rem !important; }}
  .pf-hero-top {{ display:none; }}
  .pf-bubble {{ margin-top:0; padding:.55rem .9rem !important; font-size:.9rem; line-height:1.4; }}
  .pf-bubble::before, .pf-bubble::after {{ display:none; }}
  .pf-h {{ margin:0; font-size:1.05rem; }}
  .st-key-local_path {{ display:none; }}
}}
@media (max-height:480px) and (max-width:768px) {{
  [data-testid="stMainBlockContainer"]:has(.pf-hero) {{ padding-top:2.75rem !important; }}
}}
"""


def inject() -> None:
    """Add the theme CSS (safe to call on every rerun)."""
    st.html(f"<style>{CSS}</style>")


def brand_html() -> str:
    return (f'<div class="pf-brand"><div class="pf-avatar"><img src="{CLAPPER}" alt=""/></div>'
            f'<div><b>Promo Finder</b><small>microdrama promo search</small></div></div>')


def label_html(text: str) -> str:
    return f'<div class="pf-label">{html.escape(text)}</div>'


def note_html() -> str:
    return ('<div class="pf-note"><i></i>This reads scripts, not footage. '
            'Check every cut in the video before posting.</div>')


def hero_html(model: str) -> str:
    return f"""
<div class="pf-hero">
  <div class="pf-hero-top">
    <div class="pf-avatar"><img src="{CLAPPER}" alt=""/></div>
    <div class="pf-chips"><span class="pf-chip"><i></i>20-60 s promos</span>
      <span class="pf-chip">{html.escape(model)}</span></div>
  </div>
  <div class="pf-bubble">
    <p>Hey! I'm Promo Finder. Give me a screenplay and I'll find its best promos.</p>
    <p>Each one opens on a hook, cuts on a cliffhanger and has exact timestamps.<span class="pf-cursor"></span></p>
  </div>
</div>"""


def section_html(title: str, body: str = "", results: bool = False) -> str:
    cls = "pf-results pf-gap" if results else "pf-gap"
    sub = f'<div class="pf-p">{html.escape(body)}</div>' if body else ""
    return f'<div class="{cls}"><div class="pf-h">{html.escape(title)}</div>{sub}</div>'


def stats_html(meta: dict) -> str:
    qc = meta["qc"]
    tiles = [(meta["episodes"], "Episodes"), (meta["candidates"], "Candidates"),
             (f"{qc['PASS']} / {qc['REVIEW']} / {qc['FAIL']}", "QC pass / review / fail"), (meta["llm_calls"], "Model calls")]
    cells = "".join(f'<div class="pf-stat"><b>{html.escape(str(v))}</b><span>{html.escape(k)}</span></div>' for v, k in tiles)
    return f'<div class="pf-stats">{cells}</div>'


def pick_html(pick: dict) -> str:
    """Hook, cliffhanger and why for one promo. Everything comes from the script or a model, so escape it."""
    row = lambda k, v: f"<dt>{k}</dt><dd>{html.escape(str(v or 'None found'))}</dd>"
    status = pick["qc"]["status"]
    tags = [f'<span class="pf-tag {"ok" if status == "PASS" else "warn"}"><i></i>QC {html.escape(status)}</span>']
    tags += [f'<span class="pf-tag warn">{html.escape(str(f))}</span>' for f in pick["qc"]["flags"]]
    return (f'<dl class="pf-pick">{row("Hook", pick["hook"])}{row("Cliffhanger", pick["cliffhanger"])}'
            f'{row("Why", pick["why"])}<dt>Checks</dt><dd><div class="pf-tags">{"".join(tags)}</div></dd></dl>')


def status_html(status: str) -> str:
    return (f'<div class="pf-status"><img src="{CLAPPER}" alt=""/>'
            f'<span><i></i>{html.escape(status)}</span></div>')
