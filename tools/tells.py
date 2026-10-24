#!/usr/bin/env python3
"""
FILE: tools/tells.py  —  AI-writing tell linter for the Shinro posts.

Source of the categories: Wikipedia:Signs of AI writing (WP:AISIGNS),
which is explicitly DESCRIPTIVE, not prescriptive. This tool therefore
  1. only FLAGS, never rewrites, and
  2. treats em-dash density as a NOTE, not a violation, because the
     punctuation is frequently load-bearing (it licenses elliptical
     fragments and brackets comma-bearing asides).

Usage:
    python3 tools/tells.py writing/*/index.html index.html about/index.html
    python3 tools/tells.py --strict <files>   # exit 1 on any WARN

Exit codes: 0 clean/heed-only, 1 violations in --strict mode.
"""

import re
import sys
import html

# ---------------------------------------------------------------- categories
# Each entry: (category, severity, [patterns])
# severity: "WARN" = real tell, worth fixing.  "NOTE" = context only.
CHECKS = [
    ("Significance puffery", "WARN", [
        r"\bstands? as\b", r"\bserves? as\b", r"\bis a testament\b",
        r"\ba reminder that\b", r"\b(crucial|pivotal|vital|significant|key)\s+(role|moment|part)\b",
        r"\bunderscores?\b", r"\bhighlights? (the )?importance\b", r"\breflects? (a )?broader\b",
        r"\bsymboli[sz]ing\b", r"\benduring\b", r"\bcontributing to the\b",
        r"\bsetting the stage\b", r"\b(represents?|marks?|marking) a shift\b",
        r"\bturning point\b", r"\bevolving landscape\b", r"\bfocal point\b",
        r"\bindelible\b", r"\bdeeply rooted\b", r"\bdistinction matters because\b",
        r"\bplay(?:s|ed)? an? (important|crucial|key|vital) role\b",
    ]),
    ("Vague attribution", "WARN", [
        r"\bexperts (say|believe|note|agree)\b", r"\bobservers (say|note)\b",
        r"\bcritics (argue|say|note)\b", r"\bhas been (described|characteri[sz]ed) as\b",
        r"\bis (widely )?(considered|regarded)\b", r"\bmany (believe|argue|say)\b",
        r"\bit is (widely )?(said|believed|thought)\b", r"\bsources say\b",
        r"\breportedly\b", r"\ballegedly\b",
    ]),
    ("Canned notability", "WARN", [
        r"\b(gained|drew|attracted) (widespread |significant |considerable )?attention\b",
        r"\breceived (widespread |significant |extensive )?coverage\b",
        r"\bwidely (covered|reported|cited)\b", r"\bhas been featured in\b",
        r"\bprominent(ly)? (figure|voice)\b",
    ]),
    ("Not-just-X construction", "WARN", [
        r"\b(is|was|are|were)n'?t? just\b", r"\bnot (just|only|merely) (a|an|the)?\b.*\bbut\b",
        r"\bmore than just\b", r"\bit'?s not about\b.*\bit'?s about\b",
    ]),
    ("Signposting", "WARN", [
        r"\bit'?s worth noting\b", r"\bit is important to note\b",
        r"\bimportantly,?", r"\binterestingly,?", r"\bnotably,?",
        r"\bat the end of the day\b", r"\bwhen it comes to\b",
        r"\bin today'?s\b", r"\bnavigat(e|ing) the\b", r"\bunlock(ing)? the\b",
    ]),
    ("Obligatory summary", "WARN", [
        r"\bin conclusion\b", r"\bto summari[sz]e\b", r"\boverall,\s",
        r"<h[1-6][^>]*>\s*(the )?takeaway", r"<h[1-6][^>]*>\s*conclusion",
        r"\bkey takeaways?\b",
    ]),
    ("LLM vocabulary", "NOTE", [
        r"\bdelv(e|ing)\b", r"\bseamless(ly)?\b", r"\brobust(ly)?\b",
        r"\bgame[- ]chang(er|ing)\b", r"\bleverag(e|ing)\b",
        r"\blandscape of\b", r"\brealm of\b", r"\bmyriad\b", r"\bplethora\b",
        r"\btapestry\b", r"\bcrucially\b", r"\bfurthermore\b", r"\bmoreover\b",
    ]),
]

# Em-dash is a NOTE with a threshold, not a rule. Measured density in this
# corpus sits near 3-5/1k after tuning; >12/1k is worth a look, not a fix.
DASH_NOTE_THRESHOLD = 12.0


def visible_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def lint(path: str):
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = visible_text(raw)
    words = len(text.split())
    findings = []

    for category, severity, patterns in CHECKS:
        for pat in patterns:
            for m in re.finditer(pat, raw, re.I):
                ctx = re.sub(r"\s+", " ", raw[max(0, m.start() - 55): m.end() + 55])
                ctx = re.sub(r"<[^>]+>", "", ctx).strip()
                findings.append((severity, category, m.group(0), ctx))

    # em-dash density — informational
    dashes = text.count("\u2014")
    per_k = dashes / max(words, 1) * 1000
    dash_note = None
    if per_k > DASH_NOTE_THRESHOLD:
        dash_note = f"{dashes} em-dashes / {words:,} words = {per_k:.1f} per 1k (>{DASH_NOTE_THRESHOLD})"

    return words, findings, dash_note


def main(argv):
    strict = "--strict" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 0

    total_warn = 0
    for path in files:
        words, findings, dash_note = lint(path)
        warns = [f for f in findings if f[0] == "WARN"]
        notes = [f for f in findings if f[0] == "NOTE"]
        total_warn += len(warns)

        status = "CLEAN" if not warns else f"{len(warns)} WARN"
        print(f"\n{'=' * 72}\n{path}   ({words:,} words) — {status}\n{'=' * 72}")

        if not findings:
            print("  no tells detected")
        for sev, cat, hit, ctx in warns + notes:
            mark = "!" if sev == "WARN" else "·"
            print(f"  {mark} [{cat}] \"{hit}\"")
            print(f"      …{ctx}…")
        if dash_note:
            print(f"  ~ [density] {dash_note}  (note only — do not fix mechanically)")

    print(f"\n{'-' * 72}\n  total WARN across {len(files)} file(s): {total_warn}")
    if strict and total_warn:
        print("  --strict: failing")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
