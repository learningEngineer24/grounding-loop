#!/usr/bin/env python3
"""Convert a Grounding Loop markdown draft to a site HTML page.

Usage: convert_to_html.py <draft.md> <writings|projects> <slug> <out.html>
Applies the per-page link map for WRITEUP_DRAFT_PART*.md cross-links.
"""
import re
import sys
import html as htmllib

LINK_MAPS = {
    "grounding-loop-organization": {
        "WRITEUP_DRAFT_PART1.md": "../projects/grounding-loop.html",
        "WRITEUP_DRAFT_PART2.md": "../projects/grounding-loop-managing-drift.html",
    },
    "grounding-loop": {
        "WRITEUP_DRAFT_PART2.md": "grounding-loop-managing-drift.html",
        "WRITEUP_DRAFT_PART3.md": "../writings/grounding-loop-organization.html",
    },
    "grounding-loop-managing-drift": {
        "WRITEUP_DRAFT_PART1.md": "grounding-loop.html",
        "WRITEUP_DRAFT_PART3.md": "../writings/grounding-loop-organization.html",
    },
}

SVG_PATH = "/home/hatch/workspace/site-deploy/images/grounding-loop-feedback-loop.svg"


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, incode = [], "", False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            incode = not incode
            cur += ch
        elif ch == "|" and not incode:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def is_sep_row(line):
    cells = split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


class Converter:
    def __init__(self, slug):
        self.linkmap = LINK_MAPS[slug]
        self.slug = slug
        self.unmapped = []

    def inline(self, s):
        # Extract code spans first so inner markup is untouched
        codes = []

        def stash(m):
            codes.append("<code>" + htmllib.escape(m.group(1), quote=False) + "</code>")
            return "\x00CODE%d\x00" % (len(codes) - 1)

        s = re.sub(r"`([^`]+)`", stash, s)
        s = htmllib.escape(s, quote=False)

        def link_repl(m):
            text, url = m.group(1), m.group(2)
            if url in self.linkmap:
                url = self.linkmap[url]
            elif not url.startswith(("http://", "https://", "#", "mailto:")) and not url.endswith(".svg"):
                self.unmapped.append(url)
            return '<a href="%s">%s</a>' % (url, text)

        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link_repl, s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
        for i, code in enumerate(codes):
            s = s.replace("\x00CODE%d\x00" % i, code)
        return s

    def figure_for_svg(self, alt):
        with open(SVG_PATH) as f:
            svg = f.read()
        svg = re.sub(r"<\?xml[^?]*\?>\s*", "", svg)
        # add accessible label from alt text
        svg = svg.replace("<svg ", '<svg role="img" aria-label="%s" ' % htmllib.escape(alt, quote=True), 1)
        return '<figure class="diagram">\n' + svg.strip() + "\n</figure>"

    def convert(self, lines):
        out = []
        i, n = 0, len(lines)
        para = []

        def flush_para():
            if para:
                out.append("<p>" + self.inline(" ".join(para)) + "</p>")
                para.clear()

        while i < n:
            line = lines[i].rstrip("\n")
            s = line.strip()

            # Fenced code block
            if s.startswith("```"):
                flush_para()
                lang = s[3:].strip()
                buf = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    buf.append(lines[i].rstrip("\n"))
                    i += 1
                i += 1  # skip closing fence
                cls = ' class="language-%s"' % lang if lang else ""
                out.append("<pre><code%s>%s</code></pre>" % (cls, htmllib.escape("\n".join(buf), quote=False)))
                continue

            # Headings
            m = re.match(r"^(#{2,3})\s+(.*)$", s)
            if m:
                flush_para()
                level = len(m.group(1))
                out.append("<h%d>%s</h%d>" % (level, self.inline(m.group(2)), level))
                i += 1
                continue

            # Horizontal rule
            if s == "---":
                flush_para()
                out.append("<hr>")
                i += 1
                continue

            # Blockquote
            if s.startswith(">"):
                flush_para()
                buf = []
                while i < n and lines[i].strip().startswith(">"):
                    buf.append(lines[i].strip()[1:].strip())
                    i += 1
                out.append("<blockquote><p>" + self.inline(" ".join(buf)) + "</p></blockquote>")
                continue

            # Table
            if "|" in s and i + 1 < n and is_sep_row(lines[i + 1]):
                flush_para()
                header = split_row(s)
                i += 2
                rows = []
                while i < n and "|" in lines[i] and lines[i].strip():
                    rows.append(split_row(lines[i].strip()))
                    i += 1
                parts = ['<div class="table-scroll">', '<table class="mw-table">', "<thead>",
                         "<tr>" + "".join("<th>%s</th>" % self.inline(c) for c in header) + "</tr>",
                         "</thead>", "<tbody>"]
                for r in rows:
                    parts.append("<tr>" + "".join("<td>%s</td>" % self.inline(c) for c in r) + "</tr>")
                parts += ["</tbody>", "</table>", "</div>"]
                out.append("\n".join(parts))
                continue

            # Unordered list
            if re.match(r"^-\s+", s):
                flush_para()
                items = []
                while i < n and re.match(r"^-\s+", lines[i].strip()):
                    items.append(re.sub(r"^-\s+", "", lines[i].strip()))
                    i += 1
                out.append("<ul>\n" + "\n".join("<li>%s</li>" % self.inline(x) for x in items) + "\n</ul>")
                continue

            # Ordered list
            if re.match(r"^\d+\.\s+", s):
                flush_para()
                items = []
                while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                    items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                    i += 1
                out.append("<ol>\n" + "\n".join("<li>%s</li>" % self.inline(x) for x in items) + "\n</ol>")
                continue

            # Standalone image
            m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
            if m:
                flush_para()
                alt, src = m.group(1), m.group(2)
                if src.endswith("grounding-loop-feedback-loop.svg"):
                    out.append(self.figure_for_svg(alt))
                else:
                    out.append('<p><img src="%s" alt="%s"></p>' % (src, htmllib.escape(alt, quote=True)))
                i += 1
                continue

            # Blank line
            if not s:
                flush_para()
                i += 1
                continue

            # Metadata lines
            if s.startswith("**Status:**") or s.startswith("**Intended:**") or s.startswith("**Repo:**"):
                i += 1
                continue
            if s.startswith("**Series:**"):
                flush_para()
                out.append('<p class="series">' + self.inline(s) + "</p>")
                i += 1
                continue

            # Regular paragraph line
            para.append(s)
            i += 1

        flush_para()
        return "\n\n".join(out)


CLOUDFLARE = ("<!-- Cloudflare Web Analytics --><script type='module' "
              "src='https://static.cloudflareinsights.com/beacon.min.js' "
              "data-cf-beacon='{\"token\": \"4ad785e448f9467da46e966065a11e30\"}'>"
              "</script><!-- End Cloudflare Web Analytics -->")

WRITINGS_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Nebo Iwenofu</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://neboiwenofu.com/writings/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{title} — Nebo Iwenofu">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="https://neboiwenofu.com/writings/{slug}.html">
  <meta property="og:image" content="https://neboiwenofu.com/profile.jpg">
  <link rel="stylesheet" href="../styles.css">
  <style>
    .diagram svg {{ width: 100%; height: auto; display: block; }}
    .diagram {{ border: 1px solid var(--rule); padding: 1.25rem 1rem 0.5rem; background: #fbfbfa; }}
  </style>
</head>
<body>
<div class="wrap">

  <header class="site-header">
    <p class="site-name"><a href="../index.html">Nebo Iwenofu</a></p>
    <nav class="site-nav">
      <a href="../index.html">Home</a>
      <a href="../projects.html">Projects</a>
      <a href="../writing.html" aria-current="page">Writing</a>
      <a href="../reading.html">Reading</a>
    </nav>
  </header>

  <main>
    <article>
      <h1>{title}</h1>
      <p class="meta">October 2026</p>

{body}
    </article>
  </main>

  <footer class="site-footer">
    <p>
      <a href="mailto:neboiwenofu@gmail.com">neboiwenofu@gmail.com</a>
      · Built by hand, no framework.
    </p>
  </footer>

</div>
{cf} </body>
</html>
"""

PROJECTS_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Nebo Iwenofu</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://neboiwenofu.com/projects/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{title} — Nebo Iwenofu">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="https://neboiwenofu.com/projects/{slug}.html">
  <meta property="og:image" content="https://neboiwenofu.com/profile.jpg">
  <link rel="stylesheet" href="../styles.css">
</head>
<body>
<div class="wrap">

  <header class="site-header">
    <p class="site-name"><a href="../index.html">Nebo Iwenofu</a></p>
    <nav class="site-nav">
      <a href="../index.html">Home</a>
      <a href="../projects.html" aria-current="page">Projects</a>
      <a href="../writing.html">Writing</a>
      <a href="../reading.html">Reading</a>
    </nav>
  </header>

  <main>
    <article>
      <h1>{title}</h1>
      <div class="essay-meta">
        A public build · October 2026
        <br>
        <span class="tag">Data engineering</span><span class="tag">AI evaluation</span>
      </div>

{body}
    </article>
  </main>

  <footer class="site-footer">
    <p>
      <a href="mailto:neboiwenofu@gmail.com">neboiwenofu@gmail.com</a>
      · Built by hand, no framework.
    </p>
  </footer>

</div>
{cf} </body>
</html>
"""


def main():
    draft_path, section, slug, out_path = sys.argv[1:5]
    with open(draft_path) as f:
        lines = f.readlines()

    # Title is the first h1 line
    title = None
    body_lines = []
    for ln in lines:
        if title is None and ln.startswith("# "):
            title = ln[2:].strip()
            continue
        body_lines.append(ln)

    desc = sys.argv[5] if len(sys.argv) > 5 else title

    conv = Converter(slug)
    body = conv.convert(body_lines)

    template = WRITINGS_HEAD if section == "writings" else PROJECTS_HEAD
    page = template.format(title=title, desc=htmllib.escape(desc, quote=True),
                           slug=slug, body=body, cf=CLOUDFLARE)
    with open(out_path, "w") as f:
        f.write(page)

    print("wrote", out_path, "(%d bytes)" % len(page))
    if conv.unmapped:
        print("UNMAPPED RELATIVE LINKS:", sorted(set(conv.unmapped)))
    # sanity: no leftover draft filenames
    leftovers = re.findall(r"WRITEUP_DRAFT_PART\d\.md", page)
    if leftovers:
        print("LEFTOVER DRAFT LINKS:", leftovers)


if __name__ == "__main__":
    main()
