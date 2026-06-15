#!/usr/bin/env bash
# Start a real KTX 4on4 frogbot match on the cloud box — one that actually forms
# teams, fights, and records an MVD — for spectating via the cloud hub (recorded
# demo, listed under "demos recorded online") and live QTV.
#
# Proven recipe (2026-06-15, komodobots cloud box):
#   * k_matchless 0 + k_defmode 4on4 + k_allowed_free_modes 4095
#     (without 4095 KTX logs "UserMode: sv 4on4 discarded ..." and falls back to ffa,
#      which zeroes teamplay — that was the project's long-standing #1 blocker).
#   * A connected client that JOINS A TEAM and READIES anchors the match start
#     (a 4on4 match needs a ready team player; an idle team-less client never starts it).
#     That client also adds the frogbots via `botcmd addbot` (CF_BOTH) and is the seed
#     of the komodobot-policy client.
#   * Anti-idle cvars keep the anchor connected so the match runs to the timelimit and
#     the MVD finalizes instead of aborting.
#
# Usage: start_match.sh [port] [map] [client_seconds]   (defaults 28590 dm3 660)
set -euo pipefail
PORT="${1:-28590}"
MAP="${2:-dm3}"
CLIENT_SECONDS="${3:-660}"
NQ="$HOME/nquakesv"
REPO="$HOME/projects/komodobots"
CFG="$NQ/ktx/match_${PORT}.cfg"
SESS="komodo_match_${PORT}"

cat > "$CFG" <<CFG
hostname "komodo 4on4 :$PORT"
set sv_demodir demos
set k_demo_mintime 0
maxclients 8
set k_matchless 0
set k_defmode 4on4
set k_allowed_free_modes 4095
set k_mode 3
set k_defmap $MAP
set k_fb_enabled 1
set k_fb_autoadd_limit 0
set k_fb_skill 9
set k_fb_auto_delay 1
timelimit 10
fraglimit 0
deathmatch 1
set sv_getrealip 0
set sv_timeout 3600
set k_idletime 0
set k_matchless_max_idle_time 0
set qtv_streamport $PORT
set qtv_maxstreams 16
set qtv_password ""
map $MAP
CFG

cd "$NQ"
screen -S "$SESS" -X quit 2>/dev/null || true
screen -wipe >/dev/null 2>&1 || true
screen -L -Logfile "$NQ/match_${PORT}.log" -dmS "$SESS" \
  ./mvdsv -port "$PORT" -mem 64 -game ktx +exec "$(basename "$CFG")"

# Wait for the server to bind + load the map before the anchor client connects.
up=0
for _ in $(seq 1 40); do
  if quakestat -qws "127.0.0.1:$PORT" 2>/dev/null | grep -q ":$PORT"; then up=1; break; fi
  sleep 0.5
done
[ "$up" = 1 ] || { echo "server did not come up on :$PORT" >&2; exit 7; }

# Anchor client: real player on red, readies, adds 7 frogbots -> auto-balanced 4on4.
# (Seed of the komodobot-policy client; idles on red for now.)
cd "$REPO"
setsid python3 experiments/qw_min_client.py "$PORT" --host 127.0.0.1 \
  --bot-count 7 --bot-spacing 1 --run-for "$CLIENT_SECONDS" --quiet \
  --cmd "setinfo team red" --cmd "ready" \
  > "$HOME/match_${PORT}_client.log" 2>&1 &

echo "4on4 match starting on :$PORT ($MAP)."
echo "  spectate (ezQuake/FTE):  /qtvplay <host>:$PORT"
echo "  recorded demo lands in:  $NQ/ktx/demos/   (-> cloud hub 'demos recorded online')"
echo "  server log: $NQ/match_${PORT}.log   client log: ~/match_${PORT}_client.log"
