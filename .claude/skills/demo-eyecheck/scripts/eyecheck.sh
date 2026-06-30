#!/usr/bin/env bash
# demo-eyecheck driver — render a player's POV around a match-time event and pull readable frames.
# Runs on aws-dev; orchestrates the GPU box (winnacle, Windows + demoshots) over ssh. See SKILL.md.
#
#   eyecheck.sh <demo> <player> <match_sec> [offset_sec=0] [context_sec=3]
#     <demo>      local demo path (auto-staged to the GPU box) OR a name already under qw\demos
#     <match_sec> event time on the MATCH clock; demo_sec = match_sec + offset (calibrate offset/demo)
#
# Box-specific paths default to this machine's pinnacle box; override via env if they move.
set -euo pipefail

DEMO=${1:?usage: eyecheck.sh <demo> <player> <match_sec> [offset_sec=0] [context_sec=3]}
PLAYER=${2:?need player name/userid}
MATCH=${3:?need match_sec}
OFFSET=${4:-0}
CTX=${5:-3}

WIN_HOST=${EYECHECK_WIN_HOST:-winnacle}            # Windows/PowerShell ssh host (GPU + demoshots)
LIN_HOST=${EYECHECK_LIN_HOST:-linnacle}            # WSL2 ssh host on the same box (scp via /mnt/c)
WIN_NQ=${EYECHECK_WIN_NQ:-'C:\nQuake'}
WIN_DEMOSHOTS=${EYECHECK_DEMOSHOTS:-'C:\Users\benya\.claude\skills\demoshots'}
WIN_PY=${EYECHECK_WIN_PY:-'C:\Users\benya\AppData\Local\Programs\Python\Python312\python.exe'}
WIN_OUT=${EYECHECK_WIN_OUT:-'C:\Users\benya\demoshots\eyecheck'}
LIN_OUT=${EYECHECK_LIN_OUT:-/mnt/c/Users/benya/demoshots/eyecheck}   # same dir, WSL view
LIN_DEMOS=${EYECHECK_LIN_DEMOS:-/mnt/c/nQuake/qw/demos}              # qw\demos, WSL view
LOCAL=${EYECHECK_OUT:-/tmp/eyecheck}
CHUNK=${EYECHECK_CHUNK:-80}                         # shots per ezQuake launch; demoshots' runaway-loop
                                                    # guard trips ~140+, so a high match_sec (long
                                                    # 0..MaxSec capture) needs chunking — 80 stays under it
HERE=$(cd "$(dirname "$0")" && pwd)

# Robust file pull: linnacle (WSL2) scp first, else winnacle PowerShell base64. The WSL2 scp host is
# flaky ("Connection closed"); winnacle reads the SAME files (it's the Windows side of /mnt/c), so the
# base64 fallback always works when linnacle is down.
pull() { # <wsl_src> <win_src> <local_dst>
  scp -q "$LIN_HOST:$1" "$3" 2>/dev/null && [ -s "$3" ] && return 0
  ssh "$WIN_HOST" "pwsh -NoProfile -Command \"[Convert]::ToBase64String([IO.File]::ReadAllBytes('$2'))\"" 2>/dev/null | tr -d '\r\n ' | base64 -d > "$3"
  [ -s "$3" ]
}

demo_sec=$(python3 -c "print(int(round($MATCH + $OFFSET)))")
lo=$((demo_sec - CTX)); ((lo < 0)) && lo=0
hi=$((demo_sec + CTX))
maxsec=$((hi + 2))
safe=$(printf '%s' "$PLAYER" | tr -cd 'A-Za-z0-9'); [ -z "$safe" ] && safe=pov
echo "match_sec=$MATCH offset=$OFFSET -> demo_sec=$demo_sec  strip t$lo..t$hi  (MaxSec=$maxsec)"

# 1. stage the demo onto the GPU box if a local path was given (else assume already under qw\demos)
if [ -f "$DEMO" ]; then
  base=$(basename "$DEMO")
  scp -q "$DEMO" "$LIN_HOST:$LIN_DEMOS/$base"
  WINDEMO="$WIN_NQ\\qw\\demos\\$base"
else
  WINDEMO="$DEMO"
fi

# 2. capture the POV (demoshots: 1 screenshot per demo-second, 0..MaxSec). -Chunk keeps each ezQuake
#    launch under the runaway-loop guard so a high match_sec doesn't trip ("chunk 0-N TIMEOUT").
ssh "$WIN_HOST" "pwsh -NoProfile -File '$WIN_DEMOSHOTS\\scripts\\capture-pov.ps1' -Demo '$WINDEMO' -Player '$PLAYER' -MaxSec $maxsec -Chunk $CHUNK -OutRoot '$WIN_OUT'"

# 3. build the labelled contact sheet on the GPU box (it has Pillow; aws-dev does not). contact_sheet.py
#    is small, so on a linnacle-scp failure fall back to writing it via winnacle base64.
scp -q "$HERE/contact_sheet.py" "$LIN_HOST:$LIN_OUT/contact_sheet.py" 2>/dev/null \
  || ssh "$WIN_HOST" "pwsh -NoProfile -Command \"[IO.File]::WriteAllBytes('$WIN_OUT\\contact_sheet.py',[Convert]::FromBase64String('$(base64 -w0 "$HERE/contact_sheet.py")'))\""
ssh "$WIN_HOST" "& '$WIN_PY' '$WIN_OUT\\contact_sheet.py' '$WIN_OUT\\$safe' $lo $hi"

# 4. pull the sheet + the in-range full-res frames to aws-dev (linnacle scp, else winnacle base64)
mkdir -p "$LOCAL/$safe"
pull "$LIN_OUT/$safe/sheet_${lo}-${hi}.jpg" "$WIN_OUT\\$safe\\sheet_${lo}-${hi}.jpg" "$LOCAL/$safe/sheet_${lo}-${hi}.jpg" \
  || { echo "ERROR: could not pull the contact sheet (linnacle scp AND winnacle base64 both failed)" >&2; exit 1; }
for s in $(seq "$lo" "$hi"); do
  f=$(printf 't%06d.jpg' "$s")
  pull "$LIN_OUT/$safe/$f" "$WIN_OUT\\$safe\\$f" "$LOCAL/$safe/$f" 2>/dev/null || true
done
echo "READ: $LOCAL/$safe/sheet_${lo}-${hi}.jpg   (then zoom: $LOCAL/$safe/t<sec>.jpg)"
