#!/usr/bin/env bash
# demo-povshot/grab.sh — from aws-dev, grab ONE real ezQuake POV screenshot of a demo at
# <player>@<demo_sec>, rendered headless on servexeri, pulled to a local PNG for Claude to Read.
# Deploys + runs scripts/povshot.sh on servexeri and pulls the result.
#   usage: grab.sh <demo-rel-to-qw> <player|-|userid> <demo_sec> <local-out.png>
# player MUST be a single token: a QW name without spaces, a numeric userid (use the userid for
# color-byte names), or '-' for the default POV. demo path is relative to ~/nquake/qw/.
set -uo pipefail
DEMO="${1:?demo path relative to ~/nquake/qw/ (e.g. matchinfo/demos/foo.mvd)}"
PLAYER="${2:?player name|userid|-}"
SEC="${3:?demo-second}"
OUT="${4:?local output .png path}"

HERE="$(cd "$(dirname "$0")" && pwd)"
WIN="${POVSHOT_JUMP:-winnacle}"            # pinnacle Windows host (tailscale)
SX="${POVSHOT_HOST:-xerial@192.168.86.33}" # real servexeri over pinnacle LAN
NAME="g$(printf '%s|%s|%s' "$DEMO" "$PLAYER" "$SEC" | cksum | cut -d' ' -f1)"

# 1) deploy/refresh the servexeri driver (idempotent, cheap)
B64=$(base64 -w0 "$HERE/povshot.sh")
ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=15 $SX 'echo $B64 | base64 -d > ~/nquake/povshot.sh; chmod +x ~/nquake/povshot.sh'" \
  || { echo "deploy failed"; exit 2; }

# 2) capture (player/demo/sec are single tokens -> safe through the ssh chain)
echo "capturing POV[$PLAYER] @ demo_sec $SEC of $DEMO ..."
RES=$(ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=15 $SX 'cd ~/nquake && ./povshot.sh $DEMO $PLAYER $SEC $NAME 2>&1 | tail -4'")
echo "$RES"
echo "$RES" | grep -q "^SHOT=" || { echo "CAPTURE FAILED (see above)"; exit 4; }

# 3) pull the PNG to the local path
ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=12 $SX 'base64 -w0 ~/nquake/qw/matchinfo/screenshots/$NAME.png'" 2>/dev/null | base64 -d > "$OUT"
[ -s "$OUT" ] && echo "LOCAL=$OUT ($(wc -c < "$OUT") bytes)" || { echo "pull failed"; exit 5; }
