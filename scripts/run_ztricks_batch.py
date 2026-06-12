#!/usr/bin/env python3
"""Run a batched ztricks Distance lab session.

This runner is the efficient version of the manual "try once, stop, document"
loop. It keeps one temporary MVDSV/KTX server and one MVD recording alive,
then executes N single-bot ztricks Distance attempts with a small cvar sweep.

Each attempt still removes and re-adds the bot so spawn-snap state is clean.
The post-run pipeline writes the usual lab artifacts plus
`ztricks-batch-score.json/md`.
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from demo_archive import archive_run_demo
from extract_movement_metrics import write_movement_metrics
from run_frobodm2_lab import (
    ARTIFACT_ROOT,
    DEFAULT_ANALYZER,
    choose_port,
    ensure_prereqs,
    powershell_safe_path,
    run,
    run_analyzer,
    scp_from_remote,
    upload_shim,
    utc_run_id,
    validate_run_id,
    write_moveprobe_assign_logs,
    write_moveprobe_command_logs,
    write_moveprobe_qwd_event_logs,
    write_moveprobe_replay_event_logs,
    write_summary,
)
from score_ztricks_batch import render_markdown, score_run_dir, write_outputs


REMOTE_BATCH_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

run_id="$1"
port="$2"
map_name="$3"
attempt_seconds="$4"
keeper_seconds="$5"
plan_b64="$6"
timelimit_min="$7"
mvdsv_bin="$8"

session="komodobots_lab_${map_name}_${port}_${run_id}"
rundir="$HOME/komodobots-lab/runs/$run_id"
nq="$HOME/nquakesv"
cfg_name="kbot_${map_name}_${port}.cfg"
cfg_path="$nq/ktx/$cfg_name"
keeper_pid=""

mkdir -p "$rundir"
touch "$rundir/start.marker"
printf '%s' "$plan_b64" | base64 -d > "$rundir/ztricks-batch-plan.tsv"

log() {
  printf '[remote] %s\n' "$*"
}

session_exists() {
  screen -ls | grep -q "[.]${session}[[:space:]]"
}

send_cmd() {
  local cmd="$1"
  local delay="${2:-0.35}"
  screen -S "$session" -p 0 -X stuff "$(printf '\025%s\r' "$cmd")"
  sleep "$delay"
}

lab_lock="$HOME/komodobots-lab/lab.lock"
acquire_lab_lock() {
  mkdir -p "$HOME/komodobots-lab"
  printf '{"owner":"harness","run_id":"%s","pid":%s,"ts":"%s"}\n' \
    "$run_id" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$lab_lock"
}
release_lab_lock() {
  if [ -f "$lab_lock" ] && grep -q "\"run_id\":\"${run_id}\"" "$lab_lock"; then
    rm -f -- "$lab_lock"
  fi
}

cleanup() {
  set +e
  if [ -n "${keeper_pid:-}" ]; then
    kill "$keeper_pid" >/dev/null 2>&1 || true
  fi
  if session_exists; then
    send_cmd "sv_demostop" 0.5
    screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.cleanup.txt"
    screen -S "$session" -X quit
  fi
  release_lab_lock
}
trap cleanup EXIT

if session_exists; then
  echo "Screen session already exists: $session" >&2
  exit 2
fi
if screen -ls | grep -q "[.]komodobots_lab_${port}[[:space:]]"; then
  echo "Lab port $port is held by dashboard session komodobots_lab_${port}" >&2
  exit 2
fi
if [ ! -x "$nq/$mvdsv_bin" ]; then
  echo "Missing executable: $nq/$mvdsv_bin" >&2
  exit 3
fi
if [ ! -f "$nq/qw/maps/${map_name}.bsp" ]; then
  echo "Missing map: $nq/qw/maps/${map_name}.bsp" >&2
  exit 4
fi
if [ ! -f "$rundir/qw_min_client.py" ]; then
  echo "Missing uploaded shim: $rundir/qw_min_client.py" >&2
  exit 6
fi

route_file="$nq/ktx/bots/maps/${map_name}.bot"
route_file_present_original=0
route_file_used=0
if [ -f "$route_file" ]; then
  route_file_present_original=1
  route_file_used=1
else
  log "warning: missing route file $route_file; attempting map anyway"
fi

cat > "$cfg_path" <<EOF
// Auto-generated Komodobots ztricks batch config $run_id
hostname "komodobots-ztricks-batch:$port"
set k_motd1 "Komodobots ztricks batch $run_id"
set k_matchless 1
set k_use_matchless_dir 1
set k_defmode ffa
set k_mode 3
set k_defmap $map_name
set k_fb_enabled 0
set k_count 0
set k_matchless_countdown 0
set k_fb_moveprobe_mode 24
set k_fb_moveprobe_log_commands 1
set k_fb_moveprobe_log_interval 0
timelimit $timelimit_min
fraglimit 0
samelevel 1
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
set qtv_streamport $port
set qtv_maxstreams 8
set qtv_password ""
serverinfo hostname "komodobots-ztricks-batch:$port"
EOF
cp "$cfg_path" "$rundir/lab.cfg"

attempt_count="$(($(wc -l < "$rundir/ztricks-batch-plan.tsv") - 1))"
cat > "$rundir/run.env" <<EOF
RUN_ID=$run_id
SESSION=$session
PORT=$port
MAP=$map_name
RUNDIR=$rundir
CFG=$cfg_path
ROUTE_FILE=$route_file
ROUTE_FILE_PRESENT_ORIGINAL=$route_file_present_original
ROUTE_FILE_USED=$route_file_used
MOVEPROBE_MODE=23
MOVEPROBE_YAW=0
MOVEPROBE_FORWARDMOVE=800
MOVEPROBE_SIDEMOVE=0
MOVEPROBE_UPMOVE=0
MOVEPROBE_LOG_COMMANDS=1
MOVEPROBE_LOG_INTERVAL=0
MOVEPROBE_TRANSITION_SCALE=
MOVEPROBE_TRANSITION_WINDOW=
MOVEPROBE_QWD_WAYPOINTS=
MOVEPROBE_QWD_POINT_RADIUS=
MOVEPROBE_QWD_START_RADIUS=
ZTRICKS_BATCH_ATTEMPTS=$attempt_count
ZTRICKS_BATCH_ATTEMPT_SECONDS=$attempt_seconds
START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

acquire_lab_lock
log "starting $session on port $port"
cd "$nq"
screen -L -Logfile "$rundir/screen.log" -dmS "$session" "./$mvdsv_bin" -port "$port" -mem 64 -game ktx +exec "$cfg_name"

server_up=0
for _ in $(seq 1 40); do
  qs="$(quakestat -qws "localhost:$port" -P -nh 2>/dev/null || true)"
  printf '%s\n' "$qs" > "$rundir/quakestat.last"
  if [ -n "$qs" ] && ! printf '%s' "$qs" | grep -q 'DOWN'; then
    server_up=1
    break
  fi
  sleep 0.5
done
if [ "$server_up" -ne 1 ]; then
  echo "Server did not come up on port $port" >&2
  exit 7
fi

send_cmd "set k_fb_enabled 1"
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_auto_delay 1"
send_cmd "set k_fb_skill 10"
send_cmd "map $map_name" 1.0
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_autoremove_at 0"
send_cmd "set sv_getrealip 0"
send_cmd "set sv_timeout 3600"
send_cmd "set k_idletime 0"
send_cmd "set k_matchless_max_idle_time 0"

log "starting keeper client for $keeper_seconds seconds"
python3 "$rundir/qw_min_client.py" "$port" \
  --host 127.0.0.1 \
  --run-for "$keeper_seconds" \
  --bot-count 0 \
  --name KomodoBatchKeep \
  --quiet \
  > "$rundir/pyclient.keeper.stdout" \
  2> "$rundir/pyclient.keeper.stderr" &
keeper_pid=$!
sleep 2.0

send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_${map_name}_${run_id}" 1.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.before-attempts.txt"

printf 'attempt\tstart_utc\tend_utc\tlaunch_vh\tlaunch_angle\tswing\trelease_vh_min\tcarve_d\tcarve_angle\trelease_lip\n' > "$rundir/ztricks-batch-execution.tsv"

{
  read -r _header || true
  while IFS=$'\t' read -r attempt launch_vh launch_angle swing release_min carve_d carve_angle release_lip; do
    if [ -z "${attempt:-}" ]; then
      continue
    fi
    log "attempt $attempt launch_vh=$launch_vh angle=$launch_angle swing=$swing"
    send_cmd 'set k_fb_moveprobe_spawn_origin ""' 0.2
    send_cmd "set k_fb_moveprobe_mode 24" 0.05
    python3 "$rundir/qw_min_client.py" "$port" \
      --host 127.0.0.1 \
      --run-for 5 \
      --bot-count 0 \
      --botcmd removeall \
      --name "KBatchRm${attempt}" \
      --quiet \
      > "$rundir/pyclient.remove.${attempt}.stdout" \
      2> "$rundir/pyclient.remove.${attempt}.stderr"

    send_cmd "set k_fb_moveprobe_mode 23" 0.05
    send_cmd "set k_fb_moveprobe_fixed_goal 8" 0.05
    send_cmd "set k_fb_moveprobe_s23_launch_vh $launch_vh" 0.05
    send_cmd "set k_fb_moveprobe_s23_launch_angle $launch_angle" 0.05
    send_cmd "set k_fb_moveprobe_s21_swing $swing" 0.05
    send_cmd "set k_fb_moveprobe_s23_launch_target_x -3044.1" 0.05
    send_cmd "set k_fb_moveprobe_s23_launch_target_y 3760.5" 0.05
    send_cmd "set k_fb_moveprobe_s23_launch_target_z -488" 0.05
    send_cmd "set k_fb_moveprobe_s23_lip_x -3348" 0.05
    send_cmd "set k_fb_moveprobe_s23_release_vh 470" 0.05
    send_cmd "set k_fb_moveprobe_s23_release_vh_min $release_min" 0.05
    send_cmd "set k_fb_moveprobe_s23_carve_d $carve_d" 0.05
    send_cmd "set k_fb_moveprobe_s23_carve_angle $carve_angle" 0.05
    send_cmd "set k_fb_moveprobe_s23_carve_side 1" 0.05
    send_cmd "set k_fb_moveprobe_s23_release_lip $release_lip" 0.05
    send_cmd "set k_fb_moveprobe_s23_yawlead_min -12" 0.05
    send_cmd "set k_fb_moveprobe_s23_yawlead_max -4" 0.05
    send_cmd "set k_fb_moveprobe_s23_targeterr_min -2" 0.05
    send_cmd "set k_fb_moveprobe_s23_targeterr_max 10" 0.05
    send_cmd 'set k_fb_moveprobe_spawn_origin "-3516.125 3712 -453.125"' 0.35

    start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python3 "$rundir/qw_min_client.py" "$port" \
      --host 127.0.0.1 \
      --run-for "$attempt_seconds" \
      --bot-count 1 \
      --bot-spacing 0 \
      --name "KBatch${attempt}" \
      --quiet \
      > "$rundir/pyclient.attempt.${attempt}.stdout" \
      2> "$rundir/pyclient.attempt.${attempt}.stderr"
    end_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$attempt" "$start_utc" "$end_utc" "$launch_vh" "$launch_angle" "$swing" \
      "$release_min" "$carve_d" "$carve_angle" "$release_lip" \
      >> "$rundir/ztricks-batch-execution.tsv"
  done
} < "$rundir/ztricks-batch-plan.tsv"

send_cmd 'set k_fb_moveprobe_spawn_origin ""' 0.2
python3 "$rundir/qw_min_client.py" "$port" \
  --host 127.0.0.1 \
  --run-for 5 \
  --bot-count 0 \
  --botcmd removeall \
  --name KBatchFinalRm \
  --quiet \
  > "$rundir/pyclient.final-remove.stdout" \
  2> "$rundir/pyclient.final-remove.stderr" || true
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.after-attempts.txt"
send_cmd "sv_demostop" 2.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.final.txt"

demo="$(
  find "$nq/ktx/demos" -maxdepth 1 -type f -name '*.mvd' -newer "$rundir/start.marker" -printf '%T@ %p\n' \
    | sort -n \
    | tail -1 \
    | cut -d' ' -f2-
)"
if [ -z "$demo" ] || [ ! -s "$demo" ]; then
  echo "No non-empty MVD was produced after $rundir/start.marker" >&2
  exit 8
fi

cp -- "$demo" "$rundir/demo.mvd"
printf '%s\n' "$demo" > "$rundir/demo.remote-path.txt"
if [ -f "${demo%.mvd}.txt" ]; then
  cp -- "${demo%.mvd}.txt" "$rundir/demo.txt"
fi
stat -c '%s' "$rundir/demo.mvd" > "$rundir/demo.size"
sha256sum "$rundir/demo.mvd" > "$rundir/demo.sha256"

log "stopping $session"
if [ -n "${keeper_pid:-}" ]; then
  kill "$keeper_pid" >/dev/null 2>&1 || true
fi
screen -S "$session" -X quit
trap - EXIT
release_lab_lock

cat >> "$rundir/run.env" <<EOF
END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEMO_REMOTE_PATH=$demo
EOF
"""


def parse_csv_floats(value: str) -> list[float]:
    values: list[float] = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        values.append(float(stripped))
    if not values:
        raise argparse.ArgumentTypeError("at least one numeric value is required")
    return values


def validate_map_name(map_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_+-]+", map_name):
        raise argparse.ArgumentTypeError("Map names may only contain letters, digits, underscore, plus, or dash.")
    return map_name


def build_attempt_plan(args: argparse.Namespace) -> list[dict[str, float | int]]:
    launch_vh = parse_csv_floats(args.launch_vh)
    launch_angles = parse_csv_floats(args.launch_angle)
    swings = parse_csv_floats(args.swing)
    combos = itertools.cycle(itertools.product(launch_vh, launch_angles, swings))
    plan: list[dict[str, float | int]] = []
    for index in range(1, args.attempts + 1):
        vh, angle, swing = next(combos)
        plan.append(
            {
                "attempt": index,
                "launch_vh": vh,
                "launch_angle": angle,
                "swing": swing,
                "release_vh_min": float(args.release_vh_min),
                "carve_d": float(args.carve_d),
                "carve_angle": float(args.carve_angle),
                "release_lip": float(args.release_lip),
            }
        )
    return plan


def plan_to_tsv(plan: list[dict[str, float | int]]) -> str:
    lines = [
        "attempt\tlaunch_vh\tlaunch_angle\tswing\trelease_vh_min\tcarve_d\tcarve_angle\trelease_lip"
    ]
    for row in plan:
        lines.append(
            "\t".join(
                [
                    str(row["attempt"]),
                    str(row["launch_vh"]),
                    str(row["launch_angle"]),
                    str(row["swing"]),
                    str(row["release_vh_min"]),
                    str(row["carve_d"]),
                    str(row["carve_angle"]),
                    str(row["release_lip"]),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def run_remote_batch(
    *,
    host: str,
    run_id: str,
    port: int,
    map_name: str,
    attempt_seconds: float,
    keeper_seconds: float,
    plan_tsv: str,
    timelimit: int,
    mvdsv_bin: str,
    local_run_dir: Path,
) -> None:
    proc = run(
        [
            "ssh",
            host,
            "bash",
            "-s",
            "--",
            run_id,
            str(port),
            map_name,
            str(attempt_seconds),
            str(keeper_seconds),
            base64.b64encode(plan_tsv.encode("utf-8")).decode("ascii"),
            str(timelimit),
            mvdsv_bin,
        ],
        input_text=REMOTE_BATCH_SCRIPT,
        check=False,
    )
    local_run_dir.mkdir(parents=True, exist_ok=True)
    (local_run_dir / "remote.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "remote.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Remote ztricks batch failed with exit {proc.returncode}; see remote stdout/stderr")


def ensure_batch_prereqs(args: argparse.Namespace) -> None:
    ensure_prereqs(args.host, args.wsl_distro, args.analyzer, args.map_name)
    run(["ssh", args.host, f"test -x ~/nquakesv/{args.lab_mvdsv}"])


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a batched ztricks Distance lab session.")
    parser.add_argument("--host", default="servexeri", help="SSH host. Defaults to servexeri.")
    parser.add_argument("--port", type=int, default=28599, help="Preferred MVDSV UDP port.")
    parser.add_argument("--map", dest="map_name", type=validate_map_name, default="ztricks")
    parser.add_argument("--run-id", type=validate_run_id, default=None)
    parser.add_argument("--attempts", type=int, default=6, help="Number of attempts in the batch.")
    parser.add_argument("--attempt-seconds", type=float, default=8.0, help="Seconds to let each attempt run.")
    parser.add_argument("--launch-vh", default="430,400,360", help="Comma-separated launch_vh sweep.")
    parser.add_argument("--launch-angle", default="50,45,40", help="Comma-separated launch_angle sweep.")
    parser.add_argument("--swing", default="8,14", help="Comma-separated s21 swing sweep.")
    parser.add_argument("--release-vh-min", type=float, default=453.0)
    parser.add_argument("--carve-d", type=float, default=80.0)
    parser.add_argument("--carve-angle", type=float, default=52.0)
    parser.add_argument("--release-lip", type=float, default=35.0)
    parser.add_argument("--timelimit", type=int, default=5, help="KTX timelimit minutes.")
    parser.add_argument(
        "--lab-mvdsv",
        default="mvdsv-lab",
        help="MVDSV binary under ~/nquakesv. Defaults to mvdsv-lab.",
    )
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER)
    parser.add_argument("--strict-port", action="store_true")
    parser.add_argument("--skip-prereq-check", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    if args.attempts <= 0:
        print("--attempts must be positive", file=sys.stderr)
        return 2
    run_id = args.run_id or f"zbatch_{utc_run_id()}"
    local_run_dir = ARTIFACT_ROOT / run_id
    local_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        plan = build_attempt_plan(args)
        plan_tsv = plan_to_tsv(plan)
        (local_run_dir / "ztricks-batch-plan.tsv").write_text(plan_tsv, encoding="utf-8")
        (local_run_dir / "ztricks-batch-plan.json").write_text(
            json.dumps({"schema": "komodobots.ztricks_batch_plan.v1", "attempts": plan}, indent=2) + "\n",
            encoding="utf-8",
        )

        if not args.skip_prereq_check:
            ensure_batch_prereqs(args)

        port = choose_port(args.host, args.port, explicit=args.strict_port)
        upload_shim(args.host, run_id)
        keeper_seconds = args.attempts * (args.attempt_seconds + 8.5) + 15.0
        run_remote_batch(
            host=args.host,
            run_id=run_id,
            port=port,
            map_name=args.map_name,
            attempt_seconds=args.attempt_seconds,
            keeper_seconds=keeper_seconds,
            plan_tsv=plan_tsv,
            timelimit=args.timelimit,
            mvdsv_bin=args.lab_mvdsv,
            local_run_dir=local_run_dir,
        )

        archive_run_demo(args.host, run_id, args.map_name, local_run_dir=local_run_dir)
        scp_from_remote(args.host, run_id, local_run_dir)
        parser_exits = run_analyzer(local_run_dir, args.wsl_distro, args.analyzer)
        movement_metrics = write_movement_metrics(local_run_dir)
        write_moveprobe_command_logs(local_run_dir)
        write_moveprobe_qwd_event_logs(local_run_dir)
        write_moveprobe_replay_event_logs(local_run_dir)
        write_moveprobe_assign_logs(local_run_dir)
        write_summary(local_run_dir, args.host, port, run_id, args.map_name, parser_exits)

        batch_report = score_run_dir(local_run_dir)
        write_outputs(
            batch_report,
            local_run_dir / "ztricks-batch-score.json",
            local_run_dir / "ztricks-batch-score.md",
        )

        print(f"run_id={run_id}")
        print(f"port={port}")
        print(f"artifacts={powershell_safe_path(local_run_dir)}")
        print(f"attempts={batch_report['attempt_count']}")
        print(f"movement_players={len(movement_metrics.get('players', []))}")
        print(render_markdown(batch_report))
        return 0
    except Exception as exc:
        (local_run_dir / "runner.error.txt").write_text(f"{exc}\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"artifacts={local_run_dir}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
