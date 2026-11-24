"""Generate docs/images/opm-family.svg — opm and TEI Publisher, two siblings built on the TEI Processing Model.

Usage: python scripts/gen_family_svg.py docs/images/opm-family.svg
Same helpers and conventions as gen_overview_svg.py; ids, classes and keyframes use the opmfam- prefix.
"""
from html import escape as esc

DUR = [9.0, 10.0, 9.0, 11.0]   # seconds per scene
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
    name = f"opmfam-a{_n[0]}"
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
    return f"opmfam-anim {name}"


def g(cls, inner, x=0, y=0):
    """animated group; positioned by an outer translate so CSS transform is free."""
    if x or y:
        return f'<g transform="translate({x},{y})"><g class="{cls}">{inner}</g></g>'
    return f'<g class="{cls}">{inner}</g>'


def rect(x, y, w, h, rx=6, fill=PANEL, stroke=None, sw=1, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s} {extra}/>'


def text(x, y, s, size=13, fill=INK, weight=400, anchor="start", cls="", mono=False, raw=False):
    fam = ' class="opmfam-mono"' if mono else ""
    if cls:
        fam = f' class="{cls}{" opmfam-mono" if mono else ""}"'
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
TEAL = "#5CC8C0"
PAPER = "#F7F5F0"

# ---------------------------------------------------------------- frame
add(rect(0, 0, 1000, 492, rx=20, fill=BG))
add('<defs>'
    '<marker id="opmfam-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{ORANGE}"/></marker>'
    '<marker id="opmfam-arrt" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{TEAL}"/></marker>'
    '<marker id="opmfam-arrm" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker>'
    '</defs>')

add(text(32, 42, "opm & TEI Publisher", size=18, weight=700))

steps = ["Standard", "Siblings", "Single files", "Websites"]
px0, pw, pg = 344, 150, 8
for i, s in enumerate(steps):
    x = px0 + i * (pw + pg)
    add(f'<g class="opmfam-step" data-scene="{i}" data-label="{s}">')
    add(rect(x, 22, pw, 28, rx=14, fill="#2A2C38"))
    add(text(x + pw / 2, 41, f"{i+1}  {s}", size=12.5, fill=MUTED, weight=500, anchor="middle"))
    t0, t1 = scene_range(i)
    add(g(show(t0, t1, fade=0.3) + " opmfam-pill",
          rect(x, 22, pw, 28, rx=14, fill=ORANGE)
          + text(x + pw / 2, 41, f"{i+1}  {s}", size=12.5, fill=BG, weight=700, anchor="middle")))
    add('</g>')
add(rect(32, 64, 936, 3, rx=1.5, fill="#2A2C38"))
add(f'<rect class="opmfam-progress" data-role="progress" x="32" y="64" width="936" height="3" rx="1.5" fill="{ORANGE}"/>')

SX, SY, SW, SH = 32, 86, 936, 384
add(rect(SX, SY, SW, SH, rx=14, fill="#252733", stroke="#2F3242"))


def stage(i, inner):
    t0, t1 = scene_range(i)
    add(f'<g transform="translate({SX},{SY})"><g class="{show(t0, t1, fade=0.4)} opmfam-scene opmfam-s{i}">{inner}</g></g>')


def heading(s):
    return text(20, 28, s, size=12.5, fill=MUTED, weight=600)


# ---------------------------------------------------------------- icons
def opm_logo(x, y, size=40):
    k = size / 64
    return (f'<g transform="translate({x},{y}) scale({k:.4f})">'
            '<rect x="2" y="2" width="60" height="60" rx="14" fill="#2F3140"/>'
            f'<path d="M28 17 L15 32 L28 47" fill="none" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<rect x="34" y="20" width="17" height="4.6" rx="2.3" fill="{INK}"/>'
            f'<rect x="34" y="29.7" width="17" height="4.6" rx="2.3" fill="{ORANGE}"/>'
            f'<rect x="34" y="39.4" width="11" height="4.6" rx="2.3" fill="{INK}"/></g>')


def db_icon(x, y, w=36, h=44, color=TEAL):
    e = h * 0.14
    return (f'<path d="M{x} {y+e} V{y+h-e} A{w/2} {e} 0 0 0 {x+w} {y+h-e} V{y+e}" fill="#2F3140" stroke="{color}" stroke-width="2"/>'
            f'<ellipse cx="{x+w/2}" cy="{y+e}" rx="{w/2}" ry="{e}" fill="#2F3140" stroke="{color}" stroke-width="2"/>'
            f'<path d="M{x} {y+h*0.42} A{w/2} {e} 0 0 0 {x+w} {y+h*0.42}" fill="none" stroke="{color}" stroke-width="1.5" opacity=".7"/>'
            f'<path d="M{x} {y+h*0.66} A{w/2} {e} 0 0 0 {x+w} {y+h*0.66}" fill="none" stroke="{color}" stroke-width="1.5" opacity=".7"/>')


def tool_tile(x, y, w, h, which, sub=None):
    if which == "tp":
        body = rect(x, y, w, h, rx=12, fill=PANEL, stroke=TEAL, sw=1.5) + db_icon(x + 14, y + (h - 34) / 2, 28, 34)
        name = "TEI Publisher"
    else:
        body = rect(x, y, w, h, rx=12, fill=PANEL, stroke=ORANGE, sw=1.5) + opm_logo(x + 10, y + (h - 38) / 2, 38)
        name = "opm"
    ty = y + h / 2 + (0 if sub else 6)
    body += text(x + 56, ty, name, size=16, weight=700)
    if sub:
        body += text(x + 56, ty + 17, sub, size=10.5, fill=MUTED)
    return body


def tei_sheet(x, y, w=96, h=118):
    return (sheet(x, y, w, h) + text(x + 12, y + 24, "<TEI>", size=11, fill=ORANGE, mono=True)
            + bars(x + 18, y + 36, [w * .62, w * .48, w * .66, w * .4, w * .56, w * .3][: max(2, int((h - 50) / 11))], gap=11, h=3.5)
            )


def odd_sheet(x, y, w=96, h=96):
    return (sheet(x, y, w, h) + text(x + 12, y + 24, "ODD", size=11, fill=INK, weight=700, mono=True)
            + text(x + 12, y + 44, "<model", size=10, fill=ORANGE, mono=True) + text(x + 56, y + 44, "/>", size=10, fill=MUTED, mono=True)
            + text(x + 12, y + 62, "<model", size=10, fill=ORANGE, mono=True) + text(x + 56, y + 62, "/>", size=10, fill=MUTED, mono=True)
            + bars(x + 12, y + 72, [w * .5], h=3.5))


def browser(x, y, w, h, title="", lines=6):
    b = rect(x, y, w, h, rx=8, fill=PAPER, stroke="#3E4153")
    b += rect(x, y, w, 18, rx=8, fill="#3E4153") + rect(x, y + 10, w, 8, rx=0, fill="#3E4153")
    b += "".join(f'<circle cx="{x+10+i*9}" cy="{y+9}" r="2.6" fill="{c}"/>' for i, c in enumerate(["#E0533D", ORANGE, "#5CB85C"]))
    b += rect(x, y + 18, w, 16, rx=0, fill="#2B2420")
    b += rect(x + 8, y + 23, 8, 6, rx=2, fill=ORANGE)
    if title:
        b += text(x + 20, y + 30, title, size=8.5, fill=PAPER, weight=700)
    b += rect(x + 10, y + 44, w * 0.5, 5, rx=2, fill="#2B2420")
    b += bars(x + 10, y + 56, [w * f for f in (0.8, 0.7, 0.78, 0.6, 0.74, 0.5, 0.68)][:lines], gap=10, h=3.5, fill="#C9C2B6")
    return b


def mini_out(x, y, kind):
    w, h = 112, 64
    b = rect(x, y, w, h, rx=10, fill=PANEL, stroke=LINE)
    if kind == "HTML":
        b += rect(x + 12, y + 12, 40, 32, rx=3, fill="#343747") + rect(x + 12, y + 12, 40, 7, rx=3, fill="#3E4153")
        b += rect(x + 17, y + 24, 30, 4, rx=2, fill=ORANGE) + bars(x + 17, y + 32, [28, 22], gap=6, h=2.5, fill="#555869")
    elif kind == "PDF":
        b += sheet(x + 16, y + 9, 30, 40, fill=INK, stroke=INK, fold=7) + bars(x + 21, y + 19, [18, 20, 14, 18], gap=6, h=2.5, fill=MUTED)
        b += chip(x + 30, y + 38, "PDF", fill="#E0533D", color="#fff", size=7.5, pad=3)
    else:
        b += rect(x + 18, y + 8, 28, 44, rx=5, fill="#343747", stroke="#555869") + rect(x + 22, y + 13, 20, 30, rx=1.5, fill=INK)
        b += bars(x + 25, y + 17, [14, 12, 14, 10], gap=6, h=2.5, fill=MUTED)
    b += text(x + 62, y + 38, kind, size=14, weight=700)
    return b


# ---- Scene 0: the shared standard ---------------------------------------
E = end(0)
sc = [heading("One standard at the core")]
sc.append(g(show(at(0, 0.3), E, dx=-10), tei_sheet(40, 52, 110, 128) + text(95, 200, "TEI document", size=11.5, fill=MUTED, weight=600, anchor="middle")))
sc.append(g(show(at(0, 0.7), E, dx=-10), odd_sheet(40, 222, 110, 104) + text(95, 346, "ODD", size=11.5, fill=MUTED, weight=600, anchor="middle")))
sc.append(g(show(at(0, 1.3), E),
            f'<path class="opmfam-flow" d="M156 116 C230 116 230 180 296 186" fill="none" stroke="{ORANGE}" stroke-width="2"/>'
            f'<path class="opmfam-flow" d="M156 274 C230 274 230 210 296 202" fill="none" stroke="{ORANGE}" stroke-width="2"/>'))
pm = rect(300, 44, 340, 300, rx=14, fill=PANEL, stroke=ORANGE, sw=1.5)
pm += text(322, 76, "TEI Processing Model", size=18, weight=700)
pm += text(322, 96, "part of the TEI Guidelines", size=11, fill=MUTED)
code = [
    '<tspan fill="#F5A623">&lt;model</tspan> <tspan fill="#8EC5FF">behaviour</tspan>=<tspan fill="#B5E08A">"heading"</tspan><tspan fill="#F5A623">/&gt;</tspan>',
    '<tspan fill="#F5A623">&lt;model</tspan> <tspan fill="#8EC5FF">behaviour</tspan>=<tspan fill="#B5E08A">"link"</tspan><tspan fill="#F5A623">&gt;</tspan>',
    '  <tspan fill="#F5A623">&lt;param</tspan> <tspan fill="#8EC5FF">name</tspan>=<tspan fill="#B5E08A">"uri"</tspan> <tspan fill="#8EC5FF">value</tspan>=<tspan fill="#B5E08A">"@ref"</tspan><tspan fill="#F5A623">/&gt;</tspan>',
    '<tspan fill="#F5A623">&lt;/model&gt;</tspan>',
    '<tspan fill="#F5A623">&lt;model</tspan> <tspan fill="#8EC5FF">behaviour</tspan>=<tspan fill="#B5E08A">"note"</tspan><tspan fill="#F5A623">/&gt;</tspan>',
]
for i, ln in enumerate(code):
    pm += g(show(at(0, 2.1 + i * 0.2), E, fade=0.25, dx=-6),
            text(322, 126 + i * 20, ln, size=11.5, fill=INK, mono=True, raw=True).replace('<text ', '<text xml:space="preserve" '))
pm += g(show(at(0, 3.3), E), text(322, 244, "standard behaviours", size=10.5, fill=MUTED, weight=600))
behav = ["block", "inline", "heading", "paragraph", "link", "note", "list", "table", "alternate", "omit"]
cx, cy = 322, 254
for k, b_ in enumerate(behav):
    w = len(b_) * 9.5 * 0.6 + 14
    if cx + w > 624:
        cx, cy = 322, cy + 27
    pm += g(show(at(0, 3.5 + k * 0.12), E, fade=0.2), chip(cx, cy, b_, fill="#343747", color=INK, size=9.5, pad=7))
    cx += w + 6
sc.append(g(show(at(0, 1.7), E, sc=0.95), pm))
sc.append(g(show(at(0, 5.0), E, dx=-8), f'<path d="M648 194 L690 194" stroke="{ORANGE}" stroke-width="2.5" marker-end="url(#opmfam-arr)"/>'))
out = rect(704, 44, 200, 250, rx=12, fill=PANEL, stroke=LINE)
out += text(720, 66, "rendered output", size=11, fill=MUTED, weight=600)
out += rect(718, 78, 172, 202, rx=4, fill=PAPER)
out += text(732, 104, "No. 12 · Kraków", size=13, fill="#2B2420", weight=700)
out += bars(732, 118, [140, 126, 136], gap=11, h=4, fill="#C9C2B6")
out += text(732, 164, "Letter to", size=12, fill="#2B2420")
out += '<text x="786" y="164" font-size="12" fill="#C2410C" font-weight="600" style="font-variant:small-caps" text-decoration="underline">Mikołaj Serafin¹</text>'
out += bars(732, 176, [140, 132, 110, 138, 96], gap=11, h=4, fill="#C9C2B6")
out += rect(732, 240, 60, 1, rx=0, fill="#B9B2A6") + text(732, 258, "¹ note", size=9.5, fill="#6A5F50")
sc.append(g(show(at(0, 5.3), E, dx=-10), out))
sc.append(g(show(at(0, 6.3), E, dy=6), text(804, 322, "same TEI + same ODD", size=12.5, fill=ORANGE, weight=700, anchor="middle")
            + text(804, 340, "= same result, whichever tool runs it", size=11, fill=MUTED, anchor="middle")))
stage(0, "".join(sc))

# ---- Scene 1: two siblings -----------------------------------------------
E = end(1)
sc = []
core = rect(338, 40, 260, 46, rx=23, fill=PANEL, stroke=ORANGE, sw=1.5) + text(468, 68, "TEI Processing Model", size=14.5, weight=700, anchor="middle")
sc.append(g(show(at(1, 0.3), E, sc=0.9), core))
sc.append(g(show(at(1, 1.0), E),
            f'<path class="opmfam-flow" d="M420 86 C420 100 230 92 230 108" fill="none" stroke="{TEAL}" stroke-width="2"/>'
            f'<path class="opmfam-flow" d="M516 86 C516 100 706 92 706 108" fill="none" stroke="{ORANGE}" stroke-width="2"/>'))


def sibling(x, which, rows, t):
    color = TEAL if which == "tp" else ORANGE
    b = rect(x, 110, 380, 170, rx=14, fill=PANEL, stroke=color, sw=1.5)
    if which == "tp":
        b += db_icon(x + 20, 128, 34, 42)
        b += text(x + 68, 150, "TEI Publisher", size=18, weight=700) + text(x + 68, 168, "web application in eXist-db", size=11, fill=MUTED)
    else:
        b += opm_logo(x + 16, 126, 44)
        b += text(x + 68, 150, "opm", size=18, weight=700) + text(x + 68, 168, "Python, on the command line", size=11, fill=MUTED)
    out = [g(show(at(1, t), E, dy=10), b)]
    for k, r in enumerate(rows):
        yy = 202 + k * 24
        out.append(g(show(at(1, t + 0.6 + k * 0.3), E, dx=-6),
                     f'<circle cx="{x+26}" cy="{yy-4}" r="3" fill="{color}"/>' + text(x + 38, yy, r, size=12.5, fill=INK)))
    return "".join(out)


sc.append(sibling(40, "tp", ["compiles the ODD to XQuery", "runs inside a database", "builds pages on request"], 1.4))
sc.append(sibling(516, "opm", ["compiles the ODD to Python", "needs no database", "renders everything in advance"], 2.4))
band = (rect(40, 296, 856, 70, rx=14, fill="#2F3140", stroke=MUTED, extra='stroke-dasharray="4 4"')
        + text(62, 326, "Shared", size=14, weight=700) + text(62, 346, "learn one, know the other", size=11, fill=MUTED))
sc.append(g(show(at(1, 4.6), E, dy=8), band))
shared = ["ODD rules", "XML sources", "Jinks templates", "Layout concepts"]
cx = 260
for k, s_ in enumerate(shared):
    w = len(s_) * 11 * 0.6 + 18
    sc.append(g(show(at(1, 5.2 + k * 0.35), E, sc=0.85), chip(cx, 320, s_, fill=ORANGE, color=BG, size=11, pad=9)))
    cx += w + 8
stage(1, "".join(sc))

# ---- Scene 2: single files --------------------------------------------------
E = end(2)
sc = [heading("Any single file, from either tool")]
inp = tei_sheet(24, 120, 80, 96) + odd_sheet(52, 168, 80, 86) + text(78, 280, "TEI + ODD", size=11.5, fill=MUTED, weight=600, anchor="middle")
sc.append(g(show(at(2, 0.3), E, dx=-10), inp))
sc.append(g(show(at(2, 0.9), E, dx=-10), tool_tile(214, 48, 200, 64, "tp")))
sc.append(g(show(at(2, 1.2), E, dx=-10), tool_tile(214, 266, 200, 64, "opm")))
sc.append(g(show(at(2, 1.5), E),
            f'<path class="opmfam-flow" d="M136 200 C176 200 170 80 210 80" fill="none" stroke="{TEAL}" stroke-width="2"/>'
            f'<path class="opmfam-flow" d="M136 214 C176 214 170 298 210 298" fill="none" stroke="{ORANGE}" stroke-width="2"/>'))
cols2 = [480, 622, 764]
kinds = ["HTML", "PDF", "EPUB"]
sc.append(g(show(at(2, 1.9), E),
            f'<path class="opmfam-flow" d="M418 80 L474 80" stroke="{TEAL}" stroke-width="2" fill="none"/>'
            f'<path class="opmfam-flow" d="M418 298 L474 298" stroke="{ORANGE}" stroke-width="2" fill="none"/>'))
for k, kind in enumerate(kinds):
    sc.append(g(show(at(2, 2.1 + k * 0.35), E, sc=0.85), mini_out(cols2[k], 48, kind)))
    sc.append(g(show(at(2, 3.2 + k * 0.35), E, sc=0.85), mini_out(cols2[k], 266, kind)))
for k in range(3):
    sc.append(g(show(at(2, 4.5 + k * 0.25), E, sc=0.6), text(cols2[k] + 56, 202, "=", size=34, fill=ORANGE, weight=700, anchor="middle")))
sc.append(g(show(at(2, 5.4), E), text(678, 236, "same ODD, same result", size=12, fill=INK, weight=700, anchor="middle")))
stage(2, "".join(sc))

# ---- Scene 3: websites -------------------------------------------------------
E = end(3)
sc = [heading("… and complete websites")]
sc.append(g(show(at(3, 0.2), E), f'<line x1="468" y1="44" x2="468" y2="300" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="4 5"/>'))
# TEI Publisher: dynamic
sc.append(g(show(at(3, 0.3), E, dy=-8), tool_tile(24, 40, 214, 56, "tp", sub="dynamic website")))
tp_chips = chip(252, 46, "built on request", fill="#2F3140", color=TEAL, size=10) + chip(252, 72, "feature rich, performant queries", fill="#2F3140", color=TEAL, size=10)
sc.append(g(show(at(3, 0.9), E), tp_chips))
db = db_icon(48, 140, 84, 104) + text(90, 268, "Database", size=11.5, fill=MUTED, weight=600, anchor="middle")
sc.append(g(show(at(3, 1.4), E, sc=0.9), db))
sc.append(g(show(at(3, 1.9), E, dx=10), browser(236, 124, 210, 150, "My Edition")
            + rect(380, 146, 58, 12, rx=6, fill=PAPER) + text(386, 155, "search…", size=7.5, fill="#8A7F70")))
sc.append(g(show(at(3, 2.5), E),
            f'<path class="opmfam-flow" d="M232 176 L142 176" stroke="{TEAL}" stroke-width="2" fill="none" marker-end="url(#opmfam-arrt)"/>'
            f'<path class="opmfam-flow" d="M142 214 L230 214" stroke="{TEAL}" stroke-width="2" fill="none" marker-end="url(#opmfam-arrt)"/>'
            + text(187, 168, "request", size=9.5, fill=TEAL, anchor="middle", mono=True)
            + text(187, 232, "page", size=9.5, fill=TEAL, anchor="middle", mono=True)))
# opm: static
sc.append(g(show(at(3, 3.8), E, dy=-8), tool_tile(490, 40, 200, 56, "opm", sub="static website")))
op_chips = chip(704, 46, "rendered in advance", fill="#2F3140", color=ORANGE, size=10) + chip(704, 72, "limited dynamic features", fill="#2F3140", color=ORANGE, size=10)
sc.append(g(show(at(3, 4.4), E), op_chips))
folder = (f'<path d="M490 144 h40 l8 8 h62 v118 h-110 z" fill="#2F3140" stroke="{ORANGE}" stroke-width="1.5"/>'
          + text(500, 172, "site/", size=11, fill=ORANGE, weight=700, mono=True))
for k, f in enumerate(["index.html", "letter-01.html", "letter-02.html", "persons.html", "…"]):
    folder += text(500, 192 + k * 15, f, size=9, fill=INK, mono=True)
folder += text(545, 292, "Filesystem", size=11.5, fill=MUTED, weight=600, anchor="middle")
sc.append(g(show(at(3, 4.9), E, sc=0.9), folder))
host = rect(636, 170, 90, 66, rx=8, fill=PANEL, stroke=LINE) + bars(648, 182, [66, 66, 66], gap=14, h=8, fill="#3B3E4E")
host += "".join(f'<circle cx="{706}" cy="{186 + k*14}" r="2" fill="#5CB85C"/>' for k in range(3))
host += text(681, 254, "any web server", size=10, fill=MUTED, anchor="middle")
sc.append(g(show(at(3, 5.6), E),
            f'<path class="opmfam-flow" d="M604 204 L630 204" stroke="{ORANGE}" stroke-width="2" fill="none"/>' + host))
sc.append(g(show(at(3, 6.2), E, dx=10),
            f'<path class="opmfam-flow" d="M730 204 L752 204" stroke="{ORANGE}" stroke-width="2" fill="none"/>'
            + browser(756, 124, 160, 150, "My Edition")))
# bridge
bridge = (f'<path class="opmfam-flow" d="M598 274 C598 340 340 340 340 280" fill="none" stroke="{ORANGE}" stroke-width="2" marker-end="url(#opmfam-arr)"/>'
          + rect(330, 336, 276, 26, rx=13, fill=ORANGE)
          + text(468, 353, "opm can also pre-render pages for TEI Publisher", size=10.5, fill=BG, weight=700, anchor="middle"))
sc.append(g(show(at(3, 7.6), E), bridge))
stage(3, "".join(sc))

css = f"""
.opm-fam text{{font-family:Inter,"Segoe UI",Roboto,system-ui,-apple-system,sans-serif}}
.opm-fam .opmfam-mono{{font-family:"JetBrains Mono","SFMono-Regular",Menlo,Consolas,ui-monospace,monospace}}
.opm-fam .opmfam-anim{{transform-box:fill-box;transform-origin:center}}
.opm-fam .opmfam-flow{{stroke-dasharray:5 7;animation:opmfam-flow 1.1s linear infinite}}
@keyframes opmfam-flow{{to{{stroke-dashoffset:-24}}}}
.opm-fam .opmfam-progress{{transform-box:fill-box;transform-origin:left center;animation:opmfam-prog {D}s linear infinite}}
@keyframes opmfam-prog{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
.opm-ov-js .opmfam-step{{cursor:pointer}}
.opm-ov-js .opmfam-step:hover > rect{{fill:#343747}}
{''.join(kf)}
/* Without the docs script nothing can pause it, so reduced motion gets a still frame. */
@media (prefers-reduced-motion: reduce){{
  .opm-fam:not(.opm-ov-js) .opmfam-anim,.opm-fam:not(.opm-ov-js) .opmfam-flow,
  .opm-fam:not(.opm-ov-js) .opmfam-progress{{animation:none!important}}
  .opm-fam:not(.opm-ov-js) :is(.opmfam-s0,.opmfam-s2,.opmfam-s3,.opmfam-pill,.opmfam-progress){{display:none}}
}}
"""

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 492" class="opm-fam" role="img" '
       f'data-scenes="{",".join(f"{t:g}" for t in START)}" data-durations="{",".join(f"{t:g}" for t in DUR)}" '
       f'aria-labelledby="opmfam-title opmfam-desc">'
       f'<title id="opmfam-title">opm and TEI Publisher: two siblings built on the TEI Processing Model</title>'
       f'<desc id="opmfam-desc">Animated overview in four steps: 1. a TEI document and an ODD with processing model rules '
       f'produce the same rendered output, whichever tool runs them; 2. TEI Publisher compiles the ODD to XQuery and runs in the eXist-db database, '
       f'opm compiles it to Python and needs no database; both share the same ODD files, Jinks templates, profiles, fragments and pagination; '
       f'3. both turn a TEI document and its ODD into single files such as HTML, PDF or EPUB with the same result; '
       f'4. for complete websites, TEI Publisher builds a dynamic, database-backed site that renders pages on request, while opm renders a static site '
       f'in advance that can be hosted on any web server; opm can also pre-render pages for TEI Publisher.</desc>'
       f'<style>{css}</style>' + "".join(parts) + '</svg>')

import sys
open(sys.argv[1], "w").write(svg)
print(len(svg), "bytes")
