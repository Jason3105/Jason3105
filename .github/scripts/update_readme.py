#!/usr/bin/env python3
"""
Dynamic README updater for Jason3105's GitHub profile.
Fetches live data from GitHub GraphQL & REST APIs and injects into README.md
"""

import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta

# ─── Config ───────────────────────────────────────────────────────────────────
USERNAME     = "Jason3105"
README_PATH  = "README.md"
TOKEN        = os.environ.get("GITHUB_TOKEN", "")
IST          = timezone(timedelta(hours=5, minutes=30))
HEADERS      = {
    "Authorization": f"bearer {TOKEN}",
    "Content-Type":  "application/json",
}

# ─── GraphQL ──────────────────────────────────────────────────────────────────
PINNED_REPOS_QUERY = """
{
  user(login: "%s") {
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          description
          url
          stargazerCount
          forkCount
          homepageUrl
          isPrivate
          primaryLanguage { name color }
          repositoryTopics(first: 5) {
            nodes { topic { name } }
          }
          updatedAt
        }
      }
    }
  }
}
""" % USERNAME

RECENT_COMMITS_QUERY = """
{
  user(login: "%s") {
    contributionsCollection {
      commitContributionsByRepository(maxRepositories: 5) {
        repository { name url }
        contributions(first: 1) {
          nodes { occurredAt commitCount }
        }
      }
    }
  }
}
""" % USERNAME

# Not used now — kept as reference
# We use the Events REST API instead for truly recent data


# ─── Helpers ──────────────────────────────────────────────────────────────────
def graphql(query: str) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print("GraphQL errors:", data["errors"])
    return data.get("data", {})


def rest(endpoint: str) -> dict | list:
    resp = requests.get(
        f"https://api.github.com{endpoint}",
        headers={**HEADERS, "Accept": "application/vnd.github.v3+json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def inject_section(content: str, start_marker: str, end_marker: str, body: str) -> str:
    pattern = rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}"
    replacement = f"{start_marker}\n\n{body}\n\n{end_marker}"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


def lang_color_badge(name: str, color: str) -> str:
    """Returns a shields.io badge for a language using its GitHub color."""
    safe_name  = name.replace("-", "--").replace(" ", "_")
    safe_color = (color or "58a6ff").lstrip("#")
    return f"![{name}](https://img.shields.io/badge/{safe_name}-{safe_color}?style=flat-square&logoColor=white)"


def time_ago(iso: str) -> str:
    dt   = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    now  = datetime.now(tz=timezone.utc)
    diff = now - dt
    if diff.days >= 365:
        return f"{diff.days // 365}y ago"
    if diff.days >= 30:
        return f"{diff.days // 30}mo ago"
    if diff.days >= 1:
        return f"{diff.days}d ago"
    return "today"


# ─── Section generators ───────────────────────────────────────────────────────
def build_playground(repos: list) -> str:
    if not repos:
        return (
            "> No pinned repositories found.\n"
            f"> [⭐ Pin some repos on your profile!](https://github.com/{USERNAME})"
        )

    card_url = (
        "https://github-readme-stats.vercel.app/api/pin/"
        "?username={username}&repo={repo}"
        "&theme=tokyonight&hide_border=true"
        "&bg_color=1a1b27&title_color=00d9ff"
        "&icon_color=a9b1d6&text_color=a9b1d6&border_radius=10"
    )

    lines = []
    for i, repo in enumerate(repos):
        name = repo["name"]
        url  = repo["url"]
        img  = card_url.format(username=USERNAME, repo=name)
        lines.append(
            f'<a href="{url}">\n'
            f'  <img width="49%" src="{img}" />\n'
            f'</a>'
        )
        # blank line after every pair for visual spacing
        if i % 2 == 1:
            lines.append("")

    return "\n".join(lines)


# ─── Recent activity via Events API ─────────────────────────────────────────
def get_recent_events() -> list:
    """Fetch recent push events via REST Events API — truly current data."""
    try:
        events = rest(f"/users/{USERNAME}/events?per_page=100")
    except Exception as e:
        print(f"  Error fetching events: {e}")
        return []

    seen: dict = {}
    for event in events:
        if event["type"] != "PushEvent":
            continue
        full_name  = event["repo"]["name"]           # e.g. Jason3105/Authblock
        short_name = full_name.split("/")[-1]
        if short_name in seen or short_name == USERNAME:
            continue
        seen[short_name] = {
            "name":         short_name,
            "url":          f"https://github.com/{full_name}",
            "commit_count": len(event["payload"].get("commits", [])),
            "occurred_at":  event["created_at"],
        }
        if len(seen) >= 5:
            break

    return list(seen.values())


def build_recent_commits(recent_events: list) -> str:
    if not recent_events:
        return "> _No recent push activity found._"

    lines = []
    for item in recent_events:
        count    = item["commit_count"]
        occurred = time_ago(item["occurred_at"])
        lines.append(
            f"- [`{item['name']}`]({item['url']}) &nbsp;·&nbsp; "
            f"**{count}** commit{'s' if count != 1 else ''} &nbsp;·&nbsp; "
            f"<sub>{occurred}</sub>"
        )

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now(IST).strftime('%d %b %Y %I:%M %p IST')}] Updating README…\n")

    # 1. Fetch pinned repos via GraphQL
    print("→ Fetching pinned repositories via GraphQL…")
    pinned_data = graphql(PINNED_REPOS_QUERY)
    repos       = pinned_data.get("user", {}).get("pinnedItems", {}).get("nodes", [])
    print(f"  Found {len(repos)} pinned repos")

    # FALLBACK: if no pinned repos, use top 6 own repos sorted by stars
    if not repos:
        print("  ⚠️  No pinned repos found — falling back to top repos by stars…")
        raw = rest(f"/users/{USERNAME}/repos?sort=stars&per_page=20&type=owner")
        repos = [
            {
                "name":            r["name"],
                "description":     r.get("description") or "",
                "url":             r["html_url"],
                "stargazerCount":  r["stargazers_count"],
                "forkCount":       r["forks_count"],
                "homepageUrl":     r.get("homepage") or "",
                "updatedAt":       r["updated_at"],
                "primaryLanguage": {"name": r["language"], "color": "#58a6ff"}
                                   if r.get("language") else None,
                "repositoryTopics": {"nodes": []},
            }
            for r in raw
            if not r["fork"] and r["name"] != USERNAME   # skip forks & profile repo
        ][:6]
        print(f"  Using {len(repos)} top repos as fallback")

    # 2. Fetch RECENT activity via Events API (truly current)
    print("\u2192 Fetching recent push events via Events API\u2026")
    recent_events = get_recent_events()
    print(f"  Found {len(recent_events)} repos with recent pushes")

    # 3. Read README
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    # 4. Inject PLAYGROUND section
    playground_md = build_playground(repos)
    readme = inject_section(
        readme,
        "<!-- PLAYGROUND_START -->",
        "<!-- PLAYGROUND_END -->",
        playground_md,
    )
    print("→ Injected PLAYGROUND section")

    # 5. (Removed RECENT_COMMITS injection)

    # 6. Write README back
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)

    print("\n✅ README.md updated successfully!")


if __name__ == "__main__":
    main()
