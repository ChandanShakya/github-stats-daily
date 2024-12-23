import os
import requests
import json
from datetime import datetime, timedelta
from matplotlib import pyplot as plt
import matplotlib.dates as mdates
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# --- Configuration ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
USERNAME = os.getenv("USERNAME")
OUTPUT_IMAGE = "stats_image.png"

if not GITHUB_TOKEN or not USERNAME:
    raise ValueError("GITHUB_TOKEN and USERNAME must be set as environment variables."

# GitHub API URLs
BASE_URL = "https://api.github.com"
USER_URL = f"{BASE_URL}/users/{USERNAME}"
REPOS_URL = f"{BASE_URL}/users/{USERNAME}/repos"
CONTRIBUTIONS_URL = f"{BASE_URL}/search/issues"

# --- Helper Functions ---

def fetch_data(url):
    """Fetch data from GitHub API."""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_user_data():
    """Fetch basic user statistics."""
    data = fetch_data(USER_URL)
    return {
        "username": data["login"],
        "name": data.get("name", "N/A"),
        "public_repos": data["public_repos"],
        "followers": data["followers"],
        "following": data["following"]
    }

def get_repo_data():
    """Fetch repository statistics."""
    repos = fetch_data(REPOS_URL)
    stars = sum(repo["stargazers_count"] for repo in repos)
    languages = {}
    for repo in repos:
        if repo["language"]:
            languages[repo["language"]] = languages.get(repo["language"], 0) + 1
    return {
        "stars": stars,
        "languages": languages
    }

def get_contributions():
    """Fetch contribution statistics."""
    issues = fetch_data(f"{CONTRIBUTIONS_URL}?q=author:{USERNAME}")
    return len(issues.get("items", []))

def get_contribution_history():
    """Fetch contribution history for the past year."""
    query = f"""
    query {{
      user(login: "{USERNAME}") {{
        contributionsCollection {{
          contributionCalendar {{
            totalContributions
            weeks {{
              contributionDays {{
                date
                contributionCount
              }}
            }}
          }}
        }}
      }}
    }}
    """
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    response = requests.post("https://api.github.com/graphql", json={"query": query}, headers=headers)
    data = response.json()
    return data['data']['user']['contributionsCollection']['contributionCalendar']

def get_extended_stats():
    """Fetch extended stats like earned stars, lines added, lines deleted, etc."""
    query = """
    query($login: String!) {
      user(login: $login) {
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}) {
          edges {
            node {
              name
              stargazers {
                totalCount
              }
              defaultBranchRef {
                target {
                  ... on Commit {
                    history(first: 100) {
                      totalCount
                      edges {
                        node {
                          additions
                          deletions
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        issues {
          totalCount
        }
        pullRequests {
          totalCount
        }
      }
    }
    """
    variables = {"login": USERNAME}
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    response = requests.post("https://api.github.com/graphql", json={"query": query, "variables": variables}, headers=headers)
    data = response.json()["data"]["user"]

    # Earned stars is sum of all stargazers across repos
    earned_stars = sum(repo["node"]["stargazers"]["totalCount"] for repo in data["repositories"]["edges"])
    # Rough additions / deletions from the latest 100 commits in the default branches of top repos
    lines_added = 0
    lines_deleted = 0
    for repo in data["repositories"]["edges"]:
        branches = repo["node"]["defaultBranchRef"]
        if branches and "target" in branches:
            history = branches["target"]["history"]
            for commit in history["edges"]:
                lines_added += commit["node"]["additions"]
                lines_deleted += commit["node"]["deletions"]

    return {
        "earned_stars": earned_stars,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "total_issues": data["issues"]["totalCount"],
        "total_prs": data["pullRequests"]["totalCount"]
    }

def get_achievements():
    """Compute achievements from contribution history."""
    cal = get_contribution_history()
    all_days = []
    for week in cal['weeks']:
        for day in week['contributionDays']:
            if day['contributionCount'] > 0:
                all_days.append(datetime.strptime(day['date'], '%Y-%m-%d'))

    # Longest streak calculation (simplified)
    streak, max_streak = 1, 1
    all_days.sort()
    for i in range(1, len(all_days)):
        delta = all_days[i] - all_days[i - 1]
        if delta.days == 1:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1

    first_contribution = all_days[0].strftime("%b %d, %Y") if all_days else "N/A"

    # Example placeholders
    return {
        "longest_streak": max_streak,
        "first_contribution": first_contribution,
        "followers_gained": 50,  # You can adjust this logic as needed
        "most_starred_repo": "Example (500 stars)"  # Or fetch from real data
    }

# --- Generate Image ---

def create_pie_chart(data, title, output_file):
    """Create a pie chart for language distribution."""
    labels = data.keys()
    sizes = data.values()
    colors = plt.cm.Paired(range(len(data)))
    plt.figure(figsize=(5, 5))
    plt.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=140)
    plt.title(title)
    plt.savefig(output_file)
    plt.close()

def create_contribution_chart(contribution_data, output_file):
    """Create contribution trend chart."""
    dates, counts = [], []
    for week in contribution_data['weeks']:
        for day in week['contributionDays']:
            dates.append(datetime.strptime(day['date'], '%Y-%m-%d'))
            counts.append(day['contributionCount'])

    plt.figure(figsize=(10, 3))
    plt.plot(dates, counts)
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
    plt.title("Contribution Activity")
    plt.savefig(output_file, bbox_inches='tight')
    plt.close()

def create_image(user_data, repo_data, contributions):
    # Dark mode background & text
    width, height = 1000, 1600
    bg_color = (35, 35, 35)
    text_color = (255, 255, 255)
    accent_color = (100, 149, 237)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 28)
    smaller_font = ImageFont.truetype(font_path, 22)

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Header
    current_date = datetime.now().strftime("%b %d, %Y")
    draw.text((40, 40), f"GitHub Statistics for @{user_data['username']}", fill=accent_color, font=font)
    draw.text((40, 90), f"Updated: {current_date}", fill=text_color, font=smaller_font)

    # Key Metrics (expanded)
    start_y = 150
    ext_stats = get_extended_stats()
    metrics = [
        f"Total Stars: {repo_data['stars']} (Earned: {ext_stats['earned_stars']})",
        f"Lines Added: +{ext_stats['lines_added']} | Lines Deleted: -{ext_stats['lines_deleted']}",
        f"Total Contributions: {contributions}",
        f"Issues: {ext_stats['total_issues']} | Pull Requests: {ext_stats['total_prs']}"
    ]
    for i, m in enumerate(metrics):
        draw.text((40, start_y + i * 40), m, fill=text_color, font=smaller_font)

    # Contribution Trends (reuse existing chart logic)
    contrib_chart_file = "contribution_chart.png"
    contribution_data = get_contribution_history()
    create_contribution_chart(contribution_data, contrib_chart_file)
    contrib_chart = Image.open(contrib_chart_file)
    img.paste(contrib_chart.resize((900, 250)), (40, start_y + 300))

    # Language Distribution (reuse existing pie chart logic)
    pie_chart_file = "languages_pie_chart.png"
    create_pie_chart(repo_data["languages"], "Language Distribution", pie_chart_file)
    lang_chart = Image.open(pie_chart_file)
    img.paste(lang_chart.resize((400, 400)), (40, start_y + 580))

    # Repository Engagement (basic example)
    top_repos = sorted(fetch_data(REPOS_URL), key=lambda r: r["stargazers_count"], reverse=True)[:3]
    repos_start_y = start_y + 1000
    draw.text((40, repos_start_y), "Top Repositories", fill=accent_color, font=font)
    for idx, repo in enumerate(top_repos):
        line = (
            f"{idx+1}. {repo['name']} | Stars: {repo['stargazers_count']} "
            f"| Forks: {repo['forks_count']}"
        )
        draw.text((40, repos_start_y + 50 + (idx * 40)), line, fill=text_color, font=smaller_font)

    # Achievements Section (placeholders)
    achiev_y = repos_start_y + 200
    draw.text((40, achiev_y), "Achievements", fill=accent_color, font=font)
    achievements_data = get_achievements()
    achievements = [
        f"Longest Streak: {achievements_data['longest_streak']} days",
        f"Followers Gained: {achievements_data['followers_gained']} this year",
        f"First Contribution: {achievements_data['first_contribution']}",
        f"Most Starred Repo: {achievements_data['most_starred_repo']}"
    ]
    for i, ach in enumerate(achievements):
        draw.text((40, achiev_y + 50 + i * 40), ach, fill=text_color, font=smaller_font)

    # Footer
    footer_y = height - 60
    draw.text((40, footer_y), "Generated automatically by GitHub Stats Project", fill=text_color, font=smaller_font)

    # Save image
    img.save(OUTPUT_IMAGE)
    os.remove(pie_chart_file)
    os.remove(contrib_chart_file)

# --- Main Script ---

if __name__ == "__main__":
    print("Fetching GitHub data...")
    user_data = get_user_data()
    repo_data = get_repo_data()
    contributions = get_contributions()

    print("Generating statistics image...")
    create_image(user_data, repo_data, contributions)

    print(f"Image saved as {OUTPUT_IMAGE}")

