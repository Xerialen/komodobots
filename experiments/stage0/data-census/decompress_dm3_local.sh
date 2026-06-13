#!/usr/bin/env bash
# Decompress the staged dm3 .qwz POV corpus locally in pinnacle WSL2.
# Mirrors ezQuake cl_demo.c:2988 `qizmo -q -u -3 -D <file.qwz>`.
# Bundled 32-bit qizmo 2.91 run via its own loader/libs (no i386 multiarch needed).
set -u
SRC="/mnt/c/Users/benya/projects/quakeworld/data/challenge-tv-archive/stage_dm3"
WORK="$HOME/ctv_decomp"
QB="$HOME/qizmo_bundle"
LDP="$QB/libs"
mkdir -p "$WORK"

ok=0; fail=0; total=0; n=0
shopt -s nullglob
# iterate via find -print0 to survive brackets/spaces in names
while IFS= read -r -d '' f; do
  n=$((n+1))
  stem=$(basename "$f")
  stem="${stem%.*}"
  cp -f "$f" "$WORK/$stem.qwz"
  rm -f "$WORK/$stem.qwd"
  ( cd "$QB" && "$LDP/ld-linux.so.2" --library-path "$LDP" ./qizmo -q -u -3 -D "$WORK/$stem.qwz" >/dev/null 2>&1 )
  if [ -s "$WORK/$stem.qwd" ]; then
    ok=$((ok+1)); sz=$(stat -c %s "$WORK/$stem.qwd"); total=$((total+sz))
  else
    fail=$((fail+1)); echo "FAIL: $stem"
  fi
  rm -f "$WORK/$stem.qwz"
done < <(find "$SRC" -maxdepth 1 -iname '*.qwz' -print0)

echo "qwz_in=$n decompressed_ok=$ok failed=$fail total_qwd_bytes=$total"
echo "qwd_now=$(find "$WORK" -maxdepth 1 -iname '*.qwd' | wc -l)"
