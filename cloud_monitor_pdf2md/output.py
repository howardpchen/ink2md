"""Utilities for storing Markdown results."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime as dt_module, timezone
from pathlib import Path
from typing import Iterable, Optional

from .connectors.base import CloudDocument

LOGGER = logging.getLogger(__name__)


class MarkdownOutputHandler:
    """Write Markdown documents to a target directory."""

    def __init__(self, directory: str | Path, asset_directory: str | Path | None = None):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

        if asset_directory is not None:
            asset_path = Path(asset_directory).expanduser().resolve()
            asset_path.mkdir(parents=True, exist_ok=True)
            self.asset_directory: Optional[Path] = asset_path
        else:
            self.asset_directory = None

    def write(
        self,
        document: CloudDocument,
        markdown: str,
        *,
        pdf_bytes: bytes | None = None,
        basename: str | None = None,
    ) -> Path:
        if basename is None:
            basename = self._build_basename(document)

        markdown_path = self.directory / f"{basename}.md"
        markdown_path.write_text(markdown, encoding="utf-8")

        pdf_copy = self._maybe_copy_pdf(basename, pdf_bytes)
        self._post_write(document, markdown_path, pdf_copy)
        return markdown_path

    def _post_write(
        self,
        document: CloudDocument,
        markdown_path: Path,
        pdf_copy: Optional[Path],
    ) -> None:  # pragma: no cover - hook for subclasses
        del document, markdown_path, pdf_copy

    @staticmethod
    def _sanitize_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        return safe or "document"

    def _build_basename(self, document: CloudDocument) -> str:
        suffix = self._determine_timestamp_suffix(document)
        safe_name = self._sanitize_name(document.name)
        return f"{safe_name}-{suffix}"

    @staticmethod
    def _determine_timestamp_suffix(document: CloudDocument) -> str:
        if document.modified_at is not None:
            timestamp = document.modified_at.astimezone(timezone.utc)
        else:
            timestamp = dt_module.now(timezone.utc)
        return timestamp.strftime("%Y%m%d%H%M%S")

    def _maybe_copy_pdf(self, basename: str, pdf_bytes: bytes | None) -> Optional[Path]:
        if self.asset_directory is None or pdf_bytes is None:
            return None
        pdf_path = self.asset_directory / f"{basename}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        return pdf_path


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
        asset_directory: str | Path | None = None,
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

        asset_path: Optional[Path] = None
        if asset_directory is not None:
            candidate = Path(asset_directory)
            if not candidate.is_absolute():
                candidate = (self.repository_path / candidate).resolve()
            else:
                candidate = candidate.expanduser().resolve()
            try:
                candidate.relative_to(self.repository_path)
            except ValueError as exc:  # pragma: no cover - defensive guard
                raise ValueError(
                    "The asset directory must reside within the Git repository"
                ) from exc
            asset_path = candidate

        super().__init__(resolved_directory, asset_directory=asset_path)

    def write(
        self,
        document: CloudDocument,
        markdown: str,
        *,
        pdf_bytes: bytes | None = None,
    ) -> Path:
        basename = self._build_basename(document)
        markdown_path = super().write(
            document, markdown, pdf_bytes=pdf_bytes, basename=basename
        )
        return markdown_path

    def _post_write(
        self,
        document: CloudDocument,
        markdown_path: Path,
        pdf_copy: Optional[Path],
    ) -> None:
        relative_markdown = markdown_path.relative_to(self.repository_path)
        self._run_git("add", str(relative_markdown))

        relative_pdf: Optional[Path] = None
        if pdf_copy is not None and pdf_copy.exists():
            relative_pdf = pdf_copy.relative_to(self.repository_path)
            self._run_git("add", str(relative_pdf))

        paths = [str(relative_markdown)]
        if relative_pdf is not None:
            paths.append(str(relative_pdf))

        if not self._has_any_staged_changes(paths):
            self._run_git("reset", "HEAD", "--", *paths)
            return

        commit_message = self.commit_message_template.format(
            document_name=document.name,
            document_identifier=document.identifier,
        )
        self._run_git("commit", "-m", commit_message)
        if self.push:
            self._run_git("push", self.remote, self.branch)

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

    def _has_any_staged_changes(self, paths: list[str]) -> bool:
        result = self._run_git(
            "diff",
            "--cached",
            "--quiet",
            "--",
            *paths,
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


class ObsidianVaultOutputHandler(GitMarkdownOutputHandler):
    """Synchronise Markdown and media files with an Obsidian Git vault."""

    def __init__(
        self,
        *,
        repository_path: str | Path,
        repository_url: str,
        directory: str | Path,
        media_directory: str | Path,
        branch: str = "main",
        remote: str = "origin",
        commit_message_template: str = (
            "A new file from you has been added: {markdown_path}"
        ),
        media_mode: str = "pdf",
        private_key_path: str | Path | None = None,
        known_hosts_path: str | Path | None = None,
        push: bool = True,
    ) -> None:
        self.repository_path = Path(repository_path).expanduser().resolve()
        self.repository_url = repository_url
        self.media_mode = media_mode.lower()
        if self.media_mode not in {"pdf", "png"}:
            raise ValueError("media_mode must be either 'pdf' or 'png'")

        self._png_optimizer = (
            self._select_png_optimizer() if self.media_mode == "png" else None
        )

        self.private_key_path = (
            Path(private_key_path).expanduser().resolve()
            if private_key_path is not None
            else None
        )
        if self.private_key_path and not self.private_key_path.exists():
            raise FileNotFoundError(
                f"SSH private key not found: {self.private_key_path}"
            )

        default_known_hosts = Path.home() / ".ssh" / "known_hosts"
        self.known_hosts_path = (
            Path(known_hosts_path).expanduser().resolve()
            if known_hosts_path is not None
            else default_known_hosts
        )
        self._git_env = os.environ.copy()
        self._configure_git_ssh_command()

        if not (self.repository_path / ".git").exists():
            self.repository_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_known_host()
            self._clone_repository(branch)
        else:
            # Ensure the known hosts entry exists so pushes do not prompt.
            self._ensure_known_host()

        super().__init__(
            repository_path=self.repository_path,
            directory=directory,
            branch=branch,
            remote=remote,
            commit_message_template=commit_message_template,
            push=push,
            asset_directory=None,
        )

        self.media_directory = self._resolve_within_repository(media_directory)
        self.media_directory.mkdir(parents=True, exist_ok=True)
        self.media_relative_directory = self.media_directory.relative_to(
            self.repository_path
        )
        self.markdown_relative_directory = self.directory.relative_to(
            self.repository_path
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write(
        self,
        document: CloudDocument,
        markdown: str,
        pdf_bytes: bytes | None = None,
    ) -> Path:
        if pdf_bytes is None:
            raise ValueError(
                "Obsidian output requires the original PDF bytes to manage media files"
            )

        base_stem = self._build_basename(document)

        markdown_path = self._unique_path(self.directory, base_stem, ".md")
        final_base = markdown_path.stem

        attachments: list[Path] = []
        if self.media_mode == "pdf":
            pdf_path = self._unique_path(self.media_directory, final_base, ".pdf")
            pdf_path.write_bytes(pdf_bytes)
            attachments.append(pdf_path)
            markdown = self._append_pdf_reference(markdown, pdf_path)
        else:
            image_paths = self._render_pdf_to_images(pdf_bytes, final_base)
            attachments.extend(image_paths)
            markdown = self._append_image_references(markdown, image_paths)

        markdown_path.write_text(markdown, encoding="utf-8")

        staged_paths = [markdown_path, *attachments]
        for path in staged_paths:
            relative = path.relative_to(self.repository_path)
            self._run_git("add", str(relative))

        if not self._has_any_staged_changes():
            self._reset_paths(staged_paths)
            return markdown_path

        commit_message = self.commit_message_template.format(
            document_name=document.name,
            document_identifier=document.identifier,
            markdown_path=str(
                markdown_path.relative_to(self.repository_path).as_posix()
            ),
        )

        if self.push:
            pull = self._run_git(
                "pull",
                self.remote,
                self.branch,
                "--ff-only",
                check=False,
            )
            if pull.returncode != 0:
                LOGGER.warning(
                    "Unable to fast-forward branch %s from %s before committing: %s",
                    self.branch,
                    self.remote,
                    pull.stderr.strip() or pull.stdout.strip(),
                )

        self._run_git("commit", "-m", commit_message)

        if self.push:
            self._run_git("push", self.remote, self.branch)

        return markdown_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _configure_git_ssh_command(self) -> None:
        ssh_parts = ["ssh"]
        if self.private_key_path is not None:
            ssh_parts.extend(["-i", str(self.private_key_path)])
        if self.known_hosts_path is not None:
            self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
            ssh_parts.extend(["-o", f"UserKnownHostsFile={self.known_hosts_path}"])
        ssh_parts.extend(["-o", "StrictHostKeyChecking=yes"])
        self._git_env["GIT_SSH_COMMAND"] = " ".join(shlex.quote(part) for part in ssh_parts)

    def _ensure_known_host(self) -> None:
        host = self._extract_ssh_host(self.repository_url)
        if not host or self.known_hosts_path is None:
            return

        probe = subprocess.run(
            [
                "ssh-keygen",
                "-F",
                host,
                "-f",
                str(self.known_hosts_path),
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return

        scan = subprocess.run(
            ["ssh-keyscan", "-H", host], capture_output=True, text=True
        )
        if scan.returncode == 0 and scan.stdout.strip():
            with self.known_hosts_path.open("a", encoding="utf-8") as handle:
                handle.write(scan.stdout)
        else:
            LOGGER.warning(
                "Unable to automatically record the SSH fingerprint for %s. "
                "Please run `ssh-keyscan -H %s >> %s` manually if authentication prompts appear.",
                host,
                host,
                self.known_hosts_path,
            )

    @staticmethod
    def _extract_ssh_host(remote_url: str) -> str | None:
        if remote_url.startswith("ssh://"):
            from urllib.parse import urlparse

            parsed = urlparse(remote_url)
            return parsed.hostname
        if "@" in remote_url and ":" in remote_url.split("@", 1)[1]:
            return remote_url.split("@", 1)[1].split(":", 1)[0]
        return None

    def _clone_repository(self, branch: str) -> None:
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--branch",
                    branch,
                    "--single-branch",
                    self.repository_url,
                    str(self.repository_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=self._git_env,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise RuntimeError(f"Failed to clone Obsidian repository: {message}") from exc

    def _resolve_within_repository(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        if not path.is_absolute():
            path = (self.repository_path / path).resolve()
        else:
            path = path.expanduser().resolve()
        try:
            path.relative_to(self.repository_path)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError("Paths must reside inside the Obsidian repository") from exc
        return path

    def _unique_path(self, directory: Path, stem: str, suffix: str) -> Path:
        counter = 0
        while True:
            candidate_stem = stem if counter == 0 else f"{stem}-{counter}"
            candidate = directory / f"{candidate_stem}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _append_pdf_reference(self, markdown: str, pdf_path: Path) -> str:
        rel_path = self._obsidian_path_for(pdf_path)
        parts = [markdown.rstrip(), "", f"[Reference PDF]({rel_path})", f"![[{rel_path}]]", ""]
        return "\n".join(parts)

    def _append_image_references(self, markdown: str, image_paths: list[Path]) -> str:
        if not image_paths:
            return markdown
        rel_paths = [self._obsidian_path_for(path) for path in image_paths]
        link_line = " ".join(
            f"[Page {index}]({path})" for index, path in enumerate(rel_paths, start=1)
        )
        parts = [markdown.rstrip(), ""]
        if link_line:
            parts.append(link_line)
        parts.extend(f"![[{path}]]" for path in rel_paths)
        parts.append("")
        return "\n".join(parts)

    def _obsidian_path_for(self, path: Path) -> str:
        return path.relative_to(self.repository_path).as_posix()

    def _render_pdf_to_images(self, pdf_bytes: bytes, base_stem: str) -> list[Path]:
        try:
            import pypdfium2 as pdfium
        except ModuleNotFoundError as exc:  # pragma: no cover - handled in runtime
            raise RuntimeError(
                "Rendering PDFs to images requires the 'pypdfium2' package"
            ) from exc

        pdf = pdfium.PdfDocument(pdf_bytes)
        images: list[Path] = []
        try:
            for index, page in enumerate(pdf, start=1):
                width, _ = page.get_size()
                scale = 1.0
                if width:
                    scale = 800.0 / width
                bitmap = page.render(scale=scale)
                try:
                    image_path = self._unique_path(
                        self.media_directory, f"{base_stem}-p{index:02d}", ".png"
                    )
                    from PIL import Image  # Imported lazily to keep Pillow optional at runtime

                    pil_image = bitmap.to_pil()
                    lanczos = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                    try:
                        image = pil_image
                        if image.mode != "L":
                            converted = image.convert("L")
                            image.close()
                            image = converted

                        target_width = 800
                        width_px, height_px = image.size
                        if width_px > target_width:
                            ratio = target_width / width_px
                            target_height = max(1, int(round(height_px * ratio)))
                            resized = image.resize(
                                (target_width, target_height), resample=lanczos
                            )
                            image.close()
                            image = resized

                        image.save(
                            image_path,
                            format="PNG",
                            optimize=True,
                            compress_level=9,
                        )
                    finally:
                        image.close()
                    self._optimize_png(image_path)
                    images.append(image_path)
                finally:
                    bitmap.close()
                page.close()
        finally:
            pdf.close()
        return images

    def _optimize_png(self, image_path: Path) -> None:
        if self._png_optimizer is None:
            return

        command, args = self._png_optimizer
        subprocess.run(
            [command, *args, str(image_path)],
            check=False,
            capture_output=True,
        )

    def _select_png_optimizer(self) -> tuple[str, list[str]] | None:
        optimizer = shutil.which("optipng")
        if optimizer:
            return optimizer, ["-quiet", "-o7"]

        zopfli = shutil.which("zopfli")
        if zopfli:
            return zopfli, ["--png", "--iterations=50"]

        return None

    def _has_any_staged_changes(self) -> bool:
        result = self._run_git("diff", "--cached", "--quiet", check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip())
        return result.returncode == 1

    def _reset_paths(self, paths: Iterable[Path]) -> None:
        relative_paths = [str(path.relative_to(self.repository_path)) for path in paths]
        if relative_paths:
            self._run_git("reset", "HEAD", "--", *relative_paths)

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
            env=self._git_env,
        )
        return completed


__all__ = [
    "GitMarkdownOutputHandler",
    "MarkdownOutputHandler",
    "ObsidianVaultOutputHandler",
]
