# Deploying the Wardlight API

Nothing here has been deployed. These files describe how the API runs on the Oracle VM behind the existing
Cloudflare tunnel, at a subdomain he approves.

**For the judges' host (Azure, Sunday 1 Nov 2026) follow `SUNDAY-RUNBOOK.md`**: `azure_up.sh` switches the VM on and
deploys, `web/scripts/check-deploy.mjs` checks it headless. The steps below are the general and Oracle layout.

| File | What it is |
|---|---|
| `run.sh` | Starts uvicorn with the app factory (`api.main:create_app`), one worker, bound to 127.0.0.1 |
| `wardlight-api.service` | systemd unit that runs `run.sh` as user `wardlight`, hardened, restart on failure |
| `cloudflared-ingress.example.yml` | Ingress rule for the tunnel, hostname left as a placeholder |
| `t6_api.py` | T6 through the API: 200 random facilities, wall time per what-if call |
| `azure_up.sh` | Switches on the Azure host and deploys to it (reads `AZURE_*` names from `.env`; see `SUNDAY-RUNBOOK.md`) |
| `wardlight-vm.service` | systemd unit for the Azure and Oracle hosts, 127.0.0.1:8422 |
| `mem_api.py` | Resident memory after start, after one what-if and after one agent replay, measured with `ps` |

## One worker, on purpose

The per-visitor rate limits, the what-if cache, agent runs (and their event streams) and the daily agent cap all
live in process memory. Two workers would split them, so `run.sh` always passes `--workers 1`. A what-if call is
CPU-bound and runs in the worker's thread pool, so a single worker still serves reads while it computes.

## Steps on the VM

1. Create the user and folder: `sudo useradd --system --create-home --home-dir /opt/wardlight wardlight`.
2. Copy the project so that `/opt/wardlight/build/wardlight` holds `api/`, `engine/`, `agents/`, `web/dist/`,
   `data/fixtures/` and `docs/`, for example with `rsync -a --exclude .venv --exclude node_modules`.
3. Copy `data/work/` (never committed) into `/opt/wardlight/build/wardlight/data/work/`, and the parts of
   `data-local/` the engine reads at run time (`nasa-power/`, `naija-grid/`, `MANIFEST.md`) into
   `/opt/wardlight/data-local/`. Without `data/work`, run with `WARDLIGHT_FIXTURE=1`.
4. Build the on-disk store on the Mac (its builder peaks at about 800 MB, too much for the VM):
   `.venv/bin/python -m api.store_build --out store/`, then copy the four files it names (`store-*.sqlite`,
   `core-*.parquet`, `facilities-*.json.gz`, `meta-*.json`) to `/var/lib/wardlight/` on the VM. They are named
   by the data version, so a new `data/work` needs a new build; the API builds it itself if they are missing,
   which on the VM would lean on swap.
5. Create the environment: `cd /opt/wardlight/build/wardlight && uv venv .venv && uv pip install --python
   .venv/bin/python -e .`
6. Build the web app where Node is available (`web/`: `npm ci && npm run build` with `VITE_API_BASE=/api`) and copy
   `web/dist/` across. The API serves it at `/` with a fallback to `index.html` for client routes.
7. Install the unit: `sudo cp deploy/wardlight-api.service /etc/systemd/system/ && sudo systemctl daemon-reload
   && sudo systemctl enable --now wardlight-api`. Check with `curl -s 127.0.0.1:8000/api/health`.
8. Add the ingress rule from `cloudflared-ingress.example.yml` to the tunnel's config with the approved hostname,
   then restart `cloudflared`.
9. Measure T6 on the server, as PREREG requires: start a second instance with the cache off on another port
   (`WARDLIGHT_CACHE_ENTRIES=0 WARDLIGHT_RATE_SIMULATE=100000 WARDLIGHT_RATE_READ=100000 PORT=8765
   deploy/run.sh`), then `.venv/bin/python deploy/t6_api.py --base http://127.0.0.1:8765 --out t6_server.json`.

10. Check memory the same way it was measured on the Mac: `.venv/bin/python deploy/mem_api.py --port 8767`.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `WARDLIGHT_FIXTURE` | 0 | 1 serves `data/fixtures/` only: no `data/work`, no engine, no model |
| `WARDLIGHT_TRUST_CF` | 1 | Use the `CF-Connecting-IP` header as the visitor; set 0 when not behind Cloudflare |
| `WARDLIGHT_RATE_READ` / `_SIMULATE` / `_AGENT` / `_TELEPHONY` | 240 / 30 / 6 / 60 | Requests a minute per visitor (telephony: per phone number) |
| `WARDLIGHT_MAX_BODY_BYTES` | 16384 | Larger request bodies get 413 |
| `WARDLIGHT_CACHE_ENTRIES` | 4096 | What-if and plan cache size (0 turns it off) |
| `WARDLIGHT_WHATIF_DRAWS` | 32 | Supply draws per weather year in a what-if (the engine's what-if default) |
| `WARDLIGHT_AGENT_LIVE` | 0 | 1 lets the planner call the live model configured by `WARDLIGHT_LLM_*` (his approval first) |
| `WARDLIGHT_AGENT_RUNS` | all | `replay` serves recorded agent sessions only (a guard; live runs share the store and fit) |
| `WARDLIGHT_AGENT_DAILY_CAP` | 40 | Non-recorded agent runs a day (UTC); beyond it a matching recording is replayed |
| `WARDLIGHT_CACHE_DIR` | system temp `wardlight-api` | Where the on-disk store is kept (the unit uses `/var/lib/wardlight`) |
| `WARDLIGHT_CORS_ORIGINS` | empty | Comma-separated origins, only if the web app is served from another host |
| `WARDLIGHT_WORK`, `WARDLIGHT_DATA_LOCAL`, `WARDLIGHT_FIXTURES`, `WARDLIGHT_WEB_DIST` | project paths | Overrides |

## Africa's Talking sandbox

In the sandbox app's settings, point the USSD callback at `https://<host>/api/ussd` and the incoming-SMS callback
at `https://<host>/api/sms/inbound`. Both are sandbox only: the USSD reply goes back in the HTTP response, which is
how the USSD API works; the SMS reply is returned in the response body and is not sent, because this build calls no
SMS API. His account and his yes come first.
