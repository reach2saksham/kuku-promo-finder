"""CLI:  python -m promofinder <scripts.zip | folder> [options]"""
import argparse
import sys

from .llm import load_env
from .pipeline import run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promofinder", description="Find ranked 20-60s promos in a microdrama screenplay.")
    ap.add_argument("input", help="folder or .zip of episode .txt screenplays")
    ap.add_argument("-o", "--out", default="outputs", help="output folder (default: outputs)")
    ap.add_argument("-m", "--model", default="none",
                    help="none | gemini:<model> | openai:<model> | anthropic:<model> | ollama:<model> | replay:<dir>")
    ap.add_argument("--shortlist", type=int, default=60, help="how many candidates the model judges (cost control)")
    ap.add_argument("--per-episode", type=int, default=3, help="continuous promos kept per episode")
    ap.add_argument("--llm-weight", type=float, default=0.6, help="weight of the model score vs the rules score")
    ap.add_argument("--rpm", type=float, default=0, help="max model calls per minute (free tiers: ~10)")
    ap.add_argument("--export-prompts", action="store_true", help="write the judge prompts to <out>/prompts and stop there")
    ap.add_argument("--cache", default=".cache/llm", help="model response cache folder")
    a = ap.parse_args(argv)
    load_env()
    run(a.input, a.out, a.model, a.shortlist, a.per_episode, a.llm_weight, a.rpm, a.export_prompts, a.cache)


if __name__ == "__main__":
    sys.exit(main())
