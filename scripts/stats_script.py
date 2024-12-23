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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import random

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
    OUTPUT_FILE = "README.md"  # Changed from OUTPUT_IMAGE
    BASE_URL = "https://api.github.com"
    RATE_LIMIT_BUFFER = 100
    MIN_REMAINING_CALLS = 50

    @classmethod
    def validate(cls) -> None:
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

def create_contribution_chart(contribution_data: Dict[str, Any], output_file: str) -> str:
    """Create contribution trend chart and return URL for embedding."""
    dates, counts = [], []
    for week in contribution_data['weeks']:
        for day in week['contributionDays']:
            dates.append(datetime.strptime(day['date'], '%Y-%m-%d'))
            counts.append(day['contributionCount'])

    plt.style.use('dark_background')
    plt.figure(figsize=(10, 2))
    plt.plot(dates, counts, color='#6495ED', linewidth=2)
    plt.fill_between(dates, counts, alpha=0.2, color='#6495ED')
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
    plt.grid(True, alpha=0.1)
    plt.savefig(output_file, bbox_inches='tight', transparent=True)
    plt.close()

    # Return relative path to the image
    return f"./contribution_graph.png"

class MarkdownGenerator:
    """Handles the generation of the statistics markdown."""

    def __init__(self):
        self.content = []

    def add_header(self, user_data: Dict):
        """Add header section."""
        self.content.extend([
            f"# GitHub Statistics for @{user_data['username']}",
            f"*Updated: {datetime.now().strftime('%B %d, %Y')}*",
            "",
            "## 📊 Statistics"
        ])

    def add_statistics(self, repo_data: Dict, contributions: int):
        """Add statistics section."""
        ext_stats = get_extended_stats()

        # Main stats in table format
        self.content.extend([
            "| Metric | Count |",
            "|--------|--------|",
            f"| Total Contributions | {ext_stats['total_contributions']} |",
            f"| Public Contributions | {ext_stats['public_contributions']} |",
            f"| Private Contributions | {ext_stats['private_contributions']} |",
            f"| Stars Received | {repo_data['stars']} |",
            f"| Stars Given | {ext_stats['stars_given']} |",
            f"| Total Issues | {ext_stats['total_issues']} |",
            f"| Total PRs | {ext_stats['total_prs']} |",
            f"| Followers | {ext_stats['followers']} |",
            f"| Following | {ext_stats['following']} |",
            ""
        ])

    def add_contribution_graph(self, graph_path: str):
        """Add contribution graph section."""
        self.content.extend([
            "## 📈 Contribution Graph",
            "",
            f"![Contribution Graph]({graph_path})",
            ""
        ])

    def add_achievements(self):
        """Add achievements section."""
        achievements = get_achievements()
        self.content.extend([
            "## 🏆 Achievements",
            "",
            f"- 🔥 Longest Streak: {achievements['longest_streak']} days",
            f"- 👥 New Followers (avg): {achievements['followers_gained']} per year",
            f"- 📅 First Contribution: {achievements['first_contribution']}",
            f"- ⭐ Most Starred: {achievements['most_starred_repo']}",
            ""
        ])

    def generate(self) -> str:
        """Generate the complete markdown content."""
        return "\n".join(self.content)

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

        logger.info("Generating markdown content...")
        md_gen = MarkdownGenerator()

        # Generate contribution graph
        graph_path = create_contribution_chart(
            get_contribution_history(),
            "contribution_graph.png"
        )

        # Generate markdown sections
        md_gen.add_header(user_data)
        md_gen.add_statistics(repo_data, contributions)
        md_gen.add_contribution_graph(graph_path)
        md_gen.add_achievements()

        # Save markdown content
        with open(Config.OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(md_gen.generate())

        logger.info(f"Markdown file successfully saved as {Config.OUTPUT_FILE}")

    except RateLimitError as e:
        logger.error(f"Rate limit reached: {e}")
        raise
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise

if __name__ == "__main__":
    main()

