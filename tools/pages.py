#!/usr/bin/env python3
"""Keep the site's shared chrome in one copy, and check the bookkeeping.

The header, the footer and the closing tags exist once, in
``tools/templates/chrome/<region>.frag``. Every page carries them between
marker comments::

    <!-- chrome:footer:start -->
    <footer class="site-footer"> … </footer>
    <!-- chrome:footer:end -->

Nothing here runs at deploy time. ``git push origin main`` is still the
deploy: the fragments are not a build step, they are a single copy that
``check`` compares against and ``sync`` writes back out.

    python3 tools/pages.py check     # chrome, sitemap, feed, internal links
    python3 tools/pages.py sync      # rewrite the marked regions in place
    python3 tools/pages.py adopt     # one-off: wrap existing regions in markers

Exit status is 0 when everything agrees, 1 with a list of what does not.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = Path(__file__).resolve().parent / "templates" / "chrome"
REGIONS = ("header", "footer", "tail")
REQUIRED = ("header", "tail")
SITE = "https://shinro-dev.github.io"
SKIP_DIRS = {"tools", "assets", ".git", ".pi"}
NAV_CURRENT = {"/writing": "/writing/", "/about/": "/about/"}
DESCRIPTION = "Single-copy site chrome, plus sitemap, feed and link checks."

# Where each region starts and ends in a page that has no markers yet.
BOUNDARIES = (
    ("header", '<header class="site-header">', "</header>"),
    ("footer", '<footer class="site-footer">', "</footer>"),
    ("tail", '<script src="/assets/js/site.js" defer></script>', "</html>"),
)


# ---------------------------------------------------------------- regions ---

def marker(name: str, edge: str) -> str:
    return f"<!-- chrome:{name}:{edge} -->"


def pattern(name: str) -> re.Pattern[str]:
    start = re.escape(marker(name, "start"))
    end = re.escape(marker(name, "end"))
    return re.compile(f"{start}\n(.*?)\n{end}", re.S)


def fragment(name: str) -> str:
    return (CHROME / f"{name}.frag").read_text(encoding="utf-8").strip("\n")


def route_of(path: Path) -> str:
    """'/about/' for about/index.html, '/404.html' for 404.html."""
    rel = path.relative_to(ROOT).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def current_link(route: str) -> str | None:
    for prefix, href in NAV_CURRENT.items():
        if route in (prefix, href) or route.startswith(prefix + "/"):
            return href
    return None


def expected(name: str, route: str) -> str:
    text = fragment(name)
    if name != "header":
        return text
    href = current_link(route)
    if href is None:
        return text
    # The link may carry a class attribute, so match the tag, not the whole line.
    return re.sub(
        rf'<a href="{re.escape(href)}"(?=[ >])',
        f'<a href="{href}" aria-current="page"',
        text,
        count=1,
    )


def render(page: str, route: str) -> str:
    """Replace every marked region with the canonical fragment for this route."""
    for name in REGIONS:
        pat = pattern(name)
        if not pat.search(page):
            continue
        block = f"{marker(name, 'start')}\n{expected(name, route)}\n{marker(name, 'end')}"
        page = pat.sub(lambda _match, block=block: block, page, count=1)
    return page


# ------------------------------------------------------------------ pages ---

def pages() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*.html")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.split("/")[0] in SKIP_DIRS and rel != "tools/templates/post.html":
            continue
        found.append(path)
    return found


def adopt(page: str) -> str:
    """Wrap existing regions in markers, once. Idempotent."""
    for name, start_tag, end_tag in BOUNDARIES:
        if marker(name, "start") in page:
            continue
        begin = page.find(start_tag)
        if begin < 0:
            continue
        end = page.find(end_tag, begin)
        if end < 0:
            continue
        end += len(end_tag)
        block = f"{marker(name, 'start')}\n{page[begin:end]}\n{marker(name, 'end')}"
        page = page[:begin] + block + page[end:]
    return page


# ----------------------------------------------------------------- checks ---

def internal_links(page: str) -> set[tuple[str, str]]:
    """(path, fragment) for every root-absolute link; fragment may be empty."""
    found = set()
    for href in re.findall(r'href="(/[^"]*)"', page):
        path, _, fragment = href.partition("#")
        found.add((path.split("?", 1)[0], fragment))
    return found


def page_file(path: str) -> Path | None:
    resolved = (ROOT / path.lstrip("/")).resolve()
    if not resolved.is_relative_to(ROOT):
        return None
    if path.endswith("/") or resolved.is_dir():
        resolved = resolved / "index.html"
    return resolved if resolved.is_file() else None


def check_chrome() -> list[str]:
    problems = []
    for path in pages():
        page = path.read_text(encoding="utf-8")
        route = route_of(path)
        rel = path.relative_to(ROOT).as_posix()
        for name in REGIONS:
            match = pattern(name).search(page)
            if not match:
                if name in REQUIRED and not rel.startswith("tools/"):
                    problems.append(f"{rel}: no {name} region (markers missing)")
                continue
            if match.group(1) != expected(name, route):
                line = page[: match.start(1)].count("\n") + 1
                problems.append(
                    f"{rel}:{line}: {name} region differs from "
                    f"tools/templates/chrome/{name}.frag"
                )
    return problems


def check_sitemap() -> list[str]:
    problems = []
    text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    listed = {url.replace(SITE, "") or "/" for url in re.findall(r"<loc>([^<]+)</loc>", text)}
    live = set()
    for path in pages():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tools/") or rel == "404.html":
            continue
        live.add(route_of(path))
    for missing in sorted(live - listed):
        problems.append(f"sitemap.xml: no entry for {missing}")
    for stale in sorted(listed - live):
        problems.append(f"sitemap.xml: entry for {stale} has no page")
    return problems


def check_feed() -> list[str]:
    problems = []
    text = (ROOT / "feed.xml").read_text(encoding="utf-8")
    slugs = {
        url.replace(f"{SITE}/writing/", "").strip("/")
        for url in re.findall(f"<link>({re.escape(SITE)}/writing/[^<]+)</link>", text)
    }
    for slug in sorted(slugs):
        if slug and not (ROOT / "writing" / slug / "index.html").is_file():
            problems.append(f"feed.xml: item for /writing/{slug}/ has no page")
    return problems


def check_links() -> list[str]:
    problems = []
    ids: dict[Path, set[str]] = {}
    for path in pages():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tools/"):
            continue
        for link, fragment in sorted(internal_links(path.read_text(encoding="utf-8"))):
            target = page_file(link)
            if target is None:
                problems.append(f"{rel}: link {link} has no target")
                continue
            if not fragment:
                continue
            if target not in ids:
                ids[target] = set(re.findall(r'id="([^"]+)"', target.read_text(encoding="utf-8")))
            if fragment not in ids[target]:
                problems.append(f"{rel}: link {link}#{fragment} has no such anchor")
    return sorted(set(problems))


def check() -> list[str]:
    missing = [name for name in REGIONS if not (CHROME / f"{name}.frag").is_file()]
    if missing:
        return [f"missing fragment tools/templates/chrome/{name}.frag" for name in missing]
    return check_chrome() + check_sitemap() + check_feed() + check_links()


def sync() -> list[str]:
    changed = []
    for path in pages():
        page = path.read_text(encoding="utf-8")
        updated = render(page, route_of(path))
        if updated != page:
            path.write_text(updated, encoding="utf-8")
            changed.append(path.relative_to(ROOT).as_posix())
    return changed


def adopt_all() -> list[str]:
    changed = []
    for path in pages():
        page = path.read_text(encoding="utf-8")
        updated = adopt(page)
        if updated != page:
            path.write_text(updated, encoding="utf-8")
            changed.append(path.relative_to(ROOT).as_posix())
    return changed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("command", nargs="?", default="check", choices=("check", "sync", "adopt"))
    args = parser.parse_args(argv)

    if args.command == "adopt":
        changed = adopt_all()
        print(f"adopted markers in {len(changed)} file(s)")
        for rel in changed:
            print("  " + rel)
        return 0

    if args.command == "sync":
        changed = sync()
        print(f"synced {len(changed)} file(s)")
        for rel in changed:
            print("  " + rel)
        return 0

    problems = check()
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print("  " + problem)
        print("\nfix with: python3 tools/pages.py sync")
        return 1
    print("pages clean: chrome, sitemap, feed, internal links")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
