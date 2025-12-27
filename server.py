#!/usr/bin/env python3
"""
GitHub MCP Server

An MCP server that wraps the GitHub REST API, allowing Claude to interact
with GitHub repositories, issues, pull requests, and more.

Requires: GITHUB_TOKEN environment variable for authenticated requests.
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

# ============================================
# CONFIGURATION
# ============================================

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Create the MCP server
mcp = FastMCP(name="github-mcp")


# ============================================
# HTTP CLIENT HELPER
# ============================================

def get_headers() -> dict:
    """Get headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHub-MCP-Server",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


async def github_request(method: str, endpoint: str, json_data: dict = None) -> dict | list | str:
    """
    Make a request to the GitHub API.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE)
        endpoint: API endpoint (without base URL)
        json_data: Optional JSON body for POST/PATCH requests

    Returns:
        Response data or error message
    """
    url = f"{GITHUB_API_BASE}{endpoint}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=get_headers(),
                json=json_data,
            )

            if response.status_code == 404:
                return {"error": "Not found - check if the resource exists and you have access"}
            elif response.status_code == 401:
                return {"error": "Unauthorized - check your GITHUB_TOKEN"}
            elif response.status_code == 403:
                return {"error": "Forbidden - rate limited or insufficient permissions"}
            elif response.status_code >= 400:
                return {"error": f"API error: {response.status_code} - {response.text}"}

            return response.json() if response.text else {"status": "success"}
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except Exception as e:
        return {"error": str(e)}


# ============================================
# USER TOOLS
# ============================================

@mcp.tool()
async def get_authenticated_user() -> str:
    """
    Get the authenticated user's profile information.
    Requires GITHUB_TOKEN to be set.
    """
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not set. Please configure your token."

    data = await github_request("GET", "/user")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    return f"""Authenticated User:
  Username: {data.get('login')}
  Name: {data.get('name', 'N/A')}
  Bio: {data.get('bio', 'N/A')}
  Public Repos: {data.get('public_repos')}
  Followers: {data.get('followers')}
  Following: {data.get('following')}
  URL: {data.get('html_url')}"""


@mcp.tool()
async def get_user(username: str) -> str:
    """
    Get a GitHub user's public profile.

    Args:
        username: GitHub username
    """
    data = await github_request("GET", f"/users/{username}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    return f"""User: {data.get('login')}
  Name: {data.get('name', 'N/A')}
  Bio: {data.get('bio', 'N/A')}
  Company: {data.get('company', 'N/A')}
  Location: {data.get('location', 'N/A')}
  Public Repos: {data.get('public_repos')}
  Followers: {data.get('followers')}
  Following: {data.get('following')}
  URL: {data.get('html_url')}"""


# ============================================
# REPOSITORY TOOLS
# ============================================

@mcp.tool()
async def list_user_repos(username: str, sort: str = "updated", per_page: int = 10) -> str:
    """
    List public repositories for a user.

    Args:
        username: GitHub username
        sort: Sort by: created, updated, pushed, full_name (default: updated)
        per_page: Number of repos to return (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    data = await github_request("GET", f"/users/{username}/repos?sort={sort}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data:
        return f"No repositories found for {username}"

    repos = []
    for repo in data:
        stars = repo.get('stargazers_count', 0)
        lang = repo.get('language', 'N/A')
        repos.append(f"  - {repo['name']} ⭐{stars} [{lang}]")

    return f"Repositories for {username}:\n" + "\n".join(repos)


@mcp.tool()
async def get_repo(owner: str, repo: str) -> str:
    """
    Get detailed information about a repository.

    Args:
        owner: Repository owner (username or org)
        repo: Repository name
    """
    data = await github_request("GET", f"/repos/{owner}/{repo}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    return f"""Repository: {data.get('full_name')}
  Description: {data.get('description', 'N/A')}
  Language: {data.get('language', 'N/A')}
  Stars: {data.get('stargazers_count')}
  Forks: {data.get('forks_count')}
  Open Issues: {data.get('open_issues_count')}
  Default Branch: {data.get('default_branch')}
  Created: {data.get('created_at', '')[:10]}
  Updated: {data.get('updated_at', '')[:10]}
  URL: {data.get('html_url')}
  Clone: {data.get('clone_url')}"""


@mcp.tool()
async def create_repo(
    name: str,
    description: str = "",
    private: bool = False,
    auto_init: bool = False,
    gitignore_template: str = "",
    confirm: bool = False
) -> str:
    """
    Create a new GitHub repository for the authenticated user.
    Requires GITHUB_TOKEN with repo scope.

    ⚠️  MUTATING OPERATION: Set confirm=True to actually create the repository.
    If confirm=False, this will only preview what would be created.

    Args:
        name: Repository name (required)
        description: Repository description (optional)
        private: Whether the repo should be private (default: False = public)
        auto_init: Initialize with a README (default: False)
        gitignore_template: Gitignore template name, e.g., "Python", "Node" (optional)
        confirm: Must be True to actually create the repo. If False, shows preview only.
    """
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not set. Please configure your token."

    # Build the payload
    payload = {
        "name": name,
        "private": private,
        "auto_init": auto_init,
    }
    if description:
        payload["description"] = description
    if gitignore_template:
        payload["gitignore_template"] = gitignore_template

    # Preview mode - show what would be created
    if not confirm:
        visibility = "private 🔒" if private else "public 🌐"
        preview = f"""⚠️  PREVIEW - Repository will NOT be created until confirm=True

Repository to create:
  Name: {name}
  Visibility: {visibility}
  Description: {description or '(none)'}
  Auto-init with README: {auto_init}
  Gitignore template: {gitignore_template or '(none)'}

To create this repository, call create_repo again with confirm=True"""
        return preview

    # Actually create the repository
    data = await github_request("POST", "/user/repos", payload)

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    visibility = "private 🔒" if data.get('private') else "public 🌐"
    return f"""✅ Repository created successfully!

  Name: {data.get('full_name')}
  Visibility: {visibility}
  Description: {data.get('description') or '(none)'}
  URL: {data.get('html_url')}
  Clone: {data.get('clone_url')}
  SSH: {data.get('ssh_url')}"""


@mcp.tool()
async def list_my_repos(visibility: str = "all", sort: str = "updated", per_page: int = 10) -> str:
    """
    List repositories for the authenticated user.
    Requires GITHUB_TOKEN.

    Args:
        visibility: Filter by visibility: all, public, private (default: all)
        sort: Sort by: created, updated, pushed, full_name (default: updated)
        per_page: Number of repos to return (default: 10, max: 30)
    """
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not set. Please configure your token."

    per_page = min(max(1, per_page), 30)
    data = await github_request("GET", f"/user/repos?visibility={visibility}&sort={sort}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data:
        return "No repositories found"

    repos = []
    for repo in data:
        stars = repo.get('stargazers_count', 0)
        private = "🔒" if repo.get('private') else "🌐"
        repos.append(f"  {private} {repo['name']} ⭐{stars}")

    return f"Your repositories:\n" + "\n".join(repos)


# ============================================
# ISSUE TOOLS
# ============================================

@mcp.tool()
async def list_issues(owner: str, repo: str, state: str = "open", per_page: int = 10) -> str:
    """
    List issues in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: Filter by state: open, closed, all (default: open)
        per_page: Number of issues to return (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    data = await github_request("GET", f"/repos/{owner}/{repo}/issues?state={state}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data:
        return f"No {state} issues found in {owner}/{repo}"

    issues = []
    for issue in data:
        # Skip pull requests (they appear in issues endpoint)
        if "pull_request" in issue:
            continue
        labels = ", ".join([l["name"] for l in issue.get("labels", [])])
        label_str = f" [{labels}]" if labels else ""
        issues.append(f"  #{issue['number']} {issue['title']}{label_str}")

    return f"Issues in {owner}/{repo} ({state}):\n" + "\n".join(issues) if issues else f"No {state} issues found"


@mcp.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> str:
    """
    Get details of a specific issue.

    Args:
        owner: Repository owner
        repo: Repository name
        issue_number: Issue number
    """
    data = await github_request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    labels = ", ".join([l["name"] for l in data.get("labels", [])])

    return f"""Issue #{data['number']}: {data['title']}
  State: {data['state']}
  Author: {data['user']['login']}
  Labels: {labels or 'None'}
  Comments: {data['comments']}
  Created: {data['created_at'][:10]}
  URL: {data['html_url']}

Body:
{data.get('body', 'No description')}"""


@mcp.tool()
async def create_issue(owner: str, repo: str, title: str, body: str = "", labels: str = "") -> str:
    """
    Create a new issue in a repository.
    Requires GITHUB_TOKEN with repo scope.

    Args:
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue body/description (optional)
        labels: Comma-separated list of label names (optional)
    """
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not set. Please configure your token."

    payload = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = [l.strip() for l in labels.split(",")]

    data = await github_request("POST", f"/repos/{owner}/{repo}/issues", payload)

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    return f"Issue created successfully!\n  #{data['number']}: {data['title']}\n  URL: {data['html_url']}"


# ============================================
# PULL REQUEST TOOLS
# ============================================

@mcp.tool()
async def list_pull_requests(owner: str, repo: str, state: str = "open", per_page: int = 10) -> str:
    """
    List pull requests in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: Filter by state: open, closed, all (default: open)
        per_page: Number of PRs to return (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    data = await github_request("GET", f"/repos/{owner}/{repo}/pulls?state={state}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data:
        return f"No {state} pull requests found in {owner}/{repo}"

    prs = []
    for pr in data:
        draft = "📝" if pr.get("draft") else "🔀"
        prs.append(f"  {draft} #{pr['number']} {pr['title']} ({pr['user']['login']})")

    return f"Pull Requests in {owner}/{repo} ({state}):\n" + "\n".join(prs)


@mcp.tool()
async def get_pull_request(owner: str, repo: str, pr_number: int) -> str:
    """
    Get details of a specific pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
    """
    data = await github_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    return f"""PR #{data['number']}: {data['title']}
  State: {data['state']} {'(draft)' if data.get('draft') else ''}
  Author: {data['user']['login']}
  Branch: {data['head']['ref']} -> {data['base']['ref']}
  Commits: {data['commits']}
  Changed Files: {data['changed_files']}
  Additions: +{data['additions']} Deletions: -{data['deletions']}
  Mergeable: {data.get('mergeable', 'unknown')}
  Created: {data['created_at'][:10]}
  URL: {data['html_url']}

Body:
{data.get('body', 'No description')[:500]}"""


# ============================================
# SEARCH TOOLS
# ============================================

@mcp.tool()
async def search_repos(query: str, sort: str = "stars", per_page: int = 10) -> str:
    """
    Search for repositories on GitHub.

    Args:
        query: Search query (e.g., "fastapi language:python", "react stars:>1000")
        sort: Sort by: stars, forks, updated (default: stars)
        per_page: Number of results (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    # URL encode the query
    encoded_query = query.replace(" ", "+")
    data = await github_request("GET", f"/search/repositories?q={encoded_query}&sort={sort}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data.get("items"):
        return f"No repositories found for: {query}"

    results = [f"Found {data['total_count']} repositories for: {query}\n"]
    for repo in data["items"]:
        stars = repo.get('stargazers_count', 0)
        lang = repo.get('language', 'N/A')
        desc = repo.get('description', '')[:60]
        results.append(f"  - {repo['full_name']} ⭐{stars} [{lang}]\n    {desc}")

    return "\n".join(results)


@mcp.tool()
async def search_issues(query: str, per_page: int = 10) -> str:
    """
    Search for issues and pull requests across GitHub.

    Args:
        query: Search query (e.g., "bug repo:owner/repo", "is:open is:issue label:bug")
        per_page: Number of results (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    encoded_query = query.replace(" ", "+")
    data = await github_request("GET", f"/search/issues?q={encoded_query}&per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data.get("items"):
        return f"No issues found for: {query}"

    results = [f"Found {data['total_count']} issues for: {query}\n"]
    for issue in data["items"]:
        repo_name = issue['repository_url'].split('/')[-2] + "/" + issue['repository_url'].split('/')[-1]
        pr_icon = "🔀" if "pull_request" in issue else "📋"
        results.append(f"  {pr_icon} {repo_name}#{issue['number']}: {issue['title'][:50]}")

    return "\n".join(results)


# ============================================
# WORKFLOW/ACTIONS TOOLS
# ============================================

@mcp.tool()
async def list_workflows(owner: str, repo: str) -> str:
    """
    List GitHub Actions workflows in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    data = await github_request("GET", f"/repos/{owner}/{repo}/actions/workflows")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data.get("workflows"):
        return f"No workflows found in {owner}/{repo}"

    workflows = []
    for wf in data["workflows"]:
        state = "✅" if wf["state"] == "active" else "⏸️"
        workflows.append(f"  {state} {wf['name']} ({wf['path']})")

    return f"Workflows in {owner}/{repo}:\n" + "\n".join(workflows)


@mcp.tool()
async def list_workflow_runs(owner: str, repo: str, per_page: int = 10) -> str:
    """
    List recent workflow runs in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        per_page: Number of runs to return (default: 10, max: 30)
    """
    per_page = min(max(1, per_page), 30)
    data = await github_request("GET", f"/repos/{owner}/{repo}/actions/runs?per_page={per_page}")

    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not data.get("workflow_runs"):
        return f"No workflow runs found in {owner}/{repo}"

    runs = []
    status_icons = {
        "completed": "✅",
        "in_progress": "🔄",
        "queued": "⏳",
        "failure": "❌",
        "cancelled": "⛔",
    }
    for run in data["workflow_runs"]:
        icon = status_icons.get(run["status"], "❓")
        if run["conclusion"] == "failure":
            icon = "❌"
        runs.append(f"  {icon} {run['name']} - {run['head_branch']} ({run['status']})")

    return f"Recent workflow runs in {owner}/{repo}:\n" + "\n".join(runs)


# ============================================
# START THE SERVER
# ============================================

if __name__ == "__main__":
    mcp.run()
