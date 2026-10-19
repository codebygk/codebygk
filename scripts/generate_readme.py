
#!/usr/bin/env python3
"""Generate Code By GK's GitHub profile README and SVG statistics."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"

README_FILE = ROOT / "README.md"
TECHNOLOGIES_FILE = DATA_DIR / "technologies.toml"

load_dotenv = getattr(__import__("dotenv"), "load_dotenv", None)
if load_dotenv:
    load_dotenv(ROOT / ".env")
USERNAME = os.getenv("GITHUB_USERNAME", "codebygk")
TOKEN = os.getenv("GITHUB_TOKEN", "")

API_BASE = "https://api.github.com"
GRAPHQL_URL = f"{API_BASE}/graphql"

BG = "#0B1120"
PANEL = "#101A2D"
BORDER = "#24324A"
TEXT = "#E6EDF7"
MUTED = "#94A3B8"
GREEN = "#3DDC97"
BLUE = "#60A5FA"
PURPLE = "#A78BFA"

LANGUAGE_COLORS = [
    GREEN,
    BLUE,
    PURPLE,
    "#FBBF24",
    "#F472B6",
    "#22D3EE",
]

HEATMAP_COLORS = [
    "#1B2638",
    "#15543F",
    "#16845C",
    "#2DBB80",
    "#6EE7B7",
]


# ---------------------------------------------------------------------------
# Files and JSON cache
# ---------------------------------------------------------------------------

def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(filename: str, content: dict | list) -> None:
    """Write JSON atomically to avoid leaving a partially written cache."""
    path = DATA_DIR / filename
    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(filename: str) -> dict | list | None:
    path = DATA_DIR / filename

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: could not read {path}: {exc}", file=sys.stderr)
        return None


def fetch_or_cache(
    filename: str,
    fetch_function,
    expected_type: type,
) -> dict | list:
    """Fetch fresh data, saving it on success; otherwise use cached data."""
    try:
        result = fetch_function()

        if not isinstance(result, expected_type):
            raise RuntimeError(
                f"Unexpected response type for {filename}: "
                f"{type(result).__name__}"
            )

        save_json(filename, result)
        return result

    except (RuntimeError, OSError, ValueError) as exc:
        cached = load_json(filename)

        if isinstance(cached, expected_type):
            print(
                f"Warning: {filename}: {exc}. Using cached data.",
                file=sys.stderr,
            )
            return cached

        raise RuntimeError(
            f"Unable to fetch {filename} and no valid cache exists."
        ) from exc


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def request_json(url: str, payload: dict | None = None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CodeByGK-Profile-Stats",
    }

    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    data = None
    method = "GET"

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        method = "POST"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API HTTP {exc.code}: {detail[:300]}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API connection failed: {exc}") from exc


def get_profile() -> dict:
    result = request_json(f"{API_BASE}/users/{USERNAME}")

    if not isinstance(result, dict) or "login" not in result:
        raise RuntimeError("GitHub returned an invalid profile response.")

    return result


def get_repositories() -> list[dict]:
    """Fetch every public repository owned by the user."""
    repositories = []
    page = 1

    while True:
        url = (
            f"{API_BASE}/users/{USERNAME}/repos"
            f"?per_page=100&page={page}&sort=updated"
            "&direction=desc&type=owner"
        )

        batch = request_json(url)

        if not isinstance(batch, list):
            raise RuntimeError("Invalid repositories API response.")

        repositories.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    return repositories


def get_contribution_calendar() -> dict:
    """Fetch the last 365 days of contributions using GraphQL."""
    if not TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN is required for the contribution calendar."
        )

    today = date.today()
    start = today - timedelta(days=364)

    from_date = f"{start.isoformat()}T00:00:00Z"
    to_date = f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z"

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
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

    result = request_json(
        GRAPHQL_URL,
        {
            "query": query,
            "variables": {
                "login": USERNAME,
                "from": from_date,
                "to": to_date,
            },
        },
    )

    if not isinstance(result, dict):
        raise RuntimeError("Invalid GraphQL response.")

    if result.get("errors"):
        raise RuntimeError(
            "GraphQL error: " + json.dumps(result["errors"])[:300]
        )

    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"Could not find GitHub user {USERNAME!r}.")

    return user["contributionsCollection"]["contributionCalendar"]


# ---------------------------------------------------------------------------
# Technology configuration
# ---------------------------------------------------------------------------

def load_technologies() -> list[tuple[str, list[str]]]:
    if not TECHNOLOGIES_FILE.exists():
        print(
            f"Warning: {TECHNOLOGIES_FILE} not found.",
            file=sys.stderr,
        )
        return []

    with TECHNOLOGIES_FILE.open("rb") as file:
        config = tomllib.load(file)

    categories = []

    for key, value in config.items():
        if not isinstance(value, dict):
            continue

        label = value.get(
            "label",
            key.replace("_", " ").replace("and", "&"),
        )

        items = list(dict.fromkeys(
            str(item).strip()
            for item in value.get("items", [])
            if str(item).strip()
        ))

        if items:
            categories.append((label, items))

    return categories


# ---------------------------------------------------------------------------
# SVG utilities
# ---------------------------------------------------------------------------

def svg_text(value: object) -> str:
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def svg_start(width: int, height: int, title: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg"
    width="{width}" height="{height}"
    viewBox="0 0 {width} {height}"
    role="img" aria-labelledby="svg-title">
    <title id="svg-title">{svg_text(title)}</title>
    <rect width="100%" height="100%" rx="16" fill="{BG}"/>
    """


def write_svg(filename: str, content: str) -> None:
    (ASSETS_DIR / filename).write_text(content, encoding="utf-8")


def fmt(number: int) -> str:
    return f"{number:,}"


# ---------------------------------------------------------------------------
# Statistics SVG
# ---------------------------------------------------------------------------

def write_stats_svg(
    profile: dict,
    repositories: list[dict],
    calendar: dict | None,
) -> None:
    stars = sum(r.get("stargazers_count", 0) for r in repositories)
    forks = sum(r.get("forks_count", 0) for r in repositories)

    metrics = [
        ("PUBLIC REPOSITORIES", fmt(profile.get("public_repos", 0)), GREEN),
        ("FOLLOWERS", fmt(profile.get("followers", 0)), BLUE),
        ("STARS", fmt(stars), PURPLE),
        ("FORKS", fmt(forks), GREEN),
    ]

    width, height = 760, 230
    svg = [svg_start(width, height, "GitHub statistics")]

    svg.append(
        f'<text x="24" y="32" fill="{MUTED}" font-size="11" '
        'letter-spacing="2" font-family="Arial, sans-serif">'
        'CODE BY GK / GITHUB OVERVIEW</text>'
    )

    positions = [(24, 48), (392, 48), (24, 132), (392, 132)]

    for (label, value, accent), (x, y) in zip(metrics, positions):
        svg.append(
            f'<rect x="{x}" y="{y}" width="344" height="70" rx="12" '
            f'fill="{PANEL}" stroke="{BORDER}"/>'
        )
        svg.append(
            f'<rect x="{x}" y="{y + 13}" width="3" height="44" '
            f'rx="1.5" fill="{accent}"/>'
        )
        svg.append(
            f'<text x="{x + 16}" y="{y + 25}" fill="{MUTED}" '
            'font-size="10" letter-spacing="1" '
            'font-family="Arial, sans-serif">'
            f'{svg_text(label)}</text>'
        )
        svg.append(
            f'<text x="{x + 16}" y="{y + 53}" fill="{TEXT}" '
            'font-size="23" font-weight="700" '
            'font-family="Arial, sans-serif">'
            f'{svg_text(value)}</text>'
        )

    if calendar is not None:
        contributions = calendar.get("totalContributions", 0)
        svg.append(
            f'<text x="380" y="220" text-anchor="middle" '
            f'fill="{MUTED}" font-size="10" '
            'font-family="Arial, sans-serif">'
            f'{fmt(contributions)} contributions in the last 365 days'
            '</text>'
        )

    svg.append("</svg>\n")
    write_svg("github-stats.svg", "".join(svg))


# ---------------------------------------------------------------------------
# Contribution heatmap SVG
# ---------------------------------------------------------------------------

def heatmap_color(count: int) -> str:
    if count == 0:
        return HEATMAP_COLORS[0]
    if count <= 2:
        return HEATMAP_COLORS[1]
    if count <= 5:
        return HEATMAP_COLORS[2]
    if count <= 9:
        return HEATMAP_COLORS[3]
    return HEATMAP_COLORS[4]


def write_heatmap(calendar: dict | None) -> None:
    width, height = 900, 174
    svg = [svg_start(width, height, "Contribution activity")]

    svg.append(
        f'<text x="24" y="29" fill="{TEXT}" font-size="15" '
        'font-weight="700" font-family="Arial, sans-serif">'
        'Contribution activity</text>'
    )

    if not calendar:
        svg.append(
            f'<text x="24" y="64" fill="{MUTED}" font-size="12" '
            'font-family="Arial, sans-serif">'
            'Contribution data is not available yet.'
            '</text></svg>'
        )
        write_svg("contribution-heatmap.svg", "".join(svg))
        return

    weeks = calendar.get("weeks", [])
    cell_size = 10
    gap = 4
    x_origin, y_origin = 24, 50
    month_labels = []
    last_month = None

    for column, week in enumerate(weeks):
        for row, day_data in enumerate(week.get("contributionDays", [])):
            count = day_data.get("contributionCount", 0)
            day_date = day_data.get("date", "")
            x = x_origin + column * (cell_size + gap)
            y = y_origin + row * (cell_size + gap)

            svg.append(
                f'<rect x="{x}" y="{y}" width="{cell_size}" '
                f'height="{cell_size}" rx="2" '
                f'fill="{heatmap_color(count)}">'
                f'<title>{svg_text(day_date)}: {count} contributions</title>'
                '</rect>'
            )

            month = day_date[:7]
            if month != last_month:
                month_labels.append((x, month))
                last_month = month

    for x, month in month_labels:
        try:
            label = date.fromisoformat(month + "-01").strftime("%b")
        except ValueError:
            continue

        svg.append(
            f'<text x="{x}" y="43" fill="{MUTED}" font-size="10" '
            'font-family="Arial, sans-serif">'
            f'{label}</text>'
        )

    legend_y = 151
    svg.append(
        f'<text x="24" y="{legend_y + 9}" fill="{MUTED}" '
        'font-size="10" font-family="Arial, sans-serif">Less</text>'
    )

    for index, color in enumerate(HEATMAP_COLORS):
        svg.append(
            f'<rect x="{62 + index * 17}" y="{legend_y}" '
            f'width="11" height="11" rx="2" fill="{color}"/>'
        )

    svg.append(
        f'<text x="155" y="{legend_y + 9}" fill="{MUTED}" '
        'font-size="10" font-family="Arial, sans-serif">More</text>'
    )
    svg.append("</svg>\n")

    write_svg("contribution-heatmap.svg", "".join(svg))


# ---------------------------------------------------------------------------
# Language statistics
# ---------------------------------------------------------------------------

def get_language_totals(repositories: list[dict]) -> Counter:
    """Fetch language byte counts; use cached totals if any request fails."""
    totals = Counter()
    failed = []

    for repo in repositories:
        if repo.get("fork") or repo.get("archived"):
            continue

        languages_url = repo.get("languages_url")
        if not languages_url:
            continue

        try:
            languages = request_json(languages_url)
            if not isinstance(languages, dict):
                raise RuntimeError("Invalid language response.")

            for name, byte_count in languages.items():
                totals[name] += byte_count

        except (RuntimeError, OSError, ValueError) as exc:
            failed.append(f"{repo.get('name', '?')}: {exc}")

    if failed:
        cached = load_json("languages.json")

        if isinstance(cached, dict) and cached:
            print(
                "Warning: some language requests failed. "
                "Using cached language totals.",
                file=sys.stderr,
            )
            return Counter({
                str(name): int(count)
                for name, count in cached.items()
                if isinstance(count, (int, float))
            })

        print(
            f"Warning: {len(failed)} language requests failed.",
            file=sys.stderr,
        )

    save_json("languages.json", dict(totals))
    return totals


def write_language_svg(totals: Counter) -> None:
    width, height = 760, 250
    svg = [svg_start(width, height, "Language distribution")]

    svg.append(
        f'<text x="24" y="32" fill="{TEXT}" font-size="15" '
        'font-weight="700" font-family="Arial, sans-serif">'
        'Language distribution</text>'
    )

    top_languages = totals.most_common(6)
    total_bytes = sum(totals.values())

    if not top_languages or total_bytes == 0:
        svg.append(
            f'<text x="24" y="65" fill="{MUTED}" font-size="12" '
            'font-family="Arial, sans-serif">'
            'No language data available.</text>'
        )
    else:
        bar_x, bar_y, bar_width = 24, 51, 712
        cursor = bar_x

        for index, (language, byte_count) in enumerate(top_languages):
            segment = bar_width * byte_count / total_bytes
            visible_width = max(1, segment - 3)
            color = LANGUAGE_COLORS[index % len(LANGUAGE_COLORS)]

            svg.append(
                f'<rect x="{cursor:.2f}" y="{bar_y}" '
                f'width="{visible_width:.2f}" height="9" '
                f'rx="3" fill="{color}"/>'
            )
            cursor += segment

        for index, (language, byte_count) in enumerate(top_languages):
            row_y = 91 + index * 25
            percentage = byte_count / total_bytes * 100
            color = LANGUAGE_COLORS[index % len(LANGUAGE_COLORS)]

            svg.append(
                f'<circle cx="29" cy="{row_y - 4}" r="4" fill="{color}"/>'
            )
            svg.append(
                f'<text x="43" y="{row_y}" fill="{TEXT}" font-size="12" '
                'font-family="Arial, sans-serif">'
                f'{svg_text(language)}</text>'
            )
            svg.append(
                f'<text x="736" y="{row_y}" text-anchor="end" '
                f'fill="{MUTED}" font-size="12" '
                'font-family="Arial, sans-serif">'
                f'{percentage:.1f}%</text>'
            )

    svg.append("</svg>\n")
    write_svg("language-stats.svg", "".join(svg))


# ---------------------------------------------------------------------------
# README sections
# ---------------------------------------------------------------------------

def repository_table(repositories: list[dict]) -> str:
    candidates = [
        repo for repo in repositories
        if not repo.get("fork")
        and not repo.get("archived")
        and repo.get("name", "").lower() != USERNAME.lower()
    ]

    candidates.sort(
        key=lambda repo: (
            repo.get("stargazers_count", 0),
            repo.get("forks_count", 0),
            repo.get("pushed_at") or "",
        ),
        reverse=True,
    )

    if not candidates:
        return "_No public repositories available for highlights._\n"

    lines = [
        "| Repository | Description | Stars | Forks |",
        "|:--|:--|--:|--:|",
    ]

    for repo in candidates[:6]:
        name = repo.get("name", "repository")
        url = repo.get("html_url", f"https://github.com/{USERNAME}")
        description = re.sub(
            r"\s+",
            " ",
            (repo.get("description") or "No description").strip(),
        )

        if len(description) > 90:
            description = description[:87] + "..."

        description = description.replace("|", "\\|")
        description = description.replace("[", "\\[").replace("]", "\\]")

        lines.append(
            f"| [{name}]({url}) | {description} | "
            f"{repo.get('stargazers_count', 0)} | "
            f"{repo.get('forks_count', 0)} |"
        )

    return "\n".join(lines) + "\n"


def technology_markdown(
    categories: list[tuple[str, list[str]]],
) -> str:
    if not categories:
        return "_Add technologies to `technologies.toml` to display your stack._"

    sections = []

    for label, items in categories:
        pills = " ".join(f"`{item}`" for item in items)
        sections.append(f"**{label}**\n\n{pills}")

    return "\n\n".join(sections)


def generate_readme(
    profile: dict,
    repositories: list[dict],
    calendar: dict | None,
    technologies: list[tuple[str, list[str]]],
) -> str:
    stars = sum(r.get("stargazers_count", 0) for r in repositories)
    forks = sum(r.get("forks_count", 0) for r in repositories)

    contributions = (
        fmt(calendar.get("totalContributions", 0))
        if calendar is not None
        else "Unavailable"
    )

    name = profile.get("name") or USERNAME
    bio = profile.get("bio") or (
        "Building practical tools, products, and resources."
    )

    website = profile.get("blog") or "https://codebygk.com"
    if not website.startswith(("https://", "http://")):
        website = f"https://{website}"

    return f"""<div align="center">

# {name}

### Building Practical Tools, Products & Resources

Developer tools · Automation · AI · Learning in public

[Website](https://codebygk.com) · [GitHub](https://github.com/{USERNAME})

</div>

---

## GitHub at a glance

<div align="center">

<img src="assets/github-stats.svg" alt="GitHub statistics" width="100%"/>

</div>

| Metric | Value |
|:--|--:|
| Contributions in the last 365 days | {contributions} |
| Public repositories | {fmt(profile.get("public_repos", 0))} |
| Stars across public repositories | {fmt(stars)} |
| Forks across public repositories | {fmt(forks)} |
| Followers | {fmt(profile.get("followers", 0))} |
| Following | {fmt(profile.get("following", 0))} |

## Contribution activity

<div align="center">

<img src="assets/contribution-heatmap.svg" alt="Contribution heatmap" width="100%"/>

</div>

## Language distribution

<div align="center">

<img src="assets/language-stats.svg" alt="Language distribution" width="100%"/>

</div>

_Language percentages are based on GitHub's reported language byte counts for public, non-fork repositories._

## Featured repositories

{repository_table(repositories)}
## Technology stack

{technology_markdown(technologies)}

## About

{bio}

- Website: {website}
- GitHub: https://github.com/{USERNAME}

---

<div align="center">

<sub>Automatically updated from GitHub API · Last generated {
    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
}</sub>

</div>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ensure_directories()

    print(f"Generating profile for @{USERNAME}")

    profile = fetch_or_cache(
        "profile.json",
        get_profile,
        dict,
    )

    repositories = fetch_or_cache(
        "repositories.json",
        get_repositories,
        list,
    )

    try:
        calendar = get_contribution_calendar()
        save_json("contributions.json", calendar)
    except (RuntimeError, OSError, ValueError) as exc:
        cached_calendar = load_json("contributions.json")
        calendar = (
            cached_calendar if isinstance(cached_calendar, dict) else None
        )
        print(
            f"Warning: contribution calendar: {exc}. "
            f"{'Using cached data.' if calendar else 'Heatmap will be unavailable.'}",
            file=sys.stderr,
        )

    print("Generating statistics SVG...")
    write_stats_svg(profile, repositories, calendar)

    print("Generating contribution heatmap...")
    write_heatmap(calendar)

    print("Calculating language distribution...")
    language_totals = get_language_totals(repositories)
    write_language_svg(language_totals)

    print("Loading technology configuration...")
    technologies = load_technologies()

    print("Generating README...")
    readme = generate_readme(
        profile,
        repositories,
        calendar,
        technologies,
    )

    README_FILE.write_text(readme, encoding="utf-8")

    print()
    print("Successfully generated:")
    print(f"  {README_FILE}")
    print(f"  {ASSETS_DIR / 'github-stats.svg'}")
    print(f"  {ASSETS_DIR / 'contribution-heatmap.svg'}")
    print(f"  {ASSETS_DIR / 'language-stats.svg'}")
    print(f"  JSON data: {DATA_DIR}")


if __name__ == "__main__":
    main()
