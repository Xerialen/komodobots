#!/usr/bin/env bash
# demo-povshot driver (runs ON servexeri) — ONE real ezQuake POV screenshot of a demo at
# <player>@<demo_sec>, rendered headless (Intel HD 530 + Xvfb). Encodes the owner's proven
# clipsmith render.cfg recipe (f_spawn -> demo_jump -> track -> screenshot). Engine notes (hard-won):
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
  *'"'*|*';'*|*'$'*|*'`'*|*'\'*|*$'\n'*)
    echo "FATAL: illegal metachar (\" ; \$ \` \\ newline) in demo/player" >&2; exit 2;;
esac

NQ="$HOME/nquake"
EZ="$NQ/ezQuake-x86_64.AppImage"
SHOTDIR="$NQ/qw/matchinfo/screenshots"
CFG="$NQ/qw/_povshot.cfg"
LOG="$NQ/_povshot.log"

[ -f "$EZ" ] || { echo "FATAL: AppImage missing: $EZ"; exit 3; }

TRACK=""
[ -n "$PLAYER" ] && [ "$PLAYER" != "-" ] && TRACK="track \"$PLAYER\";"

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
cl_maxfps 30
alias do_render "echo POVSHOT_SPAWN;unalias f_spawn;demo_jump_skip_messages 0;demo_jump $SEC;${TRACK}wait;wait;wait;wait;wait;wait;wait;wait;screenshot $OUT;echo POVSHOT_DONE;wait;wait;wait;wait;wait;wait;quit"
alias f_spawn "do_render"
playdemo $DEMO
EOF

rm -f "$SHOTDIR/$OUT.png"
cd "$NQ" || exit 3   # OWD must contain id1/ so AppRun keeps the right gamedir context
timeout 150 xvfb-run -a -s "-screen 0 ${W}x${H}x24" \
  env APPIMAGE_EXTRACT_AND_RUN=1 LIBGL_ALWAYS_SOFTWARE=1 "$EZ" -basedir "$NQ" +exec _povshot.cfg > "$LOG" 2>&1
RC=$?

if [ -f "$SHOTDIR/$OUT.png" ]; then
  echo "SHOT=$SHOTDIR/$OUT.png"
else
  echo "NO-SHOT (ezquake rc=$RC). last log lines:"
  tail -20 "$LOG"
  exit 4
fi
