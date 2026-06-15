#!/usr/bin/env bash
# A watchable, recorded 4on4: team frog vs team leap, all skill-20 frogbots, real
# combat. One ready anchor client (on leap) starts the match and adds the 7 frogbots
# (3 leap + 4 frog) -> balanced 4v4. (The leap seats are placeholders for the named,
# policy-driven komodobots once the policy-client exists.) Manual record persists it.
set -uo pipefail
PORT=28593; MAP=dm3; NQ=$HOME/nquakesv; REPO=$HOME/projects/komodobots
SESS=komodo_match_$PORT; CFG=$NQ/ktx/match_$PORT.cfg
cat > "$CFG" <<CFG
hostname "frog vs leap :$PORT"
set sv_demodir demos
maxclients 8
set k_matchless 0
set k_defmode 4on4
set k_allowed_free_modes 4095
set k_mode 3
set k_defmap $MAP
set k_fb_enabled 1
set k_fb_autoadd_limit 0
set k_fb_skill 20
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
screen -S "$SESS" -X quit 2>/dev/null || true; screen -wipe >/dev/null 2>&1 || true
rm -f "$NQ/match_$PORT.log"
screen -L -Logfile "$NQ/match_$PORT.log" -dmS "$SESS" ./mvdsv -port $PORT -mem 64 -game ktx +exec "match_$PORT.cfg"
up=0; for _ in $(seq 1 40); do quakestat -qws 127.0.0.1:$PORT 2>/dev/null | grep -q ":$PORT" && { up=1; break; }; sleep 0.5; done
[ "$up" = 1 ] || { echo "server did not come up"; exit 7; }
sleep 5   # let dm3 fully load before the client challenges (fixes the connect race)
cd "$REPO"
setsid python3 experiments/qw_min_client.py $PORT --host 127.0.0.1 --bot-count 0 --run-for 130 --quiet \
  --name leapcap --cmd "setinfo team leap" --cmd "ready" \
  --botcmd "addbot 20 leap" --botcmd "addbot 20 leap" --botcmd "addbot 20 leap" \
  --botcmd "addbot 20 frog" --botcmd "addbot 20 frog" --botcmd "addbot 20 frog" --botcmd "addbot 20 frog" \
  > "$HOME/match_${PORT}_client.log" 2>&1 &
stuff(){ screen -S "$SESS" -p 0 -X stuff "$(printf '\025%s\r' "$1")"; }
sleep 16                      # bots join + match begins
stuff "sv_demoeasyrecord frog_vs_leap_4v4"
sleep 45                      # record combat
stuff "sv_demostop"
sleep 3
echo "=== quakestat -P (teams + frags) ==="; quakestat -P -qws 127.0.0.1:$PORT 2>&1 | sed -n '1,12p'
echo "=== saved demo ==="; ls -la "$NQ/ktx/demos/frog_vs_leap_4v4"*.mvd 2>/dev/null
echo "=== client log (errors?) ==="; tail -3 "$HOME/match_${PORT}_client.log" 2>/dev/null
echo "=== log: teams/begun/frags ==="; grep -iE "is ready \[|match has begun|telefragged|was killed|leap|frog" "$NQ/match_$PORT.log" 2>/dev/null | tail -18
