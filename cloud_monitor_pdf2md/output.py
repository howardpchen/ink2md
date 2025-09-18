"""Utilities for storing Markdown results."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .connectors.base import CloudDocument


class MarkdownOutputHandler:
    """Write Markdown documents to a target directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, document: CloudDocument, markdown: str) -> Path:
        safe_name = self._sanitize_name(document.name)
        target_path = self.directory / f"{safe_name}.md"
        target_path.write_text(markdown, encoding="utf-8")
        return target_path

    @staticmethod
    def _sanitize_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        return safe or "document"


class GitMarkdownOutputHandler(MarkdownOutputHandler):
    """Persist Markdown files inside a Git repository and commit the changes."""

    def __init__(
        self,
        repository_path: str | Path,
        directory: str | Path,
        *,
        branch: str = "main",
        remote: str = "origin",
        commit_message_template: str = "Add {document_name}",
        push: bool = False,
    ) -> None:
        self.repository_path = Path(repository_path).expanduser().resolve()
        if not self.repository_path.exists():
            raise FileNotFoundError(
                f"Git repository path does not exist: {self.repository_path}"
            )
        self._verify_repository()
        self.branch = branch
        self.remote = remote
        self.commit_message_template = commit_message_template
        self.push = push

        self._ensure_branch()

        resolved_directory = Path(directory)
        if not resolved_directory.is_absolute():
            resolved_directory = (self.repository_path / resolved_directory).resolve()
        else:
            resolved_directory = resolved_directory.expanduser().resolve()

        try:
            resolved_directory.relative_to(self.repository_path)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError(
                "The output directory must reside within the Git repository"
            ) from exc

        super().__init__(resolved_directory)

    def write(self, document: CloudDocument, markdown: str) -> Path:
        output_path = super().write(document, markdown)
        relative_path = output_path.relative_to(self.repository_path)
        self._run_git("add", str(relative_path))

        if not self._has_staged_changes(relative_path):
            # Revert the staged file to keep the index clean when nothing changed.
            self._run_git("reset", "HEAD", "--", str(relative_path))
            return output_path

        commit_message = self.commit_message_template.format(
            document_name=document.name,
            document_identifier=document.identifier,
        )
        self._run_git("commit", "-m", commit_message)
        if self.push:
            self._run_git("push", self.remote, self.branch)
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _verify_repository(self) -> None:
        result = self._run_git("rev-parse", "--is-inside-work-tree", check=False)
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise ValueError(f"Path is not a Git repository: {self.repository_path}")

    def _ensure_branch(self) -> None:
        current = (
            self._run_git("rev-parse", "--abbrev-ref", "HEAD", check=False)
            .stdout.strip()
        )
        if current == self.branch:
            return
        checkout = self._run_git("checkout", self.branch, check=False)
        if checkout.returncode != 0:
            self._run_git("checkout", "-b", self.branch)

    def _has_staged_changes(self, relative_path: Path) -> bool:
        result = self._run_git(
            "diff",
            "--cached",
            "--quiet",
            "--",
            str(relative_path),
            check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip())
        return result.returncode == 1

    def _run_git(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", "-C", str(self.repository_path), *args],
            check=check,
            capture_output=capture_output,
            text=True,
        )
        return completed


__all__ = ["GitMarkdownOutputHandler", "MarkdownOutputHandler"]
