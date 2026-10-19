#!/usr/bin/env python3
"""Generate one animated SVG card per product from products.toml, and
(optionally) rewrite the clickable shelf block in README.md.

Usage:
    python build_shelf.py
    python build_shelf.py --data data/products.toml --outdir assets/shelf --readme README.md
"""
import argparse
import re
import sys
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # pip install tomli
    except ModuleNotFoundError:
        sys.exit("Python 3.11+ is required (or: pip install tomli).")

W, H = 300, 200
PALETTE = ["#2dd4bf", "#f5c542", "#a78bfa", "#38bdf8", "#fb7185", "#4ade80"]
STATUS = {
    "live":     ("LIVE",     "#22c55e"),
    "beta":     ("BETA",     "#f5c542"),
    "building": ("BUILDING", "#38bdf8"),
    "planned":  ("PLANNED",  "#6b7a90"),
}
START, END = "<!-- SHELF:START -->", "<!-- SHELF:END -->"


# ---------- data ----------
def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load(path):
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    columns = int(data.get("shelf", {}).get("columns", 3))
    if not 1 <= columns <= 4:
        raise ValueError("shelf.columns must be between 1 and 4")

    products, seen = [], set()
    for i, p in enumerate(data.get("product", [])):
        for key in ("name", "tagline", "type", "status"):
            if not p.get(key):
                raise ValueError(f"product #{i + 1}: missing '{key}'")
        if p["status"] not in STATUS:
            raise ValueError(f"{p['name']}: status must be one of {', '.join(STATUS)}")
        url = p.get("url", "")
        if url and not url.startswith(("http://", "https://", "mailto:")):
            raise ValueError(f"{p['name']}: url must start with http(s)://")
        slug = slugify(p["name"])
        if not slug or slug in seen:
            raise ValueError(f"{p['name']}: name is empty or duplicates another product")
        seen.add(slug)
        products.append({
            "name": p["name"],
            "tagline": p["tagline"],
            "type": p["type"],
            "status": p["status"],
            "url": url,
            "tags": list(p.get("tags", [])),
            "accent": p.get("accent", PALETTE[i % len(PALETTE)]),
            "slug": slug,
            "delay": round(i * 0.45, 2),
        })
    if not products:
        raise ValueError("No [[product]] entries found")
    return products, columns


# ---------- svg ----------
def status_marker(status, color):
    """Animated dot at (30, 180) that behaves differently per status."""
    cx, cy = 30, 180
    if status == "live":
        return (
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="{color}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{color}" stroke-width="2" opacity="0">'
            '<animate attributeName="r" values="5;14;14" keyTimes="0;0.6;1" dur="2s" repeatCount="indefinite"/>'
            '<animate attributeName="opacity" values="0.8;0;0" keyTimes="0;0.6;1" dur="2s" repeatCount="indefinite"/>'
            "</circle>"
        )
    if status == "beta":
        return (
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="{color}">'
            '<animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite"/></circle>'
        )
    if status == "building":
        return (
            f'<circle cx="{cx}" cy="{cy}" r="7" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="6 5">'
            f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" '
            'dur="3s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{color}"/>'
        )
    return f'<circle cx="{cx}" cy="{cy}" r="6" fill="none" stroke="{color}" stroke-width="2"/>'


def tag_chips(tags, accent):
    out, x = [], 24
    for tag in tags[:3]:
        w = len(tag) * 6.8 + 18
        if x + w > W - 24:
            break
        out.append(
            f'<rect x="{x:.1f}" y="132" width="{w:.1f}" height="20" rx="10" fill="{accent}" fill-opacity="0.12" '
            f'stroke="{accent}" stroke-opacity="0.5"/>'
            f'<text x="{x + w / 2:.1f}" y="146" text-anchor="middle" style="font-size:11px;fill:{accent}">{escape(tag)}</text>'
        )
        x += w + 8
    return "".join(out)


def build_card(p):
    accent = p["accent"]
    label, scolor = STATUS[p["status"]]
    dashed = ' stroke-dasharray="6 5"' if p["status"] == "planned" else ""
    d = p["delay"]

    # shrink long names so they always fit
    name_size = max(14, min(22, (W - 48) / (len(p["name"]) * 0.62)))

    lines = textwrap.wrap(p["tagline"], 33)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:30].rstrip() + "…"]
    tagline = "".join(
        f'<text x="24" y="{102 + i * 18}" style="font-size:12px;fill:#9fb0c8">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    action = "open ↗" if p["url"] else "coming soon"
    action_color = accent if p["url"] else "#6b7a90"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label={quoteattr(f"{p['name']}: {p['tagline']} ({p['status']})")}>
  <defs>
    <clipPath id="card"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="12"/></clipPath>
    <linearGradient id="sweep" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.85"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <style>text {{ font-family: 'JetBrains Mono','Fira Code',Menlo,Consolas,monospace; }}</style>

  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="12" fill="#0f172a" stroke="#1b2740" stroke-width="2"{dashed}/>

  <g clip-path="url(#card)">
    <rect x="0" y="0" width="{W}" height="5" fill="{accent}"/>
    <rect x="-90" y="0" width="90" height="5" fill="url(#sweep)">
      <animate attributeName="x" values="-90;{W}" dur="3.2s" begin="{d}s" repeatCount="indefinite"/>
    </rect>
  </g>

  <text x="24" y="38" style="font-size:11px;letter-spacing:2px;fill:{accent}">{escape(p["type"].upper())}</text>
  <text x="24" y="72" style="font-size:{name_size:.1f}px;font-weight:700;fill:#e6edf7">{escape(p["name"])}</text>
  {tagline}
  {tag_chips(p["tags"], accent)}

  <line x1="24" y1="164" x2="{W - 24}" y2="164" stroke="#1b2740"/>
  {status_marker(p["status"], scolor)}
  <text x="46" y="185" style="font-size:12px;font-weight:700;letter-spacing:1px;fill:{scolor}">{label}</text>
  <text x="{W - 24}" y="185" text-anchor="end" style="font-size:12px;fill:{action_color}">{action}</text>
</svg>
'''


# ---------- README block ----------
def build_block(products, columns, svg_dir):
    rows = []
    for start in range(0, len(products), columns):
        cells = []
        for p in products[start:start + columns]:
            img = (
                f'<img src="{svg_dir}/{p["slug"]}.svg" width="300" '
                f'alt={quoteattr(p["name"] + ": " + p["tagline"])}/>'
            )
            body = f'<a href="{p["url"]}">{img}</a>' if p["url"] else img
            cells.append(f'  <td align="center" valign="top">{body}</td>')
        rows.append("<tr>\n" + "\n".join(cells) + "\n</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def update_readme(path, block):
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        print(f"! {path}: markers not found. Add {START} and {END} where the shelf should go.")
        return False
    Path(path).write_text(pattern.sub(lambda _: f"{START}\n{block}\n{END}", text), encoding="utf-8")
    return True


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/products.toml")
    ap.add_argument("--outdir", default="assets/shelf")
    ap.add_argument("--readme", help="README to update between the SHELF markers (optional)")
    args = ap.parse_args()

    try:
        products, columns = load(args.data)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as err:
        sys.exit(f"error: {err}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    written = set()
    for p in products:
        target = outdir / f"{p['slug']}.svg"
        target.write_text(build_card(p), encoding="utf-8")
        written.add(target.name)
        print(f"wrote {target}  [{p['status']}]")

    # remove cards for products you deleted from the TOML
    for old in outdir.glob("*.svg"):
        if old.name not in written:
            old.unlink()
            print(f"removed stale {old}")

    if args.readme:
        svg_dir = outdir.as_posix()
        if update_readme(args.readme, build_block(products, columns, svg_dir)):
            print(f"updated {args.readme}")


if __name__ == "__main__":
    main()