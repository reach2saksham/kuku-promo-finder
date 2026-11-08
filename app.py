"""Web UI for editors:  streamlit run app.py
Upload a screenplay .zip, pick a model (or none), get ranked promos + downloads.
Nothing is stored server-side beyond a temp folder for the run; keys are used for this run only.
"""
import io
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

import ui_theme as ui
from promofinder.llm import load_env
from promofinder.pipeline import run
from promofinder.render import seg_str, transcript

load_env()  # GEMINI_API_KEY etc. from .env, so the key box can stay empty

st.set_page_config(page_title="Promo Finder", page_icon=":material/movie:")
ui.inject()

MODEL_DEFAULTS = {"gemini": "gemini-3.8-flash", "openai / compatible": "gpt-4o-mini", "anthropic": "claude-haiku-5-5", "ollama": "llama3.1"}

with st.sidebar:
    st.html(ui.brand_html())
    st.html(ui.label_html("Model"))
    provider = st.selectbox("Provider", ["none (rules only, free)", "gemini", "openai / compatible", "anthropic", "ollama"],
                            label_visibility="collapsed")
    use_model = not provider.startswith("none")
    model_name, api_key, base_url, shortlist, rpm = "", "", "", 40, 10
    if use_model:
        model_name = st.text_input("Model name", MODEL_DEFAULTS[provider])
        if provider != "ollama":
            api_key = st.text_input("API key (blank = use .env)", type="password")
        if provider in ("openai / compatible", "ollama"):
            base_url = st.text_input("Base URL (optional)", "", help="Any OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
        shortlist = st.slider("Candidates the model judges", 5, 100, 40)
        rpm = st.number_input("Max calls per minute", 0, 600, 10, help="Free tiers: ~10. 0 = no limit")
    st.html(ui.note_html())

r = st.session_state.get("result")
st.html(ui.status_html("Done" if r else "Ready"))

if r:
    runner = st.expander("Run another script")
else:
    st.html(ui.hero_html(model_name or "Rules only"))
    st.html(ui.section_html("Screenplay", "Upload a .zip with one .txt per episode."))
    runner = st.container()

with runner:
    up = st.file_uploader("Screenplay .zip (one .txt per episode)", type=["zip"], label_visibility="collapsed")
    local = st.text_input("...or a folder / .zip path on this machine (when running locally)", "",
                          placeholder="tests/fixtures/sample_show", key="local_path")
    if (up or local.strip()) and st.button("Find promos", type="primary", key="find_promos", width="stretch"):
        spec = "none" if not use_model else {"openai / compatible": "openai"}.get(provider, provider) + ":" + model_name
        with tempfile.TemporaryDirectory() as d:
            if up:
                zp = Path(d) / "input.zip"
                zp.write_bytes(up.getvalue())
            else:
                zp = Path(local.strip().strip('"'))
            log = st.empty()
            lines = []

            def logger(msg):
                lines.append(msg)
                log.code("\n".join(lines[-12:]))

            try:
                res = run(str(zp), out_dir=str(Path(d) / "out"), model_spec=spec, shortlist_n=shortlist, rpm=rpm,
                          cache_dir=str(Path(d) / "cache"), log=logger, api_key=api_key or None, base_url=base_url or None)
            except Exception as e:  # show the error to the editor instead of a stack trace
                st.error(f"Run failed: {e}")
                st.stop()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for f in (Path(d) / "out").glob("*.*"):
                    z.write(f, f.name)
            st.session_state["result"] = {
                "meta": res["meta"],
                "picks": [{**p.to_dict(), "transcript": transcript(p, res["idx"])} for p in res["picks"]],
                "all": [{**p.to_dict(), "seg": seg_str(p)} for p in res["promos"]],
                "zip": buf.getvalue(),
            }
        st.rerun()  # results take over the page

if r:
    m = r["meta"]
    st.html(ui.section_html(m.get("show") or "Results", results=True))
    st.html(ui.stats_html(m))
    st.download_button("Download all outputs (.zip)", r["zip"], "promos_output.zip", key="download")
    st.html(ui.section_html("Post these first", "Ranked, with one promo per episode and no failed checks."))
    for p in r["picks"]:
        segs = " + ".join(f"E{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])
        with st.expander(f"#{p['rank']}  {segs}  ({p['duration']:.0f}s, {p['kind']})  - QC {p['qc']['status']}", expanded=p["rank"] <= 3):
            st.html(ui.pick_html(p))
            st.code("\n".join(p["transcript"]), language=None, wrap_lines=True)
    st.html(ui.section_html("All candidates", "Every promo found, highest score first."))
    st.dataframe([{"id": p["id"], "rank": p["rank"] or "", "shape": p["kind"], "segments": p["seg"], "len": round(p["duration"]),
                   "score": p["final_score"], "qc": p["qc"]["status"], "hook": p["hook"], "cliffhanger": p["cliffhanger"]}
                  for p in sorted(r["all"], key=lambda x: -x["final_score"])], width="stretch")
