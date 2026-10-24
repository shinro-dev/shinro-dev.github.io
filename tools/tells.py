#!/usr/bin/env python3
"""
FILE: tools/tells.py  —  AI-writing tell scanner for the Shinro posts.

Two audiences:
  1. a human reading a diff (default output), and
  2. an agent (pi) that must self-check before committing (--json).

Built from the whole of Wikipedia:Signs of AI writing (WP:AISIGNS), which is
explicitly DESCRIPTIVE, not prescriptive. Sections that are Wikipedia-specific
(DOI/ISBN validation, AfC drafts, maintenance templates, edit summaries, wiki
markup, citation formatting, talk-page conventions) are excluded as
inapplicable to a static blog.

Design rules
  * FLAGS, never rewrites. WP:AISIGNS warns that fixing surface signs without
    fixing the underlying problem only makes detection harder.
  * Em-dash density is a NOTE, never a violation: the dash is load-bearing when
    it licenses an elliptical fragment or brackets a comma-bearing aside.
  * Every finding carries a byte offset so an agent can locate and edit it.

Usage
    python3 tools/tells.py writing/*/index.html index.html
    python3 tools/tells.py --strict <files>    # exit 1 on any WARN (CI / pre-commit)
    python3 tools/tells.py --summary <files>   # counts only
    python3 tools/tells.py --json <files>      # machine-readable, for pi

Exit codes
    0  clean, or NOTE-level only
    1  WARN found under --strict
    2  usage error
"""

import re
import sys
import json
import html
import collections

# ---------------------------------------------------------------------------
# CONTENT tells
# ---------------------------------------------------------------------------
WORD_CHECKS = [
    ("significance_puffery", "WARN", [
        r"\bstands? as\b", r"\bis a testament\b", r"\ba reminder that\b",
        r"\b(crucial|pivotal|vital|significant|key)\s+(role|moment|part)\b",
        r"\bplay(?:s|ed)? an? (important|crucial|key|vital|significant) role\b",
        r"\bunderscores?\b", r"\bhighlights? the importance\b", r"\breflects? (a )?broader\b",
        r"\bsymboli[sz]ing\b", r"\benduring\b", r"\bcontributing to the\b",
        r"\bsetting the stage\b", r"\b(represents?|marks?|marking) a shift\b",
        r"\bturning point\b", r"\bevolving landscape\b", r"\bfocal point\b",
        r"\bindelible\b", r"\bdeeply rooted\b",
    ]),
    # The single most characteristic AI construction per WP:SUPERFICIAL:
    # a participle phrase bolted on to imply significance.
    ("superficial_analysis", "WARN", [
        r",\s+(highlighting|underscoring|emphasi[sz]ing|ensuring|reflecting|"
        r"symboli[sz]ing|contributing to|cultivating|fostering|encompassing|"
        r"enhancing|showcasing|demonstrating|illustrating|signaling|"
        r"reinforcing|cementing|solidifying|positioning|enabling|allowing|"
        r"paving the way|marking|representing)\b",
        r"\bvaluable insights\b", r"\b(aligns?|resonates?) with\b",
    ]),
    ("promotional_language", "WARN", [
        r"\bboasts? a\b", r"\bvibrant\b", r"\bprofound\b", r"\bshowcas(es|ing)\b",
        r"\bexemplifies\b", r"\bcommitment to\b", r"\bnestled\b", r"\bin the heart of\b",
        r"\bgroundbreaking\b", r"\brenowned\b", r"\bdiverse array\b",
        r"\brich (history|tradition|culture)\b",
    ]),
    ("vague_connection", "WARN", [
        r"\bin connection with\b", r"\bconnected (with|to)\b", r"\bin association with\b",
        r"\bassociated with (the )?(role|work|development|growth)\b", r"\bwidely associated\b",
    ]),
    ("vague_attribution", "WARN", [
        r"\bexperts (say|believe|note|agree|argue)\b", r"\bobservers (say|note|argue)\b",
        r"\bcritics (argue|say|note)\b", r"\bhas been (described|characteri[sz]ed) as\b",
        r"\bis (widely )?(considered|regarded|seen as)\b", r"\bmany (believe|argue|say|note)\b",
        r"\bit is (widely )?(said|believed|thought|understood)\b", r"\bsources say\b",
    ]),
    ("canned_notability", "WARN", [
        r"\b(gained|drew|attracted) (widespread |significant |considerable |growing )?attention\b",
        r"\breceived (widespread |significant |extensive |critical )?(coverage|acclaim)\b",
        r"\bwidely (covered|reported|cited|acclaimed)\b", r"\bhas been featured in\b",
        r"\bprominent(ly)? (figure|voice)\b",
    ]),
    ("challenges_prospects_ending", "WARN", [
        r"\b(challenges|opportunities) and (future )?(prospects|directions)\b",
        r"\blooking ahead\b", r"\bmoving forward\b", r"\bdespite these challenges\b",
        r"\bremains to be seen\b",
    ]),
    ("signposting", "WARN", [
        r"\bit'?s worth noting\b", r"\bit is important to note\b",
        r"\bimportantly,", r"\binterestingly,", r"\bnotably,",
        r"\bat the end of the day\b", r"\bwhen it comes to\b", r"\bin today'?s\b",
    ]),
    ("ai_vocabulary", "NOTE", [
        r"\bdelv(e|ing)\b", r"\bseamless(ly)?\b", r"\brobust(ly)?\b",
        r"\bgame[- ]chang(er|ing)\b", r"\bleverag(e|ing|ed)\b",
        r"\blandscape of\b", r"\brealm of\b", r"\bmyriad\b", r"\bplethora\b",
        r"\btapestry\b", r"\bfurthermore\b", r"\bmoreover\b", r"\bcrucially\b",
    ]),
]

# ---------------------------------------------------------------------------
# SYNTAX tells
# ---------------------------------------------------------------------------
SYNTAX_CHECKS = [
    ("averted_copula", "WARN", [
        r"\bserves? as\b", r"\bfunctions? as\b", r"\boperates? as\b", r"\bacts? as\b",
        r"\brepresents? a\b", r"\bboasts? a\b", r"\bfeatures? a\b", r"\boffers? a\b",
    ]),
    ("negative_parallelism_not_just", "WARN", [
        r"\bnot (just|only|merely)\b[^.]{0,80}\b(but|also)\b",
        r"\b(is|was|are|were)n'?t? just\b", r"\bmore than just\b",
        r"\bit'?s not about\b[^.]{0,60}\bit'?s about\b",
    ]),
    ("negative_parallelism_not_x_but_y", "WARN", [
        r"\bit'?s not [^.,]{1,40}, it'?s\b",
        r"\bnot (a|an|the) [^.,]{1,40}, but (a|an|the)\b",
    ]),
    ("reversed_parallelism_rather_than", "NOTE", [r"\brather than\b"]),
    ("rule_of_three", "NOTE", [
        r"\b(\w+[^,]{0,22}), (\w+[^,]{0,22}),? and (\w+[^,.]{0,22})\b",
    ]),
    ("obligatory_summary_heading", "WARN", [
        r"<h[1-6][^>]*>[\s\d.]*(the )?takeaways?\b",
        r"<h[1-6][^>]*>[\s\d.]*(in )?conclusion\b",
        r"<h[1-6][^>]*>[\s\d.]*summary\b",
        r"<h[1-6][^>]*>[\s\d.]*key (points|takeaways)\b",
    ]),
]

DASH_NOTE_THRESHOLD = 12.0
BOLD_PER_WORD_FLOOR = 90  # closer than 1 bold per N words => overuse


def visible_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def structural(raw: str, text: str):
    out = []
    words = max(len(text.split()), 1)

    # WP:AIBOLD — overuse of boldface
    bolds = re.findall(r"(?is)<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", raw)
    bolds = [re.sub(r"(?s)<[^>]+>", "", b).strip() for b in bolds]
    bolds = [b for b in bolds if b and not re.match(r"^(fig\.?|figure|table)\s*\d", b, re.I)]
    if bolds:
        per = words / len(bolds)
        if per < BOLD_PER_WORD_FLOOR:
            out.append({
                "severity": "WARN", "category": "overuse_of_boldface",
                "detail": f"{len(bolds)} bold spans, 1 per {per:.0f} words "
                          f"(threshold 1/{BOLD_PER_WORD_FLOOR})",
            })

    # WP:AILIST — inline-header vertical lists:  <li><b>Term</b>: description
    ai_list = re.findall(
        r"(?is)<li[^>]*>\s*<(?:strong|b)\b[^>]*>[^<]{1,60}</(?:strong|b)>\s*[:—–-]", raw)
    if ai_list:
        out.append({
            "severity": "WARN", "category": "inline_header_vertical_list",
            "detail": f"{len(ai_list)} list item(s) shaped '<b>Term</b>: description' (WP:AILIST)",
        })

    # WP:AITITLECASE — headings capitalising nearly every word
    heads = re.findall(r"(?is)<h[1-6][^>]*>(.*?)</h[1-6]>", raw)
    small = {"a", "an", "the", "and", "or", "but", "for", "of", "to", "in", "on",
             "at", "by", "with", "as", "is", "it", "vs"}
    tc = 0
    for h in heads:
        t = re.sub(r"(?s)<[^>]+>", "", h).strip()
        ws = re.findall(r"[A-Za-z][\w'-]*", t)
        if len(ws) >= 4:
            mids = ws[1:-1]
            caps = sum(1 for w in mids if w[0].isupper() and w.lower() not in small)
            if mids and caps / len(mids) > 0.75:
                tc += 1
    if tc:
        out.append({
            "severity": "WARN", "category": "title_case_headings",
            "detail": f"{tc}/{len(heads)} headings capitalise nearly every word (WP:AITITLECASE)",
        })

    # emoji as formatting
    emoji = re.findall(r"[\U0001F300-\U0001FAFF\u2700-\u27BF]", raw)
    if emoji:
        out.append({
            "severity": "WARN", "category": "emoji_formatting",
            "detail": f"{len(emoji)} emoji character(s) in body copy",
        })

    # em-dash density — NOTE only
    dashes = text.count("\u2014")
    per_k = dashes / words * 1000
    if per_k > DASH_NOTE_THRESHOLD:
        out.append({
            "severity": "NOTE", "category": "em_dash_density",
            "detail": f"{dashes} em-dashes / {words:,} words = {per_k:.1f} per 1k "
                      "(NOTE ONLY — load-bearing when it licenses a fragment "
                      "or brackets a comma-bearing aside; do not fix mechanically)",
        })
    return out


def lint(path: str) -> dict:
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = visible_text(raw)
    words = len(text.split())
    findings = []

    for group in (WORD_CHECKS, SYNTAX_CHECKS):
        for category, severity, patterns in group:
            for pat in patterns:
                for m in re.finditer(pat, raw, re.I):
                    ctx = re.sub(r"\s+", " ", raw[max(0, m.start() - 60): m.end() + 60])
                    findings.append({
                        "severity": severity,
                        "category": category,
                        "match": m.group(0).strip(),
                        "offset": m.start(),
                        "context": re.sub(r"<[^>]+>", "", ctx).strip(),
                    })

    findings.extend(structural(raw, text))
    warns = [f for f in findings if f["severity"] == "WARN"]

    return {
        "file": path,
        "words": words,
        "clean": not warns,
        "warn_count": len(warns),
        "note_count": len(findings) - len(warns),
        "findings": findings,
    }


def main(argv):
    strict = "--strict" in argv
    as_json = "--json" in argv
    summary = "--summary" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2

    results = [lint(f) for f in files]
    total_warn = sum(r["warn_count"] for r in results)

    if as_json:
        print(json.dumps({
            "tool": "tells.py",
            "source": "Wikipedia:Signs of AI writing (WP:AISIGNS), blog-applicable sections",
            "clean": total_warn == 0,
            "total_warn": total_warn,
            "files": results,
        }, indent=2, ensure_ascii=False))
        return 1 if (strict and total_warn) else 0

    counts = collections.Counter()
    for r in results:
        for f in r["findings"]:
            if f["severity"] == "WARN":
                counts[f["category"]] += 1

    if summary:
        for r in results:
            print(f"  {r['file']:<52} {r['words']:>6,}w  "
                  f"WARN {r['warn_count']:>3}  NOTE {r['note_count']:>3}")
        print(f"\n  total WARN: {total_warn}")
        for cat, n in counts.most_common():
            print(f"    {n:>3}  {cat}")
        return 1 if (strict and total_warn) else 0

    for r in results:
        status = "CLEAN" if r["clean"] else f"{r['warn_count']} WARN"
        print(f"\n{'=' * 76}\n{r['file']}   ({r['words']:,} words) — {status}\n{'=' * 76}")
        if not r["findings"]:
            print("  no tells detected")
        for f in r["findings"]:
            mark = "!" if f["severity"] == "WARN" else "·"
            if "match" in f:
                print(f"  {mark} [{f['category']}] \"{f['match']}\"")
                print(f"      …{f['context']}…")
            else:
                print(f"  {mark} [{f['category']}] {f['detail']}")

    print(f"\n{'-' * 76}\n  total WARN across {len(files)} file(s): {total_warn}")
    return 1 if (strict and total_warn) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
