"""Tests for the Git-backed Markdown output handler."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cloud_monitor_pdf2md.connectors.base import CloudDocument
from cloud_monitor_pdf2md.output import GitMarkdownOutputHandler


def _init_git_repository(path: Path) -> None:
    result = subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(["git", "init"], cwd=path, check=True)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=path, check=True)


def _git_output(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_git_output_handler_commits_changes(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _init_git_repository(repository)

    handler = GitMarkdownOutputHandler(
        repository_path=repository,
        directory="notes",
        branch="main",
        commit_message_template="Add {document_name}",
        push=False,
    )

    document = CloudDocument(identifier="doc-123", name="Project Plan")
    output_path = handler.write(document, "# Project Plan\n")

    assert output_path.exists()
    assert output_path.relative_to(repository) == Path("notes/Project-Plan.md")

    last_commit_message = _git_output("log", "-1", "--pretty=%s", cwd=repository)
    assert last_commit_message == "Add Project Plan"

    rev_count = _git_output("rev-list", "--count", "HEAD", cwd=repository)
    assert rev_count == "1"

    # Writing new content should produce another commit.
    handler.write(CloudDocument(identifier="doc-456", name="Status Update"), "# Update\n")
    rev_count_after = _git_output("rev-list", "--count", "HEAD", cwd=repository)
    assert rev_count_after == "2"


def test_git_output_handler_skips_empty_commits(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _init_git_repository(repository)

    handler = GitMarkdownOutputHandler(
        repository_path=repository,
        directory="notes",
        branch="main",
        commit_message_template="Add {document_name}",
        push=False,
    )

    document = CloudDocument(identifier="doc-1", name="Notebook")
    handler.write(document, "# Notes\n")
    initial_rev_count = _git_output("rev-list", "--count", "HEAD", cwd=repository)

    handler.write(document, "# Notes\n")
    rev_count_after = _git_output("rev-list", "--count", "HEAD", cwd=repository)

    assert initial_rev_count == rev_count_after
