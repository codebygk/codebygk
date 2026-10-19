#!/usr/bin/env python3
"""Generate an animated repo-constellation SVG (and an optional linked README
table) from your GitHub repos or a manual list.

Usage:
    python build_constellation.py
    python build_constellation.py --readme README.md
    python build_constellation.py --offline          # use repos_cache.json only
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # pip install tomli
    except ModuleNotFoundError:
        sys.exit("Python 3.11+ is required (or: pip install tomli).")

W, H = 900, 560
CX, CY = W // 2, 275
GOLDEN = math.radians(137.508)
SPACING = 40
PALETTE = ["#2dd4bf", "#f5c542", "#a78bfa", "#fb7185", "#38bdf8", "#4ade80"]
OTHER_COLOR = "#6b7a90"
NO_LANG = ("Other", "#94a3b8")
LANG_COLORS = {
    "Python": "#3776ab", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Java": "#ed8b00", "C#": "#9b4f96", "Go": "#00add8", "Rust": "#dea584",
    "HTML": "#e34c26", "CSS": "#8b5cf6", "Shell": "#89e051", "Dart": "#00b4ab",
    "Vue": "#42b883", "Jupyter Notebook": "#da5b0b", "Dockerfile": "#2496ed",
    "C++": "#f34b7d", "C": "#a0a0a0", "Kotlin": "#a97bff", "Swift": "#f05138",
}
START, END = "<!-- CONSTELLATION:START -->", "<!-- CONSTELLATION:END -->"


# ---------- config ----------
def load_config(path):
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    c = data.get("constellation", {})
    cfg = {
        "user": c.get("user", ""),
        "source": c.get("source", "github"),
        "max_repos": int(c.get("max_repos", 20)),
        "max_per_theme": int(c.get("max_per_theme", 7)),
        "include_forks": bool(c.get("include_forks", False)),
        "include_archived": bool(c.get("include_archived", False)),
        "exclude": {x.lower() for x in c.get("exclude", [])},
        "other_name": c.get("other_name", "Experiments"),
        "themes": data.get("theme", []),
        "manual": data.get("repo", []),
    }
    if cfg["source"] not in ("github", "manual"):
        raise ValueError('constellation.source must be "github" or "manual"')
    if not cfg["user"]:
        raise ValueError("constellation.user is required")
    for i, t in enumerate(cfg["themes"]):
        if not t.get("name"):
            raise ValueError(f"theme #{i + 1}: missing name")
        t.setdefault("color", PALETTE[i % len(PALETTE)])
    return cfg


# ---------- data ----------
def fetch_github(user, token=None):
    raw, page = [], 1
    while page <= 5:
        url = f"https://api.github.com/users/{user}/repos?per_page=100&page={page}&sort=pushed"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "constellation-builder"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            batch = json.load(r)
        raw.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [
        {
            "name": r["name"],
            "desc": r.get("description") or "",
            "lang": r.get("language") or "",
            "stars": r.get("stargazers_count", 0),
            "pushed": r.get("pushed_at") or "",
            "topics": r.get("topics", []),
            "url": r["html_url"],
            "fork": r.get("fork", False),
            "archived": r.get("archived", False),
        }
        for r in raw
    ]


def from_manual(cfg):
    out = []
    for r in cfg["manual"]:
        if not r.get("name"):
            raise ValueError(f"manual repo missing name: {r}")
        out.append({
            "name": r["name"],
            "desc": r.get("description", ""),
            "lang": r.get("language", ""),
            "stars": int(r.get("stars", 0)),
            "pushed": r.get("pushed", ""),
            "topics": list(r.get("topics", [])),
            "url": r.get("url", f"https://github.com/{cfg['user']}/{r['name']}"),
            "fork": False,
            "archived": False,
        })
    return out


def get_repos(cfg, cache_path, offline):
    if cfg["source"] == "manual":
        return from_manual(cfg)
    cache = Path(cache_path)
    if not offline:
        try:
            repos = fetch_github(cfg["user"], os.environ.get("GITHUB_TOKEN"))
            cache.write_text(json.dumps(repos, indent=1), encoding="utf-8")
            return repos
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
            print(f"! GitHub fetch failed ({err}); trying cache", file=sys.stderr)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    raise RuntimeError("No data: GitHub fetch failed and no cache file exists")


def parse_date(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def score(r, now):
    d = parse_date(r["pushed"])
    days = (now - d).days if d else 365
    days = max(0, days) // 7 * 7          # weekly buckets keep the SVG stable day to day
    recency = math.exp(-days / 150)
    stars = min(1.0, math.log1p(r["stars"]) / math.log1p(50))
    return 0.7 * recency + 0.3 * stars


def pick(repos, cfg, now):
    keep = []
    for r in repos:
        if r["name"].lower() in cfg["exclude"] or r["name"].lower() == cfg["user"].lower():
            continue
        if r["fork"] and not cfg["include_forks"]:
            continue
        if r["archived"] and not cfg["include_archived"]:
            continue
        r["score"] = score(r, now)
        keep.append(r)
    keep.sort(key=lambda r: (-r["score"], r["name"].lower()))
    return keep[: cfg["max_repos"]]


# ---------- grouping ----------
def assign(repo, themes):
    name = repo["name"].lower()
    topics = {t.lower() for t in repo["topics"]}
    hay = f'{repo["name"]} {repo["desc"]}'.lower()
    for t in themes:                                   # pass 1: explicit names
        if name in [x.lower() for x in t.get("repos", [])]:
            return t["name"]
    for t in themes:                                   # pass 2: topics
        if topics & {x.lower() for x in t.get("topics", [])}:
            return t["name"]
    for t in themes:                                   # pass 3: keywords
        if any(k.lower() in hay for k in t.get("keywords", [])):
            return t["name"]
    return None


def group(repos, cfg):
    colors = {t["name"]: t["color"] for t in cfg["themes"]}
    order = [t["name"] for t in cfg["themes"]]
    buckets = {n: [] for n in order}
    buckets[cfg["other_name"]] = []
    colors[cfg["other_name"]] = OTHER_COLOR
    for r in repos:
        buckets[assign(r, cfg["themes"]) or cfg["other_name"]].append(r)
    groups = []
    for name in order + [cfg["other_name"]]:
        members = buckets[name][: cfg["max_per_theme"]]
        if members:
            groups.append({"name": name, "color": colors[name], "repos": members})
    if not groups:
        raise ValueError("No repositories to draw (check filters, user name and themes)")
    for g in groups:
        for r in g["repos"]:
            r["theme"] = g["name"]
    return groups


# ---------- layout ----------
def lang_color(lang):
    if not lang:
        return NO_LANG
    if lang in LANG_COLORS:
        return lang, LANG_COLORS[lang]
    h = int(hashlib.md5(lang.encode()).hexdigest(), 16)
    return lang, PALETTE[h % len(PALETTE)]


def layout(groups):
    k = len(groups)
    base = 180 if k == 2 else -90
    clusters = []
    for i, g in enumerate(groups):
        if k == 1:
            cx, cy = CX, CY
        else:
            a = math.radians(base + i * 360 / k)
            cx, cy = CX + 290 * math.cos(a), CY - 5 + 165 * math.sin(a)
        nodes = []
        for j, r in enumerate(g["repos"]):
            dist = 0 if j == 0 else SPACING * math.sqrt(j)
            x = max(70, min(W - 70, cx + dist * math.cos(j * GOLDEN)))
            y = max(80, min(H - 80, cy + dist * math.sin(j * GOLDEN)))
            lang, color = lang_color(r["lang"])
            nodes.append({"repo": r, "x": x, "y": y, "r": 7 + 12 * r["score"],
                          "lang": lang, "color": color})
        edges = []
        for j in range(1, len(nodes)):
            nearest = min(range(j), key=lambda m: (nodes[m]["x"] - nodes[j]["x"]) ** 2
                                                  + (nodes[m]["y"] - nodes[j]["y"]) ** 2)
            edges.append((nearest, j))
        clusters.append({"name": g["name"], "color": g["color"], "cx": cx, "cy": cy,
                         "nodes": nodes, "edges": edges})
    return clusters


# ---------- svg ----------
def short(s, n):
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def build_svg(user, clusters):
    rng = random.Random(user)
    total = sum(len(c["nodes"]) for c in clusters)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label={quoteattr(f"Constellation of {total} repositories by {user}, grouped into " + ", ".join(c["name"] for c in clusters))}>',
        "<style>text { font-family: 'JetBrains Mono','Fira Code',Menlo,Consolas,monospace; }</style>",
        "<defs>",
        '<radialGradient id="bg" cx="50%" cy="45%" r="75%">'
        '<stop offset="0" stop-color="#111c33"/><stop offset="1" stop-color="#0b1220"/></radialGradient>',
    ]
    for i, c in enumerate(clusters):
        out.append(
            f'<radialGradient id="neb{i}"><stop offset="0" stop-color="{c["color"]}" stop-opacity="0.18"/>'
            f'<stop offset="1" stop-color="{c["color"]}" stop-opacity="0"/></radialGradient>'
        )
    out.append("</defs>")
    out.append(f'<rect width="{W}" height="{H}" rx="14" fill="url(#bg)"/>')

    # background dust
    for _ in range(90):
        x, y = rng.uniform(10, W - 10), rng.uniform(10, H - 10)
        r = rng.choice([0.6, 0.8, 1.0, 1.3])
        dur, begin = rng.uniform(2.5, 6), rng.uniform(0, 5)
        out.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="#9fb0c8" opacity="0.5">'
            f'<animate attributeName="opacity" values="0.15;0.7;0.15" dur="{dur:.1f}s" begin="-{begin:.1f}s" repeatCount="indefinite"/></circle>'
        )

    out.append('<text x="32" y="38" style="font-size:12px;letter-spacing:5px;fill:#6b7a90">REPO CONSTELLATION</text>')
    out.append(f'<text x="{W - 32}" y="38" text-anchor="end" style="font-size:12px;fill:#6b7a90">@{escape(user)} · {total} repos</text>')

    for i, c in enumerate(clusters):
        nodes = c["nodes"]
        reach = max(math.hypot(n["x"] - c["cx"], n["y"] - c["cy"]) for n in nodes) + 70
        out.append(f'<circle cx="{c["cx"]:.0f}" cy="{c["cy"]:.0f}" r="{reach:.0f}" fill="url(#neb{i})"/>')

        for a, b in c["edges"]:
            na, nb = nodes[a], nodes[b]
            out.append(
                f'<line x1="{na["x"]:.1f}" y1="{na["y"]:.1f}" x2="{nb["x"]:.1f}" y2="{nb["y"]:.1f}" '
                f'stroke="{c["color"]}" stroke-opacity="0.45" stroke-width="1" stroke-dasharray="3 6">'
                '<animate attributeName="stroke-dashoffset" from="0" to="-27" dur="3s" repeatCount="indefinite"/></line>'
            )

        top = max(62, min(n["y"] - n["r"] for n in nodes) - 18)
        out.append(
            f'<text x="{c["cx"]:.0f}" y="{top:.0f}" text-anchor="middle" '
            f'style="font-size:11px;letter-spacing:3px;font-weight:700;fill:{c["color"]}">{escape(c["name"].upper())}</text>'
        )

        for n in nodes:
            r = n["repo"]
            dur, begin = rng.uniform(2.5, 4.5), rng.uniform(0, 4)
            tip = f'{r["name"]} · {n["lang"]} · ★ {r["stars"]}'
            sub = f'★ {r["stars"]}' if r["stars"] else n["lang"]
            out.append(
                f'<g><title>{escape(tip)}</title>'
                f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"] * 2.1:.1f}" fill="{n["color"]}" opacity="0.14">'
                f'<animate attributeName="opacity" values="0.08;0.3;0.08" dur="{dur:.1f}s" begin="-{begin:.1f}s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"]:.1f}" fill="{n["color"]}"/>'
                f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"] * 0.38:.1f}" fill="#ffffff" opacity="0.9"/>'
                f'<text x="{n["x"]:.1f}" y="{n["y"] + n["r"] + 15:.1f}" text-anchor="middle" '
                f'style="font-size:11px;font-weight:700;fill:#e6edf7">{escape(short(r["name"], 18))}</text>'
                f'<text x="{n["x"]:.1f}" y="{n["y"] + n["r"] + 28:.1f}" text-anchor="middle" '
                f'style="font-size:10px;fill:#6b7a90">{escape(sub)}</text></g>'
            )

    # legend
    langs = {}
    for c in clusters:
        for n in c["nodes"]:
            langs.setdefault(n["lang"], [n["color"], 0])[1] += 1
    x = 32
    for lang, (color, _) in sorted(langs.items(), key=lambda kv: -kv[1][1])[:7]:
        out.append(f'<circle cx="{x + 5}" cy="{H - 26}" r="5" fill="{color}"/>')
        out.append(f'<text x="{x + 16}" y="{H - 22}" style="font-size:11px;fill:#9fb0c8">{escape(lang)}</text>')
        x += 16 + len(lang) * 7 + 18
    out.append(f'<text x="{W - 32}" y="{H - 22}" text-anchor="end" style="font-size:11px;fill:#6b7a90">size = recent activity · color = language</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------- README block ----------
def build_block(user, clusters, svg_path):
    total = sum(len(c["nodes"]) for c in clusters)
    lines = [
        '<div align="center">',
        f'  <img src="{svg_path}" width="100%" alt="Constellation of {total} repositories by {escape(user)}"/>',
        "</div>",
        "",
        "| Repo | Cluster | Language | ★ | Last push |",
        "|:--|:--|:--|--:|:--|",
    ]
    for c in clusters:
        for n in c["nodes"]:
            r = n["repo"]
            desc = short(r["desc"].replace("|", "/"), 60)
            label = f'**[{r["name"]}]({r["url"]})**' + (f"<br><sub>{desc}</sub>" if desc else "")
            lines.append(f'| {label} | {c["name"]} | {n["lang"]} | {r["stars"]} | {r["pushed"][:10] or "-"} |')
    return "\n".join(lines)


def update_readme(path, block):
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        print(f"! {path}: markers not found. Add {START} and {END} where the constellation should go.")
        return False
    Path(path).write_text(pattern.sub(lambda _: f"{START}\n{block}\n{END}", text), encoding="utf-8")
    return True


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="data/constellation.toml")
    ap.add_argument("--out", default="assets/constellation.svg")
    ap.add_argument("--cache", default="repos_cache.json")
    ap.add_argument("--readme", help="README to update between the CONSTELLATION markers (optional)")
    ap.add_argument("--offline", action="store_true", help="skip the GitHub API and use the cache")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        now = datetime.now(timezone.utc)
        repos = pick(get_repos(cfg, args.cache, args.offline), cfg, now)
        clusters = layout(group(repos, cfg))
    except (OSError, RuntimeError, ValueError, tomllib.TOMLDecodeError) as err:
        sys.exit(f"error: {err}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_svg(cfg["user"], clusters), encoding="utf-8")
    print(f"wrote {out}")
    for c in clusters:
        print(f'  {c["name"]:<16} {len(c["nodes"])} repos')

    if args.readme and update_readme(args.readme, build_block(cfg["user"], clusters, out.as_posix())):
        print(f"updated {args.readme}")


if __name__ == "__main__":
    main()