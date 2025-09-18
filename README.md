# Cloud Monitor PDF2MD

Cloud Monitor PDF2MD is a Python project that watches a configured folder in a
cloud storage service, identifies new PDF files, and converts them into clean
Markdown using a Large Language Model (LLM) vision endpoint. The first target
integration focuses on Google Drive, with the goal of supporting additional
providers in the future. The repository now ships with a fully functional
development pipeline that can monitor either Google Drive (when credentials are
available) or a local folder for PDFs.

## Repository Goals

- **Folder Monitoring** – Poll a designated Google Drive folder and maintain a
  record of processed vs. unprocessed documents.
- **PDF Extraction** – Discover new PDF files and forward their content to a
  configurable multimodal LLM endpoint (for example, `gemini-2.5-flash`).
- **Prompt-Driven Conversion** – Submit a reusable conversion prompt that asks
  the LLM to produce publication-quality Markdown from each PDF.
- **Result Management** – Store the generated Markdown documents in a local
  destination that can be synchronized with tools such as Obsidian.

## Planned Components

The core modules that make up the project include:

1. **Configuration** – Dataclasses and helpers that hydrate the runtime from a
   JSON configuration file.
2. **Cloud Connectors** – A pluggable abstraction with concrete
   implementations for Google Drive and the local filesystem.
3. **Processing State Tracker** – A JSON-backed tracker that stores processed
   document IDs and timestamps to avoid duplicate conversions.
4. **LLM Client** – A pluggable interface with an initial implementation that
   uses [`pypdf`](https://pypi.org/project/pypdf/) to extract text locally and
   emit Markdown. This can be swapped with a real LLM integration.
5. **Markdown Output Handler** – Writes conversion results to the destination
   folder and prepares a foundation for future asset management.

## Getting Started

The project requires Python 3.10+ and the typical tooling for virtual
environments and dependency management. A high-level bootstrap process looks
like the following:

```bash
python -m venv .venv
source .venv/bin/activate
pip install .[dev]
```

You will also need to supply:

- Google Drive credentials with permission to read the monitored folder (for
  the Google Drive connector).
- Configuration values describing folder IDs, polling intervals, and local
  output paths. A starter configuration can be found in
  [`example.config.json`](example.config.json).
- An optional prompt file that provides guidance to the downstream Markdown
  generator. A default prompt lives in [`prompts/default_prompt.txt`](prompts/default_prompt.txt).

## Running the Processor

The project exposes a console script and module entrypoint. Assuming a
configuration file similar to [`example.config.json`](example.config.json), run:

```bash
cloud-monitor-pdf2md --config example.config.json --once
```

or with Python directly:

```bash
python -m cloud_monitor_pdf2md --config example.config.json
```

Omit `--once` to continuously poll the configured provider using the
`poll_interval` defined in the configuration. On each iteration the processor
will:

1. Discover PDFs from the provider.
2. Skip files that already appear in the processing state file.
3. Convert new PDFs into Markdown using the configured LLM client.
4. Write Markdown files to the output directory.
5. Record the processed document in the state tracker.

## Status

This repository is in its initialization phase. Contributions that help define
the project structure, configuration management, and integrations are
welcome.

## License

This project is licensed under the terms of the MIT License. See the
[`LICENSE`](LICENSE) file for details.

