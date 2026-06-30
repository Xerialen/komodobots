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

# --- input validation: DEMO/PLAYER/SEC flow through the ssh chain + (on servexeri) into the
#     ezQuake cfg. Validate here too (fail fast, clear error) so a hostile value never reaches
#     the remote. SEC numeric; reject shell/cfg metachars in demo/player. ---
case "$SEC" in ''|*[!0-9.]*) echo "demo-second must be numeric: '$SEC'" >&2; exit 2;; esac
case "$DEMO$PLAYER" in
  *' '*|*$'\t'*|*'"'*|*"'"*|*';'*|*'$'*|*'`'*|*'\'*|*$'\n'*)
    echo "illegal char (whitespace or \" ' ; \$ \` \\ newline) in demo/player" >&2; exit 2;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
WIN="${POVSHOT_JUMP:-winnacle}"            # pinnacle Windows host (tailscale)
SX="${POVSHOT_HOST:-xerial@192.168.86.33}" # real servexeri over pinnacle LAN
NAME="g$(printf '%s|%s|%s' "$DEMO" "$PLAYER" "$SEC" | cksum | cut -d' ' -f1)"

# 1) deploy/refresh the servexeri driver (idempotent, cheap)
B64=$(base64 -w0 "$HERE/povshot.sh")
ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=15 $SX 'echo $B64 | base64 -d > ~/nquake/povshot.sh; chmod +x ~/nquake/povshot.sh'" \
  || { echo "deploy failed"; exit 2; }

# 2) capture. Marshal the remote command safely: printf %q shell-quotes each user value for
#    servexeri's bash, then base64 the whole inner command so it survives the Windows middle hop
#    with zero quoting hazards (pattern: memory servexeri-demo-archive — nested quotes/parens
#    otherwise break across the 3 ssh layers). No raw user byte reaches the ssh string.
echo "capturing POV[$PLAYER] @ demo_sec $SEC of $DEMO ..."
INNER=$(printf 'cd ~/nquake && ./povshot.sh %q %q %q %q 2>&1 | tail -6' "$DEMO" "$PLAYER" "$SEC" "$NAME")
IB64=$(printf %s "$INNER" | base64 -w0)
RES=$(ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=15 $SX 'echo $IB64 | base64 -d | bash'") \
  || { echo "capture ssh failed"; exit 4; }
echo "$RES"
echo "$RES" | grep -q "^SHOT=" || { echo "CAPTURE FAILED (see above)"; exit 4; }

# 3) pull the PNG ATOMICALLY: stream to a temp, require BOTH legs of the ssh|base64 pipe to succeed
#    AND the result to be a real PNG (magic bytes), then mv into place. An interrupted two-hop
#    transfer otherwise leaves a non-empty PARTIAL file that the old `-s` check would accept as a
#    successful capture (truncated/corrupt evidence).
TMP="$(mktemp "${OUT}.part.XXXXXX")" || { echo "pull failed (mktemp)"; exit 5; }
ssh -o ConnectTimeout=20 "$WIN" "ssh -o ConnectTimeout=12 $SX 'base64 -w0 ~/nquake/qw/matchinfo/screenshots/$NAME.png'" 2>/dev/null | base64 -d > "$TMP"
st_ssh=${PIPESTATUS[0]} st_b64=${PIPESTATUS[1]}
if [ "$st_ssh" -ne 0 ] || [ "$st_b64" -ne 0 ] || [ ! -s "$TMP" ]; then
  rm -f "$TMP"; echo "pull failed (transfer error: ssh=$st_ssh base64=$st_b64)"; exit 5
fi
if [ "$(head -c8 "$TMP" | od -An -tx1 | tr -d ' \n')" != "89504e470d0a1a0a" ]; then
  rm -f "$TMP"; echo "pull failed (not a valid PNG — truncated/corrupt transfer)"; exit 5
fi
mv -f "$TMP" "$OUT" || { rm -f "$TMP"; echo "pull failed (mv)"; exit 5; }
echo "LOCAL=$OUT ($(wc -c < "$OUT") bytes)"
