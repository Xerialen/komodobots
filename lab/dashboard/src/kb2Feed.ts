// Data layer for the komodobots2 match-history feed (komodobots.kb2_matches.v2,
// built by lab/server/kb2_matches_build.py and served at
// /demos/records/kb2-matches.json), the bench live feed (/v2/servers/bench,
// written by kb2 bench_poller.py, which infers liveness from the harness
// write pattern on lanister — a run dir without run-meta.json is in
// progress) and the version-history feed (komodobots.kb2_versions.v1).
//
// All fetches degrade gracefully: a 404 renders as an empty state, never an
// error page — the dashboard must stay usable while a feed is still being
// wired up on the hub.

import { useEffect, useState } from "react";
import { logError } from "./logger.ts";

// --- komodobots.kb2_matches.v2 ---

export interface Kb2Side {
  team: string | null;
  brain: string | null;
  version: string | null;
}

export interface Kb2Player {
  name: string;
  team: string;
  frags: number;
  deaths: number;
  dmg_given: number;
  dmg_taken: number;
  // v2 (owner requirement 2026-07-07): powerups, RL/LG pickups, direct RL
  // hits and taken-to-die per player per match. Optional so a stale v1 feed
  // still renders (columns show "—").
  quad?: number;
  pent?: number;
  ring?: number;
  rl_pickups?: number;
  lg_pickups?: number;
  rl_direct_hits?: number;
  rl_attacks?: number;
  taken_to_die?: number | null;
  avg_speed?: number | null;
  max_speed?: number | null;
}

// Per-lane jump attempt accounting (v2). attempts = actual launches
// (LAND + FAIL_*); declines = approaches that never launched.
export interface Kb2JumpLaneCounts {
  attempts: number;
  lands: number;
  fails: number;
  declines: number;
}

export interface Kb2MatchJumps {
  attempts: number;
  lands: number;
  fails: number;
  declines: number;
  lanes: Record<string, Kb2JumpLaneCounts>;
}

export interface Kb2JumpLaneAggregate extends Kb2JumpLaneCounts {
  matches: number;
  land_rate: number | null;
  last_land_utc: string | null;
}

export interface Kb2Match {
  run_id: string;
  started_utc: string | null;
  ended_utc: string | null;
  ok: boolean;
  error: string | null;
  map: string;
  port: number | null;
  timelimit: number | null;
  duration_s: number | null;
  candidate: Kb2Side;
  control: Kb2Side;
  team_frags: Record<string, number>;
  frag_margin: number | null;
  winner: string | null; // team name | "draw" | null
  cvars: Record<string, string>;
  features: string[];
  in_ledger: boolean;
  demo: { name: string | null; url: string | null };
  players: Kb2Player[];
  jumps: Kb2MatchJumps;
}

export interface Kb2Jump {
  run_id: string;
  map: string;
  t_s: number;
  lane: string;
  name: string | null;
  team: string | null;
  hdist: number;
  peak_speed: number;
  tair: number;
  watch_url: string | null;
}

export interface Kb2Aggregate {
  matches: number;
  wins: number;
  losses: number;
  draws: number;
  margin_total: number;
  margin_mean: number | null;
  best: { run_id: string; frag_margin: number } | null;
}

export interface Kb2RecordHolder extends Kb2Aggregate {
  key: string;
}

export interface Kb2LedgerBench {
  games_scored: number;
  candidate_wins: number;
  control_wins: number;
  draws: number;
  frag_margin_mean: number | null;
  frag_margin_stdev?: number | null;
  frag_margin_total?: number | null;
}

export interface Kb2Feed {
  schema: string;
  generated_utc: string;
  source: { data_dir: string; runs_scanned: number; runs_included: number };
  matches: Kb2Match[];
  jumps: Kb2Jump[];
  jump_lanes?: Record<string, Kb2JumpLaneAggregate>;
  features: Record<string, Kb2Aggregate>;
  configs: Record<string, Kb2Aggregate>;
  record_holder: {
    feature: Kb2RecordHolder | null;
    config: Kb2RecordHolder | null;
  };
  ledger: { bench: Record<string, Kb2LedgerBench>; valid_games: number | null };
}

const KB2_PRIMARY_URL = "/demos/records/kb2-matches.json";
const KB2_FIXTURE_URL = "/botlab/data/kb2-matches.example.json";
export const KB2_REFRESH_MS = 30000;

export function kb2DataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("matches_src");
  if (explicit) return explicit;
  return params.get("fixture") === "kb2" ? KB2_FIXTURE_URL : KB2_PRIMARY_URL;
}

// Shared polling fetch: null while loading or on failure (callers render an
// empty state), refreshed every KB2_REFRESH_MS.
function usePolledJson<T>(url: string, refreshMs: number): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () => {
      fetch(url)
        .then((res) => {
          if (!res.ok) throw new Error(`${url} ${res.status}`);
          return res.json() as Promise<T>;
        })
        .then((d) => {
          if (!cancelled) setData(d);
        })
        .catch((exc) => {
          // 404 = feed not deployed yet; keep whatever we had.
          logError("kb2 feed fetch failed", exc, { url });
        })
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(load, refreshMs);
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [url, refreshMs]);
  return data;
}

export function useKb2Feed(): Kb2Feed | null {
  return usePolledJson<Kb2Feed>(kb2DataUrl(), KB2_REFRESH_MS);
}

// --- bench live feed (/v2/servers/bench) ---

export interface BenchServer {
  address: string; // "192.168.86.34:28600"
  hostname?: string;
  map?: string;
  status?: string; // "Standby" | "Countdown" | "3 min left" ...
  players: Array<{ name: string; team?: string; frags?: number }>;
  team_frags?: Record<string, number>;
  time?: { elapsed?: number; total?: number; remaining?: number };
  // What the FTE pane should qtvplay through the relay, e.g.
  // "tcp:192.168.86.34:28600". Written by the poller so the transport
  // decision (direct LAN vs loopback forward) lives server-side.
  qtv_upstream?: string;
}

const BENCH_URL = "/v2/servers/bench";
export const BENCH_REFRESH_MS = 10000;

export function benchDataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("bench_src") || BENCH_URL;
}

export function useBenchServers(): BenchServer[] {
  const data = usePolledJson<BenchServer[]>(benchDataUrl(), BENCH_REFRESH_MS);
  return Array.isArray(data) ? data : [];
}

// A bench match counts as live when bots are actually seated on the server —
// a lone empty "Standby" server is idle, not live.
export function benchIsLive(servers: BenchServer[]): boolean {
  return servers.some((s) => (s.players?.length ?? 0) > 0);
}

// --- komodobots.kb2_versions.v1 ---

export interface Kb2Version {
  merged_at: string;
  pr: number | null;
  title: string;
  name: string; // short human name, e.g. "Harvester"
  summary: string; // jargon-free explanation (owner language)
  stamps: string[]; // candidate_version stamps this merge shipped as
  bench: {
    games: number;
    margin_mean: number | null;
    wins: number;
    losses: number;
  } | null;
  test_matches: number; // scratch/uncounted matches seen in the lab feed
}

export interface Kb2VersionsFeed {
  schema: string;
  generated_utc: string;
  repo: string;
  versions: Kb2Version[];
}

const VERSIONS_PRIMARY_URL = "/demos/records/kb2-versions.json";
const VERSIONS_FIXTURE_URL = "/botlab/data/kb2-versions.example.json";

export function versionsDataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("versions_src");
  if (explicit) return explicit;
  return params.get("fixture") === "kb2"
    ? VERSIONS_FIXTURE_URL
    : VERSIONS_PRIMARY_URL;
}

export function useKb2Versions(): Kb2VersionsFeed | null {
  return usePolledJson<Kb2VersionsFeed>(versionsDataUrl(), KB2_REFRESH_MS * 4);
}

// --- shared formatting helpers ---

export function fmtDuration(s: number | null): string {
  if (s == null || !Number.isFinite(s)) return "—";
  // Round the total first so e.g. 299.7 renders "5:00", never "4:60".
  const t = Math.round(s);
  const m = Math.floor(t / 60);
  return `${m}:${(t % 60).toString().padStart(2, "0")}`;
}

export function fmtUtc(iso: string | null): string {
  if (!iso) return "—";
  // 2026-07-07T02:29:51Z -> "07-07 02:29"
  const m = iso.match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : iso;
}

export function fmtMargin(margin: number | null): string {
  if (margin == null) return "—";
  return margin > 0 ? `+${margin}` : `${margin}`;
}
