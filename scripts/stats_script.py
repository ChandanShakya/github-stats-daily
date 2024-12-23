"""
GitHub Statistics Generator Script

This script fetches GitHub statistics for a user and generates a visual representation
of their activity, including contributions, languages, and achievements.

Required environment variables:
    - GITHUB_TOKEN: GitHub personal access token
    - USERNAME: GitHub username
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests
from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    """Script configuration constants."""
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    USERNAME = os.getenv("USERNAME")
    OUTPUT_IMAGE = "stats_image.png"
    BASE_URL = "https://api.github.com"
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.GITHUB_TOKEN or not cls.USERNAME:
            raise ValueError("GITHUB_TOKEN and USERNAME must be set as environment variables.")

# --- API Interaction ---
def fetch_data(url: str) -> Dict[str, Any]:
    """
    Fetch data from GitHub API with error handling.

    Args:
        url: GitHub API endpoint URL

    Returns:
        Dictionary containing the API response

    Raises:
        requests.exceptions.RequestException: If API request fails
    """
    try:
        headers = {"Authorization": f"token {Config.GITHUB_TOKEN}"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        raise

def get_user_data() -> Dict[str, Any]:
    """Fetch basic user statistics."""
    data = fetch_data(f"{Config.BASE_URL}/users/{Config.USERNAME}")
    return {
        "username": data["login"],
        "name": data.get("name", "N/A"),
        "public_repos": data["public_repos"],
        "followers": data["followers"],
        "following": data["following"]
    }

def get_repo_data() -> Dict[str, Any]:
    """Fetch repository statistics."""
    repos = fetch_data(f"{Config.BASE_URL}/users/{Config.USERNAME}/repos")
    stars = sum(repo["stargazers_count"] for repo in repos)
    languages = {}
    for repo in repos:
        if repo["language"]:
            languages[repo["language"]] = languages.get(repo["language"], 0) + 1
    return {
        "stars": stars,
        "languages": languages
    }

def get_contributions() -> int:
    """Fetch contribution statistics."""
    issues = fetch_data(f"{Config.BASE_URL}/search/issues?q=author:{Config.USERNAME}")
    return len(issues.get("items", []))

def get_contribution_history() -> Dict[str, Any]:
    """Fetch contribution history for the past year."""
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
        variables = {"login": Config.USERNAME}
        headers = {
            "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            logger.error(f"GraphQL Error: {result['errors']}")
            return {"totalContributions": 0, "weeks": []}

        if not result.get("data") or not result["data"].get("user"):
            logger.error("Invalid GraphQL response structure")
            return {"totalContributions": 0, "weeks": []}

        return result["data"]["user"]["contributionsCollection"]["contributionCalendar"]

    except Exception as e:
        logger.error(f"Failed to fetch contribution history: {e}")
        return {"totalContributions": 0, "weeks": []}

def get_extended_stats() -> Dict[str, Any]:
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
    try:
        variables = {"login": Config.USERNAME}
        headers = {
            "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            logger.error(f"GraphQL Error: {result['errors']}")
            return {
                "earned_stars": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "total_issues": 0,
                "total_prs": 0
            }

        if not result.get("data") or not result["data"].get("user"):
            logger.error("Invalid GraphQL response structure")
            return {
                "earned_stars": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "total_issues": 0,
                "total_prs": 0
            }

        data = result["data"]["user"]
        earned_stars = sum(
            repo["node"]["stargazers"]["totalCount"]
            for repo in data["repositories"]["edges"]
        )

        lines_added = 0
        lines_deleted = 0
        for repo in data["repositories"]["edges"]:
            branches = repo["node"].get("defaultBranchRef")
            if branches and branches.get("target"):
                history = branches["target"]["history"]
                for commit in history.get("edges", []):
                    lines_added += commit["node"].get("additions", 0)
                    lines_deleted += commit["node"].get("deletions", 0)

        return {
            "earned_stars": earned_stars,
            "lines_added": lines_added,
            "lines_deleted": lines_deleted,
            "total_issues": data["issues"]["totalCount"],
            "total_prs": data["pullRequests"]["totalCount"]
        }

    except Exception as e:
        logger.error(f"Failed to fetch extended stats: {e}")
        return {
            "earned_stars": 0,
            "lines_added": 0,
            "lines_deleted": 0,
            "total_issues": 0,
            "total_prs": 0
        }

def get_achievements() -> Dict[str, Any]:
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

def create_pie_chart(data: Dict[str, int], title: str, output_file: str) -> None:
    """Create a pie chart for language distribution."""
    labels = data.keys()
    sizes = data.values()
    colors = plt.cm.Paired(range(len(data)))
    plt.figure(figsize=(5, 5))
    plt.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=140)
    plt.title(title)
    plt.savefig(output_file)
    plt.close()

def create_contribution_chart(contribution_data: Dict[str, Any], output_file: str) -> None:
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

class ImageGenerator:
    """Handles the generation of the statistics image."""

    def __init__(self, width: int = 1000, height: int = 1600):
        self.width = width
        self.height = height
        self.bg_color = (35, 35, 35)
        self.text_color = (255, 255, 255)
        self.accent_color = (100, 149, 237)
        self.font = ImageFont.truetype(Config.FONT_PATH, 28)
        self.smaller_font = ImageFont.truetype(Config.FONT_PATH, 22)
        self.img = None
        self.draw = None

    def create_image(self, user_data: Dict, repo_data: Dict, contributions: int) -> None:
        """Create the main statistics image."""
        try:
            self.img = Image.new("RGB", (self.width, self.height), color=self.bg_color)
            self.draw = ImageDraw.Draw(self.img)

            # Draw header
            self._draw_header(user_data)

            # Draw statistics
            self._draw_statistics(repo_data, contributions)

            # Save the final image
            self.img.save(Config.OUTPUT_IMAGE)
            logger.info(f"Image successfully saved as {Config.OUTPUT_IMAGE}")

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            raise
        finally:
            # Cleanup temporary files if they exist
            for temp_file in ["contribution_chart.png", "languages_pie_chart.png"]:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file}: {e}")

    def _draw_header(self, user_data: Dict) -> None:
        """Draw the header section of the image."""
        if not self.draw:
            return
        current_date = datetime.now().strftime("%b %d, %Y")
        self.draw.text((40, 40), f"GitHub Statistics for @{user_data['username']}",
                      fill=self.accent_color, font=self.font)
        self.draw.text((40, 90), f"Updated: {current_date}",
                      fill=self.text_color, font=self.smaller_font)

    def _draw_statistics(self, repo_data: Dict, contributions: int) -> None:
        """Draw the statistics section of the image."""
        if not self.draw or not self.img:
            return

        try:
            start_y = 150
            ext_stats = get_extended_stats()
            metrics = [
                f"Total Stars: {repo_data['stars']} (Earned: {ext_stats['earned_stars']})",
                f"Lines Added: +{ext_stats['lines_added']} | Lines Deleted: -{ext_stats['lines_deleted']}",
                f"Total Contributions: {contributions}",
                f"Issues: {ext_stats['total_issues']} | Pull Requests: {ext_stats['total_prs']}"
            ]
            for i, m in enumerate(metrics):
                self.draw.text((40, start_y + i * 40), m, fill=self.text_color, font=self.smaller_font)

            # Contribution Trends
            contrib_chart_file = "contribution_chart.png"
            try:
                contribution_data = get_contribution_history()
                create_contribution_chart(contribution_data, contrib_chart_file)
                if os.path.exists(contrib_chart_file):
                    contrib_chart = Image.open(contrib_chart_file)
                    self.img.paste(contrib_chart.resize((900, 250)), (40, start_y + 300))
                    contrib_chart.close()
            except Exception as e:
                logger.error(f"Failed to create contribution chart: {e}")

            # Language Distribution
            pie_chart_file = "languages_pie_chart.png"
            try:
                create_pie_chart(repo_data["languages"], "Language Distribution", pie_chart_file)
                if os.path.exists(pie_chart_file):
                    lang_chart = Image.open(pie_chart_file)
                    self.img.paste(lang_chart.resize((400, 400)), (40, start_y + 580))
                    lang_chart.close()
            except Exception as e:
                logger.error(f"Failed to create language chart: {e}")

            # Rest of the statistics drawing
            self._draw_repositories(start_y)
            self._draw_achievements(start_y)
            self._draw_footer()

        except Exception as e:
            logger.error(f"Error in drawing statistics: {e}")
            raise

    def _draw_repositories(self, start_y: int) -> None:
        """Draw repository section."""
        if not self.draw:
            return
        try:
            top_repos = sorted(
                fetch_data(f"{Config.BASE_URL}/users/{Config.USERNAME}/repos"),
                key=lambda r: r["stargazers_count"],
                reverse=True
            )[:3]
            repos_start_y = start_y + 1000
            self.draw.text((40, repos_start_y), "Top Repositories",
                         fill=self.accent_color, font=self.font)
            for idx, repo in enumerate(top_repos):
                line = (
                    f"{idx+1}. {repo['name']} | Stars: {repo['stargazers_count']} "
                    f"| Forks: {repo['forks_count']}"
                )
                self.draw.text((40, repos_start_y + 50 + (idx * 40)), line,
                             fill=self.text_color, font=self.smaller_font)
        except Exception as e:
            logger.error(f"Failed to draw repositories: {e}")

    def _draw_achievements(self, start_y: int) -> None:
        """Draw achievements section."""
        if not self.draw:
            return
        try:
            achiev_y = start_y + 1200
            self.draw.text((40, achiev_y), "Achievements",
                         fill=self.accent_color, font=self.font)
            achievements_data = get_achievements()
            achievements = [
                f"Longest Streak: {achievements_data['longest_streak']} days",
                f"Followers Gained: {achievements_data['followers_gained']} this year",
                f"First Contribution: {achievements_data['first_contribution']}",
                f"Most Starred Repo: {achievements_data['most_starred_repo']}"
            ]
            for i, ach in enumerate(achievements):
                self.draw.text((40, achiev_y + 50 + i * 40), ach,
                             fill=self.text_color, font=self.smaller_font)
        except Exception as e:
            logger.error(f"Failed to draw achievements: {e}")

    def _draw_footer(self) -> None:
        """Draw footer section."""
        if not self.draw:
            return
        footer_y = self.height - 60
        self.draw.text((40, footer_y), "Generated automatically by GitHub Stats Project",
                      fill=self.text_color, font=self.smaller_font)

# --- Main Script ---

def main() -> None:
    """Main script execution."""
    try:
        Config.validate()
        logger.info("Fetching GitHub data...")

        user_data = get_user_data()
        repo_data = get_repo_data()
        contributions = get_contributions()

        logger.info("Generating statistics image...")
        image_generator = ImageGenerator()
        image_generator.create_image(user_data, repo_data, contributions)

    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise

if __name__ == "__main__":
    main()

