# Cloud Monitor PDF2MD

Cloud Monitor PDF2MD is a Python project that watches a configured folder in a
cloud storage service, identifies new PDF files, and converts them into clean
Markdown using a Large Language Model (LLM) vision endpoint. The first target
integration focuses on Google Drive, with the goal of supporting additional
providers in the future.

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

While the initial implementation is under development, the following modules
are expected to make up the core of the project:

1. **Configuration** – Define credentials, API keys, folder IDs, polling
   frequency, and prompt text.
2. **Cloud Connectors** – Implement Google Drive first, with an abstraction to
   allow additional providers.
3. **Processing State Tracker** – Persist the list of PDFs that have already
   been converted to avoid duplicate work.
4. **LLM Client** – Handle interactions with the chosen vision-capable model
   (e.g., Gemini) and encapsulate retry logic.
5. **Markdown Output Handler** – Save conversion results to the target folder
   and optionally organize assets such as extracted images.

## Getting Started

The project will require Python 3.10+ and the typical tooling for virtual
environments and dependency management. A high-level bootstrap process will be
documented as the code base evolves, but you can expect steps along the lines
of:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # (to be created)
```

You will also need to supply:

- Google Drive credentials with permission to read the monitored folder.
- API access credentials for the selected LLM service.
- Configuration values describing folder IDs, polling intervals, and local
  output paths.

## Status

This repository is in its initialization phase. Contributions that help define
the project structure, configuration management, and integrations are
welcome.

## License

This project is licensed under the terms of the MIT License. See the
[`LICENSE`](LICENSE) file for details.

