#!/usr/bin/env python3
"""Run the repeatable Komodobots bot smoke lab.

This script is intentionally one-command from the repo root. Prefer the neutral
entry point:

    python scripts/run_bot_lab.py --map dm3

The original frobodm2 path remains valid:

    python scripts/run_frobodm2_lab.py

It starts a temporary MVDSV/KTX server on servexeri, drives Frogbot spawning via
the minimal QuakeWorld client shim, copies the resulting MVD back under
artifacts/lab-runs/<run-id>/, parses it with qw-analyze-v20 in WSL, writes a
small Markdown summary, and stops only the lab screen session it created.

The default map remains frobodm2 because it has a known route file. Use
`--map <name>` for other maps that already have Frogbot route files, such as
`dm3`. Stock `dm2` is intentionally not a Frogbot target here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from extract_movement_metrics import write_movement_metrics


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = REPO_ROOT / "experiments" / "qw_min_client.py"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_ANALYZER = "/home/xerial/qw-sim/bin/qw-analyze-v20"


REMOTE_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

run_id="$1"
port="$2"
duration="$3"
bot_count="$4"
bot_spacing="$5"
map_name="$6"

session="komodobots_lab_${map_name}_${port}_${run_id}"
rundir="$HOME/komodobots-lab/runs/$run_id"
nq="$HOME/nquakesv"
# Keep the +exec filename short. The deployed MVDSV/KTX build crashed before
# executing very long generated config names.
cfg_name="kbot_${map_name}_${port}.cfg"
cfg_path="$nq/ktx/$cfg_name"

mkdir -p "$rundir"
touch "$rundir/start.marker"

log() {
  printf '[remote] %s\n' "$*"
}

session_exists() {
  screen -ls | grep -q "[.]${session}[[:space:]]"
}

send_cmd() {
  local cmd="$1"
  local delay="${2:-0.5}"
  screen -S "$session" -p 0 -X stuff "$(printf '\025%s\r' "$cmd")"
  sleep "$delay"
}

cleanup() {
  set +e
  if session_exists; then
    send_cmd "sv_demostop" 0.5
    screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.cleanup.txt"
    screen -S "$session" -X quit
  fi
}
trap cleanup EXIT

if session_exists; then
  echo "Screen session already exists: $session" >&2
  exit 2
fi

if [ ! -x "$nq/mvdsv" ]; then
  echo "Missing executable: $nq/mvdsv" >&2
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
// Auto-generated Komodobots $map_name lab config $run_id
hostname "komodobots-lab:$port"
set k_motd1 "Komodobots lab $run_id"
set k_matchless 1
set k_use_matchless_dir 1
set k_defmode ffa
set k_mode 3
set k_defmap $map_name
set k_fb_enabled 0
set k_count 0
set k_matchless_countdown 0
timelimit 1
fraglimit 0
samelevel 1
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
serverinfo hostname "komodobots-lab:$port"
EOF
cp "$cfg_path" "$rundir/lab.cfg"

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
START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

log "starting $session on port $port"
cd "$nq"
screen -L -Logfile "$rundir/screen.log" -dmS "$session" ./mvdsv -port "$port" -mem 64 -game ktx +exec "$cfg_name"

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
send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_${map_name}_${run_id}" 1.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.before-client.txt"

log "running client shim"
python3 "$rundir/qw_min_client.py" "$port" \
  --host 127.0.0.1 \
  --run-for "$duration" \
  --bot-count "$bot_count" \
  --bot-spacing "$bot_spacing" \
  > "$rundir/pyclient.stdout" \
  2> "$rundir/pyclient.stderr"

send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.after-client.txt"
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
screen -S "$session" -X quit
trap - EXIT

cat >> "$rundir/run.env" <<EOF
END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEMO_REMOTE_PATH=$demo
EOF
"""


def run(
    args: list[str],
    *,
    input_text: str | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if input_text is None:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
        )
    else:
        raw_proc = subprocess.run(
            args,
            input=input_text.replace("\r\n", "\n").encode("utf-8"),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
        )
        proc = subprocess.CompletedProcess(
            raw_proc.args,
            raw_proc.returncode,
            raw_proc.stdout.decode("utf-8", "replace"),
            raw_proc.stderr.decode("utf-8", "replace"),
        )
    if check and proc.returncode != 0:
        rendered = " ".join(args)
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {rendered}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def powershell_safe_path(path: Path) -> str:
    return str(path.resolve())


def to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise RuntimeError(f"Cannot convert path to WSL form: {resolved}")
    rest = resolved.relative_to(resolved.anchor).as_posix()
    return f"/mnt/{drive}/{rest}"


def remote_port_is_down(host: str, port: int) -> bool:
    proc = run(
        ["ssh", host, f"quakestat -qws localhost:{port} -P -nh 2>/dev/null || true"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not query port {port} on {host}: {proc.stderr.strip()}")
    output = proc.stdout.strip()
    return not output or "DOWN" in output


def choose_port(host: str, requested_port: int, explicit: bool) -> int:
    if remote_port_is_down(host, requested_port):
        return requested_port
    if explicit:
        raise RuntimeError(f"Requested port {requested_port} is already in use on {host}.")

    for port in range(requested_port + 1, requested_port + 51):
        if remote_port_is_down(host, port):
            return port
    raise RuntimeError(f"No free lab port found in {requested_port}-{requested_port + 50}.")


def scp_from_remote(host: str, run_id: str, local_run_dir: Path) -> None:
    local_run_dir.mkdir(parents=True, exist_ok=True)
    source = f"{host}:komodobots-lab/runs/{run_id}/*"
    proc = run(["scp", source, powershell_safe_path(local_run_dir)], check=False)
    (local_run_dir / "scp.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "scp.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"scp failed with exit {proc.returncode}; see scp.stderr")


def run_analyzer(local_run_dir: Path, distro: str, analyzer: str) -> dict[str, int]:
    demo = local_run_dir / "demo.mvd"
    if not demo.is_file() or demo.stat().st_size == 0:
        raise RuntimeError(f"Missing non-empty demo: {demo}")

    wsl_demo = to_wsl_path(demo)
    exits: dict[str, int] = {}
    for mode, output_name in (
        ("json", "analysis.json"),
        ("md", "analysis.md"),
        ("events", "events.txt"),
    ):
        output = local_run_dir / output_name
        error = local_run_dir / f"{output_name}.stderr"
        proc = run(
            ["wsl", "-d", distro, "--", analyzer, "-format", mode, wsl_demo],
            check=False,
        )
        output.write_text(proc.stdout, encoding="utf-8")
        error.write_text(proc.stderr, encoding="utf-8")
        exits[mode] = proc.returncode

    if exits["json"] != 0:
        raise RuntimeError(f"JSON parser failed with exit {exits['json']}; see analysis.json.stderr")
    if exits["md"] != 0:
        raise RuntimeError(f"Markdown parser failed with exit {exits['md']}; see analysis.md.stderr")
    if exits["events"] not in (0, 1):
        raise RuntimeError(f"Events parser failed unexpectedly with exit {exits['events']}; see events.txt.stderr")
    return exits


def first_line(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readline().strip()


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_bot_entries(screen_log: str) -> list[str]:
    entries = []
    for line in screen_log.splitlines():
        match = re.search(r"\] (/[^ ]+|/ [^ ]+) entered the game", line)
        if match:
            name = match.group(1).strip()
            if name not in entries:
                entries.append(name)
    return entries


def write_summary(
    local_run_dir: Path,
    host: str,
    port: int,
    run_id: str,
    map_name: str,
    parser_exits: dict[str, int],
) -> None:
    analysis = read_json(local_run_dir / "analysis.json")
    match = analysis.get("match", {})
    frags = analysis.get("frags", {})
    frag_rows = frags.get("frags", []) or []
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    bots = find_bot_entries(screen_log)
    movement_path = local_run_dir / "movement-metrics.json"
    movement = read_json(movement_path) if movement_path.exists() else {}
    movement_rows = movement.get("players", []) if isinstance(movement, dict) else []
    demo_sha = first_line(local_run_dir / "demo.sha256")
    demo_size = first_line(local_run_dir / "demo.size")
    remote_demo = first_line(local_run_dir / "demo.remote-path.txt")
    route_present_original = ""
    route_used = ""
    route_file = ""
    run_env = local_run_dir / "run.env"
    if run_env.exists():
        for line in run_env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ROUTE_FILE_PRESENT_ORIGINAL="):
                route_present_original = line.split("=", 1)[1]
            elif line.startswith("ROUTE_FILE_USED="):
                route_used = line.split("=", 1)[1]
            elif line.startswith("ROUTE_FILE="):
                route_file = line.split("=", 1)[1]
    events_stderr = (local_run_dir / "events.txt.stderr").read_text(encoding="utf-8", errors="replace").strip()

    lines = [
        f"# {map_name} lab run {run_id}",
        "",
        "## Run",
        "",
        f"- Host: `{host}`",
        f"- Port: `{port}`",
        f"- Map command: `{map_name}`",
        f"- Route file originally present: `{route_present_original}`",
        f"- Route file used: `{route_used}`",
        f"- Route file: `{route_file}`",
        f"- Remote demo: `{remote_demo}`",
        f"- Local demo: `{local_run_dir / 'demo.mvd'}`",
        f"- Demo size: `{demo_size}` bytes",
        f"- Demo SHA-256: `{demo_sha.split()[0] if demo_sha else ''}`",
        "",
        "## Parser",
        "",
        f"- JSON exit: `{parser_exits['json']}`",
        f"- Markdown exit: `{parser_exits['md']}`",
        f"- Events exit: `{parser_exits['events']}`",
    ]
    if events_stderr:
        lines.append(f"- Events stderr: `{events_stderr}`")

    lines.extend(
        [
            "",
            "## Analysis",
            "",
            f"- Map title: `{match.get('map', '')}`",
            f"- Duration: `{match.get('duration', '')}` ms",
            f"- Total frags: `{frags.get('totalFrags', '')}`",
            f"- Bots observed in server log: `{', '.join(bots)}`",
            "",
            "## Movement",
            "",
            f"- Movement metrics: `{local_run_dir / 'movement-metrics.md'}`",
        ]
    )

    if movement_rows:
        for player in movement_rows:
            try:
                over_maxspeed = f"{float(player.get('over_maxspeed_time_ratio', 0.0)) * 100.0:.1f}%"
            except (TypeError, ValueError):
                over_maxspeed = ""
            lines.append(
                f"- `{player.get('name')}`: avg `{player.get('avg_horizontal_speed_qu_per_s')}` qu/s, "
                f"max `{player.get('max_horizontal_speed_qu_per_s')}` qu/s, "
                f"p95 `{player.get('p95_horizontal_speed_qu_per_s')}` qu/s, "
                f"over maxspeed `{over_maxspeed}`"
            )
    else:
        lines.append("- No named-player movement metrics recorded.")

    lines.extend(
        [
            "",
            "## Frags",
            "",
        ]
    )

    if frag_rows:
        for frag in frag_rows:
            lines.append(
                f"- `{frag.get('time')}` ms: `{frag.get('killer')}` killed "
                f"`{frag.get('victim')}` with `{frag.get('weapon')}`"
            )
    else:
        lines.append("- No frags recorded in parser summary.")

    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"One-command {map_name} lab run completed: server started, MVD copied, parser summary written, and the lab screen session stopped.",
            "",
        ]
    )
    (local_run_dir / "run-summary.md").write_text("\n".join(lines), encoding="utf-8")


def ensure_prereqs(host: str, distro: str, analyzer: str, map_name: str) -> None:
    for tool in ("ssh", "scp", "wsl", "python"):
        require_tool(tool)
    if not SHIM_PATH.is_file():
        raise RuntimeError(f"Missing shim: {SHIM_PATH}")

    remote_check = (
        "python3 --version >/dev/null && "
        "command -v screen >/dev/null && "
        "command -v quakestat >/dev/null && "
        "test -x ~/nquakesv/mvdsv && "
        f"test -f ~/nquakesv/qw/maps/{map_name}.bsp"
    )
    run(["ssh", host, remote_check])
    run(["wsl", "-d", distro, "--", "bash", "-lc", f"test -x {analyzer!r}"])


def upload_shim(host: str, run_id: str) -> None:
    remote_dir = f"komodobots-lab/runs/{run_id}"
    run(["ssh", host, f"mkdir -p {remote_dir}"])
    run(["scp", powershell_safe_path(SHIM_PATH), f"{host}:{remote_dir}/qw_min_client.py"])


def run_remote_lab(
    host: str,
    run_id: str,
    port: int,
    duration: float,
    bot_count: int,
    bot_spacing: float,
    map_name: str,
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
            str(duration),
            str(bot_count),
            str(bot_spacing),
            map_name,
        ],
        input_text=REMOTE_SCRIPT,
        check=False,
    )
    local_run_dir.mkdir(parents=True, exist_ok=True)
    (local_run_dir / "remote.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "remote.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Remote lab failed with exit {proc.returncode}; see remote.stdout and remote.stderr")


def validate_map_name(map_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_+-]+", map_name):
        raise argparse.ArgumentTypeError("Map names may only contain letters, digits, underscore, plus, or dash.")
    return map_name


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise argparse.ArgumentTypeError("Run IDs may only contain letters, digits, underscore, or dash.")
    return run_id


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-command Komodobots bot lab.")
    parser.add_argument("--host", default="servexeri", help="SSH host. Defaults to servexeri.")
    parser.add_argument("--port", type=int, default=28599, help="Preferred MVDSV UDP port. Defaults to 28599.")
    parser.add_argument("--map", dest="map_name", type=validate_map_name, default="frobodm2", help="Map to load. Defaults to frobodm2.")
    parser.add_argument("--run-id", type=validate_run_id, default=None, help="Run ID. Defaults to current UTC timestamp.")
    parser.add_argument("--duration", type=float, default=45.0, help="Client run duration in seconds. Defaults to 45.")
    parser.add_argument("--bot-count", type=int, default=2, help="Number of botcmd addbot commands. Defaults to 2.")
    parser.add_argument("--bot-spacing", type=float, default=8.0, help="Seconds between bot adds. Defaults to 8.")
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04", help="WSL distro for parser. Defaults to Ubuntu-24.04.")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER, help="Path to qw-analyze-v20 inside WSL.")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail if --port is in use instead of automatically trying the next 50 ports.",
    )
    parser.add_argument(
        "--skip-prereq-check",
        action="store_true",
        help="Skip local/remote prerequisite checks.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    run_id = args.run_id or utc_run_id()
    local_run_dir = ARTIFACT_ROOT / run_id
    local_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_prereq_check:
            ensure_prereqs(args.host, args.wsl_distro, args.analyzer, args.map_name)

        port = choose_port(args.host, args.port, explicit=args.strict_port)
        upload_shim(args.host, run_id)
        run_remote_lab(
            args.host,
            run_id,
            port,
            args.duration,
            args.bot_count,
            args.bot_spacing,
            args.map_name,
            local_run_dir,
        )
        scp_from_remote(args.host, run_id, local_run_dir)
        parser_exits = run_analyzer(local_run_dir, args.wsl_distro, args.analyzer)
        movement_metrics = write_movement_metrics(local_run_dir)
        write_summary(local_run_dir, args.host, port, run_id, args.map_name, parser_exits)

        summary = local_run_dir / "run-summary.md"
        metrics_summary = local_run_dir / "movement-metrics.md"
        print(f"run_id={run_id}")
        print(f"port={port}")
        print(f"map={args.map_name}")
        print(f"artifacts={summary.parent}")
        print(f"summary={summary}")
        print(f"movement_metrics={metrics_summary}")
        print(f"movement_players={len(movement_metrics.get('players', []))}")
        print(f"parser_exits={parser_exits}")
        return 0
    except Exception as exc:
        (local_run_dir / "runner.error.txt").write_text(f"{exc}\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"artifacts={local_run_dir}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
