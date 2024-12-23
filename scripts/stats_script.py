import os
import requests
import json
from datetime import datetime
from matplotlib import pyplot as plt
from PIL import Image, ImageDraw, ImageFont

# --- Configuration ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
USERNAME = os.getenv("USERNAME")
OUTPUT_IMAGE = "stats_image.png"

if not GITHUB_TOKEN or not USERNAME:
    raise ValueError("GITHUB_TOKEN and USERNAME must be set as environment variables.")

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

def create_image(user_data, repo_data, contributions):
    """Generate the final statistics image."""
    # Image settings
    width, height = 800, 1000
    bg_color = (255, 255, 255)
    text_color = (0, 0, 0)
    font = ImageFont.truetype("arial.ttf", size=20)
    title_font = ImageFont.truetype("arial.ttf", size=30)

    # Create base image
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((20, 20), f"GitHub Stats for @{user_data['username']}", fill=text_color, font=title_font)
    draw.text((20, 60), f"Name: {user_data['name']}", fill=text_color, font=font)
    draw.text((20, 100), f"Public Repos: {user_data['public_repos']}", fill=text_color, font=font)
    draw.text((20, 140), f"Followers: {user_data['followers']}", fill=text_color, font=font)
    draw.text((20, 180), f"Following: {user_data['following']}", fill=text_color, font=font)

    # Repo Stats
    draw.text((20, 240), f"Total Stars: {repo_data['stars']}", fill=text_color, font=font)

    # Contributions
    draw.text((20, 300), f"Total Contributions: {contributions}", fill=text_color, font=font)

    # Language Chart
    pie_chart_file = "languages_pie_chart.png"
    create_pie_chart(repo_data["languages"], "Language Distribution", pie_chart_file)
    lang_chart = Image.open(pie_chart_file)
    img.paste(lang_chart.resize((400, 400)), (20, 360))

    # Save final image
    img.save(OUTPUT_IMAGE)

# --- Main Script ---

if __name__ == "__main__":
    print("Fetching GitHub data...")
    user_data = get_user_data()
    repo_data = get_repo_data()
    contributions = get_contributions()

    print("Generating statistics image...")
    create_image(user_data, repo_data, contributions)

    print(f"Image saved as {OUTPUT_IMAGE}")

