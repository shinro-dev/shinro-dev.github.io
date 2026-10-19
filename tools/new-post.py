#!/usr/bin/env python3
"""Convert an .odt / .docx draft into a post on the Shinro site.

Mechanical conversion only: headings, paragraphs, lists, tables, inline
marks (bold/italic/code), links and images. The editorial decisions that a
person still has to make are reported at the end — title/standfirst splits,
ASCII diagrams, figure captions, the appendix cut.

    python3 tools/new-post.py --from draft.odt --slug my-post \
        --title "..." --date 2026-10-20 --kicker "Systems note · 002"

Outputs:
    writing/<slug>/index.html
    assets/img/<slug>/*            (GIFs become MP4 + WebP poster)
    writing/index.html             (new entry at the top)
    sitemap.xml                    (new URL)
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parent.parent
ORIGIN = "https://shinro-dev.github.io"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "post.html"
WORDS_PER_MINUTE = 220

# --------------------------------------------------------------------------
# ODF plumbing
# --------------------------------------------------------------------------
NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(ns: str, tag: str) -> str:
    return "{%s}%s" % (NS[ns], tag)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attr(el, ns: str, tag: str):
    return el.get(q(ns, tag))


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr_esc(text: str) -> str:
    return html.escape(text, quote=True)


def text_of(el) -> str:
    """Plain text, preserving ODF line breaks, tabs and spaces."""
    parts = [el.text or ""]
    for child in el:
        tag = local(child.tag)
        if tag == "line-break":
            parts.append("\n")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "s":
            parts.append(" ")
        elif tag in ("frame", "soft-page-break"):
            parts.append("")
        else:
            parts.append(text_of(child))
        parts.append(child.tail or "")
    return "".join(parts)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "section"


# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------
class Styles:
    def __init__(self, roots):
        self.info: dict[str, dict] = {}
        for root in roots:
            for st in root.iter(q("style", "style")):
                name = attr(st, "style", "name")
                if not name:
                    continue
                info = self.info.setdefault(name, {})
                parent = attr(st, "style", "parent-style-name")
                if parent:
                    info["parent"] = parent
                display = attr(st, "style", "display-name")
                if display:
                    info["display"] = display
                props = st.find(q("style", "text-properties"))
                if props is not None:
                    for key, ns, name_attr in (
                        ("font", "style", "font-name"),
                        ("font-family", "fo", "font-family"),
                        ("weight", "fo", "font-weight"),
                        ("italic", "fo", "font-style"),
                    ):
                        value = attr(props, ns, name_attr)
                        if value:
                            info[key] = value

    def chain(self, name):
        out, seen = [], set()
        while name and name not in seen and len(out) < 10:
            out.append(name)
            seen.add(name)
            name = self.info.get(name, {}).get("parent")
        return out

    def prop(self, name, key):
        for item in self.chain(name):
            value = self.info.get(item, {}).get(key)
            if value:
                return value
        return None

    def heading_level(self, name):
        for item in self.chain(name):
            match = re.search(r"Heading_20_(\d)", item)
            if match:
                return int(match.group(1))
            display = self.info.get(item, {}).get("display", "")
            match = re.match(r"Heading (\d)", display)
            if match:
                return int(match.group(1))
            if item == "Title" or display == "Title":
                return 1
        return None

    def is_pre(self, name):
        return any(item.startswith("Preformatted") for item in self.chain(name))

    def is_quote(self, name):
        return any(
            item.startswith("Quotation") or item.startswith("Block_20_Text")
            for item in self.chain(name)
        )

    def inline_flags(self, name):
        font = ("%s %s" % (self.prop(name, "font") or "", self.prop(name, "font-family") or "")).lower()
        mono = any(token in font for token in ("mono", "courier", "consolas", "menlo"))
        weight = (self.prop(name, "weight") or "").lower()
        bold = weight in ("bold", "semibold", "bolder", "600", "700", "800", "900")
        italic = (self.prop(name, "italic") or "").lower() == "italic"
        return mono, bold, italic


# --------------------------------------------------------------------------
# Inline rendering
# --------------------------------------------------------------------------
def render_inline(el, styles, flags=(False, False, False)) -> str:
    out = [esc(el.text) if el.text else ""]
    for child in el:
        tag = local(child.tag)
        if tag == "span":
            merged = tuple(
                a or b
                for a, b in zip(flags, styles.inline_flags(attr(child, "text", "style-name")))
            )
            inner = render_inline(child, styles, merged)
            if merged[0] and not flags[0]:
                inner = "<code>%s</code>" % inner
            if merged[1] and not flags[1]:
                inner = "<strong>%s</strong>" % inner
            if merged[2] and not flags[2]:
                inner = "<em>%s</em>" % inner
            out.append(inner)
        elif tag == "a":
            href = attr(child, "xlink", "href")
            inner = render_inline(child, styles, flags)
            if href and not href.startswith("#"):
                out.append('<a href="%s">%s</a>' % (attr_esc(href), inner))
            else:
                out.append(inner)
        elif tag == "s":
            out.append(" ")
        elif tag == "tab":
            out.append("\t" if flags[0] else " ")
        elif tag == "line-break":
            out.append("\n" if flags[0] else "<br>")
        elif tag in ("frame", "soft-page-break", "bookmark", "bookmark-start", "bookmark-end"):
            pass
        else:
            out.append(render_inline(child, styles, flags))
        if child.tail:
            out.append(esc(child.tail))
    return "".join(out)


# --------------------------------------------------------------------------
# Media helpers
# --------------------------------------------------------------------------
def image_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return width, height
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + length
    return None


def transcode_gif(source: Path, outdir: Path, stem: str, report, scale=2):
    """GIF -> MP4 + WebP poster. Returns (video, poster, width, height)."""
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg:
        dest = outdir / (stem + ".gif")
        shutil.copyfile(source, dest)
        report.warn("ffmpeg not found — kept %s as a GIF" % dest.name)
        size = image_size(source.read_bytes()) or (None, None)
        return "/assets/img/%s/%s" % (outdir.name, dest.name), None, size[0], size[1]

    mp4 = outdir / (stem + ".mp4")
    poster = outdir / (stem + "-poster.webp")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-movflags", "+faststart",
            "-vf", "scale=trunc(iw*%d/2)*2:trunc(ih*%d/2)*2:flags=lanczos" % (scale, scale),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "slow", "-an",
            str(mp4),
        ],
        check=True,
    )

    duration = None
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(source)],
            capture_output=True, text=True,
        )
        try:
            duration = float(result.stdout.strip())
        except ValueError:
            duration = None

    frame_png = outdir / (stem + "-frame.png")
    seek = ["-ss", "%.1f" % (duration * 0.45)] if duration else []
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(source),
         "-frames:v", "1", "-vf", "scale=iw*2:-2:flags=lanczos", str(frame_png)],
        check=True,
    )
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(frame_png),
         "-q:v", "82", str(poster)],
        check=True,
    )
    frame_png.unlink(missing_ok=True)

    size = image_size(source.read_bytes()) or (0, 0)
    return (
        "/assets/img/%s/%s" % (outdir.name, mp4.name),
        "/assets/img/%s/%s" % (outdir.name, poster.name),
        ((size[0] * scale) // 2) * 2 or None,
        ((size[1] * scale) // 2) * 2 or None,
    )


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.notes = []
        self.warnings = []

    def note(self, message):
        self.notes.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def print(self):
        if self.notes:
            print("\nreview:")
            for note in self.notes:
                print("  - " + note)
        if self.warnings:
            print("\nwarnings:")
            for warning in self.warnings:
                print("  - " + warning)


class Converter:
    def __init__(self, args, styles, package, report, content_root):
        self.args = args
        self.styles = styles
        self.package = package
        self.report = report
        self.content_root = content_root
        self.blocks = []
        self.toc = []
        self.section = 0
        self.figures = 0
        self.figure_blocks = {}
        self.captioned = set()
        self.pending_figure = None
        self.used_ids = set()
        self.media_dir = REPO / "assets" / "img" / args.slug
        self.first_image = None
        self.headline_el = None

    # -- headings ---------------------------------------------------------
    def add_heading(self, el, level):
        text = text_of(el).strip()
        if not text:
            return
        if not self.args.keep_appendix and re.match(r"appendix\b", text, re.I):
            raise StopIteration(text)
        if level == 1:
            # The document H1 becomes the page headline, not body content.
            if self.headline_el is None:
                self.headline_el = el
            return
        html_text = render_inline(el, self.styles).strip()
        if level == 2:
            self.section += 1
            anchor = slugify(text)
            base, n = anchor, 2
            while anchor in self.used_ids:
                anchor = "%s-%d" % (base, n)
                n += 1
            self.used_ids.add(anchor)
            self.toc.append((anchor, text))
            self.blocks.append(
                '<h2 id="%s"><span class="n">%02d</span>%s</h2>' % (anchor, self.section, html_text)
            )
        elif level == 3:
            self.blocks.append("<h3>%s</h3>" % html_text)
        else:
            self.blocks.append("<h4>%s</h4>" % html_text)

    # -- paragraphs -------------------------------------------------------
    def add_paragraph(self, el):
        if any(True for _ in el.iter(q("draw", "frame"))):
            self.add_frames(el)
            if not text_of(el).strip():
                return
        if self.styles.is_pre(attr(el, "text", "style-name")):
            code = text_of(el).rstrip("\n")
            if self.blocks and self.blocks[-1].startswith("<pre>"):
                self.blocks[-1] = (
                    self.blocks[-1][: -len("</code></pre>")] + "\n" + esc(code) + "</code></pre>"
                )
            else:
                self.blocks.append("<pre><code>%s</code></pre>" % esc(code))
            if re.search(r"[┌└│├─═]", code):
                self.report.note("a preformatted block contains box-drawing characters — redraw it as a diagram")
            return

        if self.pending_figure is not None:
            if self.paragraph_is_italic(el):
                caption = render_inline(el, self.styles).strip()
                caption = re.sub(r"</?em>", "", caption)
                number = self.pending_figure
                marker = "<!--fig-%d-->" % number
                block = self.blocks[self.figure_blocks[number]]
                self.blocks[self.figure_blocks[number]] = block.replace(
                    marker,
                    "<figcaption><b>Fig. %d</b><span>%s</span></figcaption>" % (number, caption),
                )
                self.captioned.add(number)
                self.pending_figure = None
                return
            self.pending_figure = None

        if self.styles.is_quote(attr(el, "text", "style-name")):
            self.blocks.append("<blockquote><p>%s</p></blockquote>" % render_inline(el, self.styles).strip())
            return

        content = render_inline(el, self.styles).strip()
        if content:
            self.blocks.append("<p>%s</p>" % content)

    def paragraph_is_italic(self, el):
        if not text_of(el).strip():
            return False
        spans = [s for s in el.iter(q("text", "span")) if text_of(s).strip()]
        if not spans:
            return False
        return all(self.styles.inline_flags(attr(s, "text", "style-name"))[2] for s in spans)

    # -- lists ------------------------------------------------------------
    def list_is_ordered(self, el):
        name = attr(el, "text", "style-name")
        for style in self.content_root.iter(q("text", "list-style")):
            if attr(style, "style", "name") == name:
                return any(local(child.tag) == "list-level-style-number" for child in style)
        return False

    def add_list(self, el):
        ordered = self.list_is_ordered(el)
        tag = "ol" if ordered else "ul"
        items = []
        for item in el.findall(q("text", "list-item")):
            inner = []
            for child in item:
                child_tag = local(child.tag)
                if child_tag == "p":
                    inner.append(render_inline(child, self.styles).strip())
                elif child_tag == "list":
                    inner.append(self.render_list(child))
                elif child_tag == "h":
                    inner.append(render_inline(child, self.styles).strip())
            body = "\n".join(part for part in inner if part)
            if body:
                items.append("<li>%s</li>" % body)
        if items:
            self.blocks.append("<%s>\n%s\n</%s>" % (tag, "\n".join(items), tag))

    def render_list(self, el):
        before = len(self.blocks)
        self.add_list(el)
        if len(self.blocks) == before:
            return ""
        rendered = self.blocks.pop()
        tag = "ol" if rendered.startswith("<ol>") else "ul"
        inner = rendered[len("<%s>\n" % tag) : -len("\n</%s>" % tag)]
        return "<%s>%s</%s>" % (tag, inner, tag)

    # -- tables -----------------------------------------------------------
    def add_table(self, el):
        rows = list(el.iter(q("table", "table-row")))
        if not rows:
            return
        has_header = el.find(q("table", "table-header-rows")) is not None
        header_rows = 0
        if has_header:
            header_rows = sum(
                1 for row in rows if row in list(el.find(q("table", "table-header-rows")))
            )
        html_rows = []
        for index, row in enumerate(rows):
            cells = []
            for cell in row:
                if local(cell.tag) not in ("table-cell", "covered-table-cell"):
                    continue
                parts = []
                for child in cell:
                    tag = local(child.tag)
                    if tag == "p":
                        parts.append(render_inline(child, self.styles).strip())
                    elif tag == "list":
                        parts.append(self.render_list(child))
                cells.append("<br>".join(part for part in parts if part))
            if not cells:
                continue
            cell_tag = "th" if header_rows and index < header_rows else "td"
            html_rows.append(
                "<tr>%s</tr>" % "".join("<%s>%s</%s>" % (cell_tag, c, cell_tag) for c in cells)
            )
        head = ""
        body = html_rows
        if header_rows:
            head = "<thead>%s</thead>" % "".join(html_rows[:header_rows])
            body = html_rows[header_rows:]
        self.blocks.append(
            '<div class="table-wrap"><table class="data">%s<tbody>%s</tbody></table></div>'
            % (head, "".join(body))
        )
        self.report.note("a table was emitted as .data — switch to .compare if it is a comparison")

    # -- images -----------------------------------------------------------
    def add_frames(self, el):
        for frame in el.iter(q("draw", "frame")):
            image = frame.find(q("draw", "image"))
            if image is None:
                continue
            href = attr(image, "xlink", "href")
            if not href:
                continue
            self.figures += 1
            number = self.figures
            self.media_dir.mkdir(parents=True, exist_ok=True)
            data = self.package.read(href)
            stem = "figure-%02d" % number
            suffix = Path(href).suffix.lower()
            alt_node = frame.find(q("svg", "title"))
            alt = (text_of(alt_node).strip() if alt_node is not None else "") or ""
            is_gif = data[:6] in (b"GIF87a", b"GIF89a") or suffix == ".gif"

            if is_gif:
                source = self.media_dir / (stem + ".gif")
                source.write_bytes(data)
                video, poster, width, height = transcode_gif(
                    source, self.media_dir, stem, self.report, self.args.video_scale
                )
                source.unlink(missing_ok=True)
                dims = ' width="%s" height="%s"' % (width, height) if width else ""
                media = (
                    '<div class="fig-media">\n'
                    '  <video loop muted playsinline preload="none" poster="%s"%s>\n'
                    '    <source src="%s" type="video/mp4">\n'
                    '    <img src="%s"%s alt="%s">\n'
                    "  </video>\n"
                    '  <button class="video-toggle" type="button" data-video-toggle aria-label="Play the video">Play</button>\n'
                    "</div>"
                    % (poster, dims, video, poster, dims, attr_esc(alt))
                )
                if not self.first_image:
                    self.first_image = poster
            else:
                suffix = suffix if suffix in (".png", ".jpg", ".jpeg", ".webp", ".svg") else ".png"
                dest = self.media_dir / (stem + suffix)
                dest.write_bytes(data)
                src = "/assets/img/%s/%s" % (self.args.slug, dest.name)
                size = image_size(data)
                dims = ' width="%d" height="%d"' % size if size else ""
                media = '<div class="fig-media"><img src="%s"%s loading="lazy" alt="%s"></div>' % (
                    src, dims, attr_esc(alt)
                )
                if not self.first_image:
                    self.first_image = src

            self.blocks.append('<figure class="fig">\n%s\n<!--fig-%d-->\n</figure>' % (media, number))
            self.figure_blocks[number] = len(self.blocks) - 1
            self.pending_figure = number

    # -- driver -----------------------------------------------------------
    def run(self, body):
        try:
            for child in body:
                tag = local(child.tag)
                if tag == "h":
                    self.add_heading(child, self.styles.heading_level(attr(child, "text", "style-name")) or 2)
                elif tag == "p":
                    self.add_paragraph(child)
                elif tag == "list":
                    self.add_list(child)
                elif tag == "table":
                    self.add_table(child)
                elif tag == "frame":
                    self.add_frames(child)
                elif tag == "section":
                    for grandchild in child:
                        if local(grandchild.tag) == "p":
                            self.add_paragraph(grandchild)
                        elif local(grandchild.tag) == "h":
                            self.add_heading(grandchild, self.styles.heading_level(
                                attr(grandchild, "text", "style-name")) or 2)
        except StopIteration as stop:
            self.report.note("stopped at %r — marketing notes not published" % stop.args[0])
        return self.blocks


# --------------------------------------------------------------------------
# Site updates
# --------------------------------------------------------------------------
def update_index(slug, headline, description, date, reading):
    index = REPO / "writing" / "index.html"
    text = index.read_text(encoding="utf-8")
    marker = "<!-- posts:start -->"
    if marker not in text:
        raise SystemExit("error: writing/index.html is missing the %s marker" % marker)
    item = (
        "\n      <li>\n"
        '        <a href="/writing/%s/">\n'
        '          <span class="date"><time datetime="%s">%d %s %d · %d min</time></span>\n'
        "          <div>\n"
        "            <h3>%s</h3>\n"
        "            <p>%s</p>\n"
        "          </div>\n"
        "        </a>\n"
        "      </li>"
        % (
            slug, date.isoformat(), date.day, date.strftime("%b"), date.year, reading,
            html.escape(headline, quote=False), html.escape(description, quote=False),
        )
    )
    index.write_text(text.replace(marker, marker + item, 1), encoding="utf-8")


def update_sitemap(slug, date):
    sitemap = REPO / "sitemap.xml"
    text = sitemap.read_text(encoding="utf-8")
    entry = (
        "  <url>\n"
        "    <loc>%s/writing/%s/</loc>\n"
        "    <lastmod>%s</lastmod>\n"
        "    <priority>0.8</priority>\n"
        "  </url>\n" % (ORIGIN, slug, date.isoformat())
    )
    sitemap.write_text(text.replace("</urlset>", entry + "</urlset>"), encoding="utf-8")


def check_links(page):
    text = page.read_text(encoding="utf-8")
    missing = []
    for match in re.finditer(r'(?:href|src)="(/[^"#?]*)"', text):
        url = match.group(1)
        path = REPO / url.lstrip("/")
        if url.endswith("/"):
            path = path / "index.html"
        if not path.exists():
            missing.append(url)
    return sorted(set(missing))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def to_odt(path, workdir):
    if path.suffix.lower() == ".odt":
        return path
    if path.suffix.lower() == ".docx":
        if not shutil.which("soffice"):
            sys.exit("error: .docx needs LibreOffice (soffice) to convert to ODT first")
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "odt", "--outdir", str(workdir), str(path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        converted = sorted(workdir.glob("*.odt"))
        if not converted:
            sys.exit("error: LibreOffice did not produce an .odt")
        return converted[0]
    sys.exit("error: expected an .odt or .docx file")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--from", dest="source", required=True, help=".odt or .docx draft")
    parser.add_argument("--slug", required=True, help="URL slug, e.g. same-robot-same-brain")
    parser.add_argument("--title", help="headline (default: the document's H1)")
    parser.add_argument("--subtitle", help="line under the headline")
    parser.add_argument("--lede", help="standfirst (default: the document's first paragraph)")
    parser.add_argument("--description", help="meta description (default: the lede, truncated)")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--kicker", default="Systems note", help='e.g. "Systems note · 002"')
    parser.add_argument("--tags", default="Cake · Robotics", help='meta line tags, e.g. "Cake · Robotics"')
    parser.add_argument("--no-split-title", action="store_true", help="do not split the headline at the first colon")
    parser.add_argument("--keep-appendix", action="store_true", help="keep everything after an Appendix heading")
    parser.add_argument("--no-index", action="store_true", help="do not touch writing/index.html or sitemap.xml")
    parser.add_argument("--video-scale", type=int, choices=(1, 2), default=2,
                        help="GIF -> MP4 upscale factor (2 = retina-friendly, default)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing post")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
        sys.exit("error: --slug must be lowercase letters, digits and hyphens")
    try:
        date = dt.date.fromisoformat(args.date)
    except ValueError:
        sys.exit("error: --date must be YYYY-MM-DD")
    if not TEMPLATE.exists():
        sys.exit("error: missing template %s" % TEMPLATE)

    target = REPO / "writing" / args.slug
    if target.exists() and not args.force:
        sys.exit("error: %s exists (use --force)" % target.relative_to(REPO))

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        sys.exit("error: %s not found" % source)

    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        odt = to_odt(source, Path(tmp))
        with zipfile.ZipFile(odt) as package:
            content_root = ET.fromstring(package.read("content.xml"))
            styles_root = ET.fromstring(package.read("styles.xml"))
            body = content_root.find(q("office", "body")).find(q("office", "text"))
            styles = Styles((content_root, styles_root))

            converter = Converter(args, styles, package, report, content_root)
            blocks = converter.run(body)

            headline = args.title or (text_of(converter.headline_el).strip() if converter.headline_el is not None else None)
            if not headline:
                sys.exit(
                    "error: no headline — the document has no H1/Title. "
                    "Pass --title, or check that it is a formatted document "
                    "(plain text or Markdown pasted into Word has no heading styles)."
                )
            headline = re.sub(r"\s+", " ", headline).strip()
            subtitle = re.sub(r"\s+", " ", args.subtitle or "").strip()
            if not subtitle and not args.no_split_title and ": " in headline:
                headline, subtitle = (part.strip() for part in headline.split(": ", 1))
                if subtitle[:1].islower():
                    subtitle = subtitle[:1].upper() + subtitle[1:]
                    report.note("subtitle capitalised")
                report.note("headline split at the first colon — check the wording")

            lede = args.lede
            if not lede and blocks and blocks[0].startswith("<p>"):
                block = blocks.pop(0)
                lede = html.unescape(re.sub(r"<[^>]+>", "", block))
                report.note("lede taken from the first paragraph — check it reads as a standfirst")
            lede = lede or ""

            hero = ""
            if blocks and blocks[0].startswith("<figure"):
                figure = blocks.pop(0).replace('<figure class="fig">', '<figure class="fig post-hero">', 1)
                hero = '<div class="wrap">\n%s\n</div>\n' % figure
            else:
                report.note("no lead figure — the post starts with text")

            for number in range(1, converter.figures + 1):
                if number not in converter.captioned:
                    report.note("figure %d has no caption (an italic paragraph after the figure becomes one)" % number)

            body_html = "\n".join(blocks)
            words = len(re.sub(r"<[^>]+>", " ", body_html).split())
            reading = max(1, math.ceil(words / WORDS_PER_MINUTE))
            toc = "\n".join(
                '        <li><a href="#%s">%s</a></li>' % (anchor, esc(label))
                for anchor, label in converter.toc
            )

            description = args.description or re.sub(r"<[^>]+>", "", lede)
            if len(description) > 160:
                description = description[:157].rsplit(" ", 1)[0] + "…"

            og_image, jsonld_image = "", ""
            if converter.first_image:
                url = ORIGIN + converter.first_image
                og_image = '<meta property="og:image" content="%s">\n' % url
                jsonld_image = '  "image": "%s",\n' % url

            tags = [tag.strip() for tag in args.tags.split("·") if tag.strip()]
            article_tags = "".join(
                '<meta property="article:tag" content="%s">\n' % attr_esc(tag) for tag in tags
            )
            meta_tags = "".join(
                '        <span class="sep" aria-hidden="true">·</span>\n        <span>%s</span>\n' % esc(tag)
                for tag in tags
            )

            values = {
                "TITLE": attr_esc(headline),
                "HEADLINE": esc(headline),
                "SUBTITLE_BLOCK": ('        <span class="h1-sub">%s</span>\n' % esc(subtitle)) if subtitle else "",
                "LEDE": esc(lede),
                "DESCRIPTION": attr_esc(description),
                "SLUG": args.slug,
                "DATE_ISO": date.isoformat(),
                "DATE_DISPLAY": "%d %s %d" % (date.day, date.strftime("%B"), date.year),
                "KICKER": esc(args.kicker),
                "READING_TIME": str(reading),
                "META_TAGS": meta_tags,
                "ARTICLE_TAGS": article_tags,
                "OG_IMAGE_META": og_image,
                "JSONLD_IMAGE": jsonld_image,
                "HERO": hero,
                "TOC": toc,
                "BODY": body_html,
            }

            page = TEMPLATE.read_text(encoding="utf-8")
            for key, value in values.items():
                page = page.replace("{{%s}}" % key, value)

            target.mkdir(parents=True, exist_ok=True)
            (target / "index.html").write_text(page, encoding="utf-8")

            if not args.no_index:
                update_index(args.slug, headline, description, date, reading)
                update_sitemap(args.slug, date)

            for item in check_links(target / "index.html"):
                report.warn("missing target: %s" % item)
            if "<h1>" not in page:
                report.warn("no <h1> in the generated page")

            print("wrote writing/%s/index.html (%d words, ~%d min)" % (args.slug, words, reading))
            media = sorted(p.name for p in (REPO / "assets" / "img" / args.slug).glob("*"))
            if media:
                print("media: " + ", ".join(media))
            if not args.no_index:
                print("updated writing/index.html and sitemap.xml")
            report.print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
