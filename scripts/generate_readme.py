#!/usr/bin/env python3
"""
Code By GK - GitHub Profile README Generator

Generates:
    README.md
    assets/profile-banner.svg
    assets/github-stats.svg
    assets/language-stats.svg
    assets/contribution-heatmap.svg
    output/profile.json
    output/repositories.json
    output/languages.json
    output/contributions.json

Requirements:
    Python 3.11+
    GITHUB_USERNAME environment variable (optional; defaults to codebygk)
    GITHUB_TOKEN environment variable (recommended for contribution data)

Uses only the Python standard library.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
README_PATH = ROOT / "README.md"
TECHNOLOGIES_PATH = DATA_DIR / "technologies.toml"

load_dotenv = os.getenv("LOAD_DOTENV", "1").strip() != "0"
if load_dotenv:
    dotenv_path = ROOT / ".env"
    if dotenv_path.exists():
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(dotenv_path)
USERNAME = os.getenv("GITHUB_USERNAME", "codebygk").strip()
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

API_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"

REQUEST_TIMEOUT = 20
MAX_REPOSITORIES = 100
FEATURED_REPOSITORIES = 6

# Restrained palette for a clean, premium appearance.
COLORS = {
    "background": "#0d1117",
    "panel": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#919ba6",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "purple": "#bc8cff",
    "orange": "#f0883e",
}

# Edit these links and descriptions to match the live website.
SITE_URL = "https://codebygk.com"

PRODUCTS = [
    {
        "name": "FinKite",
        "url": "https://finkite.codebygk.com",
        "description": "Personal finance calculators and planning tools.",
    },
    {
        "name": "NanoRead",
        "url": "https://nanoread.codebygk.com",
        "description": "Turn web content into concise, structured takeaways.",
    },
    {
        "name": "Dorkmine",
        "url": "https://dorkmine.codebygk.com",
        "description": "Build search queries for OSINT and security research.",
    },
    {
        "name": "DOM2POM",
        "url": f"{SITE_URL}/products/dom2pom",
        "description": "Tools for generating Page Object Model code.",
    },
]

RESOURCES = [
    {
        "name": "XPath Cheatsheet",
        "url": f"{SITE_URL}/resources/xpath-cheatsheet",
        "description": "XPath expressions, axes, functions, and locator patterns.",
    },
    {
        "name": "Playwright Locator Cheatsheet",
        "url": f"{SITE_URL}/resources/playwright-locator-cheatsheet",
        "description": "Practical locator strategies and examples.",
    },
    {
        "name": "CSS Selector Cheatsheet",
        "url": f"{SITE_URL}/resources/css-selector-cheatsheet",
        "description": "CSS selector syntax and useful patterns.",
    },
]

LEARNING_PATHS = [
    {
        "name": "Cybersecurity",
        "url": f"{SITE_URL}/learn/cybersecurity",
        "description": "Security fundamentals, reconnaissance, and testing concepts.",
    },
    {
        "name": "LLM Fundamentals",
        "url": f"{SITE_URL}/learn/llm-fundamentals",
        "description": "Core concepts behind large language models.",
    },
]

PRACTICE_LABS = [
    {
        "name": "ShopLabs",
        "url": "https://shoplabs.codebygk.com",
        "description": "E-commerce workflows for automation testing.",
    },
    {
        "name": "BankLabs",
        "url": "https://banklabs.codebygk.com",
        "description": "Banking workflows for automation testing.",
    },
    {
        "name": "CarLabs",
        "url": "https://carlabs.codebygk.com",
        "description": "Car-booking workflows for automation testing.",
    },
]

SOCIAL_LINKS = [
    ("Website", SITE_URL),
    ("GitHub", f"https://github.com/{USERNAME}"),
    ("LinkedIn", f"https://www.linkedin.com/in/{USERNAME}"),
    ("YouTube", f"https://www.youtube.com/@{USERNAME}"),
    ("Instagram", f"https://www.instagram.com/{USERNAME}"),
]

# API results older than this may be refreshed.
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60


# ---------------------------------------------------------------------------
# Files and cache helpers
# ---------------------------------------------------------------------------

def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cache_is_fresh(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
        return age < CACHE_MAX_AGE_SECONDS
    except OSError:
        return False


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def github_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "CodeByGK-Profile-README-Generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_with_cache(
    url: str,
    cache_path: Path,
    *,
    force: bool = False,
) -> Any:
    cached = load_json(cache_path)

    if cached is not None and not force and cache_is_fresh(cache_path):
        return cached

    try:
        result = github_request(url)
        save_json(cache_path, result)
        return result
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        if cached is not None:
            print(f"Warning: API request failed; using cache: {exc}", file=sys.stderr)
            return cached
        raise RuntimeError(
            f"GitHub API request failed and no cache is available: {url}\n{exc}"
        ) from exc


def fetch_profile() -> dict[str, Any]:
    return fetch_with_cache(
        f"{API_BASE}/users/{urllib.parse.quote(USERNAME)}",
        OUTPUT_DIR / "profile.json",
    )


def fetch_repositories() -> list[dict[str, Any]]:
    url = (
        f"{API_BASE}/users/{urllib.parse.quote(USERNAME)}/repos"
        "?type=owner&sort=updated&per_page=100"
    )

    repositories = fetch_with_cache(url, OUTPUT_DIR / "repositories.json")

    if not isinstance(repositories, list):
        raise RuntimeError("Unexpected repository response from GitHub API.")

    # Exclude forks and archived repositories from the featured list.
    return [
        repo for repo in repositories
        if not repo.get("fork", False)
    ]


def fetch_contributions() -> dict[str, Any]:
    cache_path = OUTPUT_DIR / "contributions.json"
    cached = load_json(cache_path)

    if not TOKEN:
        if cached is not None:
            print(
                "Warning: GITHUB_TOKEN is not set; using cached contribution data.",
                file=sys.stderr,
            )
            return cached

        print(
            "Warning: GITHUB_TOKEN is not set; contribution calendar will be empty.",
            file=sys.stderr,
        )
        return {"total": 0, "days": []}

    if cached is not None and cache_is_fresh(cache_path):
        return cached

    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    try:
        result = github_request(
            GRAPHQL_URL,
            method="POST",
            payload={
                "query": query,
                "variables": {"login": USERNAME},
            },
        )

        if result.get("errors"):
            raise RuntimeError(str(result["errors"]))

        calendar = (
            result.get("data", {})
            .get("user", {})
            .get("contributionsCollection", {})
            .get("contributionCalendar", {})
        )

        days = [
            {
                "date": day["date"],
                "count": day["contributionCount"],
            }
            for week in calendar.get("weeks", [])
            for day in week.get("contributionDays", [])
        ]

        contributions = {
            "total": calendar.get("totalContributions", 0),
            "days": days,
        }

        save_json(cache_path, contributions)
        return contributions

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        RuntimeError,
        KeyError,
    ) as exc:
        if cached is not None:
            print(f"Warning: contribution query failed; using cache: {exc}", file=sys.stderr)
            return cached

        print(f"Warning: contribution query failed: {exc}", file=sys.stderr)
        return {"total": 0, "days": []}


def fetch_languages(
    repositories: list[dict[str, Any]],
) -> dict[str, int]:
    cache_path = OUTPUT_DIR / "languages.json"
    cached = load_json(cache_path)

    if cached is not None and cache_is_fresh(cache_path):
        return cached

    totals: Counter[str] = Counter()
    failures = 0

    # Limit the number of repositories to keep API use reasonable.
    for repo in repositories[:MAX_REPOSITORIES]:
        if repo.get("archived") or repo.get("disabled"):
            continue

        language_url = repo.get("languages_url")
        if not language_url:
            continue

        try:
            languages = github_request(language_url)
            for language, byte_count in languages.items():
                totals[language] += int(byte_count)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            ValueError,
        ) as exc:
            failures += 1
            print(
                f"Warning: unable to read languages for "
                f"{repo.get('name', 'repository')}: {exc}",
                file=sys.stderr,
            )

    if failures and not totals and cached is not None:
        return cached

    result = dict(totals.most_common())
    save_json(cache_path, result)
    return result


# ---------------------------------------------------------------------------
# SVG utilities
# ---------------------------------------------------------------------------

def xml_escape(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def svg_text(
    x: int,
    y: int,
    text: str,
    *,
    size: int = 14,
    color: str | None = None,
    weight: int = 400,
    anchor: str = "start",
) -> str:
    color = color or COLORS["text"]
    return (
        f'<text x="{x}" y="{y}" fill="{color}" '
        f'font-family="Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
        f'{xml_escape(text)}</text>'
    )


def svg_header(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{xml_escape(title)}">'
        f'<rect width="100%" height="100%" rx="12" fill="{COLORS["background"]}"/>'
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" '
        f'rx="11" fill="none" stroke="{COLORS["border"]}"/>'
    )


def save_svg(name: str, contents: str) -> None:
    (ASSETS_DIR / name).write_text(contents + "\n", encoding="utf-8")

def generate_stats_svg(
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    contributions: dict[str, Any],
) -> None:
    width, height = 900, 174

    stars = sum(
        int(repo.get("stargazers_count", 0))
        for repo in repositories
    )

    forks = sum(
        int(repo.get("forks_count", 0))
        for repo in repositories
    )

    total_contributions = int(contributions.get("total", 0))

    stats = [
        ("PUBLIC REPOSITORIES", profile.get("public_repos", 0), COLORS["accent"]),
        ("FOLLOWERS", profile.get("followers", 0), COLORS["green"]),
        ("TOTAL STARS", stars, COLORS["purple"]),
        ("CONTRIBUTIONS", total_contributions, COLORS["orange"]),
    ]

    parts = [svg_header(width, height, "GitHub profile statistics")]
    parts.append(svg_text(28, 35, "GitHub at a glance", size=17, weight=650))
    parts.append(svg_text(
        width - 28,
        35,
        "CODE BY GK",
        size=11,
        color=COLORS["muted"],
        weight=600,
        anchor="end",
    ))

    card_width = 202
    gap = 15
    start_x = 28

    for index, (label, value, accent) in enumerate(stats):
        x = start_x + index * (card_width + gap)
        parts.append(
            f'<rect x="{x}" y="54" width="{card_width}" height="92" '
            f'rx="9" fill="{COLORS["panel"]}" stroke="{COLORS["border"]}"/>'
        )
        parts.append(
            f'<rect x="{x}" y="54" width="3" height="92" '
            f'rx="1.5" fill="{accent}"/>'
        )
        parts.append(svg_text(
            x + 16, 82, label, size=10,
            color=COLORS["muted"], weight=600,
        ))
        parts.append(svg_text(
            x + 16, 119, f"{int(value or 0):,}",
            size=27, color=COLORS["text"], weight=650,
        ))

    parts.append("</svg>")
    save_svg("github-stats.svg", "\n".join(parts))


def generate_language_svg(languages: dict[str, int]) -> None:
    width, height = 900, 220
    parts = [svg_header(width, height, "Programming language distribution")]
    parts.append(svg_text(28, 35, "Language distribution", size=17, weight=650))

    top = Counter({
        name: count
        for name, count in languages.items()
        if int(count) > 0
    }).most_common(6)

    if not top:
        parts.append(svg_text(
            28, 80, "Language data will appear after the first successful refresh.",
            color=COLORS["muted"],
        ))
        parts.append("</svg>")
        save_svg("language-stats.svg", "\n".join(parts))
        return

    total = sum(count for _, count in top)
    bar_x, bar_y, bar_width, bar_height = 28, 57, 844, 10

    palette = [
        COLORS["accent"],
        COLORS["purple"],
        COLORS["green"],
        COLORS["orange"],
        "#f778ba",
        "#79c0ff",
    ]

    parts.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_width}" '
        f'height="{bar_height}" rx="5" fill="{COLORS["border"]}"/>'
    )

    current_x = bar_x
    for index, (_, count) in enumerate(top):
        segment_width = bar_width * count / total
        parts.append(
            f'<rect x="{current_x:.2f}" y="{bar_y}" '
            f'width="{segment_width:.2f}" height="{bar_height}" '
            f'fill="{palette[index % len(palette)]}"/>'
        )
        current_x += segment_width

    columns = 3
    row_height = 48
    start_y = 104

    for index, (name, count) in enumerate(top):
        column = index % columns
        row = index // columns
        x = 28 + column * 285
        y = start_y + row * row_height
        percentage = count / total * 100

        parts.append(
            f'<circle cx="{x + 5}" cy="{y - 5}" r="4" '
            f'fill="{palette[index % len(palette)]}"/>'
        )
        parts.append(svg_text(x + 18, y, name, size=12, weight=550))
        parts.append(svg_text(
            x + 260, y, f"{percentage:.1f}%",
            size=12, color=COLORS["muted"], anchor="end",
        ))

    parts.append("</svg>")
    save_svg("language-stats.svg", "\n".join(parts))


def contribution_color(count: int) -> str:
    if count <= 0:
        return "#21262d"
    if count <= 2:
        return "#0e4429"
    if count <= 5:
        return "#006d32"
    if count <= 9:
        return "#26a641"
    return "#39d353"


def generate_heatmap_svg(contributions: dict[str, Any]) -> None:
    days = contributions.get("days", [])
    width, height = 1020, 246
    parts = [svg_header(width, height, "GitHub contribution heatmap")]

    parts.append(svg_text(30, 35, "Contribution activity", size=18, weight=650))
    parts.append(svg_text(
        width - 30, 35,
        f'{int(contributions.get("total", 0)):,} contributions in the last year',
        size=12, color=COLORS["accent"], weight=600, anchor="end",
    ))

    if not days:
        parts.append(svg_text(
            28, 75, "Contribution data is not available yet.",
            color=COLORS["muted"],
        ))
        parts.append("</svg>")
        save_svg("contribution-heatmap.svg", "\n".join(parts))
        return

    day_size = 13
    gap = 4
    cell_step = day_size + gap
    start_x = 68
    start_y = 72

    # Map calendar dates into weekday rows and week columns.
    parsed_days: list[tuple[date, int]] = []

    for item in days:
        try:
            parsed_days.append((
                date.fromisoformat(item["date"]),
                int(item.get("count", 0)),
            ))
        except (ValueError, TypeError, KeyError):
            continue

    if not parsed_days:
        parts.append("</svg>")
        save_svg("contribution-heatmap.svg", "\n".join(parts))
        return

    first_day = parsed_days[0][0]
    first_sunday = first_day - timedelta(days=(first_day.weekday() + 1) % 7)

    month_labels: dict[int, tuple[int, str]] = {}

    for day, count in parsed_days:
        offset = (day - first_sunday).days
        week = offset // 7
        weekday = (day.weekday() + 1) % 7
        x = start_x + week * cell_step
        y = start_y + weekday * cell_step

        parts.append(
            f'<rect x="{x}" y="{y}" width="{day_size}" height="{day_size}" '
            f'rx="2" fill="{contribution_color(count)}">'
            f'<animate attributeName="opacity" from="0" to="1" dur="420ms" '
            f'begin="{min(week * 0.012, 0.6):.2f}s" fill="freeze"/>'
            f'<title>{day.isoformat()}: {count} contributions</title></rect>'
        )

        if day.day <= 7:
            month_labels[week] = (week, day.strftime("%b"))

    for week, month in month_labels.values():
        x = start_x + week * cell_step
        parts.append(svg_text(
            x, 62, month, size=10, color=COLORS["muted"],
        ))

    for index, label in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
        if index in (0, 2, 4, 6):
            parts.append(svg_text(
                30, start_y + index * cell_step + 10,
                label, size=10, color=COLORS["muted"],
            ))

    legend_x = width - 160
    legend_y = height - 24
    parts.append(svg_text(
        legend_x - 32, legend_y + 8, "Less",
        size=10, color=COLORS["muted"],
    ))

    for index, count in enumerate([0, 1, 3, 6, 10]):
        parts.append(
            f'<rect x="{legend_x + index * 14}" y="{legend_y}" '
            f'width="10" height="10" rx="2" '
            f'fill="{contribution_color(count)}"/>'
        )

    parts.append(svg_text(
        legend_x + 80, legend_y + 8, "More",
        size=10, color=COLORS["muted"],
    ))

    parts.append("</svg>")
    save_svg("contribution-heatmap.svg", "\n".join(parts))


# ---------------------------------------------------------------------------
# README helpers
# ---------------------------------------------------------------------------

def load_technologies() -> dict[str, list[str]]:
    if not TECHNOLOGIES_PATH.exists():
        return {}

    try:
        with TECHNOLOGIES_PATH.open("rb") as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"Warning: unable to read technologies.toml: {exc}", file=sys.stderr)
        return {}

    result: dict[str, list[str]] = {}

    for section, value in config.items():
        if not isinstance(value, dict):
            continue

        label = value.get("label", section.replace("_", " "))
        items = value.get("items", [])

        if isinstance(items, list):
            result[str(label)] = [str(item) for item in items]

    return result


def markdown_link(name: str, url: str) -> str:
    return f"[{name}]({url})"


def render_link_row(items: list[tuple[str, str]]) -> str:
    return " · ".join(markdown_link(name, url) for name, url in items)


def render_content_table(items: list[dict[str, str]]) -> str:
    if not items:
        return "_More content coming soon._"

    rows = [
        "| Item | Description |",
        "|---|---|",
    ]

    for item in items:
        name = str(item["name"]).replace("|", "\\|")
        description = str(item["description"]).replace("|", "\\|")
        url = str(item["url"])

        rows.append(
            f"| **[{name}]({url})** | {description} |"
        )

    return "\n".join(rows)


def render_technologies(technologies: dict[str, list[str]]) -> str:
    if not technologies:
        return "_Add your technology groups to `technologies.toml`._"

    sections: list[str] = []

    for category, items in technologies.items():
        if not items:
            continue

        section_items = " · ".join(f"`{item}`" for item in items)
        sections.append(f"**{category}**  \n{section_items}")

    return "\n\n".join(sections)


def render_featured_repositories(
    repositories: list[dict[str, Any]],
) -> str:
    candidates = [
        repo for repo in repositories
        if not repo.get("archived", False)
        and not repo.get("disabled", False)
        and not repo.get("fork", False)
    ]

    candidates.sort(
        key=lambda repo: (
            int(repo.get("stargazers_count", 0)),
            int(repo.get("forks_count", 0)),
            repo.get("updated_at", ""),
        ),
        reverse=True,
    )

    featured = candidates[:FEATURED_REPOSITORIES]

    if not featured:
        return "_Repositories will appear here after a successful API refresh._"

    rows = [
        "| Repository | Description | Stars | Language |",
        "|---|---|---:|---|",
    ]

    for repo in featured:
        name = str(repo.get("name", "Repository"))
        url = str(repo.get("html_url", f"https://github.com/{USERNAME}"))
        description = str(repo.get("description") or "No description provided.")
        description = description.replace("|", "\\|")
        language = str(repo.get("language") or "-")
        stars = int(repo.get("stargazers_count", 0))

        rows.append(
            f"| [{name}]({url}) | {description} | {stars} | {language} |"
        )

    return "\n".join(rows)


def generate_readme(
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    technologies: dict[str, list[str]],
) -> str:
    display_name = profile.get("name") or "Gopalakrishnan"
    bio = profile.get("bio") or (
        "Senior SDET and software builder focused on automation, "
        "developer tools, and practical engineering resources."
    )
    public_repos = int(profile.get("public_repos", 0))
    followers = int(profile.get("followers", 0))

    links = [
        ("Website", SITE_URL),
        ("GitHub", f"https://github.com/{USERNAME}"),
        ("LinkedIn", f"https://www.linkedin.com/in/{USERNAME}"),
        ("YouTube", f"https://www.youtube.com/@{USERNAME}"),
        ("Instagram", f"https://www.instagram.com/{USERNAME}"),
    ]

    sections = [
        "# Code By GK",
        "### Build. Automate. Scale.",
        "",
        "",
        bio,
        "",
        render_link_row(links),
        "",
        "---",
        "",
        "## What I'm building",
        "",
        "Code By GK is a home for practical software products, developer "
        "resources, and structured learning material. The goal is simple: "
        "build useful things, explain them clearly, and make engineering work easier.",
        "",
        "## 📦 Products",
        "",
        render_content_table(PRODUCTS),
        "",
        f"[Explore all products →]({SITE_URL}/products)",
        "",
        "## 🧰 Resources",
        "",
        "Quick references and cheatsheets for common development and "
        "test automation tasks.",
        "",
        render_content_table(RESOURCES),
        "",
        f"[Browse all resources →]({SITE_URL}/resources)",
        "",
        "## 🧭 Learn",
        "",
        "A growing library of structured notes and practical learning paths.",
        "",
        render_content_table(LEARNING_PATHS),
        "",
        f"[Explore the learning library →]({SITE_URL}/learn)",
        "",
        "## 🧪 Practice labs",
        "",
        "Sample applications for practising test automation against "
        "realistic user journeys.",
        "",
        render_content_table(PRACTICE_LABS),
        "",
        "---",
        "",
        "## ⚙️ Technology",
        "",
        render_technologies(technologies),
        "",
        "---",
        "",
        "## ✨ Featured repositories",
        "",
        render_featured_repositories(repositories),
        "",
        "---",
        "",
        "## 📈 GitHub activity",
        "",
        '<div align="center">',
        "",
        '<img src="assets/github-stats.svg" alt="GitHub profile statistics" width="100%" />',
        "",
        '<img src="assets/language-stats.svg" alt="Programming language distribution" width="100%" />',
        "",
        '<img src="assets/contribution-heatmap.svg" alt="GitHub contribution heatmap" width="100%" />',
        "",
        "</div>",
        "",
        "---",
        "",
        "## 👋 A little about me",
        "",
        f"- **Public repositories:** {public_repos}",
        f"- **GitHub followers:** {followers}",
        "- **Focus:** test automation, developer tools, web applications, and AI-assisted engineering",
        "- **Approach:** build useful software, automate repetitive work, and share what I learn",
        "",
        "## 🤝 Connect",
        "",
        "Have an interesting engineering problem, a useful product idea, or an opportunity to collaborate? Let's connect.",
        "",
        render_link_row(links),
        "",
        "**Code By GK** · Build. Automate. Scale.",
        "",
    ]

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ensure_directories()

    print(f"Updating README for GitHub user: {USERNAME}")

    try:
        profile = fetch_profile()
        repositories = fetch_repositories()
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    contributions = fetch_contributions()
    languages = fetch_languages(repositories)
    technologies = load_technologies()

    generate_stats_svg(profile, repositories, contributions)
    generate_language_svg(languages)
    generate_heatmap_svg(contributions)

    readme = generate_readme(profile, repositories, technologies)
    README_PATH.write_text(readme, encoding="utf-8")

    print("README and SVG assets generated successfully.")
    print(f"README: {README_PATH}")
    print(f"Assets: {ASSETS_DIR}")
    print(f"Data cache: {OUTPUT_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())