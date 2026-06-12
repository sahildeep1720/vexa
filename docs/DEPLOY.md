# Vexa Standup — Server Deployment

## 1. Server specs

- Ubuntu 22.04 / 24.04 LTS — **x86_64** (not ARM)
- 4 vCPU · 8 GB RAM · 100 GB SSD
- Public IP, outbound internet
- Inbound: `22` (SSH) only — reach the dashboard via SSH tunnel (§8)

## 2. GitHub deploy key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Add the printed key: GitHub → repo **sahildeep1720/vexa** → **Settings → Deploy keys → Add deploy key** (paste, read access). Then:

```bash
ssh -T git@github.com    # expect: "Hi ... You've successfully authenticated"
```

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker compose version
```

## 4. Clone

```bash
git clone git@github.com:sahildeep1720/vexa.git
cd vexa
git checkout feat/openrouter
```

## 5. Configure `.env`

```bash
cp deploy/env-example .env
cat .env.openrouter.example >> .env
{
  echo "TRANSCRIPTION_SERVICE_URL=http://transcriber:8085/v1/audio/transcriptions"
  echo "POST_MEETING_HOOKS=http://standup-extractor:8086/hooks/meeting-completed"
  echo "OPENROUTER_TRANSCRIBE_MODEL=openai/gpt-4o-transcribe"
  echo "OPENROUTER_CHAT_MODEL=openai/gpt-5.5"
  echo "IMAGE_TAG=latest"
  echo "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)"
  echo "TRANSCRIPTION_SERVICE_TOKEN=$(openssl rand -hex 24)"
  echo "INTERNAL_API_SECRET=$(openssl rand -hex 24)"
  echo "ADMIN_TOKEN=$(openssl rand -hex 24)"
  echo "BOT_API_TOKEN=$(openssl rand -hex 24)"
  echo "OPENROUTER_API_KEY=PASTE_YOUR_OPENROUTER_KEY"
} >> .env
nano .env    # set OPENROUTER_API_KEY to your real sk-or-... key
```

## 6. Build & start

```bash
ops/stack.sh build          # builds our images + pulls the bot image
ops/stack.sh up-lean
make -C deploy/compose init-db
make -C deploy/compose setup-api-key
ops/stack.sh up-lean
```

## 7. Verify

```bash
ops/stack.sh ps
curl -s localhost:8085/health
curl -s localhost:8086/health
curl -s localhost:8090/health
grep '^VEXA_API_KEY=' .env
```

## 8. Firewall + dashboard access

The dashboard has **no password** (direct login) — do **not** open `3001` to the public.

Open only SSH:

```bash
sudo ufw allow 22
sudo ufw enable
sudo ufw status
```

(also allow `22` in your cloud provider's **security group**)

Start the full stack (dashboard is not in `up-lean`):

```bash
ops/stack.sh up    # full stack (adds dashboard + mcp)
```

**Access the dashboard via SSH tunnel** (recommended — nothing public). From your laptop:

```bash
ssh -L 3001:localhost:3001 -L 8056:localhost:8056 user@VM_PUBLIC_IP
```

Then open `http://localhost:3001` → log in with `admin@vexa.ai` (no password).

**Alternative — whitelist your laptop IP** instead of the tunnel. Get it with `curl ifconfig.me`, then:

```bash
sudo ufw allow from YOUR_IP to any port 3001 proto tcp
sudo ufw allow from YOUR_IP to any port 8056 proto tcp
```

(also add `YOUR_IP` + ports `3001`/`8056` in the cloud security group; re-run if your IP changes)

## 9. Daily auto-join (same meeting, every weekday)

```bash
ops/schedule-standup.sh add MEET_CODE --time 10:30 --tz Asia/Kolkata
ops/schedule-standup.sh list
```

- `MEET_CODE` = the `xxx-xxxx-xxx` from `https://meet.google.com/xxx-xxxx-xxx`
- `--time` is local time (24h); `--tz` your timezone; runs Mon–Fri
- Admit **"Vexa"** when it knocks (or enable Quick access in the meeting for no-admit)
- Change schedule: `ops/schedule-standup.sh cancel-meeting MEET_CODE` then `add` again

## Manage

```bash
ops/stack.sh logs                 # tail logs
ops/stack.sh logs transcriber     # one service
ops/stack.sh restart transcriber  # restart one
ops/stack.sh down                 # stop all
```

## Update

```bash
cd vexa && git pull && ops/stack.sh build && ops/stack.sh up-lean
```

## Troubleshooting

**`runtime-api` crash-loops with `PermissionError(13)` on `/var/run/docker.sock`** — `DOCKER_GID`
doesn't match the host's docker group (common if a Mac `.env` with `DOCKER_GID=0` was copied over):

```bash
GID=$(stat -c '%g' /var/run/docker.sock)
grep -q '^DOCKER_GID=' .env && sed -i "s/^DOCKER_GID=.*/DOCKER_GID=$GID/" .env || echo "DOCKER_GID=$GID" >> .env
ops/stack.sh up
```

**`permission denied` running `docker`/`ops/stack.sh`** — your user isn't in the `docker` group
yet. Don't use `sudo`; fix the group: `sudo usermod -aG docker $USER`, then **log out and back in**,
then `docker ps` should work with no sudo.

**Join fails: runtime-api `404 ... /containers/create` (no such image)** — the bot image isn't
pulled (runtime-api spawns it at runtime; Compose doesn't pull it):

```bash
docker pull "$(grep '^BROWSER_IMAGE=' .env | cut -d= -f2)"
```
