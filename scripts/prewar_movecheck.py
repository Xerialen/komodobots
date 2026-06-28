#!/usr/bin/env python3
"""Prewar movement-test harness for the live MoveMLP brain (LOCAL box).

Stands up N KTX Frogbots (--bots, default 1) on dm3 in PREWAR/warmup (k_matchless
0), with their MOVE driven by the learned "mode 30" sidecar, records a server MVD,
and PROVES the learned model actually drove movement via the same per-frame
freshness gate the 4v4 validation lab uses (not the silent stock frogbot fallback).

With --bots 1 there are no opponents -> no shooting (the lone-mover case). With
--bots >1 they share the ffa server and WILL fight in warmup, so it is no longer a
pure no-shooting movement check -- it just stands several movers up to watch.

Unlike run_4v4_validation_lab.py this runs everything on the LOCAL box (this is
aws-dev: build/test here) -- no SSH, no scp, no prod ports. It reuses the two pure
helpers from that runner so the cvar block and the freshness gate stay one
definition:

  * build_leap_cvar_block  -- the mode-30 / shm / stale-tick / live-log cvars
  * evaluate_live_freshness -- the per-frame live=L/T gate over screen.log

Prewar single-bot specifics (mirrors run_frobodm2_lab.py's prewar path):
  * k_matchless 0 + k_use_matchless_dir 1, ffa mode (k_defmode ffa, k_mode 3);
  * k_fb_enabled MUST be 1 at world spawn in non-matchless mode -- flipping it at
    runtime with no players segfaults this KTX build (frobodm2 runner, ~line 182);
  * the spectator shim holds client edict 1; the N bots added after it seat at
    edicts 2..N+1, logged under moveprobe slots 1..N (slot = edict - 1).

Usage (writes a GREEN/RED verdict + freshness.json + the .mvd path to stdout):

    python scripts/prewar_movecheck.py --port 28599 --run-for 90 --bots 4

On a harness that reaps the tool-call process group on return (aws-dev), launch it
detached and poll for the freshness.json it writes, e.g.:

    setsid python scripts/prewar_movecheck.py --port 28599 --run-for 90 \
        > /tmp/pw.out 2>&1 < /dev/null &

The mvdsv server and the sidecar are already setsid-daemonized internally, so they
survive regardless; only the ~run-for-second foreground block needs detaching.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
LAB_SERVER_DIR = REPO_ROOT / "lab" / "server"
for import_path in (SCRIPT_DIR, LAB_SERVER_DIR):
    text = str(import_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from run_4v4_validation_lab import build_leap_cvar_block, evaluate_live_freshness  # noqa: E402

NQ = Path("/home/ubuntu/nquakesv")
SHIM = REPO_ROOT / "experiments" / "qw_min_client.py"

DEFAULT_SHM_NAME = "komodo_move_t07_prewar"
DEFAULT_STALE_TICKS = 3
DEFAULT_SIDECAR_PYTHON = "/home/ubuntu/t0.3-venv/bin/python"
DEFAULT_SIDECAR_SCRIPT = "/home/ubuntu/komodo-t0.3/scripts/move_policy_sidecar.py"
DEFAULT_SIDECAR_CKPT = "/home/ubuntu/move_bc_policy.pt"
DEFAULT_SIDECAR_HZ = 77
DEFAULT_BOTS = 1
MAX_BOTS = 8

LOGGER = logging.getLogger(__name__)

# Accountability ledger (#424): every live attempt appends one row here so it is
# indexed + viewable in the dashboard gallery ("no success claim without a
# linked, viewable recording"). cloud_hub serves this dir at /demos/records/ and
# falls back to bot-attempts.example.json before the first real run.
LEDGER_SCHEMA = "komodobots.bot_attempts.v1"
LEDGER_PATH = REPO_ROOT / "lab" / "dashboard" / "public" / "data" / "bot-attempts.json"


def _freshness_summary(report: dict) -> dict:
    """Glanceable freshness for a ledger row from an evaluate_live_freshness report.

    Carries the per-run pass flag plus the most conservative (minimum) per-slot
    live fraction, so a multi-bot run is summarised by its weakest-driven bot.
    """
    slots = report.get("slots") or {}
    fractions = [
        s.get("fraction")
        for s in slots.values()
        if isinstance(s.get("fraction"), (int, float)) and not isinstance(s.get("fraction"), bool)
    ]
    return {
        "ok": bool(report.get("ok", False)),
        "live_fraction": round(min(fractions), 4) if fractions else None,
        "min_fraction": report.get("min_fraction"),
    }


def build_attempt_record(*, run_id: str, ts_utc: str, map_name: str, n_bots: int,
                         demo_name: str | None, demo_url: str | None,
                         freshness_report: dict, verdict_green: bool,
                         artifact_dir: str) -> dict:
    """Build the single per-attempt ledger record (pure -> unit-tested).

    demo is null on a RED attempt that produced no usable MVD: the missing
    recording is itself the accountability signal, not an error to hide.
    """
    return {
        "run_id": run_id,
        "ts_utc": ts_utc,
        "map": map_name,
        "n_bots": n_bots,
        "mode": "prewar-movecheck",
        "demo": {"name": demo_name, "url": demo_url} if demo_name else None,
        "freshness": _freshness_summary(freshness_report),
        "verdict": "GREEN" if verdict_green else "RED",
        "artifact_dir": artifact_dir,
    }


def _emit_attempt_ledger(ledger_path: Path, record: dict, *, map_name: str) -> dict:
    """Prepend `record` to the bot-attempts ledger (newest-first), creating it if
    absent. Returns the written ledger. A corrupt/unreadable existing ledger is
    replaced rather than allowed to crash the run.

    ponytail: a flat JSON file, not a DB -- the ledger is a few KB of one-row-per
    -attempt accountability records; append-and-rewrite is plenty.
    """
    ledger = {"schema": LEDGER_SCHEMA, "map": map_name, "attempts": []}
    if ledger_path.exists():
        try:
            existing = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("attempts"), list):
                ledger = existing
        except (OSError, ValueError):
            LOGGER.warning("unreadable attempt ledger at %s; starting fresh", ledger_path)
    ledger["schema"] = LEDGER_SCHEMA
    ledger["map"] = map_name
    ledger["attempts"] = [record] + list(ledger.get("attempts", []))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ledger


def bot_edicts_and_slots(bots: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Edicts to arm with mode 30, and the moveprobe slots to freshness-gate.

    The spectator shim holds client edict 1; the N bots added after it seat at
    edicts 2..N+1, which KTX logs as moveprobe slots 1..N (slot = edict - 1). We
    arm mode 30 on edict 1 (harmless on the spectator) plus all bot edicts so the
    run is robust to exact seating, and gate the bot slots 1..N.
    """
    edicts = tuple(range(1, bots + 2))
    slots = tuple(range(1, bots + 1))
    return edicts, slots


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def screen_stuff(session: str, cmd: str, delay: float = 0.5) -> None:
    """Send a console command to the mvdsv screen session (Ctrl-U + cmd + CR)."""
    payload = "\025" + cmd + "\r"
    subprocess.run(
        ["screen", "-S", session, "-p", "0", "-X", "stuff", payload],
        check=False,
    )
    time.sleep(delay)


def session_exists(session: str) -> bool:
    out = subprocess.run(["screen", "-ls"], capture_output=True, text=True).stdout
    return f".{session}\t" in out or f".{session} " in out


def port_is_down(port: int) -> bool:
    out = subprocess.run(
        ["quakestat", "-qws", f"localhost:{port}", "-P", "-nh"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return not out or "DOWN" in out


def write_cfg(cfg_path: Path, *, port: int, map_name: str, timelimit: int,
              shm_name: str, stale_ticks: int, bot_edicts: tuple[int, ...]) -> None:
    leap_cvars = build_leap_cvar_block(shm_name, stale_ticks, leap_edicts=bot_edicts)
    cfg = f"""// Auto-generated Komodobots prewar movecheck config
hostname "komodobots-prewar:{port}"
set k_motd1 "Komodobots prewar movecheck"
set k_matchless 0
set k_use_matchless_dir 1
set k_allowed_free_modes 4095
set k_defmode ffa
set k_mode 3
set k_defmap {map_name}
set k_fb_enabled 1
set k_count 0
set k_matchless_countdown 0
set k_fb_autoadd_limit 0
set k_fb_autoremove_at 0
set k_fb_auto_delay 1
set k_fb_skill 10
deathmatch 1
timelimit {timelimit}
fraglimit 0
samelevel 1
set sv_getrealip 0
set sv_login 0
set sv_timeout 3600
set k_idletime 0
set k_matchless_max_idle_time 0
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
serverinfo hostname "komodobots-prewar:{port}"
{leap_cvars}"""
    cfg_path.write_text(cfg, encoding="utf-8")


def start_sidecar_waiter(run_dir: Path, shm_name: str, py: str, script: str,
                         ckpt: str, hz: int) -> subprocess.Popen:
    """Background process: poll for /dev/shm/<shm> (KTX creates it when the first
    mode-30 bot spawns), then exec the sidecar mirroring that region. Mirrors the
    4v4 runner's REMOTE_SCRIPT waiter, locally."""
    shm_path = f"/dev/shm/{shm_name}"
    Path(shm_path).unlink(missing_ok=True)
    sidecar_log = run_dir / "sidecar.log"
    started_marker = run_dir / "sidecar.started"
    waiter = f"""
set -e
for _ in $(seq 1 120); do
  [ -e "{shm_path}" ] && break
  sleep 0.5
done
if [ -e "{shm_path}" ]; then
  echo "[prewar] sidecar attaching to {shm_path}"
  touch "{started_marker}"
  cd "{Path(script).parent}"
  exec "{py}" "{script}" --shm-name "{shm_name}" --ckpt "{ckpt}" --hz "{hz}"
else
  echo "[prewar] WARN: {shm_path} never appeared; sidecar not started" >&2
fi
"""
    log_fh = sidecar_log.open("w")
    # setsid: daemonize the waiter into its own session so a parent-process reaper
    # (e.g. a sandbox that group-kills the launching shell) cannot take it down
    # mid-run. The harness on aws-dev reaps the tool-call process group on return,
    # which would otherwise kill an undetached sidecar; the live brain must outlive
    # the launch call and serve for the whole run.
    return subprocess.Popen(
        ["setsid", "bash", "-c", waiter],
        stdout=log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Prewar MoveMLP movecheck, N bots (local).")
    p.add_argument("--port", type=int, default=28599,
                   help="Scratch lab port in 28599..28609 (NOT a prod port).")
    p.add_argument("--bots", type=int, default=DEFAULT_BOTS,
                   help=f"Number of mode-30 bots to add (1..{MAX_BOTS}). "
                        "NOTE: with >1 bot they share the ffa server and WILL "
                        "fight in warmup -- not the lone 'no shooting' case.")
    p.add_argument("--map", dest="map_name", default="dm3")
    p.add_argument("--timelimit", type=int, default=10, help="KTX timelimit (min); outlasts the run.")
    p.add_argument("--run-for", type=float, default=90.0, help="Seconds the bot moves before teardown.")
    p.add_argument("--shm-name", default=DEFAULT_SHM_NAME)
    p.add_argument("--stale-ticks", type=int, default=DEFAULT_STALE_TICKS)
    p.add_argument("--sidecar-python", default=DEFAULT_SIDECAR_PYTHON)
    p.add_argument("--sidecar-script", default=DEFAULT_SIDECAR_SCRIPT)
    p.add_argument("--sidecar-ckpt", default=DEFAULT_SIDECAR_CKPT)
    p.add_argument("--sidecar-hz", type=int, default=DEFAULT_SIDECAR_HZ)
    p.add_argument("--min-live-fraction", type=float, default=0.5)
    p.add_argument("--out-root", type=Path, default=REPO_ROOT / "experiments" / "prewar-movecheck")
    args = p.parse_args(argv)

    if not 28599 <= args.port <= 28609:
        print(f"ERROR: port {args.port} not in scratch range 28599..28609", file=sys.stderr)
        return 2
    if not 1 <= args.bots <= MAX_BOTS:
        print(f"ERROR: --bots {args.bots} not in 1..{MAX_BOTS}", file=sys.stderr)
        return 2

    bot_edicts, bot_slots = bot_edicts_and_slots(args.bots)
    run_id = utc_run_id()
    run_dir = args.out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    session = f"komodobots_prewar_{args.port}_{run_id}"
    cfg_name = f"kbot_prewar_{args.port}.cfg"
    cfg_path = NQ / "ktx" / cfg_name
    screen_log = run_dir / "screen.log"
    demo_name = f"prewar_movecheck_{args.map_name}_{run_id}"
    start_marker = run_dir / "start.marker"

    # Preflight.
    for path, what in ((NQ / "mvdsv", "mvdsv binary"),
                       (NQ / "qw" / "maps" / f"{args.map_name}.bsp", "map"),
                       (NQ / "ktx" / "bots" / "maps" / f"{args.map_name}.bot", "route file"),
                       (SHIM, "client shim"),
                       (Path(args.sidecar_ckpt), "checkpoint")):
        if not path.exists():
            print(f"ERROR: missing {what}: {path}", file=sys.stderr)
            return 3
    if not port_is_down(args.port):
        print(f"ERROR: port {args.port} already serving QuakeWorld", file=sys.stderr)
        return 3
    if session_exists(session):
        print(f"ERROR: screen session already exists: {session}", file=sys.stderr)
        return 3

    sidecar_proc: subprocess.Popen | None = None
    try:
        write_cfg(cfg_path, port=args.port, map_name=args.map_name,
                  timelimit=args.timelimit, shm_name=args.shm_name,
                  stale_ticks=args.stale_ticks, bot_edicts=bot_edicts)
        (run_dir / "lab.cfg").write_text(cfg_path.read_text(), encoding="utf-8")
        start_marker.touch()

        # Launch mvdsv in a logged screen session. setsid daemonizes the screen so
        # it survives a parent-process-group reaper (see start_sidecar_waiter); the
        # detached `screen -dmS` itself double-forks, but setsid makes the survival
        # explicit and matches the manual-run path proven on aws-dev.
        subprocess.run(
            ["setsid", "screen", "-L", "-Logfile", str(screen_log), "-dmS", session,
             "./mvdsv", "-port", str(args.port), "-mem", "64", "-game", "ktx",
             "+exec", cfg_name],
            cwd=str(NQ), check=True, stdin=subprocess.DEVNULL,
        )

        up = False
        for _ in range(60):
            if not port_is_down(args.port):
                up = True
                break
            time.sleep(0.5)
        if not up:
            print("ERROR: server did not come up", file=sys.stderr)
            return 7

        # Prewar settings + load map. Mirror the frobodm2 prewar re-assert flow.
        screen_stuff(session, "set k_fb_enabled 1")
        screen_stuff(session, "set k_fb_autoadd_limit 0")
        screen_stuff(session, "set k_fb_autoremove_at 0")
        screen_stuff(session, "set k_fb_skill 10")
        screen_stuff(session, f"map {args.map_name}", 1.5)
        screen_stuff(session, "set k_fb_autoadd_limit 0")
        screen_stuff(session, "set k_fb_autoremove_at 0")
        screen_stuff(session, "set sv_getrealip 0")
        screen_stuff(session, "set sv_login 0")
        screen_stuff(session, "set sv_timeout 3600")
        screen_stuff(session, "set k_idletime 0")
        screen_stuff(session, "set k_matchless_max_idle_time 0")
        screen_stuff(session, "deathmatch 1")
        screen_stuff(session, f"timelimit {args.timelimit}")
        screen_stuff(session, "fraglimit 0")

        # Start the sidecar waiter BEFORE the bot spawns so it attaches the
        # instant KTX creates the shm region.
        sidecar_proc = start_sidecar_waiter(
            run_dir, args.shm_name, args.sidecar_python, args.sidecar_script,
            args.sidecar_ckpt, args.sidecar_hz,
        )

        # Start server-side MVD recording (proven path from both lab runners).
        screen_stuff(session, "sv_democancel")
        screen_stuff(session, f"sv_demoeasyrecord {demo_name}", 1.0)
        screen_stuff(session, "status")

        # Spectator shim: hold edict 1, add N bots (edicts 2..N+1), keep the client
        # connected so the server demo + bot sim stay alive for the run. `removeall`
        # first clears any stragglers; then one `addbot 10` per requested bot (all
        # fired once at sign-on), each seating at the next free edict.
        addbot_args: list[str] = []
        for _ in range(args.bots):
            addbot_args += ["--botcmd", "addbot 10"]
        client = subprocess.run(
            [sys.executable, str(SHIM), str(args.port),
             "--host", "127.0.0.1", "--spectator", "--name", "KomodoPrewar",
             "--run-for", str(args.run_for), "--bot-count", "0",
             "--botcmd", "removeall", *addbot_args],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        (run_dir / "pyclient.stdout").write_text(client.stdout, encoding="utf-8")
        (run_dir / "pyclient.stderr").write_text(client.stderr, encoding="utf-8")

        # Stop recording, locate the demo.
        screen_stuff(session, "status")
        screen_stuff(session, "sv_demostop", 2.0)
        screen_stuff(session, "status")

        demos_dir = NQ / "ktx" / "demos"
        candidates = [
            f for f in demos_dir.glob("*.mvd")
            if f.stat().st_mtime > start_marker.stat().st_mtime and f.stat().st_size > 0
        ]
        demo = max(candidates, key=lambda f: f.stat().st_mtime) if candidates else None

        # Freshness gate over screen.log (the proven per-frame live=L/T gate).
        time.sleep(0.5)  # let screen.log flush
        fresh_ok, report = evaluate_live_freshness(
            run_dir, leap_slots=bot_slots, min_fraction=args.min_live_fraction,
        )
        (run_dir / "freshness.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Report.
        print("=" * 60)
        print("PREWAR MOVECHECK RESULT")
        print("=" * 60)
        print(f"run_id        : {run_id}")
        print(f"port          : {args.port}")
        print(f"screen.log    : {screen_log}")
        if demo is not None:
            print(f"MVD demo      : {demo}  ({demo.stat().st_size} bytes)")
        else:
            print("MVD demo      : NONE PRODUCED")
        print(f"freshness.json: {run_dir / 'freshness.json'}")
        print(f"bots          : {args.bots} (slots {bot_slots})")
        for slot in bot_slots:
            slot_info = report.get("slots", {}).get(str(slot), {})
            if slot_info:
                print(f"bot slot {slot}    : live={slot_info.get('live_frames')}/"
                      f"{slot_info.get('total_frames')} "
                      f"(fraction={slot_info.get('fraction')}, "
                      f"{slot_info.get('live_loglines')}L/"
                      f"{slot_info.get('fallback_loglines')}F loglines)")
            else:
                print(f"bot slot {slot}    : NO moveprobe-live lines for this slot")

        demo_ok = demo is not None and demo.stat().st_size > 50_000
        verdict_green = fresh_ok and demo_ok
        if not demo_ok:
            print("DEMO        : RED (missing or < 50 KB)")
        print()
        print(f"VERDICT     : {'GREEN' if verdict_green else 'RED'} "
              f"(learned model drove movement: {fresh_ok}; "
              f"non-trivial MVD: {demo_ok})")

        # Accountability ledger (#424): index this attempt + its served watch URL.
        demo_filename = demo.name if demo is not None else None
        record = build_attempt_record(
            run_id=run_id,
            ts_utc=datetime.now(timezone.utc).isoformat(),
            map_name=args.map_name,
            n_bots=args.bots,
            demo_name=demo_filename,
            demo_url=(f"/demos/online/{demo_filename}" if demo_filename else None),
            freshness_report=report,
            verdict_green=verdict_green,
            artifact_dir=str(run_dir.relative_to(REPO_ROOT)),
        )
        ledger = _emit_attempt_ledger(LEDGER_PATH, record, map_name=args.map_name)
        print(f"attempt ledger: {LEDGER_PATH} ({len(ledger['attempts'])} attempts; "
              f"publish it to prod alongside the .mvd)")
        return 0 if verdict_green else 1

    finally:
        # Teardown: stop sidecar, quit mvdsv, unlink shm, remove cfg.
        if sidecar_proc is not None:
            sidecar_proc.terminate()
            try:
                sidecar_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sidecar_proc.kill()
        subprocess.run(
            ["pkill", "-f", f"move_policy_sidecar.py --shm-name {args.shm_name}"],
            check=False,
        )
        if session_exists(session):
            screen_stuff(session, "sv_demostop", 0.5)
            subprocess.run(["screen", "-S", session, "-X", "quit"], check=False)
        Path(f"/dev/shm/{args.shm_name}").unlink(missing_ok=True)
        cfg_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
