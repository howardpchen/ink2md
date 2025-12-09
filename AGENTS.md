# Repository Guidelines

## Project Structure & Module Organization
Runtime code lives under `ink2md/`, with connectors in `connectors/`, the LLM adapters in `llm/`, orchestration helpers in `processor.py`, and output/state management in `output.py` and `state.py`. CLI entry points are exposed via `cli.py` and `__main__.py`. Tests reside in `tests/`, while reusable prompts live in `prompts/`. Use `example.config.json` as a starting template when wiring up new environments; it demonstrates the agentic router with Markdown output to one Google Drive folder and mindmap output to another (both optional local copies).

## Build, Test, and Development Commands
Create an isolated environment with `python -m venv .venv` and install dependencies using `pip install -e .[dev]`. Run the processor locally with `ink2md --config example.config.json --once` for a single polling cycle, or drop `--once` to watch continuously. Invoke `python -m ink2md --config <path>` when you need to experiment against alternate configs. Use the `--headless-token` CLI flag when you must force the console-based Google Drive OAuth flow and refresh the cached token.

## Coding Style & Naming Conventions
Follow PEP 8 defaults: four-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes and dataclasses. Keep modules type-hinted, prefer `Path` objects for filesystem input, and stick with double-quoted strings as used throughout the package. Add concise docstrings to public classes and methods when behavior is non-obvious.

## Testing Guidelines
Pytest is the supported framework. Run `pytest` at the repository root before sending changes, or narrow to targeted suites with commands like `pytest tests/test_processor_google_drive.py -k state`. When extending connectors or processors, add fixtures that exercise new configuration paths and ensure state files and temporary directories are covered by tests.

## Commit & Pull Request Guidelines
Commits in the history use short, imperative summaries (for example, "Simplify Google Drive auth to OAuth"). Mirror that style, keep subject lines under 72 characters, and include contextual details in the body when the change is complex. Pull requests should describe the scenario, note configuration or secret handling implications, list manual or automated test commands, and attach screenshots or logs when they clarify behavior.

## Configuration & Secrets
Never commit real OAuth secrets or tokens. Reference them via absolute paths in your config and store sensitive JSON files outside the repository. Token caches default to `<client_secrets_stem>_token.json` beside the secrets file; override the path only when policy requires it. For Gemini-based conversions supply the API key through an environment variable and reference it from `llm.api_key`; the client uploads each PDF so even handwriting and image-only pages are preserved in the generated Markdown. Document any new required keys (for example, `markdown.google_drive.folder_id` and `mindmap.google_drive.folder_id`) in `example.config.json` so downstream users can replicate the setup safely.

When targeting Obsidian, remember that the vault handler performs a fast-forward pull before every write and aborts if the repository has uncommitted changes. Keep the vault clone clean (commit or stash manual edits) and configure the remote to accept fast-forward pushes so the service can update the branch safely.
