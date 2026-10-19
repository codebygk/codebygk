#!/usr/bin/env python3
"""Generate an animated skill-radar SVG (and optionally a README skills block)
from a TOML file.

Usage:
    python build_radar.py
    python build_radar.py --data data/skills.toml --out assets/radar.svg --readme README.md
"""
import argparse
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # pip install tomli
    except ModuleNotFoundError:
        sys.exit("Python 3.11+ is required (or: pip install tomli).")

# ---------- layout constants ----------
W, H = 640, 460
CX, CY = W // 2, H // 2
R = 140            # radius of the outer ring
LABEL_GAP = 24     # distance from outer ring to label
ACCENT = "#2dd4bf"
SWEEP = "#38bdf8"

STYLE = """
    text { font-family: 'JetBrains Mono','Fira Code',Menlo,Consolas,monospace; }
    .name { font-size: 12px; fill: #9fb0c8; }
    .pct  { font-size: 12px; fill: #2dd4bf; font-weight: 700; }
"""


# ---------- data ----------
def load(path):
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    meta = data.get("meta", {})
    max_level = meta.get("max_level", 5)
    scoring = meta.get("scoring", "mean")
    if scoring not in ("mean", "top3"):
        raise ValueError('meta.scoring must be "mean" or "top3"')

    cats = []
    for c in data.get("category", []):
        name, tools = c.get("name"), c.get("tools", {})
        if not name or not tools:
            raise ValueError(f"Every category needs a name and at least one tool: {c}")
        for tool, level in tools.items():
            if not isinstance(level, (int, float)) or not 0 <= level <= max_level:
                raise ValueError(f"{name} / {tool}: level must be 0..{max_level}, got {level!r}")
        levels = sorted(tools.values(), reverse=True)
        used = levels[:3] if scoring == "top3" else levels
        score = sum(used) / len(used) / max_level
        cats.append({"name": name, "tools": tools, "score": score})

    if not 3 <= len(cats) <= 12:
        raise ValueError(f"Radar needs 3 to 12 categories, found {len(cats)}")
    return cats, max_level


# ---------- geometry ----------
def polar(i, n, radius):
    """Point for axis i of n at the given radius (axis 0 points straight up)."""
    angle = math.radians(-90 + i * 360 / n)
    return radius * math.cos(angle), radius * math.sin(angle)


def pts(points, dx=0.0, dy=0.0):
    return " ".join(f"{x + dx:.1f},{y + dy:.1f}" for x, y in points)


# ---------- svg ----------
def build_svg(cats, max_level):
    n = len(cats)
    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="Skill radar: {escape(", ".join(c["name"] for c in cats))}">'
    )
    out.append(f"<style>{STYLE}</style>")
    out.append(f'<rect width="{W}" height="{H}" rx="14" fill="#0b1220"/>')

    # rings, one per level
    out.append('<g fill="none" stroke="#1b2740" stroke-width="1">')
    for k in range(1, int(max_level) + 1):
        ring = [polar(i, n, R * k / max_level) for i in range(n)]
        stroke = ' stroke="#26365a"' if k == max_level else ""
        out.append(f'<polygon points="{pts(ring, CX, CY)}"{stroke}/>')
    out.append("</g>")

    # axes
    out.append('<g stroke="#1b2740" stroke-width="1">')
    for i in range(n):
        x, y = polar(i, n, R)
        out.append(f'<line x1="{CX}" y1="{CY}" x2="{CX + x:.1f}" y2="{CY + y:.1f}"/>')
    out.append("</g>")

    # data polygon (relative to center so it can scale up from 0)
    shape = [polar(i, n, R * c["score"]) for i, c in enumerate(cats)]
    out.append(f'<g transform="translate({CX},{CY})">')
    out.append("<g>")
    out.append(
        '<animateTransform attributeName="transform" type="scale" from="0" to="1" '
        'dur="1.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="0.2 0.8 0.2 1"/>'
    )
    out.append(
        f'<polygon points="{pts(shape)}" fill="#0d9488" fill-opacity="0.28" '
        f'stroke="{ACCENT}" stroke-width="2" stroke-linejoin="round"/>'
    )
    for (x, y), c in zip(shape, cats):
        tip = f'{c["name"]}: {c["score"] * max_level:.1f}/{max_level}'
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{ACCENT}"><title>{escape(tip)}</title></circle>')
    out.append("</g>")

    # rotating sweep line
    out.append(
        f'<line x1="0" y1="0" x2="0" y2="{-(R + 6)}" stroke="{SWEEP}" stroke-width="2" opacity="0.55">'
        '<animateTransform attributeName="transform" type="rotate" from="0" to="360" '
        'dur="8s" repeatCount="indefinite"/></line>'
    )
    out.append("</g>")

    # labels
    for i, c in enumerate(cats):
        ux, uy = polar(i, n, 1)
        lx = CX + ux * (R + LABEL_GAP)
        ly = CY + uy * (R + LABEL_GAP)
        anchor = "start" if ux > 0.3 else "end" if ux < -0.3 else "middle"
        base = ly + 4
        if uy < -0.3:
            base -= 14      # top labels sit above the axis end
        elif uy > 0.3:
            base += 8       # bottom labels sit below it
        out.append(
            f'<text x="{lx:.1f}" y="{base:.1f}" text-anchor="{anchor}">'
            f'<tspan class="name">{escape(c["name"].upper())}</tspan>'
            f'<tspan class="pct" x="{lx:.1f}" dy="14">{round(c["score"] * 100)}%</tspan></text>'
        )

    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------- README block ----------
START, END = "<!-- SKILLS:START -->", "<!-- SKILLS:END -->"


def build_markdown(cats):
    blocks = []
    for c in cats:
        tools = sorted(c["tools"], key=lambda t: -c["tools"][t])
        blocks.append(f'**{c["name"]}** · {round(c["score"] * 100)}%  \n' + " · ".join(tools))
    return "\n\n".join(blocks)


def update_readme(path, cats):
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        print(f"! {path}: markers not found. Add {START} and {END} where the list should go.")
        return False
    block = f"{START}\n{build_markdown(cats)}\n{END}"
    Path(path).write_text(pattern.sub(lambda _: block, text), encoding="utf-8")
    return True


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/skills.toml")
    ap.add_argument("--out", default="assets/radar.svg")
    ap.add_argument("--readme", help="README to update between the SKILLS markers (optional)")
    args = ap.parse_args()

    try:
        cats, max_level = load(args.data)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as err:
        sys.exit(f"error: {err}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_svg(cats, max_level), encoding="utf-8")
    print(f"wrote {out}")
    for c in cats:
        print(f'  {c["name"]:<16} {round(c["score"] * 100):>3}%  ({len(c["tools"])} tools)')

    if args.readme and update_readme(args.readme, cats):
        print(f"updated {args.readme}")


if __name__ == "__main__":
    main()