# Sunday runbook: Wardlight on the Azure host

For Sunday 1 Nov 2026, morning (PKT). The submission deadline is 10:00 PM PKT; he uploads by 8:00 PM PKT. Winners are
announced Sat 7 Nov, 10:00 PM PKT, so the host stays on until then and is deallocated after.

Three steps need **his yes** before they run: the public hostname (Cloudflare tunnel), the live model (Nebius key on
the server), and anything that spends beyond the VM itself. Everything else here the main session can run.

Data version for every deliverable: **8606a23e82d2**. If any check below shows another version, stop: the deck, films
and one-pager quote numbers from that version.

All commands run from `build/wardlight/` on the Mac unless the step says "on the VM".

## 0. Preflight on the Mac (5 minutes)

```sh
cd "Hackathons/anneru-2026/build/wardlight"
.venv/bin/python -c "from pathlib import Path; from agents.tools import WardlightData; print(WardlightData(work_dir=Path('data/work')).version)"
# expect 8606a23e82d2

STORE="$(cd ../../data-local/deploy-store/8606a23e82d2 && pwd)"
(cd "$STORE" && shasum -a 256 -c SHA256SUMS)          # four OK lines; the store was rebuilt 31 Oct for this version
ls web/dist/index.html                                # built 31 Oct; rebuild with (cd web && npm run build) only if web/ changed
az account show --query user.name -o tsv              # his Azure for Students login; if this fails, he signs in with az login
```

The old scratch store `1ae9c20fcf3f` (in a session scratchpad) is stale; never copy it.

## 1. Switch on and deploy (about 10 minutes; billing starts here)

```sh
WARDLIGHT_STORE_DIR="$STORE" bash deploy/azure_up.sh
```

`azure_up.sh` reads `AZURE_VM_HOST`, `AZURE_VM_USER`, `AZURE_VM_SSH_KEY`, `AZURE_RESOURCE_GROUP` and `AZURE_VM_NAME`
from the workspace `.env` (never printed), starts the VM, installs uv and Python 3.12, copies the app, `web/dist`, the
data files (now including `data/work/brief13/`, added 31 Oct; without it every brief 13 route answered 404), the
`nasa-power` and `naija-grid` folders and the store, installs the `wardlight` systemd unit on **127.0.0.1:8422** with
`WARDLIGHT_AGENT_LIVE=0`, and prints the health line. It stops before any Cloudflare change.

Expect the last lines to show `"ok":true,"fixture":false,"sample":false,"data_version":"8606a23e82d2"` and the memory
line from `free -m`.

## 2. Health checks before anything is public

Open an SSH tunnel from the Mac to the service (the values come from `.env` and are not printed):

```sh
set -a; source <(grep -E '^AZURE_VM_(HOST|USER|SSH_KEY)=' ../../../../.env); set +a
KEY="${AZURE_VM_SSH_KEY/#\~/$HOME}"
ssh -i "$KEY" "$AZURE_VM_USER@$AZURE_VM_HOST" 'systemctl is-active wardlight; curl -s 127.0.0.1:8422/api/health | head -c 160; echo; ps -o rss= -C python | sort -n | tail -1; free -m | sed -n 2p'
ssh -i "$KEY" -N -L 8766:127.0.0.1:8422 "$AZURE_VM_USER@$AZURE_VM_HOST" &     # local 8766 -> VM 8422
```

Then the headless page check, which opens no window:

```sh
cd web && BASE=http://127.0.0.1:8766 node scripts/check-deploy.mjs && cd ..
```

It must print `all checks passed`: `/`, `/plan`, a site page, `/method`, `/about` and the health-facility pages at 390
and 1440 px with 0 console errors and 0 horizontal overflow, data version 8606a23e82d2, and the brief 13 recordings
(including `planner13_live_maiduguri`) listed by `/api/agent/recordings`. The same check passed on 31 Oct against a
local copy of exactly what `azure_up.sh` ships (see the dry run at the end).

Spot checks, through the same tunnel:

```sh
curl -s "http://127.0.0.1:8766/api/city/maiduguri/metrics?days=60" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['headline'])"
# If the line goes down for two months, Maiduguri's critical sites keep 6.9% of critical service-hours today and 99.9% with the plan.
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" "http://127.0.0.1:8766/api/sites/W-BH-589/outage_trace?days=60"   # 200, a live engine run
```

## 3. T6 on the server (PREREG names the deployed server)

On the VM, a second instance with the cache off on port 8423, then the measurement:

```sh
ssh -i "$KEY" "$AZURE_VM_USER@$AZURE_VM_HOST"
# on the VM:
cd ~/wardlight/app
WARDLIGHT_WORK=$HOME/wardlight/app/data/work WARDLIGHT_DATA_LOCAL=$HOME/wardlight/data-local WARDLIGHT_CACHE_DIR=$HOME/wardlight/cache \
WARDLIGHT_CACHE_ENTRIES=0 WARDLIGHT_RATE_SIMULATE=100000 WARDLIGHT_RATE_READ=100000 WARDLIGHT_TRUST_CF=0 \
  ~/wardlight/.venv/bin/python -m uvicorn --factory api.main:create_app --host 127.0.0.1 --port 8423 --workers 1 &
sleep 20
~/wardlight/.venv/bin/python deploy/t6_api.py --base http://127.0.0.1:8423 --out ~/t6_server.json
kill %1
```

(`deploy/run.sh` expects `.venv` inside the app folder; on the VM the venv is `~/wardlight/.venv`, hence the direct
command.) Copy `~/t6_server.json` back, and add the result to `docs/RESULTS.md` under T6 as a hit or a miss against
"p95 under 1 s", dated, whatever it is.

## 4. Public address: wardlight.aashanjaved.com (his yes first)

The service listens on 127.0.0.1:8422 only. Check on the VM whether `cloudflared` is installed (`cloudflared --version`).
If it is not, with his yes:

```sh
# on the VM
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
cloudflared tunnel login                     # prints a URL: he opens it and authorises his Cloudflare zone
cloudflared tunnel create wardlight
cloudflared tunnel route dns wardlight wardlight.aashanjaved.com
```

Write `~/.cloudflared/config.yml` from `deploy/cloudflared-ingress.example.yml`, with hostname
`wardlight.aashanjaved.com`, the tunnel id and credentials file `tunnel create` printed, and **service
`http://127.0.0.1:8422`** (the example file says 8000, which is the Oracle layout). Then
`sudo cloudflared --config ~/.cloudflared/config.yml service install` and `sudo systemctl status cloudflared`.

Check from the Mac, signed out of everything:

```sh
curl -s https://wardlight.aashanjaved.com/api/health | head -c 160; echo
cd web && BASE=https://wardlight.aashanjaved.com node scripts/check-deploy.mjs && cd ..
```

The unit sets `WARDLIGHT_TRUST_CF=1`, so per-visitor rate limits key on Cloudflare's visitor header.

## 5. Live model for the planner (his yes first; costs cents)

Without this, the planner replays the recorded sessions (labelled "Recorded session" on screen), which is the safe
default. With his yes, put the settings in `~/wardlight/env` on the VM (the unit reads it; mode 600), copying the
Nebius key from `.env` without printing it:

```sh
grep -E '^NEBIUS_API_KEY=' ../../../../.env | cut -d= -f2- | tr -d "\"' " | ssh -i "$KEY" "$AZURE_VM_USER@$AZURE_VM_HOST" \
  'umask 077; k=$(cat); printf "WARDLIGHT_AGENT_LIVE=1\nWARDLIGHT_LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1\nWARDLIGHT_LLM_MODEL=openai/gpt-oss-120b\nWARDLIGHT_LLM_API_KEY=%s\n" "$k" > ~/wardlight/env; sudo systemctl restart wardlight'
```

Limits already in place: 40 live runs a day across all visitors (`WARDLIGHT_AGENT_DAILY_CAP`), 6 agent requests a
minute per visitor; past the cap a matching recording is replayed. Cost reference: the 32 live sessions of the T8/T9
runs cost USD 0.0725 in all, about USD 0.002 a session, so a full day at the cap is about USD 0.09. His Nebius cap
for the event is USD 5. To switch it off: `rm ~/wardlight/env && sudo systemctl restart wardlight`.

## 6. While the judges look (Sun 1 Nov to Sat 7 Nov)

- Health from the Mac once a day: `curl -s https://wardlight.aashanjaved.com/api/health | head -c 120`.
- Logs on the VM: `journalctl -u wardlight -n 100 --no-pager`; memory: `free -m`.
- If the service fails and cannot be fixed quickly, serve the recorded outputs: on the VM add `WARDLIGHT_FIXTURE=1` to
  `~/wardlight/env` and restart. Every screen then says "Recorded engine output".

**Cost:** the VM (Korea Central `Standard_B2als_v2`, USD 0.0468 an hour from the price API) plus its disk comes to
about USD 8 to 9 a week, from the Azure for Students credit.

## 7. After winners are announced (Sat 7 Nov, 10:00 PM PKT): deallocate

```sh
set -a; source <(grep -E '^AZURE_(RESOURCE_GROUP|VM_NAME)=' ../../../../.env); set +a
az vm deallocate -g "$AZURE_RESOURCE_GROUP" -n "$AZURE_VM_NAME"
az vm show -d -g "$AZURE_RESOURCE_GROUP" -n "$AZURE_VM_NAME" --query powerState -o tsv     # VM deallocated
```

Deallocated, the VM stops billing for compute; the disk keeps a small charge until he deletes it. Ask him whether to
keep the tunnel and DNS record (the URL then shows a Cloudflare error page) or remove them with
`cloudflared tunnel route dns` cleanup in his Cloudflare dashboard.

## Dry run, 31 Oct 2026 (local only, no remote machine touched)

`deploy/azure_up.sh`'s own tar commands were run into a local folder (app, `data/work` list plus `brief13`,
`data-local/nasa-power` and `naija-grid`, the rebuilt store), and the service was started with the unit's exact
command and environment on port 8766. Results: data version 8606a23e82d2 after the copy; every brief 13 route 200;
a live water-site trace in 2.5 s with only `nasa-power` present; 8 brief 13 recordings listed, including
`planner13_live_maiduguri`; `web/scripts/check-deploy.mjs` passed all 16 page checks (8 pages at 390 and 1440 px,
0 console errors, 0 overflow); resident memory about 107 MB on the Mac after the checks. Found and fixed during the dry run:
`azure_up.sh` did not copy `data/work/brief13/`.
