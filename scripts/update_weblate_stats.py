#!/usr/bin/env python3
"""Fetch Weblate translation stats and update README.md."""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode, quote

BASE_URL = "https://hosted.weblate.org/api"
USERNAME = "fray-cloud"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"
START_MARKER = "<!-- weblate-stats:start -->"
END_MARKER = "<!-- weblate-stats:end -->"


def _make_request(url):
    token = os.environ.get("WEBLATE_API_KEY", "")
    req = Request(url)
    if token:
        req.add_header("Authorization", f"Token {token}")
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"API error {e.code} for {url}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def api_get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urlencode(params)
    return _make_request(url)


def api_get_url(url):
    """Fetch an absolute API URL."""
    return _make_request(url)


def paginate(path, params=None):
    """Fetch all pages from a paginated endpoint."""
    if params is None:
        params = {}
    params["page_size"] = 1000
    results = []
    data = api_get(path, params)
    results.extend(data.get("results", []))
    while data.get("next"):
        data = _make_request(data["next"])
        results.extend(data.get("results", []))
    return results


def fetch_stats():
    return api_get(f"/users/{USERNAME}/statistics/")


def fetch_contributions():
    """Fetch changes by user and aggregate by project/component."""
    changes = paginate("/changes/", {"user": USERNAME})

    # Collect unique component URLs
    comp_urls = set()
    for change in changes:
        if change.get("component"):
            comp_urls.add(change["component"])

    # Fetch display names for each component
    comp_info = {}
    for url in comp_urls:
        data = api_get_url(url)
        parts = [p for p in url.rstrip("/").split("/") if p]
        proj_slug, comp_slug = parts[-2], parts[-1]
        proj_name = data.get("project", {}).get("name", proj_slug)
        comp_name = data.get("name", comp_slug)
        comp_info[url] = {
            "project": proj_name,
            "component": comp_name,
            "proj_slug": proj_slug,
            "comp_slug": comp_slug,
        }

    # Count changes per component
    comp_counts = defaultdict(int)
    for change in changes:
        url = change.get("component", "")
        if url:
            comp_counts[url] += 1

    return comp_info, comp_counts


def badge(label, value, color="blue", logo=None):
    """Generate a shields.io badge markdown."""
    label_enc = quote(str(label), safe="")
    value_enc = quote(str(value), safe="")
    logo_param = f"&logo={quote(logo, safe='')}&logoColor=white" if logo else ""
    return f"![{label}: {value}](https://img.shields.io/badge/{label_enc}-{value_enc}-{color}?style=flat{logo_param})"


def build_markdown(stats, comp_info, comp_counts):
    lines = []
    lines.append("## 🌐 Translation Contributions\n")

    translated = stats.get("translated", 0)
    suggested = stats.get("suggested", 0)
    languages = stats.get("languages", 0)

    # Stats badges
    lines.append(
        f"{badge('Translated', f'{translated:,}', 'brightgreen', 'weblate')} "
        f"{badge('Suggested', f'{suggested:,}', 'orange', 'weblate')} "
        f"{badge('Languages', languages, 'blue', 'weblate')}"
    )
    lines.append("")

    if comp_info:
        # Sort by count descending
        sorted_comps = sorted(comp_counts.items(), key=lambda r: r[1], reverse=True)

        # Group by project
        projects = defaultdict(list)
        for comp_url, count in sorted_comps:
            info = comp_info[comp_url]
            projects[info["project"]].append((comp_url, info, count))

        proj_order = sorted(projects.items(), key=lambda p: sum(c for _, _, c in p[1]), reverse=True)

        lines.append("| Project | Details |")
        lines.append("|---------|---------|")
        for proj_name, comps in proj_order:
            comps.sort(key=lambda r: r[2], reverse=True)
            badges = []
            for comp_url, info, count in comps:
                url = f"https://hosted.weblate.org/projects/{info['proj_slug']}/{info['comp_slug']}/"
                label = quote(f"{info['project']}/{info['component']}", safe="")
                value = quote(f"{count:,} changes", safe="")
                badges.append(f"[![{info['project']}/{info['component']}](https://img.shields.io/badge/{label}-{value}-brightgreen?style=flat&logo=weblate&logoColor=white)]({url})")
            lines.append(f"| {proj_name} | {' '.join(badges)} |")
        lines.append("")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"*Last updated: {today}*")

    return "\n".join(lines)


def update_readme(content):
    readme = README_PATH.read_text(encoding="utf-8")
    start_idx = readme.find(START_MARKER)
    end_idx = readme.find(END_MARKER)
    if start_idx == -1 or end_idx == -1:
        print("Markers not found in README.md", file=sys.stderr)
        sys.exit(1)

    new_readme = (
        readme[: start_idx + len(START_MARKER)]
        + "\n"
        + content
        + "\n"
        + readme[end_idx:]
    )

    if new_readme != readme:
        README_PATH.write_text(new_readme, encoding="utf-8")
        print("README.md updated.")
    else:
        print("No changes to README.md.")


def main():
    if not os.environ.get("WEBLATE_API_KEY"):
        print("Warning: WEBLATE_API_KEY not set, using unauthenticated access (rate limited)", file=sys.stderr)

    print("Fetching user statistics...")
    stats = fetch_stats()

    print("Fetching contributions...")
    comp_info, comp_counts = fetch_contributions()

    print(f"Found {len(comp_info)} components")
    md = build_markdown(stats, comp_info, comp_counts)
    update_readme(md)


if __name__ == "__main__":
    main()
