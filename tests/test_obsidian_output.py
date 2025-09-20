"""Tests for the Obsidian Git output handler."""

from __future__ import annotations

import io
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pypdf import PdfWriter

from ink2md.connectors.base import CloudDocument
from ink2md.output import ObsidianVaultOutputHandler


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


def _seed_commit(path: Path, filename: str) -> None:
    target = path / filename
    target.write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True)


def _configure_clone_identity(path: Path) -> None:
    subprocess.run(["git", "config", "user.email", "vault@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Vault"], cwd=path, check=True)


def test_obsidian_handler_copies_pdf_and_appends_reference(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    remote.mkdir()
    _init_git_repository(remote)
    _seed_commit(remote, "README.md")

    vault_path = tmp_path / "vault"
    handler = ObsidianVaultOutputHandler(
        repository_path=vault_path,
        repository_url=str(remote),
        directory="notes",
        media_directory="media",
        push=False,
    )
    _configure_clone_identity(vault_path)

    timestamp = datetime(2024, 9, 18, 10, 30, tzinfo=timezone.utc)
    document = CloudDocument(
        identifier="doc-1",
        name="Monthly Report",
        modified_at=timestamp,
    )
    markdown = "# Monthly Report\n\nSummary"
    pdf_bytes = b"%PDF-1.4\n%"

    output_path = handler.write(document, markdown, pdf_bytes=pdf_bytes)

    expected_basename = "Monthly-Report-20240918103000"
    assert output_path.exists()
    assert output_path.parent == vault_path / "notes"
    assert output_path.stem == expected_basename

    pdf_files = list((vault_path / "media").glob("*.pdf"))
    assert len(pdf_files) == 1
    pdf_file = pdf_files[0]
    assert pdf_file.read_bytes() == pdf_bytes
    assert pdf_file.stem == expected_basename

    rendered = output_path.read_text(encoding="utf-8")
    pdf_relative = pdf_file.relative_to(vault_path).as_posix()
    assert f"[Reference PDF]({pdf_relative})" in rendered
    assert f"![[{pdf_relative}]]" in rendered

    log_output = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=vault_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_markdown = output_path.relative_to(vault_path).as_posix()
    assert log_output == f"A new file from you has been added: {expected_markdown}"

    history = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=vault_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert history == "2"


def test_obsidian_handler_renders_jpgs_for_jpg_mode(tmp_path: Path) -> None:
    pytest.importorskip(
        "pypdfium2", reason="pypdfium2 is required to render pages into JPEG files"
    )
    Image = pytest.importorskip("PIL.Image", reason="Pillow is required to inspect JPEGs")

    remote = tmp_path / "remote"
    remote.mkdir()
    _init_git_repository(remote)
    _seed_commit(remote, "README.md")

    vault_path = tmp_path / "vault"
    handler = ObsidianVaultOutputHandler(
        repository_path=vault_path,
        repository_url=str(remote),
        directory="notes",
        media_directory="assets",
        media_mode="jpg",
        push=False,
    )
    _configure_clone_identity(vault_path)

    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    pdf_writer.write(buffer)
    pdf_bytes = buffer.getvalue()

    timestamp = datetime(2024, 9, 18, 10, 30, tzinfo=timezone.utc)
    document = CloudDocument(
        identifier="doc-3",
        name="Project Scope",
        modified_at=timestamp,
    )

    markdown = "# Scope\n"
    handler.write(document, markdown, pdf_bytes=pdf_bytes)

    image_files = sorted((vault_path / "assets").glob("*.jpg"))
    assert len(image_files) == 1
    image_file = image_files[0]
    assert image_file.stem == "Project-Scope-20240918103000-p01"

    with Image.open(image_file) as img:
        assert img.format == "JPEG"
        assert img.mode == "L"


def test_obsidian_handler_inverts_grayscale_when_requested(tmp_path: Path) -> None:
    pytest.importorskip(
        "pypdfium2", reason="pypdfium2 is required to render pages into PNG files"
    )
    Image = pytest.importorskip("PIL.Image", reason="Pillow is required to inspect PNGs")

    remote = tmp_path / "remote"
    remote.mkdir()
    _init_git_repository(remote)
    _seed_commit(remote, "README.md")

    vault_path = tmp_path / "vault"
    handler = ObsidianVaultOutputHandler(
        repository_path=vault_path,
        repository_url=str(remote),
        directory="notes",
        media_directory="assets",
        media_mode="png",
        media_invert=True,
        push=False,
    )
    _configure_clone_identity(vault_path)

    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    pdf_writer.write(buffer)
    pdf_bytes = buffer.getvalue()

    timestamp = datetime(2024, 9, 18, 10, 30, tzinfo=timezone.utc)
    document = CloudDocument(
        identifier="doc-4",
        name="Inverted",
        modified_at=timestamp,
    )

    markdown = "# Inverted\n"
    handler.write(document, markdown, pdf_bytes=pdf_bytes)

    image_files = list((vault_path / "assets").glob("*.png"))
    assert len(image_files) == 1
    with Image.open(image_files[0]) as img:
        minima, maxima = img.getextrema()
        assert maxima < 128
        assert minima == maxima


def test_obsidian_handler_rejects_media_invert_for_pdf_mode(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    remote.mkdir()
    _init_git_repository(remote)
    _seed_commit(remote, "README.md")

    vault_path = tmp_path / "vault"
    with pytest.raises(ValueError, match="media_invert is only supported"):
        ObsidianVaultOutputHandler(
            repository_path=vault_path,
            repository_url=str(remote),
            directory="notes",
            media_directory="assets",
            media_mode="pdf",
            media_invert=True,
            push=False,
        )


def test_obsidian_handler_renders_pngs_for_png_mode(tmp_path: Path) -> None:
    pytest.importorskip(
        "pypdfium2", reason="pypdfium2 is required to render pages into PNG files"
    )
    Image = pytest.importorskip("PIL.Image", reason="Pillow is required to inspect PNGs")

    remote = tmp_path / "remote"
    remote.mkdir()
    _init_git_repository(remote)
    _seed_commit(remote, "README.md")

    vault_path = tmp_path / "vault"
    handler = ObsidianVaultOutputHandler(
        repository_path=vault_path,
        repository_url=str(remote),
        directory="notes",
        media_directory="assets",
        media_mode="png",
        push=False,
    )
    _configure_clone_identity(vault_path)

    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    pdf_writer.write(buffer)
    pdf_bytes = buffer.getvalue()

    timestamp = datetime(2024, 9, 18, 10, 30, tzinfo=timezone.utc)
    document = CloudDocument(
        identifier="doc-2",
        name="Project Scope",
        modified_at=timestamp,
    )
    markdown = "# Scope\n"

    output_path = handler.write(document, markdown, pdf_bytes=pdf_bytes)

    expected_basename = "Project-Scope-20240918103000"
    assert output_path.exists()
    assert output_path.parent == vault_path / "notes"
    assert output_path.stem == expected_basename

    image_files = sorted((vault_path / "assets").glob("*.png"))
    assert len(image_files) == 1
    image_file = image_files[0]
    assert image_file.stem == f"{expected_basename}-p01"

    with Image.open(image_file) as img:
        assert img.width == 800
        assert img.mode == "L"

    rendered = output_path.read_text(encoding="utf-8")
    image_relative = image_file.relative_to(vault_path).as_posix()
    assert image_relative in rendered
    assert f"![[{image_relative}]]" in rendered

    history = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=vault_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert history == "2"
