"""Tests for the doto git command."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def store_with_task(tmp_path):
    """A JSON store with a single task."""
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store_file = store_dir / "tasks.json"
    data = {
        "version": 3,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "TASK-001": {
                "title": "Test task",
                "status": "open",
                "priority": "medium",
                "tags": [],
                "depends_on": [],
                "body": "",
                "created": "2024-01-01T00:00:00",
                "updated": "2024-01-01T00:00:00",
                "archived": False,
                "archived_on": None,
                "_sync": {},
            }
        },
        "series": {},
    }
    store_file.write_text(json.dumps(data))
    return store_file


def test_git_link_with_explicit_commit(runner, store_with_task):
    """doto git TASK-001 --commit abc123 stores the commit in _git.commits."""
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "abc123def456789"],
    )
    assert result.exit_code == 0
    assert "Linked commit abc123def456" in result.output

    data = json.loads(store_with_task.read_text())
    task = data["tasks"]["TASK-001"]
    assert "_git" in task
    assert "commits" in task["_git"]
    assert len(task["_git"]["commits"]) == 1
    assert task["_git"]["commits"][0]["hash"] == "abc123def456789"


def test_git_link_with_message_and_branch(runner, store_with_task):
    """doto git with --message and --branch stores both."""
    result = runner.invoke(
        cli,
        [
            "--json",
            str(store_with_task),
            "git",
            "TASK-001",
            "--commit",
            "abc123",
            "--message",
            "Fix the bug",
            "--branch",
            "feature/fix",
        ],
    )
    assert result.exit_code == 0

    data = json.loads(store_with_task.read_text())
    commit = data["tasks"]["TASK-001"]["_git"]["commits"][0]
    assert commit["hash"] == "abc123"
    assert commit["message"] == "Fix the bug"
    assert commit["branch"] == "feature/fix"


def test_git_log_shows_linked_commits(runner, store_with_task):
    """doto git TASK-001 --log lists linked commits."""
    # First, link a commit
    runner.invoke(
        cli,
        [
            "--json",
            str(store_with_task),
            "git",
            "TASK-001",
            "--commit",
            "abc123def456",
            "--message",
            "Initial commit",
            "--branch",
            "main",
        ],
    )

    # Then list commits
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--log"],
    )
    assert result.exit_code == 0
    assert "abc123def456" in result.output
    assert "Initial commit" in result.output
    assert "main" in result.output


def test_git_log_json_format(runner, store_with_task):
    """doto git TASK-001 --log --format json outputs valid JSON."""
    # First, link a commit
    runner.invoke(
        cli,
        [
            "--json",
            str(store_with_task),
            "git",
            "TASK-001",
            "--commit",
            "abc123",
            "--message",
            "Test",
        ],
    )

    # Then list in JSON format
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--log", "--format", "json"],
    )
    assert result.exit_code == 0
    # Output should contain JSON array
    assert "abc123" in result.output


def test_git_log_no_commits(runner, store_with_task):
    """doto git TASK-001 --log with no commits shows message."""
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--log"],
    )
    assert result.exit_code == 0
    assert "No commits linked" in result.output


def test_git_deduplicate_same_hash(runner, store_with_task):
    """Linking the same hash twice doesn't create duplicate entries."""
    # Link first time
    runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "abc123"],
    )

    # Link second time
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "abc123"],
    )
    assert result.exit_code == 0
    assert "already linked" in result.output

    data = json.loads(store_with_task.read_text())
    assert len(data["tasks"]["TASK-001"]["_git"]["commits"]) == 1


def test_git_remove_commit_link(runner, store_with_task):
    """doto git TASK-001 --remove abc removes the matching link."""
    # First, link a commit
    runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "abc123def456"],
    )

    # Remove it
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--remove", "abc123"],
    )
    assert result.exit_code == 0
    assert "Removed" in result.output

    data = json.loads(store_with_task.read_text())
    assert len(data["tasks"]["TASK-001"]["_git"]["commits"]) == 0


def test_git_remove_nonexistent_link_errors(runner, store_with_task):
    """doto git --remove with no matching hash errors."""
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--remove", "nonexistent"],
    )
    assert result.exit_code != 0
    assert "No link with hash prefix" in result.output


def test_git_unknown_task_errors(runner, store_with_task):
    """doto git UNKNOWN --commit abc errors when task doesn't exist."""
    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "UNKNOWN", "--commit", "abc123"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_git_no_commit_no_git_errors(runner, store_with_task):
    """doto git without --commit and no git available errors gracefully."""
    with patch("doxtr_doto.cli.commands.git._get_current_commit", return_value=None):
        result = runner.invoke(
            cli,
            ["--json", str(store_with_task), "git", "TASK-001"],
        )
        assert result.exit_code != 0
        assert "Could not determine commit hash" in result.output


def test_git_auto_detects_head(runner, store_with_task):
    """doto git without --commit uses current HEAD when git is available."""
    with patch("doxtr_doto.cli.commands.git._get_current_commit", return_value="auto123456789"):
        with patch("doxtr_doto.cli.commands.git._get_current_branch", return_value="main"):
            with patch(
                "doxtr_doto.cli.commands.git._get_commit_message", return_value="Auto message"
            ):
                with patch("doxtr_doto.cli.commands.git._get_commit_author", return_value="alice"):
                    with patch(
                        "doxtr_doto.cli.commands.git._get_commit_date",
                        return_value="2024-07-26T14:30:45+00:00",
                    ):
                        result = runner.invoke(
                            cli,
                            ["--json", str(store_with_task), "git", "TASK-001"],
                        )
                        assert result.exit_code == 0
                        assert "Linked commit auto12345678" in result.output

    data = json.loads(store_with_task.read_text())
    commit = data["tasks"]["TASK-001"]["_git"]["commits"][0]
    assert commit["hash"] == "auto123456789"
    assert commit["branch"] == "main"
    assert commit["message"] == "Auto message"
    assert commit["author"] == "alice"
    assert commit["date"] == "2024-07-26T14:30:45+00:00"


def test_git_preserves_existing_links(runner, store_with_task):
    """Adding a new commit link preserves existing ones."""
    # Link first commit
    runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "first123"],
    )

    # Link second commit
    runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--commit", "second456"],
    )

    data = json.loads(store_with_task.read_text())
    commits = data["tasks"]["TASK-001"]["_git"]["commits"]
    assert len(commits) == 2
    assert commits[0]["hash"] == "first123"
    assert commits[1]["hash"] == "second456"


def test_git_log_shows_author_and_date(runner, store_with_task):
    """doto git TASK-001 --log displays author and date when available."""
    # Manually set up a task with author/date in _git metadata
    data = json.loads(store_with_task.read_text())
    data["tasks"]["TASK-001"]["_git"] = {
        "commits": [
            {
                "hash": "abc123def456",
                "message": "Fix the bug",
                "branch": "main",
                "author": "alice",
                "date": "2024-07-26T14:30:45+00:00",
            }
        ]
    }
    store_with_task.write_text(json.dumps(data))

    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--log"],
    )
    assert result.exit_code == 0
    assert "abc123def456" in result.output
    assert "Fix the bug" in result.output
    assert "alice" in result.output
    assert "2024-07-26" in result.output


def test_git_log_json_includes_author_and_date(runner, store_with_task):
    """doto git --log --format json includes author and date fields."""
    # Manually set up a task with author/date in _git metadata
    data = json.loads(store_with_task.read_text())
    data["tasks"]["TASK-001"]["_git"] = {
        "commits": [
            {
                "hash": "abc123",
                "message": "Test commit",
                "author": "bob",
                "date": "2024-08-01T10:00:00Z",
            }
        ]
    }
    store_with_task.write_text(json.dumps(data))

    result = runner.invoke(
        cli,
        ["--json", str(store_with_task), "git", "TASK-001", "--log", "--format", "json"],
    )
    assert result.exit_code == 0
    assert '"author"' in result.output or "bob" in result.output
    assert '"date"' in result.output or "2024-08-01" in result.output


def test_git_link_stores_author_and_date_from_git(runner, store_with_task):
    """doto git stores author and date retrieved from git."""
    with patch("doxtr_doto.cli.commands.git._get_current_commit", return_value="commit789"):
        with patch("doxtr_doto.cli.commands.git._get_current_branch", return_value="feature"):
            with patch(
                "doxtr_doto.cli.commands.git._get_commit_message", return_value="Feature work"
            ):
                with patch(
                    "doxtr_doto.cli.commands.git._get_commit_author", return_value="charlie"
                ):
                    with patch(
                        "doxtr_doto.cli.commands.git._get_commit_date",
                        return_value="2024-08-15T09:00:00Z",
                    ):
                        result = runner.invoke(
                            cli,
                            ["--json", str(store_with_task), "git", "TASK-001"],
                        )
                        assert result.exit_code == 0

    data = json.loads(store_with_task.read_text())
    commit = data["tasks"]["TASK-001"]["_git"]["commits"][0]
    assert commit["author"] == "charlie"
    assert commit["date"] == "2024-08-15T09:00:00Z"


def test_git_link_handles_missing_author_date(runner, store_with_task):
    """doto git works even when author/date can't be retrieved."""
    with patch("doxtr_doto.cli.commands.git._get_current_commit", return_value="noinfo123"):
        with patch("doxtr_doto.cli.commands.git._get_current_branch", return_value=None):
            with patch("doxtr_doto.cli.commands.git._get_commit_message", return_value=None):
                with patch("doxtr_doto.cli.commands.git._get_commit_author", return_value=None):
                    with patch("doxtr_doto.cli.commands.git._get_commit_date", return_value=None):
                        result = runner.invoke(
                            cli,
                            ["--json", str(store_with_task), "git", "TASK-001"],
                        )
                        assert result.exit_code == 0
                        assert "Linked commit noinfo123" in result.output

    data = json.loads(store_with_task.read_text())
    commit = data["tasks"]["TASK-001"]["_git"]["commits"][0]
    assert commit["hash"] == "noinfo123"
    # These fields should not be present when None
    assert "author" not in commit
    assert "date" not in commit
    assert "branch" not in commit
    assert "message" not in commit
