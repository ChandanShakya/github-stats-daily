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
import time
from functools import wraps

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

class RateLimitError(Exception):
    """Custom exception for rate limit handling."""
    pass

class Config:
    """Script configuration constants."""
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    USERNAME = os.getenv("USERNAME")
    OUTPUT_IMAGE = "stats_image.png"
    BASE_URL = "https://api.github.com"
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    RATE_LIMIT_BUFFER = 100  # Keep buffer of requests
    MIN_REMAINING_CALLS = 50  # Minimum remaining calls before warning

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.GITHUB_TOKEN or not cls.USERNAME:
            raise ValueError("GITHUB_TOKEN and USERNAME must be set as environment variables.")

def check_rate_limit() -> Dict[str, Any]:
    """Check current rate limit status."""
    try:
        response = requests.get(
            f"{Config.BASE_URL}/rate_limit",
            headers={"Authorization": f"token {Config.GITHUB_TOKEN}"},
            timeout=10
        )
        response.raise_for_status()
        return response.json()["resources"]
    except Exception as e:
        logger.error(f"Failed to check rate limit: {e}")
        raise

def validate_rate_limit():
    """Validate if we have enough API calls remaining."""
    try:
        limits = check_rate_limit()
        core_remaining = limits["core"]["remaining"]
        graphql_remaining = limits["graphql"]["remaining"]
        search_remaining = limits["search"]["remaining"]

        logger.info(f"API Rate Limits - Core: {core_remaining}, GraphQL: {graphql_remaining}, Search: {search_remaining}")

        if any(remaining < Config.MIN_REMAINING_CALLS for remaining in
               [core_remaining, graphql_remaining, search_remaining]):
            logger.warning("API rate limit is running low!")

        if any(remaining < 1 for remaining in
               [core_remaining, graphql_remaining, search_remaining]):
            reset_times = {
                "core": datetime.fromtimestamp(limits["core"]["reset"]),
                "graphql": datetime.fromtimestamp(limits["graphql"]["reset"]),
                "search": datetime.fromtimestamp(limits["search"]["reset"])
            }
            raise RateLimitError(f"Rate limit exceeded. Resets at: {reset_times}")

    except RateLimitError:
        raise
    except Exception as e:
        logger.error(f"Rate limit validation failed: {e}")
        raise

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
        validate_rate_limit()
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

def retry_on_error(max_retries=3, delay=5):
    """Decorator to retry functions on failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries == max_retries:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        raise
                    logger.warning(f"Attempt {retries} failed, retrying in {delay} seconds...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_on_error(max_retries=3, delay=5)
def graphql_query(query: str, variables: Dict = None) -> Dict[str, Any]:
    """Execute GraphQL query with retries."""
    try:
        validate_rate_limit()
        headers = {
            "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            raise Exception(f"GraphQL Error: {result['errors']}")
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        raise

@retry_on_error(max_retries=3, delay=5)
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
        result = graphql_query(query, variables)

        if not result.get("data") or not result["data"].get("user"):
            logger.error("Invalid GraphQL response structure")
            return {"totalContributions": 0, "weeks": []}

        return result["data"]["user"]["contributionsCollection"]["contributionCalendar"]

    except Exception as e:
        logger.error(f"Failed to fetch contribution history: {e}")
        return {"totalContributions": 0, "weeks": []}

def get_extended_stats() -> Dict[str, Any]:
    """Fetch extended stats including private contributions."""
    query = """
    query($login: String!) {
      user(login: $login) {
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
          edges {
            node {
              name
              stargazers {
                totalCount
              }
            }
          }
        }
        contributionsCollection {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
          contributionYears
        }
        followers {
          totalCount
        }
        following {
          totalCount
        }
        starredRepositories {
          totalCount
        }
        contributionsCollection {
          totalCommitContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
          }
        }
        issues(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes {
            createdAt
          }
        }
        pullRequests(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes {
            createdAt
          }
        }
      }
    }
    """

    try:
        variables = {"login": Config.USERNAME}
        result = graphql_query(query, variables)

        if not result.get("data") or not result["data"].get("user"):
            logger.error("Invalid GraphQL response structure")
            return {}

        data = result["data"]["user"]

        # Get most starred repo
        repos = data["repositories"]["edges"]
        most_starred_repo = max(repos, key=lambda x: x["node"]["stargazers"]["totalCount"], default=None)
        most_starred_repo_info = (
            f"{most_starred_repo['node']['name']} ({most_starred_repo['node']['stargazers']['totalCount']} stars)"
            if most_starred_repo else "None"
        )

        contributions = data["contributionsCollection"]

        return {
            "total_contributions": contributions["contributionCalendar"]["totalContributions"],
            "public_contributions": (
                contributions["totalCommitContributions"] +
                contributions["totalIssueContributions"] +
                contributions["totalPullRequestContributions"] +
                contributions["totalPullRequestReviewContributions"]
            ),
            "private_contributions": contributions["restrictedContributionsCount"],
            "stars_given": data["starredRepositories"]["totalCount"],
            "most_starred_repo": most_starred_repo_info,
            "total_issues": data["issues"]["totalCount"],
            "total_prs": data["pullRequests"]["totalCount"],
            "followers": data["followers"]["totalCount"],
            "following": data["following"]["totalCount"]
        }

    except Exception as e:
        logger.error(f"Failed to fetch extended stats: {e}")
        return {}

def get_contribution_counts() -> Dict[str, int]:
    """Fetch detailed contribution counts including private contributions."""
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
        }
      }
    }
    """
    try:
        variables = {"login": Config.USERNAME}
        result = graphql_query(query, variables)

        if not result.get("data") or not result["data"].get("user"):
            return {}

        contributions = result["data"]["user"]["contributionsCollection"]
        return {
            "commits": contributions["totalCommitContributions"],
            "private": contributions["restrictedContributionsCount"],
            "issues": contributions["totalIssueContributions"],
            "prs": contributions["totalPullRequestContributions"],
            "reviews": contributions["totalPullRequestReviewContributions"]
        }
    except Exception as e:
        logger.error(f"Failed to fetch contribution counts: {e}")
        return {}

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

    # Get follower growth data
    query = """
    query($login: String!) {
      user(login: $login) {
        followers {
          totalCount
        }
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
          nodes {
            name
            stargazers {
              totalCount
            }
            createdAt
          }
        }
      }
    }
    """

    try:
        variables = {"login": Config.USERNAME}
        result = graphql_query(query, variables)

        if result.get("data") and result["data"].get("user"):
            data = result["data"]["user"]

            # Get most starred repository
            repos = data["repositories"]["nodes"]
            most_starred = max(repos, key=lambda x: x["stargazers"]["totalCount"], default=None)
            most_starred_info = (
                f"{most_starred['name']} ({most_starred['stargazers']['totalCount']} stars)"
                if most_starred else "None"
            )

            # Calculate followers gained (comparing with previous data or API)
            current_followers = data["followers"]["totalCount"]

            # For followers gained, you might want to store historical data
            # Here's a simple approach using the creation date of newest repo
            newest_repo = max(repos, key=lambda x: x["createdAt"], default=None)
            days_active = (
                (datetime.now() - datetime.strptime(newest_repo["createdAt"], "%Y-%m-%dT%H:%M:%SZ")).days
                if newest_repo else 365
            )
            avg_followers_gained = round(current_followers / max(days_active/365, 1))

        else:
            most_starred_info = "None"
            avg_followers_gained = 0

        return {
            "longest_streak": max_streak,
            "first_contribution": first_contribution,
            "followers_gained": avg_followers_gained,
            "most_starred_repo": most_starred_info
        }

    except Exception as e:
        logger.error(f"Failed to fetch achievement data: {e}")
        return {
            "longest_streak": max_streak,
            "first_contribution": first_contribution,
            "followers_gained": 0,
            "most_starred_repo": "None"
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
            contribution_counts = get_contribution_counts()

            metrics = [
                f"Total Contributions: {ext_stats['total_contributions']} (Public: {ext_stats['public_contributions']}, Private: {ext_stats['private_contributions']})",
                f"Stars Earned: {repo_data['stars']} | Stars Given: {ext_stats['stars_given']}",
                f"Issues: {ext_stats['total_issues']} | Pull Requests: {ext_stats['total_prs']}",
                f"Followers: {ext_stats['followers']} | Following: {ext_stats['following']}"
            ]

            for i, m in enumerate(metrics):
                self.draw.text((40, start_y + i * 40), m, fill=self.text_color, font=self.smaller_font)

            # Contribution Trends - adjusted position
            contrib_chart_file = "contribution_chart.png"
            try:
                contribution_data = get_contribution_history()
                create_contribution_chart(contribution_data, contrib_chart_file)
                if os.path.exists(contrib_chart_file):
                    contrib_chart = Image.open(contrib_chart_file)
                    self.img.paste(contrib_chart.resize((900, 250)), (40, start_y + 200))  # Reduced from 300 to 200
                    contrib_chart.close()
            except Exception as e:
                logger.error(f"Failed to create contribution chart: {e}")

            # Rest of the drawing code remains the same
            # ...existing code...

    # Remove the _draw_footer method completely
    def _draw_footer(self) -> None:
        """Empty method to remove footer."""
        pass

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

# --- Main Script ---

def main() -> None:
    """Main script execution."""
    try:
        Config.validate()
        logger.info("Checking API rate limits...")
        validate_rate_limit()

        logger.info("Fetching GitHub data...")

        user_data = get_user_data()
        repo_data = get_repo_data()
        contributions = get_contributions()

        logger.info("Generating statistics image...")
        image_generator = ImageGenerator()
        image_generator.create_image(user_data, repo_data, contributions)

    except RateLimitError as e:
        logger.error(f"Rate limit reached: {e}")
        raise
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise

if __name__ == "__main__":
    main()

