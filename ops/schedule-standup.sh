#!/usr/bin/env bash
# ops/schedule-standup.sh — manage recurring "bot joins the standup" jobs on the
# runtime-api scheduler.
#
# The runtime-api scheduler (services/runtime-api/runtime_api/scheduler.py) stores
# jobs in a Redis sorted set and fires HTTP calls at execute_at. A job whose
# metadata.cron is set re-arms itself after each successful run (next fire =
# croniter(cron, now_utc)). We exploit that to schedule a daily POST /bots so the
# Vexa bot auto-joins your standup. Cron is evaluated in UTC INSIDE runtime-api,
# so this script converts your local HH:MM into a UTC cron expression, remapping
# the day-of-week when the UTC offset crosses midnight.
#
# Env is read from $ROOT/.env:
#   VEXA_API_KEY    (REQUIRED for `add`) — user token put in the bot-join body's
#                   X-API-Key header so api-gateway authorizes POST /bots.
#   BOT_API_TOKEN   (optional) — if set, runtime-api's scheduler API itself
#                   requires X-API-Key: $BOT_API_TOKEN (API_KEYS=${BOT_API_TOKEN}).
#   RUNTIME_API_PORT       (default 8090) — host port for runtime-api.
#   API_GATEWAY_HOST_PORT  (default 8056) — host port for api-gateway.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

# --- read a KEY=VALUE from .env (last wins; tolerate missing file) ---
env_get() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

VEXA_API_KEY="$(env_get VEXA_API_KEY)"
BOT_API_TOKEN="$(env_get BOT_API_TOKEN)"
RT_PORT="$(env_get RUNTIME_API_PORT)"; RT_PORT="${RT_PORT:-8090}"
GW_PORT="$(env_get API_GATEWAY_HOST_PORT)"; GW_PORT="${GW_PORT:-8056}"

RT_BASE="http://localhost:${RT_PORT}"
GW_BASE="http://localhost:${GW_PORT}"

# curl against the scheduler API, injecting the scheduler-auth header iff set.
rt_curl() {
  if [ -n "$BOT_API_TOKEN" ]; then
    curl -s -H "X-API-Key: $BOT_API_TOKEN" "$@"
  else
    curl -s "$@"
  fi
}

require_python3() {
  command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
}

usage() {
  cat <<'EOF'
Usage: ops/schedule-standup.sh <command> [args]

  add <meet_id> [options]      Schedule a recurring (or one-off) standup bot join
      --time HH:MM             Local wall-clock time (default 10:30)
      --tz ZONE                IANA timezone (default Asia/Kolkata)
      --days mon-fri|csv       Weekdays: range (mon-fri) or comma list (mon,wed,fri)
      --bot-name NAME          Bot display name (default "Standup Bot")
      --language CODE          Force transcription language (e.g. en, es)
      --once                   Fire once (no cron re-arm)
      --at +SECONDS|EPOCH      One-off at a relative (+N) or absolute epoch time
  list                         List standup-scheduler jobs
  show <job_id>                Show one job
  cancel <job_id>              Cancel one job
  cancel-meeting <meet_id>     Cancel all pending standup jobs for a meet_id

Examples:
  ops/schedule-standup.sh add abc-defg-hij --time 10:30 --tz Asia/Kolkata --days mon-fri
  ops/schedule-standup.sh add abc-defg-hij --once --at +120
  ops/schedule-standup.sh list
EOF
}

# ===========================================================================
# add
# ===========================================================================
cmd_add() {
  local meet_id="${1:-}"; shift || true
  if [ -z "$meet_id" ]; then echo "add requires <meet_id>" >&2; exit 2; fi

  local time="10:30" tz="Asia/Kolkata" days="mon-fri"
  local bot_name="Standup Bot" language="" once="" at="" authed=""

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --time)     time="${2:?--time needs a value}"; shift 2 ;;
      --tz)       tz="${2:?--tz needs a value}"; shift 2 ;;
      --days)     days="${2:?--days needs a value}"; shift 2 ;;
      --bot-name) bot_name="${2:?--bot-name needs a value}"; shift 2 ;;
      --language) language="${2:?--language needs a value}"; shift 2 ;;
      --authenticated) authed="1"; shift ;;   # opt-in: only if the bot account is auto-admitted (host/org)
      --once)     once="1"; shift ;;
      --at)       at="${2:?--at needs a value}"; once="1"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
  done

  if [ -z "$VEXA_API_KEY" ]; then
    echo "VEXA_API_KEY is not set in $ENV_FILE — required to authorize POST /bots." >&2
    echo "Run 'make -C deploy/compose setup-api-key' first." >&2
    exit 1
  fi

  require_python3

  # --- preflight: confirm the gateway accepts our key BEFORE scheduling. ---
  # The scheduler counts a 4xx response as a COMPLETED job (it only retries on
  # 5xx/429 — see _fire_request), so a bad key would silently "succeed" forever
  # and never actually join. Catch it now.
  # curl prints %{http_code} (000 on connect failure) on its own; the `|| true`
  # just keeps `set -e` happy when curl exits non-zero — do NOT add a fallback
  # echo or you double the code (e.g. "000000").
  local http
  http="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "X-API-Key: $VEXA_API_KEY" "$GW_BASE/bots/status" 2>/dev/null || true)"
  http="${http:-000}"
  if [ "$http" != "200" ] && [ "$http" != "304" ]; then
    echo "Preflight failed: GET $GW_BASE/bots/status returned HTTP $http." >&2
    echo "  - 000: api-gateway not reachable on port $GW_PORT (is the stack up?)." >&2
    echo "  - 401/403: VEXA_API_KEY is wrong/stale (re-run setup-api-key)." >&2
    echo "Aborting — a bad key would make the scheduler record fake 4xx 'successes'." >&2
    exit 1
  fi

  # --- compute execute_at + cron via python3 (zoneinfo for the tz math). ---
  # Emits two lines: "<execute_at_epoch_float>" then "<utc_cron_or_empty>".
  local planned
  planned="$(
    MEET_TIME="$time" MEET_TZ="$tz" MEET_DAYS="$days" \
    MEET_ONCE="$once" MEET_AT="$at" \
    python3 <<'PY'
import os, sys, time, hashlib
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    print("zoneinfo unavailable (need python>=3.9)", file=sys.stderr)
    sys.exit(1)

hhmm  = os.environ["MEET_TIME"]
tzname= os.environ["MEET_TZ"]
days  = os.environ["MEET_DAYS"]
once  = os.environ.get("MEET_ONCE", "")
at    = os.environ.get("MEET_AT", "")

# --- one-off paths -------------------------------------------------------
if at:
    if at.startswith("+"):
        epoch = time.time() + float(at[1:])
    else:
        epoch = float(at)
    print(repr(float(epoch)))
    print("")  # no cron
    sys.exit(0)

try:
    hh, mm = (int(x) for x in hhmm.split(":"))
except Exception:
    print(f"Bad --time '{hhmm}', expected HH:MM", file=sys.stderr); sys.exit(1)

try:
    tz = ZoneInfo(tzname)
except Exception as e:
    print(f"Unknown --tz '{tzname}': {e}", file=sys.stderr); sys.exit(1)

# cron DOW: 0-6 == Sun..Sat. python weekday(): 0-6 == Mon..Sun.
NAME2CRON = {"sun":0,"mon":1,"tue":2,"wed":3,"thu":4,"fri":5,"sat":6}
PY2CRON   = {0:1,1:2,2:3,3:4,4:5,5:6,6:0}  # python weekday -> cron dow

def parse_days(spec):
    spec = spec.strip().lower()
    if "-" in spec and "," not in spec:
        a, b = spec.split("-", 1)
        if a not in NAME2CRON or b not in NAME2CRON:
            print(f"Bad --days range '{spec}'", file=sys.stderr); sys.exit(1)
        ca, cb = NAME2CRON[a], NAME2CRON[b]
        # expand the range over the weekday wheel (handles fri-mon wraps)
        out, i = [], ca
        while True:
            out.append(i)
            if i == cb: break
            i = (i + 1) % 7
        return out
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if tok not in NAME2CRON:
            print(f"Bad --days token '{tok}'", file=sys.stderr); sys.exit(1)
        out.append(NAME2CRON[tok])
    return out

cron_dows = parse_days(days)                      # set of cron DOWs (local)
allowed_py = {d for d in range(7) if PY2CRON[d] in cron_dows}  # python weekdays

# --- (a) first local occurrence >= now+60s -------------------------------
now = datetime.now(tz)
floor = now + timedelta(seconds=60)
cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
for _ in range(0, 366):
    if cand.weekday() in allowed_py and cand >= floor:
        break
    cand = cand + timedelta(days=1)
    cand = cand.replace(hour=hh, minute=mm, second=0, microsecond=0)
execute_at = cand.timestamp()

# --- (b) UTC cron: convert H:M and remap DOWs if the offset crosses days --
utc = cand.astimezone(ZoneInfo("UTC"))
uh, um = utc.hour, utc.minute
day_shift = (utc.date() - cand.date()).days   # -1, 0, or +1 vs local date
utc_dows = sorted({ (d + day_shift) % 7 for d in cron_dows })
cron = f"{um} {uh} * * {','.join(str(d) for d in utc_dows)}"

# --- DST drift warning: a fixed UTC cron drifts when the zone changes offset
def has_dst(tz, year):
    o0 = datetime(year,1,1,tzinfo=tz).utcoffset()
    for m in range(2,13):
        if datetime(year,m,1,tzinfo=tz).utcoffset() != o0:
            return True
    return False
if has_dst(tz, cand.year):
    print(f"WARNING: {tzname} observes DST — this fixed UTC cron ('{cron}') will "
          f"drift by an hour across DST transitions. Re-run after each transition "
          f"to correct the wall-clock time.", file=sys.stderr)

print(repr(float(execute_at)))
print(cron)
PY
  )"

  local execute_at cron
  execute_at="$(printf '%s\n' "$planned" | sed -n '1p')"
  cron="$(printf '%s\n' "$planned" | sed -n '2p')"

  if [ -z "$execute_at" ]; then
    echo "Failed to compute schedule." >&2; exit 1
  fi

  # --- build the JSON payload (python3 for safe escaping) ------------------
  local payload
  payload="$(
    MEET_ID="$meet_id" BOT_NAME="$bot_name" LANGUAGE="$language" \
    VEXA_API_KEY="$VEXA_API_KEY" EXECUTE_AT="$execute_at" CRON="$cron" \
    LOCAL_TIME="$time" MEET_TZ="$tz" ONCE="$once" AUTHED="$authed" \
    python3 <<'PY'
import os, json, time, hashlib

meet_id = os.environ["MEET_ID"]
bot_name= os.environ["BOT_NAME"]
language= os.environ.get("LANGUAGE","")
api_key = os.environ["VEXA_API_KEY"]
execute_at = float(os.environ["EXECUTE_AT"])
cron    = os.environ.get("CRON","")
local_t = os.environ["LOCAL_TIME"]
tz      = os.environ["MEET_TZ"]
once    = os.environ.get("ONCE","")
authed  = os.environ.get("AUTHED","")

body = {
    "platform": "google_meet",
    "native_meeting_id": meet_id,
    "bot_name": bot_name,
}
# Default = anonymous (the bot knocks; a human admits) — the mode that works on a
# clean IP. --authenticated is opt-in and ONLY helps when the bot account is
# auto-admitted by the meeting (host, same Workspace org, or quick-access);
# otherwise the authenticated flow times out waiting for the join button.
if authed:
    body["authenticated"] = True
if language:
    body["language"] = language

job = {
    "execute_at": execute_at,
    "request": {
        "method": "POST",
        "url": "http://api-gateway:8000/bots",
        "headers": {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        "body": body,
        "timeout": 30,
    },
    "retry": {"max_attempts": 3, "backoff": [60, 180, 300]},
}

meta = {
    "source": "standup-scheduler",
    "meet_id": meet_id,
    "local_time": local_t,
    "tz": tz,
}
if cron and not once:
    meta["cron"] = cron
    sig = hashlib.sha1(f"{cron}|{local_t}|{tz}".encode()).hexdigest()[:8]
    job["idempotency_key"] = f"standup_join_{meet_id}_{sig}"
else:
    # one-off: a timestamp suffix keeps each run distinct (no dedup collisions)
    job["idempotency_key"] = f"standup_join_{meet_id}_once_{int(time.time())}"

job["metadata"] = meta
print(json.dumps(job))
PY
  )"

  # --- POST to the scheduler ----------------------------------------------
  local resp
  resp="$(rt_curl -X POST "$RT_BASE/scheduler/jobs" \
    -H "Content-Type: application/json" -d "$payload" || true)"

  # Validate: status must be "pending" AND execute_at must echo our value.
  # If the idempotency_key already existed, the API returns the OLD job (its
  # original execute_at), which we detect by the mismatch.
  EXPECT_AT="$execute_at" RESP="$resp" python3 <<'PY'
import os, sys, json, time
from datetime import datetime, timezone

resp = os.environ.get("RESP","")
try:
    job = json.loads(resp)
except Exception:
    print("Scheduler did not return JSON. Raw response:", file=sys.stderr)
    print(resp, file=sys.stderr)
    sys.exit(1)

if isinstance(job, dict) and job.get("detail"):
    print(f"Scheduler error: {job['detail']}", file=sys.stderr)
    sys.exit(1)

status = job.get("status")
got_at = float(job.get("execute_at", 0) or 0)
want_at = float(os.environ["EXPECT_AT"])

if status != "pending":
    print(f"Unexpected job status '{status}' (expected 'pending').", file=sys.stderr)
    print(json.dumps(job, indent=2), file=sys.stderr)
    sys.exit(1)

if abs(got_at - want_at) > 1.0:
    print("A job with this idempotency_key already exists — the scheduler "
          "returned the EXISTING job instead of creating a new one.", file=sys.stderr)
    print(f"  existing execute_at: {datetime.fromtimestamp(got_at, timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
          file=sys.stderr)
    print(f"  job_id: {job.get('job_id')}", file=sys.stderr)
    print("To reschedule: cancel the old job (cancel <job_id>) or change "
          "--time/--days/--tz so the idempotency_key differs.", file=sys.stderr)
    sys.exit(1)

ut = datetime.fromtimestamp(got_at, timezone.utc)
lt = datetime.fromtimestamp(got_at).astimezone()
print(f"Scheduled job {job.get('job_id')}")
print(f"  next run: {ut:%Y-%m-%d %H:%M:%S} UTC  ({lt:%Y-%m-%d %H:%M:%S %Z} local)")
cron = job.get("metadata", {}).get("cron")
if cron:
    print(f"  recurring cron (UTC): {cron}")
else:
    print("  one-off (no cron re-arm)")
PY
}

# ===========================================================================
# list
# ===========================================================================
cmd_list() {
  require_python3
  local resp
  resp="$(rt_curl "$RT_BASE/scheduler/jobs?source=standup-scheduler&limit=100" || true)"
  RESP="$resp" python3 <<'PY'
import os, sys, json
from datetime import datetime, timezone

try:
    jobs = json.loads(os.environ.get("RESP","") or "[]")
except Exception:
    print("Failed to parse scheduler response:", file=sys.stderr)
    print(os.environ.get("RESP",""), file=sys.stderr); sys.exit(1)

# Defensive: filter client-side too in case the server lacks ?source.
jobs = [j for j in jobs if j.get("metadata", {}).get("source") == "standup-scheduler"]
if not jobs:
    print("No standup-scheduler jobs.")
    sys.exit(0)

print(f"{'JOB_ID':<22} {'STATUS':<10} {'NEXT RUN (UTC / local)':<42} {'MEET_ID':<18} CRON")
print("-" * 110)
for j in sorted(jobs, key=lambda x: x.get("execute_at", 0)):
    at = float(j.get("execute_at", 0) or 0)
    ut = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lt = datetime.fromtimestamp(at).astimezone().strftime("%H:%M %Z")
    when = f"{ut} / {lt}"
    meta = j.get("metadata", {})
    print(f"{j.get('job_id',''):<22} {j.get('status',''):<10} {when:<42} "
          f"{meta.get('meet_id',''):<18} {meta.get('cron','-')}")
PY
}

# ===========================================================================
# show
# ===========================================================================
cmd_show() {
  local job_id="${1:-}"
  if [ -z "$job_id" ]; then echo "show requires <job_id>" >&2; exit 2; fi
  local resp
  resp="$(rt_curl "$RT_BASE/scheduler/jobs/$job_id" || true)"
  RESP="$resp" python3 <<'PY'
import os, sys, json
try:
    job = json.loads(os.environ.get("RESP","") or "{}")
except Exception:
    print(os.environ.get("RESP",""), file=sys.stderr); sys.exit(1)
if isinstance(job, dict) and job.get("detail") and "job_id" not in job:
    print(f"Error: {job['detail']}", file=sys.stderr); sys.exit(1)
print(json.dumps(job, indent=2))
print()
print("Reminder: after the first run, check result.status_code == 201 "
      "(a successful POST /bots). A 4xx here means the bot did NOT join even "
      "though the scheduler marked the job 'completed'.")
PY
}

# ===========================================================================
# cancel / cancel-meeting
# ===========================================================================
cmd_cancel() {
  local job_id="${1:-}"
  if [ -z "$job_id" ]; then echo "cancel requires <job_id>" >&2; exit 2; fi
  local resp
  resp="$(rt_curl -X DELETE "$RT_BASE/scheduler/jobs/$job_id" || true)"
  RESP="$resp" python3 <<'PY'
import os, sys, json
try:
    job = json.loads(os.environ.get("RESP","") or "{}")
except Exception:
    print(os.environ.get("RESP",""), file=sys.stderr); sys.exit(1)
if isinstance(job, dict) and job.get("detail") and "job_id" not in job:
    print(f"Error: {job['detail']}", file=sys.stderr); sys.exit(1)
print(f"Cancelled {job.get('job_id')} (status={job.get('status')}).")
PY
}

cmd_cancel_meeting() {
  local meet_id="${1:-}"
  if [ -z "$meet_id" ]; then echo "cancel-meeting requires <meet_id>" >&2; exit 2; fi
  local resp ids
  resp="$(rt_curl "$RT_BASE/scheduler/jobs?source=standup-scheduler&limit=100" || true)"
  ids="$(MEET_ID="$meet_id" RESP="$resp" python3 <<'PY'
import os, json
try:
    jobs = json.loads(os.environ.get("RESP","") or "[]")
except Exception:
    jobs = []
mid = os.environ["MEET_ID"]
for j in jobs:
    meta = j.get("metadata", {})
    if meta.get("source") == "standup-scheduler" and meta.get("meet_id") == mid \
       and j.get("status") == "pending":
        print(j.get("job_id",""))
PY
)"
  if [ -z "$ids" ]; then
    echo "No pending standup jobs for meet_id=$meet_id."
    return 0
  fi
  local id
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    rt_curl -X DELETE "$RT_BASE/scheduler/jobs/$id" >/dev/null 2>&1 || true
    echo "Cancelled $id"
  done <<< "$ids"
}

# ===========================================================================
# dispatch
# ===========================================================================
main() {
  local cmd="${1:-}"
  [ "$#" -gt 0 ] && shift || true
  case "$cmd" in
    add)            cmd_add "$@" ;;
    list)           cmd_list "$@" ;;
    show)           cmd_show "$@" ;;
    cancel)         cmd_cancel "$@" ;;
    cancel-meeting) cmd_cancel_meeting "$@" ;;
    ""|-h|--help|help) usage ;;
    *) echo "Unknown command: $cmd" >&2; echo >&2; usage; exit 2 ;;
  esac
}

main "$@"
