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

1. Create `writing/<slug>/index.html` by copying the existing post and keeping
   the header, footer, `.post-layout`, `.toc` and `.prose` structure.
2. Give every `<h2>` an `id`, add it to the `.toc` list, and number the sections
   with `<span class="n">01</span>`.
3. Add the entry to `writing/index.html` and to `sitemap.xml`.
4. Keep figures on the site's own assets — the site must not call out to
   third-party hosts.

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
