"""
Tests for the GitHub connector module (src/github_connector.py).

Covers:
  - GitHubConfig creation and validation
  - GitHubConnector connection testing (mocked)
  - Branch creation, file commit, and PR creation (mocked)
  - PR body generation with validation results
"""

import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from src.github_connector import GitHubConfig, GitHubConnector


# ---------------------------------------------------------------------------
# GitHubConfig Tests
# ---------------------------------------------------------------------------

class TestGitHubConfig:
    """Test GitHubConfig creation and validation."""

    def test_default_values(self):
        config = GitHubConfig()
        assert config.token == ""
        assert config.repo_full_name == ""
        assert config.base_branch == "main"
        assert config.models_path == "models/generated"

    def test_validate_missing_token(self):
        config = GitHubConfig(repo_full_name="owner/repo")
        missing = config.validate()
        assert "token" in missing

    def test_validate_missing_repo(self):
        config = GitHubConfig(token="ghp_test")
        missing = config.validate()
        assert "repo_full_name" in missing

    def test_validate_bad_repo_format(self):
        config = GitHubConfig(token="ghp_test", repo_full_name="noslash")
        missing = config.validate()
        assert any("owner/repo" in m for m in missing)

    def test_validate_all_fields_set(self):
        config = GitHubConfig(token="ghp_test", repo_full_name="owner/repo")
        assert config.validate() == []

    def test_custom_base_branch(self):
        config = GitHubConfig(
            token="ghp_test",
            repo_full_name="owner/repo",
            base_branch="develop",
        )
        assert config.base_branch == "develop"

    def test_custom_models_path(self):
        config = GitHubConfig(
            token="ghp_test",
            repo_full_name="owner/repo",
            models_path="dbt/models",
        )
        assert config.models_path == "dbt/models"


# ---------------------------------------------------------------------------
# GitHubConnector Connection Test
# ---------------------------------------------------------------------------

class TestGitHubConnectorConnect:
    """Test connection testing (mocked — no real token needed)."""

    def test_connection_missing_fields(self):
        config = GitHubConfig()
        connector = GitHubConnector(config)
        result = connector.test_connection()
        assert result["success"] is False
        assert "Missing" in result["message"]

    @patch("src.github_connector.GitHubConnector._get_repo")
    @patch("src.github_connector.GitHubConnector._get_github")
    def test_connection_success_mocked(self, mock_get_gh, mock_get_repo):
        mock_user = MagicMock()
        mock_user.login = "testuser"
        mock_gh = MagicMock()
        mock_gh.get_user.return_value = mock_user
        mock_get_gh.return_value = mock_gh

        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.default_branch = "main"
        mock_repo.private = False
        mock_get_repo.return_value = mock_repo

        config = GitHubConfig(token="ghp_test", repo_full_name="owner/repo")
        connector = GitHubConnector(config)
        result = connector.test_connection()

        assert result["success"] is True
        assert "@testuser" in result["message"]
        assert result["details"]["repo"] == "owner/repo"

    @patch("src.github_connector.GitHubConnector._get_github")
    def test_connection_failure_mocked(self, mock_get_gh):
        mock_get_gh.side_effect = Exception("401 Bad credentials")

        config = GitHubConfig(token="bad_token", repo_full_name="owner/repo")
        connector = GitHubConnector(config)
        result = connector.test_connection()

        assert result["success"] is False
        assert "failed" in result["message"]


# ---------------------------------------------------------------------------
# GitHubConnector Push & PR Tests
# ---------------------------------------------------------------------------

class TestGitHubConnectorPush:
    """Test branch creation, file commit, and PR creation (mocked)."""

    def _make_config(self):
        return GitHubConfig(
            token="ghp_test",
            repo_full_name="owner/repo",
            base_branch="main",
            models_path="models/generated",
        )

    def _make_files(self):
        return {
            "models/generated/test_model.sql": "SELECT 1 AS id",
            "models/generated/test_model_schema.yml": "version: 2\nmodels:\n- name: test_model",
            "models/generated/jaffle_shop_sources.yml": "version: 2\nsources:\n- name: jaffle_shop",
        }

    @patch("src.github_connector.GitHubConnector._get_repo")
    def test_push_creates_branch_and_pr(self, mock_get_repo):
        mock_repo = MagicMock()

        # Mock get_branch
        mock_branch = MagicMock()
        mock_branch.commit.sha = "abc123def456"
        mock_repo.get_branch.return_value = mock_branch

        # Mock create_git_ref (branch creation)
        mock_repo.create_git_ref.return_value = MagicMock()

        # Mock get_contents (file doesn't exist → raise to trigger create)
        mock_repo.get_contents.side_effect = Exception("Not found")

        # Mock create_file
        mock_repo.create_file.return_value = {"content": MagicMock()}

        # Mock create_pull
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.html_url = "https://github.com/owner/repo/pull/42"
        mock_repo.create_pull.return_value = mock_pr

        mock_get_repo.return_value = mock_repo

        config = self._make_config()
        connector = GitHubConnector(config)
        result = connector.push_models_and_create_pr(
            model_name="test_model",
            files=self._make_files(),
        )

        assert result["success"] is True
        assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert "dbt/migrate-test_model-" in result["branch_name"]

        # Verify branch was created
        mock_repo.create_git_ref.assert_called_once()
        ref_arg = mock_repo.create_git_ref.call_args[1]["ref"]
        assert ref_arg.startswith("refs/heads/dbt/migrate-test_model-")

        # Verify 3 files were committed
        assert mock_repo.create_file.call_count == 3

        # Verify PR was created
        mock_repo.create_pull.assert_called_once()
        pr_call_kwargs = mock_repo.create_pull.call_args[1]
        assert "test_model" in pr_call_kwargs["title"]
        assert pr_call_kwargs["base"] == "main"

    @patch("src.github_connector.GitHubConnector._get_repo")
    def test_push_updates_existing_files(self, mock_get_repo):
        mock_repo = MagicMock()

        mock_branch = MagicMock()
        mock_branch.commit.sha = "abc123"
        mock_repo.get_branch.return_value = mock_branch
        mock_repo.create_git_ref.return_value = MagicMock()

        # Mock get_contents succeeds (file exists → update)
        mock_existing = MagicMock()
        mock_existing.sha = "existing_sha"
        mock_repo.get_contents.return_value = mock_existing

        mock_repo.update_file.return_value = {"content": MagicMock()}

        mock_pr = MagicMock()
        mock_pr.number = 43
        mock_pr.html_url = "https://github.com/owner/repo/pull/43"
        mock_repo.create_pull.return_value = mock_pr

        mock_get_repo.return_value = mock_repo

        config = self._make_config()
        connector = GitHubConnector(config)
        result = connector.push_models_and_create_pr(
            model_name="test_model",
            files=self._make_files(),
        )

        assert result["success"] is True
        # Files should have been updated, not created
        assert mock_repo.update_file.call_count == 3
        assert mock_repo.create_file.call_count == 0

    @patch("src.github_connector.GitHubConnector._get_repo")
    def test_push_failure_returns_error(self, mock_get_repo):
        mock_repo = MagicMock()
        mock_repo.get_branch.side_effect = Exception("Branch not found")
        mock_get_repo.return_value = mock_repo

        config = self._make_config()
        connector = GitHubConnector(config)
        result = connector.push_models_and_create_pr(
            model_name="test_model",
            files=self._make_files(),
        )

        assert result["success"] is False
        assert "failed" in result["message"]

    @patch("src.github_connector.GitHubConnector._get_repo")
    def test_push_with_custom_base_branch(self, mock_get_repo):
        mock_repo = MagicMock()
        mock_branch = MagicMock()
        mock_branch.commit.sha = "abc123"
        mock_repo.get_branch.return_value = mock_branch
        mock_repo.create_git_ref.return_value = MagicMock()
        mock_repo.get_contents.side_effect = Exception("Not found")
        mock_repo.create_file.return_value = {"content": MagicMock()}

        mock_pr = MagicMock()
        mock_pr.number = 44
        mock_pr.html_url = "https://github.com/owner/repo/pull/44"
        mock_repo.create_pull.return_value = mock_pr

        mock_get_repo.return_value = mock_repo

        config = self._make_config()
        connector = GitHubConnector(config)
        result = connector.push_models_and_create_pr(
            model_name="test_model",
            files={"models/generated/test.sql": "SELECT 1"},
            base_branch="develop",
        )

        assert result["success"] is True
        pr_kwargs = mock_repo.create_pull.call_args[1]
        assert pr_kwargs["base"] == "develop"


# ---------------------------------------------------------------------------
# PR Body Generation Tests
# ---------------------------------------------------------------------------

class TestPRBodyGeneration:
    """Test PR description markdown generation."""

    def _make_connector(self):
        config = GitHubConfig(token="ghp_test", repo_full_name="owner/repo")
        return GitHubConnector(config)

    def test_pr_body_includes_model_name(self):
        connector = self._make_connector()
        body = connector._build_pr_body(
            model_name="active_customers",
            files={"models/generated/active_customers.sql": "SELECT 1"},
            validation_results=None,
        )
        assert "active_customers" in body

    def test_pr_body_includes_files(self):
        connector = self._make_connector()
        files = {
            "models/generated/test.sql": "SELECT 1",
            "models/generated/test_schema.yml": "version: 2",
        }
        body = connector._build_pr_body("test", files, None)
        assert "models/generated/test.sql" in body
        assert "models/generated/test_schema.yml" in body

    def test_pr_body_with_validation_results(self):
        connector = self._make_connector()
        val_results = {
            "steps": [
                {"name": "sqlfluff lint", "passed": True, "output": "All Finished!"},
                {"name": "dbt compile", "passed": True, "output": "OK compiled"},
                {"name": "dbt run", "passed": False, "output": "Error: table not found"},
            ],
            "all_passed": False,
        }
        body = connector._build_pr_body(
            "test_model",
            {"models/generated/test.sql": "SELECT 1"},
            val_results,
        )
        assert "sqlfluff lint" in body
        assert "✅ Passed" in body
        assert "❌ Failed" in body
        assert "Some validation steps failed" in body

    def test_pr_body_all_passed(self):
        connector = self._make_connector()
        val_results = {
            "steps": [
                {"name": "sqlfluff lint", "passed": True, "output": "OK"},
                {"name": "dbt compile", "passed": True, "output": "OK"},
            ],
            "all_passed": True,
        }
        body = connector._build_pr_body(
            "test_model",
            {"models/generated/test.sql": "SELECT 1"},
            val_results,
        )
        assert "All validation steps passed" in body

    def test_pr_body_no_validation(self):
        connector = self._make_connector()
        body = connector._build_pr_body(
            "test_model",
            {"models/generated/test.sql": "SELECT 1"},
            None,
        )
        assert "No validation results attached" in body

    def test_pr_body_auto_generated_tag(self):
        connector = self._make_connector()
        body = connector._build_pr_body(
            "test",
            {"models/generated/test.sql": "SELECT 1"},
            None,
        )
        assert "dbt Model Agent" in body
