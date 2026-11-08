"""How much do the rules and the model agree, and where do they disagree?

    python -m promofinder.evaluate outputs/with_model/promos.json > outputs/with_model/eval.md

Disagreements are the cheapest place for a human to look first: either the rules
have a blind spot, or the model does.
"""
import json
import sys


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    j = [p for p in d["promos"] if p["llm"].get("overall") is not None]
    out = [f"# Rules vs model on {len(j)} judged promos", ""]
    if len(j) < 3:
        print("not enough judged promos")
        return
    pairs = [("overall", "heuristic_score", None), ("hook_score", "scores", "hook"),
             ("cliffhanger_score", "scores", "cliffhanger"), ("standalone_score", "scores", "standalone")]
    out += ["| model field | rules field | Spearman |", "|---|---|---|"]
    for mf, rf, sub in pairs:
        a = [p["llm"][mf] for p in j if mf in p["llm"]]
        b = [(p[rf][sub] if sub else p[rf]) for p in j if mf in p["llm"]]
        out.append(f"| {mf} | {sub or rf} | {spearman(a, b):.2f} |")
    dist = {}
    for p in j:
        dist[int(p["llm"]["overall"])] = dist.get(int(p["llm"]["overall"]), 0) + 1
    out += ["", "Model overall score distribution: " + ", ".join(f"{k}/10 x{v}" for k, v in sorted(dist.items()))]
    by_kind = {}
    for p in j:
        by_kind.setdefault(p["kind"], []).append(p["llm"]["overall"])
    out += ["", "Mean model score by promo shape: " + ", ".join(f"{k} {sum(v) / len(v):.1f} (n={len(v)})" for k, v in by_kind.items())]
    hr = ranks([p["heuristic_score"] for p in j])
    mr = ranks([p["llm"]["overall"] for p in j])
    gap = sorted(range(len(j)), key=lambda i: -(hr[i] - mr[i]))
    fmt = lambda p: (f"- {p['id']} ({p['kind']}, E{'+E'.join(map(str, p['episodes']))}) rules {p['heuristic_score']:.2f}, "
                     f"model {p['llm']['overall']:.0f}/10 - model says: {p['llm'].get('why', '')[:160]}"
                     + (f" | problems: {'; '.join(p['llm'].get('problems', [])[:2])}" if p['llm'].get('problems') else ""))
    out += ["", "## Rules liked it, model did not (rule blind spots?)", ""] + [fmt(j[i]) for i in gap[:6]]
    out += ["", "## Model liked it, rules did not", ""] + [fmt(j[i]) for i in gap[::-1][:6]]
    rej = [(p["id"], r) for p in j for r in p["llm"].get("rejected", [])]
    out += ["", f"## Model answers rejected by validation: {len(rej)}", ""] + [f"- {a}: {b}" for a, b in rej]
    trims = [(p["id"], p["llm"]["trim"]) for p in j if p["llm"].get("trim")]
    out += ["", f"## Trims proposed by the model: {len(trims)}", ""] + [f"- {a}: {b}" for a, b in trims]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
