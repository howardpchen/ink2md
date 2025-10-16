# Ink2MD

Ink2MD is a Python project that watches a configured folder in a
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
  destination or commit the results to a Git repository that can be
  synchronized with tools such as Obsidian.

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
5. **Markdown Output Handlers** – Write conversion results either to the local
   filesystem or directly into a Git repository (committing changes and
   optionally pushing to a remote). Markdown filenames are emitted as
   `<sanitized-title>-<YYYYMMDDHHMMSS>.md`, which keeps chronological ordering
   predictable in Obsidian vaults and similar tools.

## Getting Started

The project requires Python 3.10+ and the typical tooling for virtual
environments and dependency management. A high-level bootstrap process looks
like the following:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # installs runtime + Gemini dependencies
pip install -e .[dev]            # optional: editable install with pytest
```

You will also need to supply:

- Google Drive OAuth credentials for the end user whose My Drive should be
  monitored. Provide the downloaded client secrets file via
  `google_drive.oauth_client_secrets_file` and choose a writable path for
  `google_drive.oauth_token_file` so the connector can cache the refreshable
  access token. Optional overrides are available for scopes if additional Drive
  permissions are required.
- Configuration values describing folder IDs, polling intervals, and local
  output paths. A starter configuration can be found in
  [`example.config.json`](example.config.json).
- An optional Git repository destination. Configure `output.provider` as
  `"git"`, set `output.directory` to the folder within the repository where
  Markdown should be written, and define the `output.git` block with repository
  path, branch, and commit settings.
- An optional prompt file that provides guidance to the downstream Markdown
  generator. A default prompt lives in [`prompts/default_prompt.txt`](prompts/default_prompt.txt).
  Tip: When you sync results to an Obsidian vault you can point
  `llm.prompt_path` at a dedicated note in that vault (for example
  `default-vault/ink2md prompt.md`) so the prompt stays version controlled and
  can be edited directly from Obsidian instead of logging into the server.
  This introduces a possible prompt-injection attack surface, so weigh the
  convenience against the risk and prefer a vetted local prompt file when
  security is the priority. The trade-off is that the file must keep the same
  name and location unless you update the configuration.
- LLM credentials when using a managed provider such as Gemini. Configure the
  `llm` block as described below and supply the API key via environment
  variables or a secrets manager—avoid committing secrets to git.
- Optional output settings:
  - `output.asset_directory` copies the original PDFs alongside the generated
    Markdown using the same timestamp suffix (for example,
    `Report-20240918103000.pdf`).
  - When targeting an Obsidian vault, adjust `output.obsidian.media_mode` to
    control how page assets are written: keep the default `"pdf"` to link back
    to the source document, or choose `"png"`/`"jpg"` to render 800px-wide,
    8-bit grayscale images (PNG output additionally runs through lossless
    optimizers when available). Combine with the optional
    `output.obsidian.media_invert` toggle to invert PNG or JPG pages before they
    are committed to the vault. Generated Markdown and attachments use the same
    `<name>-<timestamp>` naming pattern as filesystem output to simplify
    cross-target automation.

### Google Drive OAuth setup

To authorize access to an individual's My Drive, create a Google Cloud project,
enable the Drive API, and generate OAuth client credentials of type "Desktop
App." Download the resulting JSON secrets file and point
`google_drive.oauth_client_secrets_file` at its location. On the first run the
processor will open a local webserver and browser window to complete the OAuth
consent flow. In a headless session copy the printed authorization URL into a
browser, approve the requested scopes (the default is the read-only Drive scope),
and paste either the verification code or the full redirected URL back into the
running process. If you prefer to always perform the console-based exchange (for
example when SSH tunneling from a workstation), pass `--headless-token` on the
command line to force the console prompt and discard any cached OAuth token
before starting the flow. The connector extracts the authorization code, saves the
refreshable token to `google_drive.oauth_token_file`, and subsequent runs reuse
and transparently refresh that token so you do not need to reauthorize.

### Choosing an LLM provider

Add an `llm` block to your configuration to choose between built-in text
extraction and the Gemini integration:

```jsonc
"llm": {
  "provider": "gemini",
  "model": "models/gemini-2.5-flash",
  "api_key": "${GEMINI_API_KEY}",
  "prompt_path": "./prompts/default_prompt.txt",
  "temperature": 0.0
}
```

- `provider: "simple"` is the default and uses `pypdf` for basic text
  extraction.  Also helpful for testing during installation.
- `provider: "gemini"` uploads the original PDF to Gemini 2.5 Flash and returns
  a consolidated Markdown response that preserves handwriting and images. Set
  `GEMINI_API_KEY` in your environment before starting the processor.
- `prompt_path` is optional; when present the file contents are appended to the
  system instructions sent to the LLM.

### Using the example configuration

Copy [`example.config.json`](example.config.json) to a working file (for
example, `config.local.json`) and update the placeholders for Drive folder ID,
client secret locations, and the `llm` block. Remember to keep credentials and
token files outside version control.

## Running the Processor

The project exposes a console script and module entrypoint. Assuming a
configuration file similar to [`example.config.json`](example.config.json), run:

```bash
ink2md --config example.config.json --once
```

or with Python directly:

```bash
python -m ink2md --config example.config.json
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


## Service Deployment

### Automated Installer (Recommended)

Run the bundled installer from the repository root to provision the service,
virtual environment, configuration skeleton, and supporting timers:

```bash
sudo ./scripts/install_service.sh
```

Before running the installer ensure the host has the standard Python tooling
available—for most Debian/Ubuntu systems the following covers everything the
script expects: `sudo apt install python3 python3-venv python3-pip rsync`. The
installer copies the repository to `/opt/ink2md`, creates the
`ink2md` service account, bootstraps a virtual environment, renders the
systemd units, and enables the health check + retention timers. Re-run it after
pulling new changes to deploy upgrades. Override paths or toggle timers with
flags such as `--prefix`, `--config-dir`, `--skip-healthcheck`, and
`--skip-purge`.

When the script completes it prints any manual follow-up items (for example,
editing `/etc/ink2md/config.json` and `/etc/ink2md/env`). It
also creates `/etc/ink2md/credentials/client_secrets.json` as a
placeholder—replace it with your real Google Drive OAuth client JSON before
continuing. The installer generates an SSH deploy key at
`/etc/ink2md/ssh/id_ed25519` and seeds the `known_hosts` file based on
the configured repository URL; copy the printed public key into the Git host
that backs your Obsidian vault before starting the service. By default the
configuration writes Markdown to `/opt/ink2md/default-vault/inbox` and
attachments to `/opt/ink2md/default-vault/media`, with the repository
root at `/opt/ink2md/default-vault`. Clone or initialize your Obsidian
repository in that location and configure a Git identity for the
`ink2md` user, for example:

```bash
sudo -u ink2md git clone git@github.com:your-org/obsidian-vault.git \
  /opt/ink2md/default-vault
sudo -u ink2md git -C /opt/ink2md/default-vault config \
  user.name "Ink2MD Service"
sudo -u ink2md git -C /opt/ink2md/default-vault config \
  user.email "ops@example.com"
```

The service is already enabled and running; after you finish editing those
files apply the changes with:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ink2md.service
```

Use `systemctl status ink2md` or `journalctl -u
ink2md.service` to confirm the deployment is healthy.

Authorize Google Drive access once before leaving the service unattended. Run

```bash
sudo -u ink2md /opt/ink2md/.venv/bin/ink2md \
  --config /etc/ink2md/config.json --once
```

Follow the printed OAuth link in a browser, approve the consent screen, and
wait for the run to finish. When running on a headless host the command will
print the URL and, after you authorize in a separate browser, prompt for the
verification code—paste it back into the SSH session to complete the flow. Add
`--headless-token` if you want to force this console prompt and remove the
existing token cache before reauthorizing even when the host can launch a
browser. The resulting token is saved to
`/var/lib/ink2md/google_drive_token.json`; subsequent service runs reuse it
automatically.

The installer also updates `llm.prompt_path` to point at
`/opt/ink2md/prompts/default_prompt.txt`, and rewrites the Obsidian Git
settings to use the generated deploy key and known-hosts file under
`/etc/ink2md/ssh`. If you provide a custom prompt or different Git
credentials, store them somewhere readable by `ink2md` and adjust the
config to match. Tip: You can target a note inside the Obsidian vault
itself—create a page such as `default-vault/ink2md prompt.md`, set
`llm.prompt_path` to that file, and edit the prompt from Obsidian while keeping
it version controlled. This convenience opens the door to prompt-injection if
the note is tampered with, so adopt it only when the risk is acceptable and
fall back to a vetted local prompt file for the safest posture. Keep the
filename and path stable or update the configuration whenever you move it.

### Manual Installation

To run the processor autonomously on a Linux host without the installer,
provision the provided systemd unit and supporting environment file. The unit
templates include `${...}` placeholders that match the installer defaults—edit
them to reflect your target paths before copying them into place.


### Prepare the Host

1. Create a dedicated service account, for example `sudo useradd --system --home /var/lib/ink2md --shell /usr/sbin/nologin ink2md`.
2. Check out the repository to `/opt/ink2md` (or another root owned by the service account) and install dependencies into `/opt/ink2md/.venv`.
3. Create writable directories for runtime state, logs, and temporary files such as `/var/lib/ink2md` and `/var/tmp/ink2md`. Grant ownership to the service user.

### Install the Service

1. Copy `deploy/systemd/ink2md.service` to `/etc/systemd/system/` and adjust the service user, working directory, and virtual environment paths to match your host.
2. Copy `deploy/systemd/ink2md.env` to `/etc/ink2md/env`,
   populate the credential paths and API keys, and set permissions so only the
   service account can read the file (for example `chmod 640` and `chown ink2md:ink2md`).
3. Place your runtime configuration (for example `config.json`) under
   `/etc/ink2md/` or another directory that the service account can access.
4. Reload systemd with `sudo systemctl daemon-reload`, enable the unit with
   `sudo systemctl enable --now ink2md`, and inspect service status
   with `systemctl status ink2md`.

### Monitoring

The script `scripts/check_processor_health.py` summarizes the latest processed
document and optionally tails recent journal errors. Integrate it with your
monitoring stack or a systemd timer to ensure the pipeline keeps up with new
documents:

```bash
./scripts/check_processor_health.py --state-file /var/lib/ink2md/state/processed.json \
  --max-age 180 --journal-unit ink2md
```

For automated checks, install the provided timer template:

1. Copy `deploy/systemd/ink2md-healthcheck.service` and `.timer`
   to `/etc/systemd/system/`.
2. Adjust the script path, state file, and thresholds in the service unit.
3. Enable the timer with `sudo systemctl enable --now ink2md-healthcheck.timer`.

### Rolling Purge

Use `scripts/purge_output.py` to prune generated Markdown and attachments while
retaining the most recent 30 days. Schedule it via cron or a systemd timer
alongside the service:

```bash
./scripts/purge_output.py /var/lib/ink2md/output --days 30 --recursive --remove-empty-dirs
```

Timer templates in `deploy/systemd/ink2md-purge.service` and
`.timer` show how to run the purge job daily with a dry-run warning before
permanent deletion. Copy them into place and enable the timer to keep the output
volume bounded.

Refer to `deploy/README.md` for annotated installation commands and file descriptions.
