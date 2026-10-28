# AGENTS.md

Instructions for coding agents working in this repository.

## What this is

The Shinro organization site (`https://shinro-dev.github.io/`): a landing page,
a writing index, an About page, and three long-form posts. It is **static HTML
and one stylesheet**, served by GitHub Pages straight from `main`, `/` root.

There is no build step, no framework, no package manager, no bundler, no test
suite, and no CI. `git push origin main` is the deploy.

Read `README.md` first for the human-facing version of this; it covers the
post converter in more depth than this file.

## Non-negotiable rules

1. **Never add a build step, dependency, or toolchain.** No npm/package.json, no
   Ruby/Jekyll, no SSG. `.nojekyll` is present on purpose: Pages must serve the
   files verbatim.
2. **No third-party runtime requests.** No external CSS, JS, fonts, images, or
   analytics. Fonts are self-hosted in `assets/fonts/`, the demo video is
   local. Outbound *links* to `shinro.dev`, `docs.shinro.dev`, `github.com` are
   fine; `<img src>`, `<link href>`, `<script src>` pointing off-origin are not.
   Verify — the only acceptable match is `<link rel="canonical">`:
   ```sh
   grep -rnoE '(src|srcset)="https?://|<link[^>]+href="https?://|url\(https?://' \
     --include=*.html --include=*.css .
   ```
   A plain `<a href="https://…">` to Hugging Face, arXiv, GitHub, etc. is a
   link, not a request, and is fine.
3. **Root-absolute asset paths.** Use `/assets/...` and `/writing/<slug>/`, never
   relative or `file://` paths — pages live at two different depths.
4. **Trailing-slash directory URLs.** Every route is `<dir>/index.html` and is
   linked as `/dir/`.
5. **The HTML is the source of truth for a post.** `writing/<slug>/index.html`
   is hand-maintained after conversion. Do not re-run the converter over an
   existing slug (it would discard hand edits); `--force` overwrites the
   directory including media.
6. **Never commit or push unless explicitly asked.** One coherent change set
   per commit, no amends, no force-push.

## Layout

```text
index.html                                  landing page (hero, #stack, #compare, #evidence, #writing)
writing/index.html                          post index; entries between posts:start / posts:end
writing/<slug>/index.html                   one directory per post
writing/<slug>/<page>/index.html            a sub-page of a post (the Microduck appendix plates)
about/index.html                            About page
404.html                                    not-found page
assets/css/site.css                         all styling (design tokens at the top)
assets/js/site.js                           copy buttons, video play/pause, TOC highlight
assets/fonts/geist-*.woff2                  Geist + Geist Mono, latin subsets, OFL 1.1
assets/img/<slug>/…                         per-post figures
assets/img/microduck-*                      home-page figures, poster, demo MP4
feed.xml                                    RSS 2.0 — maintained BY HAND
sitemap.xml                                 one <url> per page — hand-maintained
robots.txt, .nojekyll
tools/new-post.py                           .odt/.docx draft -> writing/<slug>/
tools/templates/post.html                   page skeleton used by the converter
tools/tells.py                              AI-writing tell scanner (WP:AISIGNS)
```

## Preview

```sh
cd /mnt/E/github-projects/shinro-dev.github.io   # repo root — not writing/ or a post dir
python3 -m http.server 8099                     # Ctrl-C to stop; use another port if 8099 is busy
# then open http://localhost:8099/ — never the file:// path
```

Pages use root-absolute paths (`/assets/...`), so double-clicking a file will not work.

## Adding a post

```sh
python3 tools/new-post.py --from ~/Desktop/draft.odt \
  --slug my-post --date 2026-10-20 --kicker "Systems note · 003"
```

It writes `writing/<slug>/index.html`, copies/transcodes media into
`assets/img/<slug>/` (GIF → MP4 + WebP poster; `--video-scale 1` halves the
video), inserts the entry into `writing/index.html` between the
`posts:start` / `posts:end` markers, and appends to `sitemap.xml`. It converts
heading levels, paragraphs, quotes, lists, tables, inline bold/italic/monospace,
links, and images with intrinsic dimensions; it hoists the first image to the
hero and treats an italic paragraph after a figure as that figure's caption.

It prints a `review:` list of the editorial work it deliberately left alone —
title/standfirst split, ASCII diagrams, captions, the appendix cut. Work
through that list by hand.

**Then update `feed.xml` manually** — the converter does not touch it. Add an
`<item>` above the existing ones, refresh `lastBuildDate`, and match the
existing `<category>` / `<author>` shape.

Draft provenance: a post's `.odt`/`.docx` draft stays out of the repo. Appendices
(headline alternatives, HN/X/LinkedIn drafts) are internal release material and
are never published.

## Editing a post by hand

Keep the page skeleton the converter emits:

- `<head>`: title `… — Shinro`, `meta description`, `link rel=canonical`,
  `link rel=alternate` to `/feed.xml`, OG/Twitter tags, `article:published_time`
  and `article:tag`, the two `theme-color` metas, the font `preload`, the
  stylesheet, and the JSON-LD `BlogPosting` block.
- `.post-header` with `.backlink`, `.eyebrow` (the kicker), `<h1>` plus optional
  `<span class="h1-sub">`, `.lede`, then `.meta` (author · `<time>` · reading
  time at 220 wpm).
- `.post-layout` → `nav.toc` (`<ol>` of anchors) beside `article.prose`.
- Every `<h2>` needs an `id`; add the matching `<li>` to the TOC and number the
  sections consistently with the rest of the site.
- Site footer verbatim from `tools/templates/post.html`, then
  `<script src="/assets/js/site.js" defer></script>`.

Prose conventions: figures go under `/assets/img/<slug>/`, ASCII diagrams are
usually redrawn as inline SVG or CSS, demo GIFs become MP4 + WebP poster.

## Verification before reporting back

There is no test suite. Run these instead:

```sh
# 1. Style/tell scan (exit 1 under --strict when any WARN exists)
python3 tools/tells.py --summary index.html about/index.html writing/*/index.html
python3 tools/tells.py --json writing/<slug>/index.html     # per-finding byte offsets

# 2. Serve and click through the pages at desktop + ~360px width
python3 -m http.server 8099

# 3. Bookkeeping actually matches the pages
grep -c '<url>' sitemap.xml            # one per route incl. posts and /about/
grep -o 'writing/[a-z0-9-]*/' feed.xml | sort -u
ls writing/*/index.html
```

`tells.py` flags, it never rewrites — fix the underlying sentence. NOTE-level
findings (em-dash density, for example) are expected in this house style and
are not violations.

If `html-validate` happens to be installed, running it over the changed pages is
welcome but not a repo requirement.

## Conventions worth matching

- Styling tokens live at the top of `assets/css/site.css` (`--bg`, `--surface`,
  `--ink`, `--body`, `--muted`, `--line`, `--accent`, `--ink-bg`, `--wrap`,
  `--radius`, …). Use them; do not hard-code hex colours in pages.
- Palette matches `shinro.dev`: dark canvas `#070A08` with signal `#2BE07A`;
  light canvas `#FAFAF9` with signal `#087A42`. Both colour schemes must work.
- Type: Geist 400–600 and Geist Mono 400–600, self-hosted latin subsets.
- Content voice: control-layer engineering, concrete numbers, no marketing
  filler. The posts carry the site's argument; the home page summarises it.
- Keep `README.md` in step when a workflow or layout detail changes.

## Known drift / gotchas

- `README.md`'s layout block still names *Inter, Space Grotesk, JetBrains Mono*;
  the site actually ships **Geist / Geist Mono**. The `## Type` section is
  correct. Fix the drift if you touch that file.
- `feed.xml` and `sitemap.xml` are hand-maintained except for the sitemap entry
  the converter appends — check both when adding or renaming a page.
- `writing/same-robot-same-brain/index.html` references figures under
  `assets/img/same-robot-same-brain/`, but that directory has been **untracked**
  in git (13 files, ~5 MB). Before debugging a "missing figure", run
  `git status` — it may simply not be committed.
- `soffice` (LibreOffice) is required only for `.docx` drafts and for GIF
  transcoding checks; `.odt` is parsed directly with `zipfile` + `ElementTree`.
- Repo lives at `/mnt/E/github-projects/shinro-dev.github.io`; remote is
  `git@github.com:shinro-dev/shinro-dev.github.io.git`.
