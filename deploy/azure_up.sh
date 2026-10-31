#!/usr/bin/env bash
# Switch on the Azure host and deploy Wardlight to it. Run from the Mac, with bash, from build/wardlight:
#   bash deploy/azure_up.sh
# Reads AZURE_VM_* from the workspace .env. Starts the VM (it bills while running), installs the runtime,
# copies the app, data and prebuilt store, installs a systemd unit bound to 127.0.0.1, and checks health.
# It stops before any Cloudflare change: the tunnel for the public hostname needs the owner's yes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"                       # build/wardlight
WS="$(cd "$HERE/../../../.." && pwd)"                          # workspace root (holds .env)
EVENT="$(cd "$HERE/../.." && pwd)"                             # Hackathons/anneru-2026
envval() { grep -E "^$1=" "$WS/.env" | head -1 | cut -d= -f2- | tr -d "\"' "; }
HOST="$(envval AZURE_VM_HOST)"; USER_="$(envval AZURE_VM_USER)"; KEY="$(envval AZURE_VM_SSH_KEY)"
RG="$(envval AZURE_RESOURCE_GROUP)"; VM="$(envval AZURE_VM_NAME)"
KEY="${KEY/#\~/$HOME}"
REMOTE="${USER_}@${HOST}"
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -i "$KEY")
STORE="${WARDLIGHT_STORE_DIR:?set WARDLIGHT_STORE_DIR to the folder holding the prebuilt store-*.sqlite and core-*.parquet}"

echo "== starting $VM"
az vm start -g "$RG" -n "$VM" -o none
for _ in $(seq 1 30); do "${SSH[@]}" "$REMOTE" true 2>/dev/null && break; sleep 5; done

echo "== runtime: uv and Python 3.12"
"${SSH[@]}" "$REMOTE" 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh;
  mkdir -p ~/wardlight/app/data/work ~/wardlight/data-local ~/wardlight/cache'

echo "== copy (tar over SSH keeps the file times the data version depends on)"
export COPYFILE_DISABLE=1
tar -C "$HERE" -czf - --exclude .venv --exclude node_modules --exclude web/screenshots --exclude .git \
  --exclude data/work --exclude .pytest_cache --exclude __pycache__ --exclude '*.egg-info' . \
  | "${SSH[@]}" "$REMOTE" 'tar -xzf - -C ~/wardlight/app 2>/dev/null'
tar -C "$HERE/data/work" -czf - facilities.parquet matches.parquet facility_results.parquet \
  facility_results.meta.json catchments.parquet catchments.meta.json nerc_rows.parquet nerc_shortfalls.parquet \
  nerc_raw.parquet match_report.json nerc_crops brief13 | "${SSH[@]}" "$REMOTE" 'tar -xzf - -C ~/wardlight/app/data/work 2>/dev/null'
tar -C "$EVENT/data-local" -czf - nasa-power naija-grid MANIFEST.md \
  | "${SSH[@]}" "$REMOTE" 'tar -xzf - -C ~/wardlight/data-local 2>/dev/null'
tar -C "$STORE" -cf - . | "${SSH[@]}" "$REMOTE" 'tar -xf - -C ~/wardlight/cache 2>/dev/null'

echo "== environment"
"${SSH[@]}" "$REMOTE" 'cd ~/wardlight && ~/.local/bin/uv venv -q --python 3.12 .venv 2>/dev/null || true;
  ~/.local/bin/uv pip install -q --python .venv/bin/python -e app'

echo "== service"
"${SSH[@]}" "$REMOTE" "sed -e 's#/home/ubuntu#/home/${USER_}#g' -e 's#^User=ubuntu#User=${USER_}#' \
  ~/wardlight/app/deploy/wardlight-vm.service > /tmp/wardlight.service && sudo cp /tmp/wardlight.service \
  /etc/systemd/system/wardlight.service && sudo systemctl daemon-reload && sudo systemctl enable --now wardlight"
for _ in $(seq 1 40); do "${SSH[@]}" "$REMOTE" 'curl -s -m 3 127.0.0.1:8422/api/health >/dev/null' && break; sleep 3; done
"${SSH[@]}" "$REMOTE" 'curl -s -m 5 127.0.0.1:8422/api/health | head -c 200; echo; free -m | sed -n 2p'

echo "== done. Next, with his yes: the Cloudflare tunnel for wardlight.aashanjaved.com, then T6 on the server."
