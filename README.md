# Promo Finder: find the best promos in a microdrama screenplay

Reads a timestamped screenplay (one `.txt` per episode, folder or `.zip`) and returns ranked
20-60 second promos. Each promo comes with the episode, the start/end timestamps of every
segment, the hook, the cliffhanger, one line on why it works, and a QC status.

It runs in six steps:

1. Parse the screenplay (code)
2. Generate candidates and score them with rules (code, about 2 s for 50 episodes)
3. Shortlist the best ones (code)
4. Judge them with an LLM (optional, any model, one flag)
5. Run quality checks (code)
6. Rank them (code)

## Setup

Python 3.10+. The CLI needs **no installs** (standard library only). Only the optional web UI needs Streamlit.

```bash
git clone <this repo> && cd kuku-promo-finder
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt   # only for the web UI
```

To use a model, copy `.env.example` to `.env` and paste your key (e.g. a free Gemini key from
aistudio.google.com). `.env` is git-ignored and read automatically by the CLI and the UI.
Put the screenplay input in `data/` (see `data/README.md`; the scripts are not in this repo).

## Run it

```bash
python -m promofinder data/show-scripts.zip -o outputs/my_run
```

That is the free, offline, rules-only run. Add a model to judge the shortlist:

```bash
# Google Gemini. Free tier is ~20 requests/day for gemini-3.8-flash, so keep --shortlist small. Key from .env, or:
export GEMINI_API_KEY=...            # PowerShell: $env:GEMINI_API_KEY="..."
python -m promofinder show.zip -o outputs/gemini --model gemini:gemini-3.8-flash --shortlist 15 --rpm 5

# Any OpenAI-compatible API (OpenAI, Groq, OpenRouter, a company gateway, vLLM...)
export OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.groq.com/openai/v1
python -m promofinder show.zip --model openai:llama-3.3-70b-versatile

# Anthropic / local Ollama
python -m promofinder show.zip --model anthropic:claude-haiku-5-5
python -m promofinder show.zip --model ollama:llama3.1

# Re-play saved model answers (offline, identical output). They ship in the raw outputs folder, not in this repo
python -m promofinder show.zip --shortlist 60 --model replay:raw_outputs/model_prompts_and_answers/responses
```

Useful flags: `--shortlist 60` (how many candidates the model judges, which sets the cost),
`--llm-weight 0.6`, `--per-episode 3`, `--export-prompts` (write the judge prompts and stop).
Model answers are cached in `.cache/llm/`, so re-runs cost nothing.

### Web UI (optional)

```bash
python -m streamlit run app.py
```
Upload a `.zip` (or give a local path), pick a provider, paste a key, download the results.
Deploys as-is to Streamlit Community Cloud. **Do not commit show scripts to the repo.** Upload them at run time.

### Tests

```bash
python -m unittest discover -s tests -v
```
Uses a synthetic screenplay. Includes a full run through a fake OpenAI-compatible server that
returns an invented beat ID, to check the tool rejects it.

## Outputs (`-o` folder)

| File | What |
|---|---|
| `report.md` / `report.html` | Top-10 "post these first" with reasons, then every candidate by episode, with transcript (HTML) |
| `promos.csv` | One row per promo: segments, timestamps, hook, cliffhanger, why, scores, QC flags. Opens in Sheets |
| `promos.json` | Everything, including the clip transcript, for other tools |
| `qc_report.md` | Pass / review / fail counts, most common flags, model answers that were rejected |
| `run_meta.json` | Model, calls, tokens, timings |

## How it works

1. **Parse.** Each beat (CAMERA / ACTION / SOUND FX / dialogue) becomes `{id, start, end, kind, speaker, delivery, text}`.
   Beat IDs like `E07-B042` are the only handle the model is allowed to use.
2. **Generate.** Every window between two *legal cut points* (never inside a spoken line) that is 20-60s long,
   plus three montage shapes: **flash-forward** (peak moment first, then the build-up), **bridge**
   (episode N's ending + episode N+1's opening) and **premise** (an early setup + the later line that pays off
   the show title, e.g. *"You're the Duke?"*).
3. **Rule score.** Explainable 0-1 signals: *hook* (hot delivery, shock/reveal words, physical action, starting in
   the first 1.5-3s), *cliffhanger* (question/threat/cut-off line, stings, episode ending, weighted toward the
   last beat before the cut; penalised if it feels resolved), *standalone* (mid-thought openers, references to
   earlier events, too many speakers, relationships named on screen) and *energy* (dialogue coverage, intensity).
   Non-max suppression keeps the best few non-overlapping windows per episode.
4. **Shortlist.** Best per episode plus the best overall (default 60) go to the model.
5. **LLM judge.** Scores hook / cliffhanger / standalone / overall, names the hook and cliffhanger beat, writes
   the "why", and may move the start/end onto a neighbouring beat. **Every cited beat ID must exist in that clip and
   every quote must match the script**; otherwise that field is discarded and the rules' value stays. Trims are re-snapped
   to legal cuts and re-checked for 20-60s.
6. **QC.** FAIL on hard rules (length, mid-line cuts, timestamps outside the episode, model score of 3 or below); REVIEW on
   weak hook, resolved ending, mid-thought opener, a character mentioned who never appears, too many speakers.
7. **Rank.** "post first": score times a small early-episode bonus (a viewer who taps lands on episode 1), at most one
   promo per episode, no overlaps, FAILs excluded.

## Limits

- Reads the **script**, not the footage: it cannot see acting, pacing, or whether a visual sting actually lands.
  Visual-only cliffhangers are flagged for a human check.
- Lexicons are tuned for romance/revenge period drama; a new genre needs its word lists reviewed.
- Ranking weights are hand-set, not learned. With real promo performance data (CTR, installs per promo) they should be fitted.
