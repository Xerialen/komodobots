#!/bin/sh
# T0.3 live-loop launcher (#209) -- bring up a scratch KTX server in matchless
# FFA on dm3 with one-or-more bots in live mode 30, plus the MoveMLP sidecar, so
# the live brain loop can be observed end to end. Reproduces the on-box
# validation in T0.3_LIVE_MODE.md.
#
# SAFETY: runs on a SCRATCH port + SCRATCH gamedir only. It refuses the live
# game/QTV ports and never touches the live `ktx` gamedir or its qwprogs.so.
#
# Usage (on the box, after building the patched qwprogs.so):
#   PORT=28599 SO=~/t0.3-build/build/qwprogs.so ./run_live.sh
# Env (all have box defaults):
#   PORT       scratch UDP/QTV port (default 28599)
#   INSTALL    nquakesv install dir (default ~/nquakesv)
#   SO         built patched qwprogs.so (default ~/t0.3-build/build/qwprogs.so)
#   VENV       python venv with CPU torch (default ~/t0.3-venv)
#   SIDECAR    move_policy_sidecar.py (default ~/komodo-t0.3/scripts/move_policy_sidecar.py)
#   CLIENT     qw_min_client.py (default ~/komodo-t0.3/qw_min_client.py)
#   CKPT       MoveMLP checkpoint (default ~/move_bc_policy.pt)
#   SHM        shm region name (default komodo_move_t06)
#   BOTS       number of bots to add (default 2)
set -eu

PORT="${PORT:-28599}"
INSTALL="${INSTALL:-$HOME/nquakesv}"
SO="${SO:-$HOME/t0.3-build/build/qwprogs.so}"
VENV="${VENV:-$HOME/t0.3-venv}"
SIDECAR="${SIDECAR:-$HOME/komodo-t0.3/scripts/move_policy_sidecar.py}"
CLIENT="${CLIENT:-$HOME/komodo-t0.3/qw_min_client.py}"
CKPT="${CKPT:-$HOME/move_bc_policy.pt}"
SHM="${SHM:-komodo_move_t06}"
BOTS="${BOTS:-2}"
GAMEDIR="ktx_t03"
RUNLOG="$HOME/t0.3-run.log"
SIDELOG="$HOME/t0.3-sidecar.log"

# --- refuse the live ports ---
for p in 28000 28501 28502 28503 28504; do
	[ "$PORT" = "$p" ] && { echo "REFUSING live port $PORT" >&2; exit 2; }
done

echo "[run_live] scratch gamedir $INSTALL/$GAMEDIR with patched .so"
rm -rf "$INSTALL/$GAMEDIR"
cp -r "$INSTALL/ktx" "$INSTALL/$GAMEDIR"
# qwprogs.so in the gamedir is a symlink to the versioned .so; overwrite the
# target so the symlink resolves to our patched build (leaves live `ktx` alone).
cp "$SO" "$INSTALL/$GAMEDIR/$(readlink "$INSTALL/$GAMEDIR/qwprogs.so" 2>/dev/null || echo qwprogs.so)"

cat > "$INSTALL/$GAMEDIR/t03_ffa.cfg" <<CFG
hostname "komodobots-t0.3:$PORT"
set k_fb_enabled 1
set k_matchless 1
set k_defmode ffa
set k_mode 3
set k_count 0
set k_matchless_countdown 0
set k_idletime 0
set k_matchless_max_idle_time 0
set k_defmap dm3
set k_fb_moveprobe_mode_s0 30
set k_fb_moveprobe_mode_s1 30
set k_fb_moveprobe_mode_s2 30
set k_fb_moveprobe_mode_s3 30
set k_fb_moveprobe_live_shm_name "$SHM"
set k_fb_moveprobe_live_stale_ticks 3
set k_fb_moveprobe_live_log 1
CFG

echo "[run_live] launch mvdsv on scratch port $PORT (screen qw_${PORT}_t03)"
rm -f "$RUNLOG" "/dev/shm/$SHM"
( cd "$INSTALL" && screen -dmS "qw_${PORT}_t03" -L -Logfile "$RUNLOG" \
	./mvdsv -port "$PORT" -mem 64 -game "$GAMEDIR" +exec t03_ffa.cfg )
sleep 3
screen -S "qw_${PORT}_t03" -p 0 -X stuff "$(printf '\025map dm3\r')"
sleep 3

echo "[run_live] add $BOTS bot(s) via a spectator control client"
python3 "$CLIENT" "$PORT" --host 127.0.0.1 --bot-count "$BOTS" --bot-spacing 1 \
	--run-for 7 --spectator >/dev/null 2>&1 || echo "[run_live] client rc=$?"
sleep 2

echo "[run_live] start sidecar (KTX created the region; sidecar attaches)"
screen -dmS t03_sidecar sh -c \
	"'$VENV/bin/python' '$SIDECAR' --shm-name '$SHM' --ckpt '$CKPT' --hz 77 > '$SIDELOG' 2>&1"

echo "[run_live] up. watch:  tail -f $RUNLOG | grep moveprobe-live"
echo "[run_live] pause/resume the brain:  kill -STOP/-CONT \$(pgrep -f $SIDELOG)"
echo "[run_live] stop:  screen -S qw_${PORT}_t03 -X quit; screen -S t03_sidecar -X quit"
