# shinro-dev.github.io

The Shinro organization site: a landing page, a writing index, and the
[Microduck write-up](https://shinro-dev.github.io/writing/same-robot-same-brain/).

Static HTML and one stylesheet. No build step, no framework, no analytics, no
third-party requests at runtime. GitHub Pages serves this directory directly
from `main` (`/` root), which is why `.nojekyll` is present.

## Layout

```
index.html                              home
writing/index.html                      post index
writing/same-robot-same-brain/index.html  the post
404.html                                not-found page
assets/
  css/site.css                          all styling
  js/site.js                            copy buttons, video toggle, TOC highlight
  fonts/*.woff2                         Inter, Space Grotesk, JetBrains Mono (latin)
  img/                                  figures, poster, demo video
robots.txt, sitemap.xml
tools/
  new-post.py                           .odt/.docx draft -> post
  templates/post.html                   page skeleton for the converter
```

## Preview locally

```sh
python3 -m http.server 8099
# http://localhost:8099
```

Paths are root-absolute (`/assets/...`), so serve from the repository root and
open `http://localhost:<port>/`, not the file path.

## Publishing

GitHub Pages must be enabled for the repository with **Source: Deploy from a
branch**, branch `main`, folder `/ (root)`. Pushing to `main` republishes the
site; there is no workflow to run.

## Adding a post

From a draft:

```sh
python3 tools/new-post.py --from ~/Desktop/draft.odt \
  --slug my-post --date 2026-10-20 --kicker "Systems note · 002"
```

The converter reads `.odt` directly and `.docx` through LibreOffice
(`soffice --convert-to odt`), then writes `writing/<slug>/index.html`,
`assets/img/<slug>/`, a new entry in `writing/index.html` (between the
`posts:start` / `posts:end` markers) and a URL in `sitemap.xml`. GIFs are
transcoded to MP4 with a WebP poster; `--video-scale 1` halves the video size.

What it converts: heading levels, paragraphs, quotes, lists, tables, inline
bold / italic / monospace runs, links and images (with intrinsic dimensions).
It hoists the first image to the post hero and takes an italic paragraph after
a figure as its caption.

What it does not do — it prints a `review:` list at the end: ASCII diagrams
(flagged when a preformatted block contains box-drawing characters), tables
that should become the comparison style, captions that are not italic, the
appendix cut (it stops at a heading starting with "Appendix"), and the
title/standfirst split. Those are editorial.

After conversion the HTML is the source of truth. Do not keep editing the
draft and re-running the converter against the same slug: hand edits live only
in the HTML. `--force` overwrites a post directory, media included.

By hand: keep the header, footer, `.post-layout`, `.toc` and `.prose`
structure; give every `<h2>` an `id`, add it to the `.toc` and number the
sections; update the index and sitemap. Keep figures on the site's own
assets — the site must not call out to third-party hosts.

## Provenance of the first post

The post was converted from `draft_post.updated.odt` (LibreOffice, 15 October
2026). The body is the author's text with light copy-editing (grammar and
punctuation only); the two ASCII diagrams were redrawn as an inline SVG and a
CSS step flow. The document's appendix — headline options and HN / X / Reddit /
LinkedIn drafts — is internal release material and is deliberately **not**
published.

Figures were extracted from the ODT: the two timeline PNGs are used as-is; the
demo GIF is transcoded to a 311 KB MP4 (with a WebP poster) so the page does not
ship a 2 MB GIF, and the GIF remains in the ODT as the source.

## Type

Self-hosted, latin subsets:

- **Geist** 400–600 — SIL Open Font License 1.1
- **Geist Mono** 400–600 — SIL Open Font License 1.1

The palette and the type match [shinro.dev](https://shinro.dev/): `#070A08` canvas,
`#2BE07A` signal green in dark; `#FAFAF9` canvas, `#087A42` signal in light; thin
`#1E2A24` / `#E4E6E4` borders and Geist everywhere.

## Licence

Site code and copy © Shinro SAS. The fonts are distributed under the SIL Open
Font License; the demo media is from the Microduck reference demo.
