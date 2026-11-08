"""Cheap, explainable per-beat signals. No model calls here.

Every score is 0..1 and comes with the reason strings that produced it, so a
human (or the QC step) can see *why* a moment was picked.
The lexicons are deliberately small and genre-specific (romance / revenge /
period microdrama); they are the main thing to tune per genre.
"""
from __future__ import annotations

import re
from .parse import Beat

# --- delivery parentheticals ("Outraged, Accusing") ---------------------------------
HOT_DELIVERY = {
    "screaming": 1.0, "shouting": 0.9, "furious": 0.9, "outraged": 0.9, "enraged": 1.0, "roaring": 1.0,
    "crying out": 0.9, "sobbing": 0.8, "shocked": 0.9, "horrified": 0.9, "terrified": 0.8, "frantic": 0.8,
    "desperate": 0.7, "venomous": 0.8, "menacing": 0.8, "threatening": 0.8, "chilling": 0.8, "gloating": 0.7,
    "mocking": 0.7, "taunting": 0.7, "cruel": 0.7, "spiteful": 0.7, "scornful": 0.6, "contemptuous": 0.6,
    "defiant": 0.7, "fierce": 0.7, "booming": 0.7, "commanding": 0.5, "smug": 0.6, "accusing": 0.8,
    "gasping": 0.7, "pleading": 0.6, "begging": 0.7, "heartbroken": 0.7, "devastated": 0.8, "betrayed": 0.8,
    "incredulous": 0.6, "stunned": 0.7, "panicked": 0.8, "hysterical": 0.9, "seething": 0.8, "icy": 0.6,
    "cold": 0.5, "dark": 0.5, "dangerous": 0.8, "deadly": 0.8, "triumphant": 0.7, "vicious": 0.8, "viciously": 0.8,
    "choked": 0.6, "tearful": 0.5, "trembling": 0.5, "breathless": 0.4, "urgent": 0.5, "harsh": 0.6,
    "unforgiving": 0.6, "merciless": 0.8, "possessive": 0.7, "protective": 0.6, "steely": 0.5, "sharp": 0.5,
}
COOL_DELIVERY = {"gentle", "soft", "tender", "warm", "calm", "reflective", "quiet", "relieved", "amused",
                 "polite", "curious", "earnest", "kind", "soothing", "affectionate", "content", "hopeful"}

# --- visual / physical shocks (ACTION, CAMERA, SOUND FX text) ------------------------
PHYSICAL = {
    r"\bslap": 1.0, r"\bstrikes?\b": 0.9, r"\bpunch": 0.9, r"\bshoves?\b": 0.8, r"\bpush(es)?\b": 0.5,
    r"\bgrab": 0.7, r"\bseiz": 0.7, r"\bchok": 0.9, r"\bstrangl": 1.0, r"\bblood": 0.9, r"\bwound": 0.7,
    r"\bknife\b": 0.9, r"\bdagger": 0.9, r"\bblade": 0.8, r"\bsword": 0.8, r"\bpistol|\bgun\b": 0.9,
    r"\bpoison|\barsenic": 0.9, r"\bcollaps": 0.8, r"\bfaint": 0.7, r"\bfalls?\b|\btumbl": 0.6,
    r"\bkneel|\bknees\b": 0.5, r"\bslams?\b": 0.7, r"\bshatter": 0.8, r"\bsmash": 0.8, r"\bthrows?\b|\bhurl": 0.7,
    r"\bdrag": 0.7, r"\bwhip|\blash": 0.9, r"\bkiss": 0.7, r"\btears? (off|open|apart)|\brips?\b": 0.7,
    r"\bburst(s)? (open|in|through)": 0.8, r"\barrest|\bshackl|\bchains?\b": 0.8, r"\bguards? (seize|grab|drag)": 0.9,
    r"\bpins?\b.*\bwall": 0.8, r"\bscream": 0.8, r"\bgasp": 0.5, r"\bfreezes?\b": 0.4, r"\bdrops?\b": 0.4,
    r"\bwedding|\baltar": 0.4, r"\bring\b": 0.3, r"\bbetroth|\bfianc": 0.3,
}
CLIFF_VISUAL = {
    r"cut to black": 1.0, r"cliffhanger": 1.0, r"freeze[- ]frame": 0.9, r"smash cut": 0.8, r"ominous": 0.6,
    r"swells?": 0.4, r"crescendo|peak": 0.5, r"sting\b|stinger": 0.6, r"push(es|ing)?[- ]in": 0.3,
    r"door(s)? (burst|swing|fly) open": 0.8, r"silhouette": 0.4, r"shadow": 0.3, r"realiz": 0.5,
    r"eyes widen": 0.5, r"stares? in (shock|horror|disbelief)": 0.7, r"unconscious|goes limp": 0.8,
}
RESOLUTION = {
    r"\bthank you\b": 0.6, r"\brelie(f|ved)\b": 0.7, r"\bembrace": 0.5, r"\bhugs?\b": 0.5, r"\blaughs?\b": 0.4,
    r"\bsmiles? (softly|warmly|gently)": 0.6, r"\bit'?s over\b": 0.6, r"\byou'?re safe\b": 0.7,
    r"\bgoodnight\b|\bgood night\b": 0.5, r"\bwalks? away\b": 0.3, r"\bexits?\b": 0.3, r"\bfades? out\b": 0.3,
}

# --- dialogue content ----------------------------------------------------------------
REVEAL = {
    r"\bduke\b|\bduchess\b|\byour grace\b": 0.7, r"\bpregnan|\bwith child\b|\bbaby\b|\bheir\b": 0.9,
    r"\bmarr(y|ied|iage)\b|\bwedding\b|\bwife\b|\bhusband\b": 0.5, r"\bdivorce|\bannul": 0.8,
    r"\bpoison|\barsenic|\bmurder|\bkill(ed)?\b|\bdead\b|\bdie\b": 0.9, r"\bthe truth\b|\bsecret\b": 0.7,
    r"\blie[ds]?\b|\bliar\b|\bbetray": 0.7, r"\bwho are you\b": 0.8, r"\bhow dare\b": 0.8,
    r"\byou will pay\b|\byou'll pay\b|\bregret\b": 0.8, r"\bguards?\b": 0.6, r"\barrest\b|\bhang(ed)?\b|\bprison\b": 0.8,
    r"\bnever\b": 0.3, r"\bi know what you did\b|\bi know (who|what)\b": 0.9, r"\bmine\b": 0.5,
    r"\bkneel\b|\bbow\b": 0.6, r"\bstole|\bthief\b": 0.7, r"\bsister\b": 0.3, r"\bfather\b|\bmother\b": 0.2,
    r"\bdisown|\bcast out\b|\bbanish|\bdisgrace": 0.8, r"\bnothing\b|\bworthless\b|\bplain\b": 0.5,
}
# The opening line of a promo should not lean on something the viewer never saw.
CONTEXT_DEPENDENT_OPENERS = re.compile(
    r"^(and|but|so|then|because|still|also|anyway|as i said|like i said|that'?s why|which|that|it|this|those|these|he|she|they|him|her|them|yes|no|okay|ok|well)\b",
    re.I)
PAST_REFS = re.compile(r"\b(yesterday|last night|earlier|before|again|remember|you promised|as we agreed|the letter|the antidote|the vial|that night)\b", re.I)
RELATION_WORDS = re.compile(r"\b(sister|husband|wife|father|mother|fianc[eé]e?|bride|groom|duke|duchess|son|daughter|brother|maid|lord|lady)\b", re.I)


def _lex(text: str, table: dict[str, float]) -> tuple[float, list[str]]:
    best, hits = 0.0, []
    low = text.lower()
    for pat, w in table.items():
        m = re.search(pat, low)
        if m:
            hits.append(m.group(0))
            best = max(best, w)
    # a second distinct hit adds a little
    bonus = 0.1 * max(0, min(2, len(hits) - 1))
    return min(1.0, best + bonus), hits


def delivery_heat(b: Beat) -> tuple[float, list[str]]:
    if b.kind != "dialogue" or not b.delivery:
        return 0.0, []
    words = [w.strip().lower() for w in b.delivery.split(",")]
    heat, hits = 0.0, []
    for w in words:
        for k, v in HOT_DELIVERY.items():
            if k in w:
                heat = max(heat, v)
                hits.append(w)
        if w in COOL_DELIVERY:
            heat -= 0.15
    return max(0.0, min(1.0, heat)), hits


def beat_hook(b: Beat) -> tuple[float, list[str]]:
    """How likely is this beat to stop a scroll if it lands in the first 3 seconds?"""
    reasons: list[str] = []
    if b.kind == "dialogue":
        heat, dh = delivery_heat(b)
        rev, rh = _lex(b.text, REVEAL)
        punct = 0.25 if "!" in b.text else (0.15 if "?" in b.text else 0.0)
        short = 0.15 if len(b.text.split()) <= 9 else 0.0     # punchy lines land in 3s
        s = 0.45 * heat + 0.45 * rev + punct + short
        if dh:
            reasons.append(f"delivered {dh[0]}")
        if rh:
            reasons.append("line mentions " + "/".join(rh[:2]))
        if CONTEXT_DEPENDENT_OPENERS.match(b.text):
            s -= 0.2
            reasons.append("opens mid-thought")
        return max(0.0, min(1.0, s)), reasons
    phys, ph = _lex(b.text, PHYSICAL)
    if b.kind == "sfx":
        phys = max(phys, 0.3 if re.search(r"gasp|slam|crash|scream|thud|crack|shatter", b.text, re.I) else 0.0)
    if ph:
        reasons.append("visual: " + "/".join(ph[:2]))
    return phys * (0.9 if b.kind == "camera" else 1.0), reasons


def beat_cliff(b: Beat) -> tuple[float, list[str]]:
    """How unresolved does the story feel if we cut right after this beat?"""
    reasons: list[str] = []
    vis, vh = _lex(b.text, CLIFF_VISUAL)
    res, rh = _lex(b.text, RESOLUTION)
    s = vis
    if vh:
        reasons.append("visual sting: " + "/".join(vh[:2]))
    if b.kind == "dialogue":
        heat, _ = delivery_heat(b)
        rev, rv = _lex(b.text, REVEAL)
        q = 0.45 if b.text.rstrip().endswith("?") else 0.0
        threat = 0.35 if re.search(r"\b(will|shall|going to|won't|unless|or else|until)\b", b.text, re.I) and heat > 0.4 else 0.0
        trail = 0.25 if b.text.rstrip().endswith(("...", "…", "—", "-")) else 0.0
        s = max(s, 0.3 * heat + 0.4 * rev + q + threat + trail)
        if q:
            reasons.append("ends on a question")
        if threat:
            reasons.append("ends on a threat")
        if trail:
            reasons.append("line is cut off")
        if rv:
            reasons.append("ends on " + "/".join(rv[:2]))
    if res > 0:
        s -= 0.6 * res
        reasons.append("feels resolved (" + "/".join(rh[:2]) + ")")
    return max(0.0, min(1.0, s)), reasons
