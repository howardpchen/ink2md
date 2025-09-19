#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="cloud-monitor-pdf2md"
INSTALL_PREFIX="/opt/pdf2md-monitor"
CONFIG_DIR="/etc/pdf2md-monitor"
CONFIG_PATH=""
ENV_FILE=""
STATE_DIR="/var/lib/pdf2md-monitor"
OUTPUT_DIR="/var/lib/pdf2md-monitor/output"
SERVICE_USER="pdf2md-monitor"
SERVICE_GROUP=""
RETENTION_DAYS="30"
HEALTHCHECK_MAX_AGE="180"
SKIP_HEALTHCHECK=0
SKIP_PURGE=0
RESTART_SERVICE=1
PYTHON_BIN="python3"
WAS_ACTIVE=0
POST_INSTALL_NOTES=()

add_post_install_note() {
  local note existing
  note="$1"
  for existing in "${POST_INSTALL_NOTES[@]}"; do
    if [[ "$existing" == "$note" ]]; then
      return
    fi
  done
  POST_INSTALL_NOTES+=("$note")
}

usage() {
  cat <<USAGE
Usage: sudo ./scripts/install_service.sh [options]

Options:
  --prefix PATH             Install directory for application files (default: /opt/pdf2md-monitor)
  --config-dir PATH         Directory for configuration artifacts (default: /etc/pdf2md-monitor)
  --config-path PATH        Runtime configuration JSON location (default: <config-dir>/config.json)
  --env-file PATH           Environment file location (default: <config-dir>/env)
  --state-dir PATH          Directory for persistent state (default: /var/lib/pdf2md-monitor)
  --output-dir PATH         Directory for generated Markdown/assets (default: /var/lib/pdf2md-monitor/output)
  --user NAME               Service account user (default: pdf2md-monitor)
  --group NAME              Service account group (default: match user)
  --retention-days N        Retention window for purge timer (default: 30)
  --healthcheck-max-age N   Max minutes since last processed doc before alert (default: 180)
  --skip-healthcheck        Do not install or enable the healthcheck timer
  --skip-purge              Do not install or enable the purge timer
  --no-restart              Install units but do not start/restart the service immediately
  --python PATH             Python interpreter for virtualenv creation (default: python3)
  --help                    Show this help message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      INSTALL_PREFIX="$2"; shift 2 ;;
    --config-dir)
      CONFIG_DIR="$2"; shift 2 ;;
    --config-path)
      CONFIG_PATH="$2"; shift 2 ;;
    --env-file)
      ENV_FILE="$2"; shift 2 ;;
    --state-dir)
      STATE_DIR="$2"; shift 2 ;;
    --output-dir)
      OUTPUT_DIR="$2"; shift 2 ;;
    --user)
      SERVICE_USER="$2"; shift 2 ;;
    --group)
      SERVICE_GROUP="$2"; shift 2 ;;
    --retention-days)
      RETENTION_DAYS="$2"; shift 2 ;;
    --healthcheck-max-age)
      HEALTHCHECK_MAX_AGE="$2"; shift 2 ;;
    --skip-healthcheck)
      SKIP_HEALTHCHECK=1; shift ;;
    --skip-purge)
      SKIP_PURGE=1; shift ;;
    --no-restart)
      RESTART_SERVICE=0; shift ;;
    --python)
      PYTHON_BIN="$2"; shift 2 ;;
    --help)
      usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1 ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "This script must be run as root." >&2
  exit 1
fi

if [[ -z "$SERVICE_GROUP" ]]; then
  SERVICE_GROUP="$SERVICE_USER"
fi

if [[ -z "$CONFIG_PATH" ]]; then
  CONFIG_PATH="${CONFIG_DIR%/}/config.json"
fi

if [[ -z "$ENV_FILE" ]]; then
  ENV_FILE="${CONFIG_DIR%/}/env"
fi

STATE_DIR="${STATE_DIR%/}"
OUTPUT_DIR="${OUTPUT_DIR%/}"
INSTALL_PREFIX="${INSTALL_PREFIX%/}"
CONFIG_DIR="${CONFIG_DIR%/}"
CONFIG_PATH="${CONFIG_PATH%/}"
ENV_FILE="${ENV_FILE%/}"
SERVICE_HOME="$STATE_DIR"
STATE_DATA_DIR="${STATE_DIR}/state"
ASSET_DIR="${OUTPUT_DIR}/media"
STATE_FILE="${STATE_DATA_DIR}/processed.json"
CREDENTIALS_DIR="${CONFIG_DIR}/credentials"
CLIENT_SECRETS_PATH="${CREDENTIALS_DIR}/client_secrets.json"
GOOGLE_TOKEN_PATH="${STATE_DIR}/google_drive_token.json"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "Missing Python interpreter: $PYTHON_BIN" >&2; exit 1; }
PYTHON_BIN=$(command -v "$PYTHON_BIN")
command -v systemctl >/dev/null 2>&1 || { echo "systemctl is required." >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 1; }
command -v runuser >/dev/null 2>&1 || { echo "runuser is required." >&2; exit 1; }
if ! "$PYTHON_BIN" -c "import ensurepip" >/dev/null 2>&1; then
  echo "The interpreter at $PYTHON_BIN is missing the standard ensurepip module." >&2
  echo "Install the python3-venv package (e.g. 'apt install python3-venv') or rerun with --python pointing to an interpreter that bundles ensurepip." >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

create_group_and_user() {
  if ! getent group "$SERVICE_GROUP" >/dev/null; then
    echo "Creating group $SERVICE_GROUP"
    groupadd --system "$SERVICE_GROUP"
  fi
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Creating user $SERVICE_USER"
    useradd --system --gid "$SERVICE_GROUP" --home-dir "$SERVICE_HOME" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  ensure_user_properties
}

ensure_user_properties() {
  local passwd_entry current_group current_home current_shell
  if ! passwd_entry=$(getent passwd "$SERVICE_USER"); then
    return
  fi

  current_group=$(id -gn "$SERVICE_USER")
  if [[ "$current_group" != "$SERVICE_GROUP" ]]; then
    echo "Adjusting primary group for $SERVICE_USER"
    usermod -g "$SERVICE_GROUP" "$SERVICE_USER"
  fi

  current_home=$(echo "$passwd_entry" | cut -d: -f6)
  if [[ "$current_home" != "$SERVICE_HOME" ]]; then
    echo "Updating home directory for $SERVICE_USER to $SERVICE_HOME"
    usermod -d "$SERVICE_HOME" "$SERVICE_USER"
    install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$SERVICE_HOME"
  fi

  current_shell=$(echo "$passwd_entry" | cut -d: -f7)
  if [[ "$current_shell" != "/usr/sbin/nologin" ]]; then
    echo "Setting shell for $SERVICE_USER to /usr/sbin/nologin"
    usermod -s /usr/sbin/nologin "$SERVICE_USER"
  fi

  passwd -l "$SERVICE_USER" >/dev/null 2>&1 || true
}

ensure_directories() {
  local path
  for path in "$INSTALL_PREFIX" "$STATE_DIR" "$STATE_DATA_DIR" "$OUTPUT_DIR" "$ASSET_DIR" "$CONFIG_DIR" "$CREDENTIALS_DIR" /var/tmp/pdf2md-monitor; do
    if [[ -e "$path" && ! -d "$path" ]]; then
      echo "Refusing to use existing non-directory path: $path" >&2
      exit 1
    fi
  done
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$INSTALL_PREFIX"
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$STATE_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$STATE_DATA_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$OUTPUT_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 "$ASSET_DIR"
  install -d -o root -g "$SERVICE_GROUP" -m 750 "$CONFIG_DIR"
  install -d -o root -g "$SERVICE_GROUP" -m 750 "$CREDENTIALS_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 750 /var/tmp/pdf2md-monitor
}

maybe_stop_service() {
  if systemctl cat "${SERVICE_NAME}.service" >/dev/null 2>&1; then
    if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
      echo "Stopping existing ${SERVICE_NAME}.service"
      systemctl stop "${SERVICE_NAME}.service"
      WAS_ACTIVE=1
    fi
  fi
}

sync_repository() {
  echo "Syncing repository to $INSTALL_PREFIX"
  rsync -a --delete \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --chown="${SERVICE_USER}:${SERVICE_GROUP}" \
    "$REPO_ROOT"/ "$INSTALL_PREFIX"/
}

setup_virtualenv() {
  local venv_path="$INSTALL_PREFIX/.venv"
  local venv_python="$venv_path/bin/python"

  if [[ ! -x "$venv_python" ]]; then
    echo "Creating virtualenv"
    runuser -u "$SERVICE_USER" -- "$PYTHON_BIN" -m venv "$venv_path"
  fi

  if [[ ! -x "$venv_python" ]]; then
    echo "Failed to create virtualenv at $venv_path" >&2
    exit 1
  fi

  if ! runuser -u "$SERVICE_USER" -- "$venv_python" -m pip --version >/dev/null 2>&1; then
    echo "Bootstrapping pip inside virtualenv"
    runuser -u "$SERVICE_USER" -- "$venv_python" -m ensurepip --upgrade
  fi

  echo "Installing Python dependencies"
  runuser -u "$SERVICE_USER" -- "$venv_python" -m pip install --upgrade pip wheel setuptools
  runuser -u "$SERVICE_USER" -- "$venv_python" -m pip install -r "$INSTALL_PREFIX/requirements.txt"
  runuser -u "$SERVICE_USER" -- "$venv_python" -m pip install -e "$INSTALL_PREFIX"
}

update_config_paths() {
  local config_path="$1"
  local state_file="$2"
  local output_dir="$3"
  local asset_dir="$4"
  local client_secrets="$5"
  local token_path="$6"
  local install_prefix="$7"

  "$PYTHON_BIN" - <<'PY' "$config_path" "$state_file" "$output_dir" "$asset_dir" "$client_secrets" "$token_path" "$INSTALL_PREFIX"
import json
import sys
from pathlib import Path

config_path, state_file, output_dir, asset_dir, client_secrets, token_path, install_prefix = sys.argv[1:]
config_path = Path(config_path)

if not config_path.exists():
    sys.exit(0)

try:
    data = json.loads(config_path.read_text(encoding="utf-8"))
except json.JSONDecodeError:
    print(f"Warning: unable to update {config_path} (invalid JSON)", file=sys.stderr)
    sys.exit(0)

state_section = data.setdefault("state", {})
if state_section.get("path") in {None, "./state/processed.json"}:
    state_section["path"] = state_file

output_section = data.setdefault("output", {})
directory_value = output_section.get("directory")
if directory_value in {None, "inbox", "./output"}:
    output_section["directory"] = output_dir

asset_value = output_section.get("asset_directory")
if asset_value in {None, "media", "./output/media"}:
    output_section["asset_directory"] = asset_dir

gd_section = data.setdefault("google_drive", {})
client_value = gd_section.get("oauth_client_secrets_file")
if client_value in {None, "./credentials/client_secret.json", "credentials/client_secret.json"}:
    gd_section["oauth_client_secrets_file"] = client_secrets

token_value = gd_section.get("oauth_token_file")
if token_value in {None, "./credentials/client_secret_token.json", "credentials/client_secret_token.json"}:
    gd_section["oauth_token_file"] = token_path

llm_section = data.setdefault("llm", {})
prompt_value = llm_section.get("prompt_path")
default_prompts = {None, "./prompts/default_prompt.txt", "prompts/default_prompt.txt"}
if prompt_value in default_prompts:
    prompt_path = Path(install_prefix) / "prompts" / "default_prompt.txt"
    llm_section["prompt_path"] = str(prompt_path)

config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

ensure_config_and_env() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "Copying example configuration to $CONFIG_PATH"
    install -D -o root -g "$SERVICE_GROUP" -m 640 "$REPO_ROOT/example.config.json" "$CONFIG_PATH"
    add_post_install_note "Edit $CONFIG_PATH with environment-specific settings before running in production."
  else
    chgrp "$SERVICE_GROUP" "$CONFIG_PATH" || true
    chmod 640 "$CONFIG_PATH" || true
    add_post_install_note "Review $CONFIG_PATH to confirm environment-specific settings are current."
  fi
  update_config_paths "$CONFIG_PATH" "$STATE_FILE" "$OUTPUT_DIR" "$ASSET_DIR" "$CLIENT_SECRETS_PATH" "$GOOGLE_TOKEN_PATH" "$INSTALL_PREFIX"
  chgrp "$SERVICE_GROUP" "$CONFIG_PATH" || true
  chmod 640 "$CONFIG_PATH" || true
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Provisioning environment file at $ENV_FILE"
    install -D -o root -g "$SERVICE_GROUP" -m 640 "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md.env" "$ENV_FILE"
    add_post_install_note "Populate API keys, secrets, and credential paths in $ENV_FILE."
  else
    chgrp "$SERVICE_GROUP" "$ENV_FILE" || true
    chmod 640 "$ENV_FILE" || true
    add_post_install_note "Verify $ENV_FILE contains current API keys and secret paths."
  fi
  ensure_credentials_placeholder
  add_post_install_note "Perform the Google Drive OAuth bootstrap once with: sudo -u ${SERVICE_USER} ${INSTALL_PREFIX}/.venv/bin/cloud-monitor-pdf2md --config ${CONFIG_PATH} --once"
}

ensure_credentials_placeholder() {
  local message
  message='{
  "_comment": "Replace this placeholder with your Google Drive client secrets JSON."
}
'
  if [[ ! -f "$CLIENT_SECRETS_PATH" ]]; then
    echo "Creating placeholder Google Drive client secrets at $CLIENT_SECRETS_PATH"
    printf "%s" "$message" | install -D -o root -g "$SERVICE_GROUP" -m 640 /dev/stdin "$CLIENT_SECRETS_PATH"
  fi
  add_post_install_note "Replace ${CLIENT_SECRETS_PATH} with the actual Google Drive client secrets JSON."
}

ensure_state_file() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "Creating initial state file at $STATE_FILE"
    cat > "$STATE_FILE" <<'STATE'
{
  "processed": {}
}
STATE
  fi
  chown "$SERVICE_USER":"$SERVICE_GROUP" "$STATE_FILE" || true
  chmod 640 "$STATE_FILE" || true
}

print_post_install_notes() {
  if [[ ${#POST_INSTALL_NOTES[@]} -eq 0 ]]; then
    return
  fi
  echo
  echo "IMPORTANT: Review the following items before considering the deployment complete:"
  local note
  for note in "${POST_INSTALL_NOTES[@]}"; do
    echo "  - $note"
  done
}

render_template() {
  local template="$1"
  local destination="$2"
  "$PYTHON_BIN" - "$template" "$destination" <<'PY'
import os
import sys

template_path, destination_path = sys.argv[1:]
keys = [
    "SERVICE_NAME",
    "SERVICE_USER",
    "SERVICE_GROUP",
    "INSTALL_PREFIX",
    "CONFIG_PATH",
    "ENV_FILE",
    "STATE_FILE",
    "OUTPUT_DIR",
    "RETENTION_DAYS",
    "HEALTHCHECK_MAX_AGE",
]
data = open(template_path, "r", encoding="utf-8").read()
for key in keys:
    placeholder = "${" + key + "}"
    if placeholder in data:
        value = os.environ.get(key, "")
        data = data.replace(placeholder, value)
with open(destination_path, "w", encoding="utf-8") as handle:
    handle.write(data)
PY
}

install_systemd_units() {
  export SERVICE_NAME SERVICE_USER SERVICE_GROUP INSTALL_PREFIX CONFIG_PATH ENV_FILE STATE_FILE OUTPUT_DIR RETENTION_DAYS HEALTHCHECK_MAX_AGE
  local tmp
  tmp=$(mktemp)
  render_template "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md.service" "$tmp"
  install -o root -g root -m 644 "$tmp" "/etc/systemd/system/${SERVICE_NAME}.service"
  rm -f "$tmp"

  if [[ $SKIP_HEALTHCHECK -eq 0 ]]; then
    tmp=$(mktemp)
    render_template "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md-healthcheck.service" "$tmp"
    install -o root -g root -m 644 "$tmp" "/etc/systemd/system/${SERVICE_NAME}-healthcheck.service"
    rm -f "$tmp"
    tmp=$(mktemp)
    render_template "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md-healthcheck.timer" "$tmp"
    install -o root -g root -m 644 "$tmp" "/etc/systemd/system/${SERVICE_NAME}-healthcheck.timer"
    rm -f "$tmp"
  fi

  if [[ $SKIP_PURGE -eq 0 ]]; then
    tmp=$(mktemp)
    render_template "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md-purge.service" "$tmp"
    install -o root -g root -m 644 "$tmp" "/etc/systemd/system/${SERVICE_NAME}-purge.service"
    rm -f "$tmp"
    tmp=$(mktemp)
    render_template "$REPO_ROOT/deploy/systemd/cloud-monitor-pdf2md-purge.timer" "$tmp"
    install -o root -g root -m 644 "$tmp" "/etc/systemd/system/${SERVICE_NAME}-purge.timer"
    rm -f "$tmp"
  fi
}

reload_and_enable_units() {
  systemctl daemon-reload
  if [[ $RESTART_SERVICE -eq 1 ]]; then
    systemctl enable --now "${SERVICE_NAME}.service"
  else
    systemctl enable "${SERVICE_NAME}.service"
    if [[ $WAS_ACTIVE -eq 1 ]]; then
      echo "Service was previously running; start it manually when ready."
    fi
  fi
  if [[ $SKIP_HEALTHCHECK -eq 0 ]]; then
    systemctl enable --now "${SERVICE_NAME}-healthcheck.timer"
  else
    systemctl disable "${SERVICE_NAME}-healthcheck.timer" >/dev/null 2>&1 || true
  fi
  if [[ $SKIP_PURGE -eq 0 ]]; then
    systemctl enable --now "${SERVICE_NAME}-purge.timer"
  else
    systemctl disable "${SERVICE_NAME}-purge.timer" >/dev/null 2>&1 || true
  fi
}

main() {
  create_group_and_user
  ensure_directories
  maybe_stop_service
  sync_repository
  setup_virtualenv
  ensure_config_and_env
  ensure_state_file
  install_systemd_units
  reload_and_enable_units
  echo "Installation complete."
  echo "Service file: /etc/systemd/system/${SERVICE_NAME}.service"
  echo "Update configuration: ${CONFIG_PATH}"
  echo "Environment secrets: ${ENV_FILE}"
  echo "State file: ${STATE_FILE}"
  print_post_install_notes
}

main
