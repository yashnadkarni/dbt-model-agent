"""
GitHub Connector — Create branches, commit dbt models, and open Pull Requests.

Connects to a GitHub repository via a Personal Access Token (PAT) and
pushes generated dbt model files to a new branch, then opens a PR with
validation results embedded in the description.

Usage:
    from src.github_connector import GitHubConnector

    connector = GitHubConnector(
        token="ghp_xxxx",
        repo_full_name="owner/repo",
    )
    connector.test_connection()

    pr_url = connector.push_models_and_create_pr(
        model_name="completed_order_details",
        files={
            "models/generated/completed_order_details.sql": "SELECT ...",
            "models/generated/completed_order_details_schema.yml": "version: 2...",
            "models/generated/jaffle_shop_sources.yml": "version: 2...",
        },
        validation_results={"steps": [...], "all_passed": True},
        base_branch="main",
    )
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger("agent.github")


@dataclass
class GitHubConfig:
    """
    Configuration for GitHub integration.

    token: GitHub Personal Access Token (classic or fine-grained)
    repo_full_name: "owner/repo" format, e.g. "yashnadkarni/dbt-model-agent"
    base_branch: Target branch for PRs (default: "main")
    models_path: Path prefix for model files in the repo (default: "models/generated")
    """
    token: str = ""
    repo_full_name: str = ""
    base_branch: str = "main"
    models_path: str = "models/generated"

    def validate(self) -> list[str]:
        """Return list of missing required field names."""
        missing = []
        if not self.token:
            missing.append("token")
        if not self.repo_full_name:
            missing.append("repo_full_name")
        if "/" not in self.repo_full_name and self.repo_full_name:
            missing.append("repo_full_name (must be owner/repo format)")
        return missing


class GitHubConnector:
    """
    Manages GitHub operations: connection testing, branch creation,
    file commits, and Pull Request creation via the GitHub REST API.
    """

    def __init__(self, config: GitHubConfig):
        self.config = config
        self._github = None
        self._repo = None

    def _get_github(self):
        """Lazy-initialise the PyGithub client."""
        if self._github is None:
            from github import Github
            self._github = Github(self.config.token)
        return self._github

    def _get_repo(self):
        """Lazy-initialise the repository object."""
        if self._repo is None:
            self._repo = self._get_github().get_repo(self.config.repo_full_name)
        return self._repo

    def test_connection(self) -> dict:
        """
        Test GitHub connectivity and repo access.

        Returns:
            dict with keys: success (bool), message (str), details (dict)
        """
        missing = self.config.validate()
        if missing:
            return {
                "success": False,
                "message": f"Missing required fields: {', '.join(missing)}",
                "details": {"missing_fields": missing},
            }

        try:
            from github import Github
        except ImportError:
            return {
                "success": False,
                "message": (
                    "PyGithub is not installed. "
                    "Run: pip install PyGithub"
                ),
                "details": {},
            }

        try:
            gh = self._get_github()
            user = gh.get_user()
            repo = self._get_repo()

            return {
                "success": True,
                "message": f"Connected as @{user.login} → {repo.full_name}",
                "details": {
                    "user": user.login,
                    "repo": repo.full_name,
                    "default_branch": repo.default_branch,
                    "private": repo.private,
                },
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"GitHub connection failed: {exc}",
                "details": {},
            }

    def push_models_and_create_pr(
        self,
        model_name: str,
        files: Dict[str, str],
        validation_results: Optional[dict] = None,
        base_branch: Optional[str] = None,
    ) -> dict:
        """
        Create a branch, commit model files, and open a Pull Request.

        Args:
            model_name: Name of the dbt model (used in branch/PR title)
            files: Dict of {file_path: file_content} to commit
            validation_results: Optional dict with validation step results
            base_branch: Target branch for the PR (defaults to config.base_branch)

        Returns:
            dict with keys: success (bool), message (str), pr_url (str),
                            branch_name (str), details (dict)
        """
        if base_branch is None:
            base_branch = self.config.base_branch

        try:
            repo = self._get_repo()

            # Step 1: Create branch name with timestamp to avoid collisions
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            branch_name = f"dbt/migrate-{model_name}-{timestamp}"

            # Step 2: Get the SHA of the base branch
            base_ref = repo.get_branch(base_branch)
            base_sha = base_ref.commit.sha

            # Step 3: Create the new branch
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_sha,
            )
            logger.info("Created branch: %s (from %s @ %s)",
                         branch_name, base_branch, base_sha[:8])

            # Step 4: Commit files to the new branch
            for file_path, content in files.items():
                # Check if file already exists (update vs create)
                try:
                    existing = repo.get_contents(file_path, ref=branch_name)
                    repo.update_file(
                        path=file_path,
                        message=f"chore(dbt): update {file_path.split('/')[-1]}",
                        content=content,
                        sha=existing.sha,
                        branch=branch_name,
                    )
                except Exception:
                    # File doesn't exist — create it
                    repo.create_file(
                        path=file_path,
                        message=f"chore(dbt): add {file_path.split('/')[-1]}",
                        content=content,
                        branch=branch_name,
                    )

            logger.info("Committed %d files to %s", len(files), branch_name)

            # Step 5: Build PR description with validation results
            pr_body = self._build_pr_body(model_name, files, validation_results)

            # Step 6: Create the Pull Request
            pr = repo.create_pull(
                title=f"🔄 dbt migration: {model_name}",
                body=pr_body,
                head=branch_name,
                base=base_branch,
            )

            logger.info("Created PR #%d: %s", pr.number, pr.html_url)

            return {
                "success": True,
                "message": f"PR #{pr.number} created successfully",
                "pr_url": pr.html_url,
                "branch_name": branch_name,
                "details": {
                    "pr_number": pr.number,
                    "files_committed": list(files.keys()),
                    "base_branch": base_branch,
                },
            }

        except Exception as exc:
            logger.error("GitHub push failed: %s", exc)
            return {
                "success": False,
                "message": f"GitHub push failed: {exc}",
                "pr_url": "",
                "branch_name": "",
                "details": {},
            }

    def _build_pr_body(
        self,
        model_name: str,
        files: Dict[str, str],
        validation_results: Optional[dict],
    ) -> str:
        """Build a markdown PR description with validation results."""
        lines = [
            f"## 🔄 dbt Model Migration: `{model_name}`",
            "",
            "This PR was auto-generated by **dbt Model Agent** from a Talend ETL job.",
            "",
            "### 📁 Files",
        ]

        for fpath in files:
            lines.append(f"- `{fpath}`")

        lines.append("")

        # Add validation results if available
        if validation_results and validation_results.get("steps"):
            lines.append("### ✅ Validation Results")
            lines.append("")
            lines.append("| Step | Status | Details |")
            lines.append("|------|--------|---------|")

            for step in validation_results["steps"]:
                status = "✅ Passed" if step.get("passed") else "❌ Failed"
                output = step.get("output", "").replace("\n", " ").strip()
                # Truncate long output for PR readability
                if len(output) > 120:
                    output = output[:117] + "..."
                lines.append(f"| {step['name']} | {status} | {output} |")

            lines.append("")

            if validation_results.get("all_passed"):
                lines.append("> ✅ **All validation steps passed.**")
            else:
                lines.append("> ⚠️ **Some validation steps failed.** Please review before merging.")
        else:
            lines.append("> ℹ️ No validation results attached. Run `dbt compile` and `dbt test` before merging.")

        lines.extend([
            "",
            "---",
            f"*Generated by [dbt Model Agent](https://github.com/{self.config.repo_full_name}) "
            f"on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(lines)
