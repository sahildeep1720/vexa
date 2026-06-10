# Vexa + OpenRouter Standup — VM Deployment Guide

End-to-end guide to deploy and run the OpenRouter standup pipeline on a Linux VM with
Docker + Docker Compose: **build → run → one-time Google login → join meetings →
daily auto-join → monitor**.

> This is the `feat/openrouter` overlay (kept separate from Vexa core). It adds two
> services — `transcriber` (OpenRouter speech-to-text) and `standup-extractor`
> (per-person standup → English JSON → Kanban) — wired into stock Vexa via env hooks.

---

## 0. What you get

```
Google Meet ──> vexa-bot (Chromium, signed in) ──> transcriber ──> OpenRouter gpt-4o-transcribe
                                                         │
   meeting ends ──> POST_MEETING_HOOKS ──> standup-extractor ──> OpenRouter gpt-5.5
                                                         │            (English standup JSON)
                                                         └──> Kanban API (your endpoint)
```

**Lean fleet (11 containers):** redis · postgres · minio · minio-init · admin-api ·
runtime-api · meeting-api · api-gateway · tts-service · **transcriber** · **standup-extractor**.
(`dashboard` + `mcp` are dropped in the lean profile.)

**Why a real VM matters:** Google Meet blocks **anonymous** bots with reCAPTCHA. The bot
must join **signed in** to a Google account (Step 5). A real x86 Linux VM with a clean IP +
the signed-in account is the environment this is built for; a laptop with an emulated
browser will get challenged even when signed in.

---

## 1. Prerequisites

- **VM:** Ubuntu 22.04/24.04, **x86_64** (not ARM), **4 vCPU / 8 GB RAM / 100 GB SSD** min.
- **OpenRouter** account + API key (with credits). Both models route through it:
  `openai/gpt-4o-transcribe` (STT) and `openai/gpt-5.5` (extraction).
- A **dedicated Google account** for the bot (not a personal one; ideally **no 2FA**).
- Outbound internet from the VM (to Google Meet + openrouter.ai).

Install Docker Engine + Compose plugin:

```bash
sudo apt-get update && sudo apt-get install -y git make
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker      # run docker without sudo
docker compose version                                 # verify the compose plugin
```

---

## 2. Get the code

```bash
git clone https://github.com/sahildeep1720/vexa.git
cd vexa
git checkout feat/openrouter
```

---

## 3. Configure `.env`

Create the repo-root `.env` from the two templates, then edit it:

```bash
cp deploy/env-example .env
cat .env.openrouter.example >> .env
nano .env
```

**Fill / set these (the rest can stay default):**

```ini
# --- repoint Vexa at our services (do not change the hostnames) ---
TRANSCRIPTION_SERVICE_URL=http://transcriber:8085/v1/audio/transcriptions
POST_MEETING_HOOKS=http://standup-extractor:8086/hooks/meeting-completed

# --- OpenRouter (one key, both services) ---
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
OPENROUTER_TRANSCRIBE_MODEL=openai/gpt-4o-transcribe
OPENROUTER_CHAT_MODEL=openai/gpt-5.5

# --- secrets: generate random values (openssl rand -hex 24) ---
TRANSCRIPTION_SERVICE_TOKEN=<random>     # shared bot<->transcriber bearer
INTERNAL_API_SECRET=<random>             # meeting-api internal endpoints
ADMIN_TOKEN=<random>
BOT_API_TOKEN=<random>                   # also guards the scheduler API

# --- standup extraction LLM (gpt-5.5 = reasoning model) ---
REASONING_MODEL=true
MAX_COMPLETION_TOKENS=2000

# --- optional: map Meet display names -> your Kanban user names ---
# TEAM_ROSTER={"Dhruv Vakharwala":"Dhruv V","Dhrumit Yadav":"Dhrumit Y"}

# --- your Kanban API (leave empty = stub logs the payload) ---
# KANBAN_API_URL=https://your-kanban.example.com
# KANBAN_API_KEY=<token>
```

**Docker socket group (Linux):** runtime-api spawns bot containers via the Docker socket and
runs as non-root, so it needs the host docker group id:

```bash
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env
```

> **Do NOT put `COMPOSE_FILE` in `.env`** — it breaks `deploy/compose/Makefile`. If you want
> bare `docker compose` to find both files, export it in your shell instead:
> ```bash
> echo 'export COMPOSE_FILE="'"$PWD"'/deploy/compose/docker-compose.yml:'"$PWD"'/docker-compose.openrouter.yml"' >> ~/.bashrc
> echo 'export COMPOSE_PATH_SEPARATOR=":"' >> ~/.bashrc && source ~/.bashrc
> ```
> (Not required — `ops/stack.sh` already passes both files.)

---

## 4. Build & start the stack

`ops/stack.sh` is the single entry point — it always passes `--env-file .env` and both
compose files.

```bash
ops/stack.sh build            # build transcriber, standup-extractor, runtime-api(+croniter)
ops/stack.sh up-lean          # start the 11-container lean fleet (no dashboard/mcp)

# initialize DB + create the API key (writes VEXA_API_KEY into .env)
make -C deploy/compose init-db
make -C deploy/compose setup-api-key
ops/stack.sh up-lean          # re-run: setup-api-key starts the dashboard as a side effect; this trims it
```

> For the **full** stack incl. the Vexa dashboard UI (useful for debugging), use
> `ops/stack.sh up` instead of `up-lean`.

Other commands: `ops/stack.sh ps | logs [svc] | restart <svc> | down`.

---

## 5. Verify it's healthy

```bash
ops/stack.sh ps                                       # all Up / healthy
curl -s localhost:8085/health                         # transcriber: {"ready":true,"model":"openrouter"}
curl -s localhost:8086/health                         # standup-extractor: {"status":"healthy",...}
curl -s localhost:8090/health                         # runtime-api
KEY=$(grep '^VEXA_API_KEY=' .env | cut -d= -f2)
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $KEY" localhost:8056/bots   # 200
docker exec vexa-runtime-api-1 python -c "import croniter; print('cron OK')"        # scheduler dep
```

---

## 6. Two join modes — pick one

Google gates how a bot enters a Meet. There are two modes:

**Mode A — Anonymous (default, simplest).** The bot clicks "Ask to join" and **knocks**; a human
in the meeting **admits** it. No Google login needed. Reliable on a **clean server IP** (a VM).
Caveat: Google may show the bot a reCAPTCHA if the IP/browser looks automated — rare on a fresh
VM, common if you fire many bots quickly from one machine (the IP gets temporarily flagged). Just
`POST /bots` without `authenticated` (Step 7).

**Mode B — Authenticated (hands-off, advanced).** The bot joins **signed in** to a Google account,
which avoids reCAPTCHA *and* can skip the admit click — **but only if that account is auto-admitted**
by the meeting (it's the **host**, in the **same Workspace org**, or the meeting has **Quick access
ON**). If it isn't auto-admitted, the authenticated flow times out waiting for "Join now". Set it
up once below.

> **For a truly hands-off daily standup, the clean pattern is: create the standup Meet *from the
> bot's own Google account* (bot = host), then use Mode B — it auto-admits itself, no reCAPTCHA,
> no human admit.**

### Mode B setup — log the bot's Google account in (ONE-TIME)

The signed-in profile is saved to MinIO and reused by every future authenticated bot (survives
restarts; lasts weeks–months).

```bash
KEY=$(grep '^VEXA_API_KEY=' .env | cut -d= -f2)

# 1. start a browser session, capture the token
curl -s -X POST localhost:8056/bots -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"mode":"browser_session"}' | tee /tmp/bs.json
TOKEN=$(python3 -c "import json;print(json.load(open('/tmp/bs.json'))['data']['session_token'])")
echo "Open this in your browser:  http://<VM_IP>:8056/b/$TOKEN"
```

2. Open `http://<VM_IP>:8056/b/<token>` in **your laptop browser**. You'll see a live Chromium.
   - Click the **address bar**, type **`accounts.google.com`**, press Enter.
     *(The session opens to a blank tab — you must navigate to Google yourself.)*
   - Sign in with the **dedicated bot Google account**. Complete 2FA if asked. Tick
     **"Stay signed in"**.
3. Save the authenticated profile to MinIO:

```bash
curl -s -X POST "localhost:8056/b/$TOKEN/save" -H "X-API-Key: $KEY"   # {"message":"Storage saved successfully"}
```

4. Stop the browser session (optional; it also idles out after 1h):

```bash
docker ps --format '{{.Names}}' | grep browser-session | xargs -r docker stop
```

> **When do you redo this?** Only if Google later signs the bot out (password change, security
> flag, long inactivity). The symptom is bots hitting reCAPTCHA / `needs_human_help` again.

---

## 7. Send a bot to a meeting

**Mode A (default — bot knocks, you admit):**

```bash
KEY=$(grep '^VEXA_API_KEY=' .env | cut -d= -f2)
curl -s -X POST localhost:8056/bots -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"platform":"google_meet","native_meeting_id":"abc-defg-hij","bot_name":"Standup Bot"}'
```
Then **admit "Vexa"** when it knocks. `native_meeting_id` is the code from `meet.google.com/abc-defg-hij`.

**Mode B (authenticated — only if the bot account is auto-admitted):** add `"authenticated": true`
to the body. The bot joins signed in; if it's host/org/quick-access it lands directly, otherwise it
times out waiting for "Join now".

**For fully hands-off joins (no admit click):** in the meeting's Google settings, turn on
**Host management → Quick access / "Let anyone join without asking"**, or invite the bot's
Google account to the calendar event so it's a trusted participant.

**Watch it:**

```bash
curl -s -H "X-API-Key: $KEY" localhost:8056/transcripts/google_meet/abc-defg-hij | python3 -m json.tool
docker logs -f vexa-standup-extractor-1     # on meeting end: extracted English standup JSON
```

---

## 8. Daily auto-join (scheduler)

`ops/schedule-standup.sh` registers a recurring join with runtime-api's cron scheduler
(jobs persist in Redis; converts local time → UTC cron automatically):

```bash
ops/schedule-standup.sh add abc-defg-hij --time 10:30 --tz Asia/Kolkata   # weekdays 10:30 IST
ops/schedule-standup.sh list
ops/schedule-standup.sh cancel-meeting abc-defg-hij
```

> By default the scheduled join is **Mode A** (anonymous — the bot knocks, someone admits). For a
> zero-touch standup, add `--authenticated` **and** make the bot account auto-admitted (Mode B —
> easiest when the standup Meet is owned by the bot account).

---

## 9. Monitoring & maintenance

```bash
ops/stack.sh ps                                                  # service health
ops/stack.sh logs transcriber standup-extractor                  # tail our services
docker exec vexa-redis-1 redis-cli XLEN meeting-api:container-stops      # bot-stop backlog (want ~0)
docker exec vexa-redis-1 redis-cli SMEMBERS meeting-api:container-stop-dlq # stuck stops (want empty)
docker ps -a --filter status=exited | grep meeting-              # leftover bot containers
ops/schedule-standup.sh list                                     # confirm cron chain alive
```

**Log rotation (host-wide, for core services):** our two services already cap logs; for the
rest add `/etc/docker/daemon.json`:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "3" } }
```
then `sudo systemctl restart docker`.

**Back up these volumes:** `vexa_postgres-data` (meetings/transcripts), `vexa_minio-data`
(recordings **+ the bot's Google login profile**), `vexa_redis-data`.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot leaves fast, **0 transcript**, `reCAPTCHA present` / bounced to `meet.google.com/landing` | Google anti-bot challenged the join — common from a **flagged IP** (many rapid attempts) or an emulated/laptop browser | Use a **clean server IP** (VM) and don't fire bots repeatedly; let a flagged IP cool a few hours; or Mode B with an auto-admitted account |
| `join_meeting_error`, bot log: `Timeout … waiting for … "Join now"` | Signed in, but the meeting did **not auto-admit** the bot account (it's *external* to the meeting → Google shows it "Ask to join", but the authenticated flow only waits for "Join now") | Make the bot account **auto-admitted**: host turns on **Quick access**, or the bot account is in the **same Google Workspace org** as the meeting, or invite the bot account to the calendar event |
| `join_meeting_error` from an **emulated/laptop** browser | Google risk engine | Deploy on a native x86 VM with a clean IP; keep the bot account warm |
| No "Vexa wants to join" prompt appears | Bot blocked **before** the knock (reCAPTCHA), not an admit-timing issue | Same as above — authenticate; check `docker logs <bot-container>` |
| Transcript empty but bot was admitted | Nobody spoke, or `no_one_joined_timeout` (2 min alone) | Have someone speak; the bot leaves if alone |
| `make -C deploy/compose` targets fail | `COMPOSE_FILE` was put in `.env` | Remove it from `.env`; export in `~/.bashrc` instead |
| Standup output in Hindi | — | It shouldn't be; the extractor forces English. Re-check `services/standup-extractor/app/extractor.py` `_SYSTEM` |

**Inspect a live bot's browser:** find the container (`docker ps | grep meeting-`) and
`docker logs -f <name>`. A reCAPTCHA-blocked bot also starts a VNC server inside the container
for manual solving.

---

## Reference

| Service | Host port | Purpose |
|---|---|---|
| api-gateway | 8056 | public API + browser-session viewer (`/b/<token>`) |
| transcriber | 8085 | OpenRouter STT facade |
| standup-extractor | 8086 | post-meeting extraction |
| runtime-api | 8090 | bot/container lifecycle + scheduler |
| (dashboard) | 3001 | Vexa UI — only in `ops/stack.sh up` (full) |

**Model swap:** change `OPENROUTER_TRANSCRIBE_MODEL` / `OPENROUTER_CHAT_MODEL` in `.env`,
then `ops/stack.sh up-lean`. Any OpenAI-compatible endpoint works via `OPENROUTER_BASE_URL`
(set `OPENROUTER_REQUIRE_PARAMETERS=false` for proxies that reject the `provider` field).

**Kanban wiring:** implement `services/standup-extractor/app/kanban_client.py` `push()` to call
your real endpoint, set `KANBAN_API_URL`/`KANBAN_API_KEY`, then `ops/stack.sh up-lean`.
