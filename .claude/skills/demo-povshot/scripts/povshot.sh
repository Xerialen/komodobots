#!/usr/bin/env bash
# demo-povshot driver (runs ON servexeri) — ONE real ezQuake POV screenshot of a demo at
# <player>@<demo_sec>, rendered headless (Intel HD 530 + Xvfb). Recipe = the proven demoshots engine:
# track the player at f_spawn (with the engine's auto-POV overrides OFF), THEN `exec` a second cfg
# that demo_jumps to the target second + screenshots. Engine notes (hard-won):
#   * Manual `track <name>` only STICKS if mvd_autotrack/demo_autotrack/cl_hightrack are 0 — else the
#     engine re-locks the POV to the high-frag / first-present player (ezQuake cl_cam.c Cam_Track) and
#     you silently get the WRONG player. AND `track` must run in a SEPARATE cbuf pass from demo_jump
#     (an `exec` boundary) so Cam_Track latches the player before the seek. ruleset default lifts the
#     qcon wait-cap(10); cl_demospeed 5->1 fast-forwards warmup so f_spawn fires with players loaded.
#   * Run the AppImage via APPIMAGE_EXTRACT_AND_RUN=1 so AppRun picks the bundled "appimage libc"
#     glibc loader. The bare extracted binary FAILS: servexeri's system glibc is older than the
#     bundled libs (GLIBC_ABI_DT_X86_64_PLT missing) — they must NOT be mixed.
#   * AppRun SIGSEGVs on a POST-run qwurl-desktop fixup AFTER ezQuake has already quit + written
#     the shot, so the exit code is junk — we gate success on the PNG existing, not on rc.
#   * xvfb-run + LIBGL_ALWAYS_SOFTWARE=1 (llvmpipe) so GL works with no display/GPU accel.
# Prints "SHOT=<abs png path>" on the LAST line on success; non-zero + log tail on failure.
set -uo pipefail

DEMO="${1:?usage: povshot.sh <demo-path-relative-to-qw> <player|-> <demo_sec> [outname]}"
PLAYER="${2:-}"                 # in-demo name or userid; '-' or empty = default POV (no track)
SEC="${3:?need demo-second}"
OUT="${4:-povshot}"
W="${POV_W:-1280}"; H="${POV_H:-720}"

# --- input validation (cfg-injection guard): SEC/OUT/W/H/DEMO/PLAYER are interpolated into the
#     ezQuake config + the Xvfb screen spec below, where a newline / ';' / '"' / '$' would inject
#     extra console commands. Whitelist the numeric/filename ones; reject metachars in demo/player
#     so a hostile demo path or player token can't smuggle commands into the engine. ---
case "$SEC" in ''|*[!0-9.]*) echo "FATAL: demo-second must be numeric: '$SEC'" >&2; exit 2;; esac
case "$OUT" in ''|*[!A-Za-z0-9._-]*) echo "FATAL: outname must match [A-Za-z0-9._-]: '$OUT'" >&2; exit 2;; esac
case "$W$H" in ''|*[!0-9]*) echo "FATAL: POV_W/POV_H must be numeric: '${W}x${H}'" >&2; exit 2;; esac
case "$DEMO$PLAYER" in
  *' '*|*$'\t'*|*'"'*|*';'*|*'$'*|*'`'*|*'\'*|*$'\n'*)
    echo "FATAL: illegal char (whitespace or \" ; \$ \` \\ newline) in demo/player" >&2; exit 2;;
esac

NQ="$HOME/nquake"
EZ="$NQ/ezQuake-x86_64.AppImage"
SHOTDIR="$NQ/qw/matchinfo/screenshots"
CFG="$NQ/qw/_povshot.cfg"            # loop: setup + track@f_spawn -> exec shots
CFG_SHOTS="$NQ/qw/_povshot_shots.cfg" # shots: demo_jump + screenshot (separate cbuf pass)
LOG="$NQ/_povshot.log"
QCON="$NQ/qw/qconsole.log"           # ezQuake console (-condebug); CLEARED per run so the track-fail
                                     # grep below is scoped to THIS capture, not a stale prior one

[ -f "$EZ" ] || { echo "FATAL: AppImage missing: $EZ"; exit 3; }

# Serialize captures on this box. The cfg files + qconsole.log below are shared FIXED paths, so two
# overlapping renders would clobber each other's cfg and a render could screenshot the other request's
# second/outname -> a plausible but WRONG frame (evidence corruption). One ezQuake at a time also
# matches the single Intel HD 530 GPU (parallel xvfb renders just contend). The lock is held (fd 9
# stays open) from cfg generation through the shot-existence check, i.e. the whole capture.
exec 9>"$NQ/.povshot.lock" || { echo "FATAL: cannot open lockfile $NQ/.povshot.lock" >&2; exit 3; }
flock -w 200 9 || { echo "FATAL: timed out waiting for the povshot capture lock" >&2; exit 3; }

TRACK=""
# bare `track $PLAYER` (no quotes) — nested quotes inside the double-quoted alias corrupt the cfg.
# PLAYER is whitespace-free (validated above), so a single bare token is safe; color-byte names use
# the numeric userid. '-' or empty PLAYER => no track => default demo POV.
[ -n "$PLAYER" ] && [ "$PLAYER" != "-" ] && TRACK="track $PLAYER;"

# loop cfg: HUD + auto-POV overrides OFF + track at f_spawn, then `exec` the shots cfg (the exec is
# the cbuf boundary that lets Cam_Track latch the player before the seek — see header).
cat > "$CFG" <<EOF
tp_msgtriggers 0
tp_forceTriggers 0
tp_loadlocs 0
scr_centertime 0
scr_conspeed 99999
scr_consize 0
scr_newhud 1
sshot_format png
vid_width $W
vid_height $H
vid_conwidth 512
hud_recalculate
hud_tracker_show 1
r_tracker 1
cl_maxfps 0
ruleset default
mvd_autotrack 0
demo_autotrack 0
cl_hightrack 0
cl_restrictions 0
demo_jump_skip_messages 1
cl_demospeed 5
alias do_start "unalias f_spawn;cl_demospeed 1;${TRACK}echo POVSHOT_SPAWN;exec _povshot_shots.cfg"
alias f_spawn "do_start"
playdemo $DEMO
EOF

# Positive post-seek verification (only when a specific player is requested): after the seek settles,
# RE-assert `track $PLAYER` (forces the requested slot; a disconnected player errors -> caught below),
# then arm f_trackspectate as a re-lock detector. ezQuake's Cam_Lock fires f_trackspectate on EVERY
# lock (src/cl_cam.c), so if the engine SILENTLY re-locks the POV to another player in the final
# pre-screenshot window — because the requested player is dead/absent at this exact second — it echoes
# POVSHOT_RELOCK and we fail closed. A stable, present player produces no re-lock (Cam_Track branch A
# keeps spec_track == the requested slot), so a clean run has no POVSHOT_RELOCK.
RETRACK_BLOCK=""
if [ -n "$TRACK" ]; then
  RETRACK_BLOCK="track $PLAYER
alias f_trackspectate \"echo POVSHOT_RELOCK\"
wait
wait"
fi

# shots cfg: seek to the target second, settle, (re-track + arm the re-lock detector), screenshot, quit.
cat > "$CFG_SHOTS" <<EOF
demo_jump $SEC
wait
wait
wait
wait
wait
wait
$RETRACK_BLOCK
screenshot $OUT
echo POVSHOT_DONE
quit
EOF

# clear this capture's outputs FIRST (under the flock): the shot, and the SHARED console log so the
# post-run track-fail grep can't be poisoned by a stale "no such player" line from a prior capture.
rm -f "$SHOTDIR/$OUT.png" "$QCON"
cd "$NQ" || exit 3   # OWD must contain id1/ so AppRun keeps the right gamedir context
timeout 150 xvfb-run -a -s "-screen 0 ${W}x${H}x24" \
  env APPIMAGE_EXTRACT_AND_RUN=1 LIBGL_ALWAYS_SOFTWARE=1 "$EZ" -basedir "$NQ" -condebug +exec _povshot.cfg > "$LOG" 2>&1
RC=$?

if [ ! -f "$SHOTDIR/$OUT.png" ]; then
  echo "NO-SHOT (ezquake rc=$RC). console (qconsole.log) tail:"
  tail -15 "$QCON" 2>/dev/null || tail -20 "$LOG"
  exit 4
fi

# Fail CLOSED on a wrong-player frame. If a specific player was requested ($TRACK non-empty) but
# ezQuake could not resolve/lock that token (bad name, color-byte name vs userid, player absent at
# f_spawn), it SILENTLY falls back to the demo's default POV and still writes a PNG — misleading
# "exact-player" evidence. CL_Track (ezQuake src/cl_cam.c) prints a resolution error to the console
# in exactly those cases, so reject the shot when any such line is present. (Default POV = empty
# $TRACK, skips this. Overrides are off above, so a resolved track binds the requested player.)
if [ -n "$TRACK" ] && grep -qiE 'no such player|no player with userid|cannot track a spectator|only track in spectator mode|must be connected to track' "$QCON" 2>/dev/null; then
  echo "NO-SHOT: track FAILED for player '$PLAYER' — ezQuake could not resolve/lock it, so the POV is"
  echo "        the demo default, NOT '$PLAYER'. Use the exact in-demo name or a numeric userid."
  grep -iE 'no such player|no player with|cannot track|only track in spectator|connected to track' "$QCON" 2>/dev/null | tail -3
  rm -f "$SHOTDIR/$OUT.png"
  exit 5
fi

# Positive check: the requested player resolved (no error above) AND the POV stayed locked to them
# through the shot. If f_trackspectate fired in the final window, the engine re-locked to another
# player (requested player dead/absent at this exact second) -> the frame is NOT their POV -> reject.
if [ -n "$TRACK" ] && grep -qi 'POVSHOT_RELOCK' "$QCON" 2>/dev/null; then
  echo "NO-SHOT: '$PLAYER' was not a STABLE POV at demo_sec $SEC — ezQuake re-locked the view to another"
  echo "        player just before the shot (the requested player is dead/absent at this exact second)."
  echo "        Pick a second where '$PLAYER' is active."
  rm -f "$SHOTDIR/$OUT.png"
  exit 6
fi

echo "SHOT=$SHOTDIR/$OUT.png"
