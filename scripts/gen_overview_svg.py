"""Generate docs/images/opm-overview.svg — an animated explainer of opm.

Usage: python scripts/gen_overview_svg.py docs/images/opm-overview.svg
Scene lengths are set in DUR; offsets inside a scene use at(scene, seconds).
Classes, ids and keyframes are prefixed (opm-ov / opmov-) because
docs/javascripts/opm-overview.js inlines the SVG into the page.
"""
from html import escape as esc

DUR = [8.0, 9.0, 11.0, 10.0, 8.0]   # seconds per scene
START = [sum(DUR[:i]) for i in range(len(DUR))]
D = sum(DUR)                         # loop length (s)
ORANGE = "#F5A623"
INK = "#ECECF1"
MUTED = "#9A9BB0"
PANEL = "#2A2C38"
LINE = "#3B3E4E"
BG = "#21222C"
BLUE = "#8EC5FF"
GREEN = "#B5E08A"

kf = []
_n = [0]


def pct(t):
    return round(max(0.0, min(D, t)) / D * 100, 3)


def show(t0, t1, fade=0.35, dx=0, dy=0, sc=None):
    """class name: element fades (and slides) in at t0, out at t1."""
    _n[0] += 1
    name = f"opmov-a{_n[0]}"
    hid = "opacity:0"
    tr0 = []
    if dx or dy:
        tr0.append(f"translate({dx}px,{dy}px)")
    if sc:
        tr0.append(f"scale({sc})")
    if tr0:
        hid += ";transform:" + " ".join(tr0)
        vis = "opacity:1;transform:none"
    else:
        vis = "opacity:1"
    out = "opacity:0" + (";transform:none" if tr0 else "")
    steps = []
    if t0 > 0:
        steps += [(0, hid), (pct(t0), hid)]
    else:
        steps += [(0, hid)]
    steps += [(pct(t0 + fade), vis), (pct(t1 - fade), vis), (pct(t1), out)]
    if t1 < D:
        steps.append((100, out))
    body = "".join(f"{p}%{{{s}}}" for p, s in steps)
    kf.append(f"@keyframes {name}{{{body}}}.{name}{{animation:{name} {D}s linear infinite}}")
    return f"opmov-anim {name}"


def g(cls, inner, x=0, y=0):
    """animated group; positioned by an outer translate so CSS transform is free."""
    if x or y:
        return f'<g transform="translate({x},{y})"><g class="{cls}">{inner}</g></g>'
    return f'<g class="{cls}">{inner}</g>'


def rect(x, y, w, h, rx=6, fill=PANEL, stroke=None, sw=1, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s} {extra}/>'


def text(x, y, s, size=13, fill=INK, weight=400, anchor="start", cls="", mono=False, raw=False):
    fam = ' class="opmov-mono"' if mono else ""
    if cls:
        fam = f' class="{cls}{" opmov-mono" if mono else ""}"'
    content = s if raw else esc(s)
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{fam}>{content}</text>')


def bars(x, y, widths, gap=9, h=4, fill=LINE):
    return "".join(rect(x, y + i * gap, w, h, rx=2, fill=fill) for i, w in enumerate(widths))


def chip(x, y, label, fill=ORANGE, color=BG, size=11, pad=8, w=None):
    w = w or (len(label) * size * 0.6 + 2 * pad)
    return rect(x, y, w, size + 10, rx=(size + 10) / 2, fill=fill) + text(
        x + w / 2, y + size + 3, label, size=size, fill=color, weight=600, anchor="middle")


def sheet(x, y, w, h, fill=PANEL, stroke=LINE, fold=14):
    return (f'<path d="M{x} {y+4} q0 -4 4 -4 H{x+w-fold} L{x+w} {y+fold} V{y+h-4} q0 4 -4 4 H{x+4} '
            f'q-4 0 -4 -4 Z" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
            f'<path d="M{x+w-fold} {y} V{y+fold} H{x+w}" fill="none" stroke="{stroke}" stroke-width="1.2"/>')


def scene_range(i):
    return START[i], START[i] + DUR[i]


def at(i, off):
    """absolute time of an offset (s) within scene i"""
    return START[i] + off


def end(i):
    return START[i] + DUR[i]


parts = []
add = parts.append

# ---------------------------------------------------------------- frame
add(rect(0, 0, 1000, 492, rx=20, fill=BG))
add('<defs>'
    '<marker id="opmov-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{ORANGE}"/></marker>'
    '<marker id="opmov-arrm" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker>'
    '<radialGradient id="opmov-glow"><stop offset="0" stop-color="#F5A623" stop-opacity=".45"/>'
    '<stop offset="1" stop-color="#F5A623" stop-opacity="0"/></radialGradient>'
    '</defs>')

# header: logo + name
add('<g transform="translate(32,18) scale(0.5)">'
    '<rect x="2" y="2" width="60" height="60" rx="14" fill="#2F3140"/>'
    f'<path d="M28 17 L15 32 L28 47" fill="none" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    f'<rect x="34" y="20" width="17" height="4.6" rx="2.3" fill="{INK}"/>'
    f'<rect x="34" y="29.7" width="17" height="4.6" rx="2.3" fill="{ORANGE}"/>'
    f'<rect x="34" y="39.4" width="11" height="4.6" rx="2.3" fill="{INK}"/></g>')
add(text(74, 41, "opm", size=20, weight=700))
add(text(126, 41, "Open Processing Model", size=13, fill=MUTED))

# step pills
steps = ["Describe", "Transform", "Chunk", "Publish", "Integrate"]
px0, pw, pg = 336, 120, 8
for i, s in enumerate(steps):
    x = px0 + i * (pw + pg)
    add(f'<g class="opmov-step" data-scene="{i}" data-label="{s}">')
    add(rect(x, 22, pw, 28, rx=14, fill="#2A2C38"))
    add(text(x + pw / 2, 41, f"{i+1}  {s}", size=12.5, fill=MUTED, weight=500, anchor="middle"))
    t0, t1 = scene_range(i)
    add(g(show(t0, t1, fade=0.3) + " opmov-pill",
          rect(x, 22, pw, 28, rx=14, fill=ORANGE)
          + text(x + pw / 2, 41, f"{i+1}  {s}", size=12.5, fill=BG, weight=700, anchor="middle")))
    add('</g>')
# progress bar
add(rect(32, 64, 936, 3, rx=1.5, fill="#2A2C38"))
add(f'<rect class="opmov-progress" data-role="progress" x="32" y="64" width="936" height="3" rx="1.5" fill="{ORANGE}"/>')

# ---------------------------------------------------------------- left column (persistent)
# sources stack
add(sheet(64, 92, 112, 140, fill="#262835"))
add(sheet(54, 100, 112, 140, fill="#282A37"))
src = sheet(44, 108, 112, 140)
src += text(56, 134, "<TEI>", size=12, fill=ORANGE, mono=True)
src += bars(64, 146, [70, 56, 76, 48, 66, 40], gap=10)
src += text(56, 216, "</TEI>", size=12, fill=ORANGE, mono=True)
add(src)
add(chip(40, 256, "TEI", fill="#343747", color=INK, size=10.5))
add(chip(80, 256, "DocBook", fill="#343747", color=INK, size=10.5))
add(chip(146, 256, "JATS", fill="#343747", color=INK, size=10.5))
add(text(44, 298, "XML sources", size=12.5, fill=MUTED, weight=600))

# ODD card
odd = sheet(44, 318, 112, 102)
odd += text(56, 342, "my.odd", size=12, fill=INK, weight=700, mono=True)
odd += text(56, 362, "<model", size=10.5, fill=ORANGE, mono=True)
odd += text(102, 362, "…/>", size=10.5, fill=MUTED, mono=True)
odd += bars(64, 372, [62, 48], gap=9)
odd += text(56, 404, "<model", size=10.5, fill=ORANGE, mono=True)
odd += text(102, 404, "…/>", size=10.5, fill=MUTED, mono=True)
add(odd)
add(text(44, 442, "ODD · processing model", size=12.5, fill=MUTED, weight=600))

# highlights on left column
add(g(show(*scene_range(0)) + " opmov-hl", rect(38, 312, 124, 114, rx=8, fill="none", stroke=ORANGE, sw=2)))
add(g(show(START[1], end(2)) + " opmov-hl", rect(38, 86, 134, 168, rx=8, fill="none", stroke=ORANGE, sw=2)))

# connectors into the core
add(f'<path d="M168 170 C205 170 200 248 236 250" fill="none" stroke="{LINE}" stroke-width="2"/>')
add(f'<path d="M160 369 C205 369 200 282 236 280" fill="none" stroke="{LINE}" stroke-width="2"/>')
add(f'<path class="opmov-flow" d="M168 170 C205 170 200 248 236 250" fill="none" stroke="{ORANGE}" stroke-width="2"/>')
add(f'<path class="opmov-flow" d="M160 369 C205 369 200 282 236 280" fill="none" stroke="{ORANGE}" stroke-width="2"/>')
add(text(196, 336, "compile", size=10.5, fill=MUTED, anchor="middle", mono=True))

# core
add('<circle class="opmov-corepulse" cx="286" cy="265" r="78" fill="url(#opmov-glow)"/>')
add('<g transform="translate(238,217) scale(1.5)">'
    '<rect x="2" y="2" width="60" height="60" rx="14" fill="#2F3140" stroke="#F5A623" stroke-opacity=".6" stroke-width="1"/>'
    f'<path d="M28 17 L15 32 L28 47" fill="none" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    f'<rect x="34" y="20" width="17" height="4.6" rx="2.3" fill="{INK}"/>'
    f'<rect class="opmov-corebar" x="34" y="29.7" width="17" height="4.6" rx="2.3" fill="{ORANGE}"/>'
    f'<rect x="34" y="39.4" width="11" height="4.6" rx="2.3" fill="{INK}"/></g>')
add(text(286, 350, "opm", size=15, weight=700, anchor="middle"))
add(text(286, 368, "Python · no database", size=10.5, fill=MUTED, anchor="middle"))

# core -> stage
add(f'<path d="M338 265 L392 265" fill="none" stroke="{LINE}" stroke-width="2" marker-end="url(#opmov-arr)"/>')
add(f'<path class="opmov-flow" d="M338 265 L388 265" fill="none" stroke="{ORANGE}" stroke-width="2"/>')

# ---------------------------------------------------------------- stage
SX, SY, SW, SH = 400, 86, 568, 384
add(rect(SX, SY, SW, SH, rx=14, fill="#252733", stroke="#2F3242"))


def stage(i, inner):
    t0, t1 = scene_range(i)
    add(f'<g transform="translate({SX},{SY})"><g class="{show(t0, t1, fade=0.4)} opmov-scene opmov-s{i}">{inner}</g></g>')


def cmd(s):
    return ""


# ---- Scene 0: Describe ---------------------------------------------------
E = end(0)
sc = []
sc.append(text(20, 26, "Describe each element once …", size=12, fill=MUTED, weight=600))
odd_lines = [
    ('<tspan fill="#F5A623">&lt;elementSpec</tspan> <tspan fill="#8EC5FF">ident</tspan>=<tspan fill="#B5E08A">"persName"</tspan><tspan fill="#F5A623">&gt;</tspan>', 0),
    ('<tspan fill="#F5A623">&lt;model</tspan> <tspan fill="#8EC5FF">behaviour</tspan>=<tspan fill="#B5E08A">"link"</tspan><tspan fill="#F5A623">&gt;</tspan>', 1),
    ('<tspan fill="#F5A623">&lt;param</tspan> <tspan fill="#8EC5FF">name</tspan>=<tspan fill="#B5E08A">"uri"</tspan>', 2),
    ('       <tspan fill="#8EC5FF">value</tspan>=<tspan fill="#B5E08A">"@ref"</tspan><tspan fill="#F5A623">/&gt;</tspan>', 2),
    ('<tspan fill="#F5A623">&lt;/model&gt;</tspan>', 1),
    ('<tspan fill="#F5A623">&lt;/elementSpec&gt;</tspan>', 0),
]
p = rect(16, 40, 268, 236, rx=10, fill=PANEL, stroke=LINE)
p += text(30, 62, "persons.odd", size=11, fill=MUTED, weight=600, mono=True)
for i, (ln, ind) in enumerate(odd_lines):
    p += g(show(at(0, 0.5 + i * 0.17), E, fade=0.25, dx=-6),
           text(30 + ind * 12, 86 + i * 20, ln, size=11, fill=INK, mono=True, raw=True)
           .replace('<text ', '<text xml:space="preserve" '))
sc.append(g(show(at(0, 0.2), E), p))
# TEI input fragment
ti = rect(16, 292, 268, 72, rx=10, fill=PANEL, stroke=LINE)
ti += text(30, 314, "letter-12.xml", size=11, fill=MUTED, weight=600, mono=True)
ti += text(30, 338, '<tspan fill="#F5A623">&lt;persName</tspan> <tspan fill="#8EC5FF">ref</tspan>=<tspan fill="#B5E08A">"#serafin"</tspan><tspan fill="#F5A623">&gt;</tspan>', size=11, fill=INK, mono=True, raw=True)
ti += text(42, 354, '<tspan>Mikołaj Serafin</tspan><tspan fill="#F5A623">&lt;/persName&gt;</tspan>', size=11, fill=INK, mono=True, raw=True)
sc.append(g(show(at(0, 2.2), E, dy=8), ti))
# arrows into the renderer
sc.append(g(show(at(0, 2.9), E, dx=-8),
            f'<path d="M290 158 L322 158" stroke="{ORANGE}" stroke-width="2.5" marker-end="url(#opmov-arr)"/>'
            + f'<path d="M290 328 L322 328" stroke="{ORANGE}" stroke-width="2.5" marker-end="url(#opmov-arr)"/>'
            + text(306, 146, "rule", size=10, fill=ORANGE, anchor="middle", mono=True)
            + text(306, 316, "input", size=10, fill=ORANGE, anchor="middle", mono=True)))
# rendered output
p = rect(330, 40, 222, 324, rx=10, fill=PANEL, stroke=LINE)
p += text(344, 62, "rendered output", size=11, fill=MUTED, weight=600)
p += rect(344, 74, 194, 276, rx=4, fill="#F7F5F0")
p += text(358, 100, "No. 12 · Kraków", size=13, fill="#2B2420", weight=700)
p += bars(358, 114, [166, 150, 160], gap=11, h=4, fill="#C9C2B6")
p += text(358, 160, "Letter to", size=13, fill="#2B2420")
paper = (f'<text x="418" y="160" font-size="13" fill="#C2410C" font-weight="600" '
         f'text-decoration="underline">Mikołaj Serafin</text>')
p += bars(358, 172, [160, 166, 120, 158, 140, 166, 100], gap=11, h=4, fill="#C9C2B6")
sc.append(g(show(at(0, 3.3), E, dx=-10), p))
sc.append(g(show(at(0, 4.1), E), paper
            + rect(414, 146, 112, 20, rx=4, fill="none", stroke=ORANGE, sw=1.5)))
tip = (rect(402, 260, 124, 30, rx=6, fill="#2B2420")
       + f'<path d="M464 260 L470 252 L476 260 Z" fill="#2B2420"/>'
       + text(412, 279, "link →", size=10, fill="#F7F5F0", mono=True)
       + text(458, 279, "#serafin", size=10, fill="#F5A623", mono=True))
sc.append(g(show(at(0, 5.0), E, dy=6), tip))
sc.append(g(show(at(0, 5.0), E),
            f'<path d="M470 168 L470 250" stroke="{ORANGE}" stroke-width="1.4" stroke-dasharray="3 3"/>'))
stage(0, "".join(sc))

# ---- Scene 1: Transform — one document in, one file out --------------------
E = end(1)
sc = [text(20, 26, "Cross-media publishing", size=12, fill=MUTED, weight=600),
      cmd("$ opm transform letter.xml -t <format>")]
doc = sheet(20, 150, 84, 104) + text(32, 174, "<TEI>", size=11, fill=ORANGE, mono=True) + bars(36, 186, [52, 40, 56, 34, 46], gap=10)
doc += text(62, 274, "letter.xml", size=10.5, fill=MUTED, anchor="middle", mono=True)
sc.append(g(show(at(1, 0.3), E), doc))
cols = [146, 284, 422]
rows = [44, 212]
W, H = 126, 150


def card(x, y, label, sub, inner):
    return (rect(x, y, W, H, rx=10, fill=PANEL, stroke=LINE) + inner
            + text(x + W / 2, y + H - 26, label, size=13, weight=700, anchor="middle")
            + text(x + W / 2, y + H - 10, sub, size=10, fill=MUTED, anchor="middle"))


def html_icon(x, y):
    return (rect(x + 18, y + 14, 90, 70, rx=5, fill="#343747") + rect(x + 18, y + 14, 90, 12, rx=5, fill="#3E4153")
            + "".join(f'<circle cx="{x+26+i*7}" cy="{y+20}" r="2" fill="{c}"/>' for i, c in enumerate([ORANGE, MUTED, MUTED]))
            + rect(x + 26, y + 34, 74, 6, rx=3, fill=ORANGE) + bars(x + 26, y + 46, [70, 60, 66, 40], gap=8, h=3, fill="#555869"))


def pdf_icon(x, y):
    return (sheet(x + 34, y + 10, 58, 76, fill="#ECECF1", stroke="#ECECF1", fold=10)
            + rect(x + 42, y + 24, 34, 5, rx=2, fill="#21222C") + bars(x + 42, y + 36, [42, 38, 42, 30, 40], gap=8, h=3, fill="#9A9BB0")
            + chip(x + 70, y + 66, "PDF", fill="#E0533D", color="#fff", size=9, pad=5))


def epub_icon(x, y):
    return (rect(x + 38, y + 8, 50, 80, rx=8, fill="#343747", stroke="#555869")
            + rect(x + 44, y + 16, 38, 58, rx=2, fill="#ECECF1") + bars(x + 48, y + 22, [30, 26, 30, 22, 28, 18], gap=8, h=3, fill="#9A9BB0")
            + f'<circle cx="{x+63}" cy="{y+81}" r="3" fill="#555869"/>')


def word_icon(x, y):
    return (sheet(x + 38, y + 10, 58, 76, fill="#ECECF1", stroke="#ECECF1", fold=10)
            + bars(x + 50, y + 24, [38, 34, 38, 26, 36, 30], gap=8, h=3, fill="#9A9BB0")
            + rect(x + 26, y + 36, 26, 26, rx=4, fill="#2B6CD4") + text(x + 39, y + 55, "W", size=15, fill="#fff", weight=800, anchor="middle"))


def md_icon(x, y):
    return (rect(x + 16, y + 12, 94, 74, rx=6, fill="#343747")
            + text(x + 24, y + 32, "# Letter", size=11, fill=ORANGE, mono=True)
            + text(x + 24, y + 50, "**M. Serafin**", size=10, fill=INK, mono=True)
            + text(x + 24, y + 66, "see note[^1]", size=10, fill=MUTED, mono=True))


def json_icon(x, y):
    return (rect(x + 16, y + 12, 94, 74, rx=6, fill="#343747")
            + text(x + 24, y + 30, "{", size=11, fill=ORANGE, mono=True)
            + text(x + 32, y + 46, '"content":', size=10, fill=BLUE, mono=True)
            + text(x + 32, y + 62, '"toc": […]', size=10, fill=BLUE, mono=True)
            + text(x + 24, y + 78, "}", size=11, fill=ORANGE, mono=True))


fmts = [("HTML", "web page", html_icon, "html"), ("PDF", "via Typst", pdf_icon, "pdf"), ("PDF", "via PrintCSS", pdf_icon, "pdf"),
        ("EPUB", "e-book", epub_icon, "epub"), ("Word", ".docx", word_icon, "docx"), ("Markdown", "plain text", md_icon, "md")]


def curve(x, y):
    return f"M108 202 C126 202 {x-24} {y+H/2} {x} {y+H/2}"


# faint options
for i, f in enumerate(fmts):
    x, y = cols[i % 3], rows[i // 3]
    sc.append(g(show(at(1, 0.9 + i * 0.3), E, fade=0.25),
                f'<path d="{curve(x, y)}" fill="none" stroke="{LINE}" stroke-width="1.4" stroke-dasharray="3 5"/>'))
# one at a time: active line (under the cards), then ring and file name (over them)
slot0, slot = 3.2, 0.95


def slot_range(i):
    t0_ = at(1, slot0 + i * slot)
    return t0_, (t0_ + slot if i < len(fmts) - 1 else E)


for i, f in enumerate(fmts):
    x, y = cols[i % 3], rows[i // 3]
    sc.append(g(show(*slot_range(i), fade=0.15),
                f'<path class="opmov-flow" d="{curve(x, y)}" fill="none" stroke="{ORANGE}" stroke-width="2.2"/>'))
for i, (lab, sub, icon, ext) in enumerate(fmts):
    x, y = cols[i % 3], rows[i // 3]
    sc.append(g(show(at(1, 1.0 + i * 0.3), E, sc=0.85), card(x, y, lab, sub, icon(x, y))))
sc.append(g(show(at(1, 3.0), E), text(62, 316, "1 input → 1 output", size=10.5, fill=MUTED, anchor="middle", weight=600)))
for i, (lab, sub, icon, ext) in enumerate(fmts):
    x, y = cols[i % 3], rows[i // 3]
    sc.append(g(show(*slot_range(i), fade=0.15),
                rect(x - 3, y - 3, W + 6, H + 6, rx=12, fill="none", stroke=ORANGE, sw=2.5)
                + text(62, 296, f"→ letter.{ext}", size=11.5, fill=ORANGE, anchor="middle", weight=700, mono=True)))
stage(1, "".join(sc))

# ---- Scene 2: Chunk — a whole collection becomes a website ------------------
E = end(2)
sc = [text(20, 26, "A whole collection becomes a website", size=12, fill=MUTED, weight=600), cmd("$ opm chunk data/")]
sc.append(g(show(at(2, 0.2), E), text(20, 54, "data/", size=11, fill=MUTED, weight=700, mono=True)
            + text(200, 54, "site/", size=11, fill=MUTED, weight=700, mono=True)))
LY = [64, 114, 164]
for k, yy in enumerate(LY):
    d = sheet(20, yy, 72, 42, fold=9) + text(28, yy + 17, f"letter-{k+1:02d}", size=9, fill=INK, mono=True) + bars(28, yy + 25, [50, 38], gap=7, h=3)
    sc.append(g(show(at(2, 0.3 + k * 0.2), E, dx=-10), d))
# long document with page breaks
BY0, BH = 222, 150
book = sheet(20, BY0, 72, BH, fold=9) + text(28, BY0 + 16, "book.xml", size=9, fill=INK, mono=True)
for k in range(4):
    book += bars(28, BY0 + 26 + k * 32, [52, 42, 50][: 2 if k == 3 else 3], gap=7, h=3)
sc.append(g(show(at(2, 0.9), E, dx=-10), book))
pbs = [BY0 + 50, BY0 + 82, BY0 + 114]
for k, yy in enumerate(pbs):
    sc.append(g(show(at(2, 2.9 + k * 0.2), E, fade=0.2),
                f'<line x1="22" y1="{yy}" x2="90" y2="{yy}" stroke="{ORANGE}" stroke-width="1.6" stroke-dasharray="4 3"/>'
                + text(96, yy + 3, "<pb/>", size=9, fill=ORANGE, mono=True)))


def page(x, y, w, h, label, hi=False):
    return (rect(x, y, w, h, rx=5, fill=PANEL, stroke=ORANGE if hi else LINE)
            + rect(x + 7, y + 7, w * 0.45, 3.5, rx=1.75, fill=ORANGE)
            + text(x + 7, y + h - 7, label, size=8.5, fill=INK, mono=True))


# letters: one page each
for k, yy in enumerate(LY):
    t = at(2, 1.6 + k * 0.35)
    sc.append(g(show(t, E, fade=0.25), f'<path class="opmov-flow" d="M96 {yy+21} L196 {yy+21}" stroke="{ORANGE}" stroke-width="1.6" fill="none"/>'))
    sc.append(g(show(t + 0.15, E, dx=-20), page(200, yy + 1, 84, 40, f"letter-{k+1:02d}.html")))
# book: split into pages
segs = [BY0 + 2, BY0 + 50, BY0 + 82, BY0 + 114, BY0 + BH]
for k in range(4):
    cy = (segs[k] + segs[k + 1]) / 2 + (8 if k == 0 else 0)
    t = at(2, 3.8 + k * 0.3)
    sc.append(g(show(t, E, fade=0.25), f'<path class="opmov-flow" d="M96 {cy} C150 {cy} 150 {244 + k*34} 196 {244 + k*34}" stroke="{ORANGE}" stroke-width="1.6" fill="none"/>'))
    sc.append(g(show(t + 0.15, E, dx=-20), page(200, 229 + k * 34, 84, 30, f"book/p{k+1}.html")))
# extra pages
sc.append(g(show(at(2, 5.4), E), text(308, 54, "+ extra pages", size=11, fill=ORANGE, weight=700)))
extras = [("index.html", "collection overview"), ("persons.html", "register"), ("places.html", "register"), ("about.html", "project info")]
for k, (lab, sub) in enumerate(extras):
    y = 64 + k * 48
    b = (rect(308, y, 136, 40, rx=6, fill="#2F3140", stroke=ORANGE, extra='stroke-dasharray="4 3"')
         + text(318, y + 17, lab, size=10, fill=INK, weight=600, mono=True) + text(318, y + 32, sub, size=9.5, fill=MUTED))
    sc.append(g(show(at(2, 5.6 + k * 0.3), E, dy=10), b))
# every page gets fragments
fr = text(308, 270, "every page also gets", size=10.5, fill=MUTED, weight=600)
fr += chip(308, 280, "table of contents", fill="#343747", color=INK, size=9.5)
fr += chip(427, 280, "breadcrumbs", fill="#343747", color=INK, size=9.5)
fr += chip(308, 306, "notes", fill="#343747", color=INK, size=9.5)
fr += chip(358, 306, "prev / next", fill="#343747", color=INK, size=9.5)
fr += chip(443, 306, "links", fill="#343747", color=INK, size=9.5)
sc.append(g(show(at(2, 7.0), E, dy=8), fr))
# the site
site = (rect(190, 40, 366, 334, rx=12, fill="none", stroke=ORANGE, sw=2)
        + rect(308, 340, 236, 24, rx=12, fill=ORANGE)
        + text(426, 356, "a complete website", size=11.5, fill=BG, weight=700, anchor="middle"))
sc.append(g(show(at(2, 8.0), E), site))
stage(2, "".join(sc))

# ---- Scene 3: Publish ------------------------------------------------------
E = end(3)
sc = [text(20, 26, "Give the site its look and features", size=12, fill=MUTED, weight=600), cmd("$ opm serve")]
WX, WY, WW, WH = 16, 38, 536, 262
win = rect(WX, WY, WW, WH, rx=10, fill="#F7F5F0", stroke="#3E4153")
win += rect(WX, WY, WW, 26, rx=10, fill="#3E4153") + rect(WX, WY + 16, WW, 10, rx=0, fill="#3E4153")
win += "".join(f'<circle cx="{WX+16+i*12}" cy="{WY+13}" r="3.5" fill="{c}"/>' for i, c in enumerate(["#E0533D", ORANGE, "#5CB85C"]))
win += rect(WX + 60, WY + 6, 300, 14, rx=7, fill="#2F3140") + text(WX + 70, WY + 17, "my-edition.org/letters/matejko-12.html", size=9.5, fill=MUTED, mono=True)
sc.append(g(show(at(3, 0.3), E), win))
BX, BY = WX, WY + 26
theme = rect(BX, BY, WW, 30, rx=0, fill="#2B2420")
theme += rect(BX + 12, BY + 9, 12, 12, rx=3, fill=ORANGE) + text(BX + 32, BY + 20, "Matejko Letters", size=11.5, fill="#F7F5F0", weight=700)
theme += "".join(text(BX + 150 + i * 56, BY + 20, s, size=10, fill="#CFC6B8") for i, s in enumerate(["Letters", "Persons", "Places"]))
theme += bars(BX + 14, BY + 46, [80, 64, 72, 58], gap=12, h=4, fill="#D8D2C6") + rect(BX + 14, BY + 58, 64, 4, rx=2, fill=ORANGE)
theme += rect(BX + 112, BY + 30, 1, WH - 56, rx=0, fill="#E2DDD3")
theme += text(BX + 126, BY + 54, "No. 12 · Kraków, 3 May 1897", size=12.5, fill="#2B2420", weight=700)
for k, w in enumerate([196, 180, 200, 150, 192, 170, 120]):
    theme += rect(BX + 126, BY + 68 + k * 13, w, 4, rx=2, fill="#B9B2A6")
sc.append(g(show(at(3, 0.9), E), theme))
fac = rect(BX + 344, BY + 40, 180, 182, rx=6, fill="#E9E3D6", stroke="#D3CBBB")
fac += rect(BX + 362, BY + 52, 144, 150, rx=2, fill="#D8CDB4")
fac += "".join(f'<path d="M{BX+372} {BY+68+k*13} q 30 -4 60 0 t 60 0" stroke="#7A6A50" stroke-width="1.4" fill="none" opacity=".7"/>' for k in range(10))
fac += rect(BX + 352, BY + 206, 40, 12, rx=6, fill="#2B2420") + text(BX + 372, BY + 215, "+  −", size=9, fill="#fff", anchor="middle")
fac += text(BX + 500, BY + 215, "IIIF", size=9, fill="#7A6A50", weight=700, anchor="end")
reg = ""
for (xx, yy, w) in [(BX + 126, BY + 80, 60), (BX + 230, BY + 106, 48), (BX + 160, BY + 132, 70)]:
    reg += rect(xx, yy, w, 6, rx=2, fill=ORANGE)
reg += rect(BX + 10, BY + 110, 94, 112, rx=6, fill="#EFEADF", stroke="#E0D8C8")
reg += text(BX + 18, BY + 126, "Persons", size=9.5, fill="#2B2420", weight=700)
reg += text(BX + 18, BY + 140, "Matejko, Jan", size=9, fill="#6A5F50")
reg += text(BX + 18, BY + 153, "Matejko, Teodora", size=9, fill="#6A5F50")
reg += text(BX + 18, BY + 172, "Places", size=9.5, fill="#2B2420", weight=700)
reg += text(BX + 18, BY + 186, "Kraków", size=9, fill="#6A5F50")
reg += text(BX + 18, BY + 199, "Wien", size=9, fill="#6A5F50")
srch = rect(BX + 380, BY + 7, 144, 16, rx=8, fill="#F7F5F0")
srch += f'<circle cx="{BX+392}" cy="{BY+15}" r="4" fill="none" stroke="#2B2420" stroke-width="1.5"/><path d="M{BX+395} {BY+18} l4 4" stroke="#2B2420" stroke-width="1.5"/>'
srch += text(BX + 402, BY + 19, "Teodora", size=9.5, fill="#2B2420")
drop = rect(BX + 380, BY + 28, 144, 64, rx=6, fill="#FFFFFF", stroke="#D3CBBB")
drop += "".join(rect(BX + 390, BY + 38 + k * 18, 100 - k * 14, 4, rx=2, fill=ORANGE if k == 0 else "#B9B2A6")
                + rect(BX + 390, BY + 46 + k * 18, 120 - k * 10, 3, rx=1.5, fill="#D8D2C6") for k in range(3))
nav = rect(BX + 126, BY + 172, 204, 22, rx=11, fill="#EFEADF")
nav += text(BX + 140, BY + 187, "‹ No. 11", size=10, fill="#2B2420", weight=600)
nav += text(BX + 316, BY + 187, "No. 13 ›", size=10, fill="#2B2420", weight=600, anchor="end")
features = [("iiif", fac), ("registers", reg), ("pagefind", srch + drop), ("edition-navigation", nav)]
sc.append(g(show(at(3, 0.9), E), text(16, 324, "templates & themes", size=10.5, fill=MUTED, weight=600)
            + chip(16, 334, "chapbook", fill="#343747", color=INK, size=10)
            + chip(88, 334, "handbook", fill="#343747", color=INK, size=10)
            + chip(162, 334, "journal", fill="#343747", color=INK, size=10)))
sc.append(g(show(at(3, 1.8), E), text(236, 324, "profiles", size=10.5, fill=MUTED, weight=600)))
cx = 236
for k, (lab, body) in enumerate(features):
    tt = at(3, 2.0 + k * 1.3)
    w = len(lab) * 10 * 0.6 + 16
    sc.append(g(show(tt, E, dy=10), chip(cx, 334, lab, size=10)))
    sc.append(g(show(tt + 0.3, E, sc=0.96), body))
    cx += w + 6
stage(3, "".join(sc))

# ---- Scene 4: Integrate ----------------------------------------------------
E = end(4)
sc = [text(20, 26, "… or hand the results to other systems", size=12, fill=MUTED, weight=600)]
targets = [
    ("opm chunk --format json", "Astro · Hugo · Eleventy", "data files for static site generators"),
    ("opm chunk --format pb-view", "TEI Publisher", "pre-rendered pages, instant loading"),
    ("opm index", "Search engines", "JSONL records for any search engine"),
    ("opm odd document", "ODD documentation", "reference site, EPUB or PDF"),
]
pos = [(16, 42), (292, 42), (16, 206), (292, 206)]
for k, ((cmd_, tgt, sub), (x, y)) in enumerate(zip(targets, pos)):
    body = rect(x, y, 260, 150, rx=12, fill=PANEL, stroke=LINE)
    body += rect(x + 14, y + 16, 232, 26, rx=6, fill="#1F2029") + text(x + 24, y + 33, "$ " + cmd_, size=10.5, fill=ORANGE, mono=True)
    body += f'<path class="opmov-flow" d="M{x+40} {y+50} L{x+40} {y+82}" stroke="{ORANGE}" stroke-width="2" fill="none"/>'
    body += f'<path d="M{x+34} {y+78} L{x+40} {y+86} L{x+46} {y+78}" stroke="{ORANGE}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    body += text(x + 62, y + 80, tgt, size=15, weight=700)
    body += text(x + 62, y + 100, sub, size=10.5, fill=MUTED)
    body += bars(x + 62, y + 116, [150, 110], gap=9, h=3, fill="#3B3E4E")
    sc.append(g(show(at(4, 0.5 + k * 0.8), E, dy=12), body))
stage(4, "".join(sc))

# ---------------------------------------------------------------- captions
caps = [
    ("Describe, don't program", "Define once in a TEI ODD how each element is presented — opm compiles it and applies it to every document."),
    ("One document, one file", "opm transform turns a single TEI, DocBook or JATS document into HTML, PDF (via Typst), EPUB, Word, Markdown or JSON."),
    ("A collection becomes a website", "opm chunk transforms a whole collection, splits long documents into pages and adds extra pages to form a complete site."),
    ("Shape the edition", "Templates, themes and profiles give the site its look and add facsimiles, registers, search and navigation."),
    ("… or feed other systems", "Pre-render for TEI Publisher, supply data to site generators, build search indexes, or document the ODD itself."),
]
css = f"""
.opm-ov text{{font-family:Inter,"Segoe UI",Roboto,system-ui,-apple-system,sans-serif}}
.opm-ov .opmov-mono{{font-family:"JetBrains Mono","SFMono-Regular",Menlo,Consolas,ui-monospace,monospace}}
.opm-ov .opmov-anim{{transform-box:fill-box;transform-origin:center}}
.opm-ov .opmov-flow{{stroke-dasharray:5 7;animation:opmov-flow 1.1s linear infinite}}
@keyframes opmov-flow{{to{{stroke-dashoffset:-24}}}}
.opm-ov .opmov-progress{{transform-box:fill-box;transform-origin:left center;animation:opmov-prog {D}s linear infinite}}
@keyframes opmov-prog{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
.opm-ov .opmov-corepulse{{transform-box:fill-box;transform-origin:center;animation:opmov-pulse 2.4s ease-in-out infinite}}
@keyframes opmov-pulse{{0%,100%{{opacity:.55;transform:scale(.92)}}50%{{opacity:1;transform:scale(1.05)}}}}
.opm-ov-js .opmov-step{{cursor:pointer}}
.opm-ov-js .opmov-step:hover > rect{{fill:#343747}}
{''.join(kf)}
/* Without the docs script nothing can pause it, so reduced motion gets a still frame. */
@media (prefers-reduced-motion: reduce){{
  .opm-ov:not(.opm-ov-js) .opmov-anim,.opm-ov:not(.opm-ov-js) .opmov-flow,
  .opm-ov:not(.opm-ov-js) .opmov-progress,.opm-ov:not(.opm-ov-js) .opmov-corepulse{{animation:none!important}}
  .opm-ov:not(.opm-ov-js) :is(.opmov-hl,.opmov-s0,.opmov-s1,.opmov-s2,.opmov-s4,.opmov-pill,.opmov-progress){{display:none}}
}}
"""

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 492" class="opm-ov" role="img" '
       f'data-scenes="{",".join(f"{t:g}" for t in START)}" data-durations="{",".join(f"{t:g}" for t in DUR)}" '
       f'aria-labelledby="opmov-title opmov-desc">'
       f'<title id="opmov-title">What opm does</title>'
       f'<desc id="opmov-desc">Animated overview in five steps: 1. describe presentation in a TEI ODD, which opm compiles into Python; '
       f'2. transform TEI, DocBook or JATS into HTML, PDF via Typst, EPUB, Word, Markdown or JSON; 3. chunk collections into pages with '
       f'table of contents, breadcrumbs and notes; 4. generate a static edition website with templates, themes and profiles for IIIF facsimiles, '
       f'registers, Pagefind search and edition navigation; 5. feed other systems: static site generators, TEI Publisher, search indexes and ODD documentation.</desc>'
       f'<style>{css}</style>' + "".join(parts) + '</svg>')

import sys
open(sys.argv[1], "w").write(svg)
print(len(svg), "bytes")
