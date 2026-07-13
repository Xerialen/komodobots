// Data layer for the Dragonbot goals & metrics feed (dragonbot.hub_feed.v1),
// produced on Xerialen/dragonbot main at artifacts/hub/goals-metrics.json and
// mirrored to the hub by lab/server/dragonbot_hub_feed_build.py (issue #483 —
// companion to the dragonbot repo's own feed ticket, PR #56).
//
// Fetch pattern mirrors kb2Feed.ts's useKb2Versions: the frontend never talks
// to GitHub directly. lab/server/dragonbot_hub_feed_build.py runs on servexeri
// (same host/cadence as version_history_build.py — a PAT read from
// ~/.git-credentials or $GITHUB_TOKEN, throttled to ~hourly since the feed
// only changes when a batch-of-record merges), fetches the committed JSON via
// the GitHub REST contents API, and atomically writes it to
// /demos/records/dragonbot-hub-feed.json — the same-origin static path this
// module polls.
//
// Fail-closed, two layers:
//  1. The build script never overwrites its output on a failed/invalid
//     upstream fetch, so the served file is always the last GOOD snapshot.
//  2. This module never overwrites in-memory state with a failed fetch
//     either — `stale` flips true (rendered as a banner by DragonbotPanel)
//     but `feed` keeps the last successfully parsed snapshot. A brand-new
//     page load that has never seen a good snapshot renders the plain empty
//     state, not a stale banner (nothing to consider stale yet).
//
// `fetchedUtc` is added by the build script and is NOT part of the upstream
// dragonbot.hub_feed.v1 schema — the schema itself carries no generation
// timestamp (it is a committed artifact, not a live-rendered one). It lets
// the panel flag a build-side-stale snapshot (the static file fetch itself
// succeeded, but the build script has not refreshed it recently) separately
// from an outright fetch failure.

import { useEffect, useState } from "react";
import { logError } from "./logger.ts";

export const DRAGONBOT_SCHEMA = "dragonbot.hub_feed.v1";

export interface DragonbotMetricSource {
  path: string;
  pointer: string;
  measured?: boolean;
}

// A measured stat: either a mean/sigma (gaussian-shaped metrics like
// fragMargin/dmgDiff/sg.accuracy) or a quantile band (p25/median/p75, used by
// the G2 elite bands). `reason` explains a null/absent value honestly (e.g.
// "predates schema-version stamping") — render it, never substitute 0.
export interface DragonbotStatValue {
  mean?: number | null;
  sigma?: number | null;
  sem?: number | null;
  p25?: number | null;
  median?: number | null;
  p75?: number | null;
  n?: number | null;
  reason?: string | null;
  source?: DragonbotMetricSource | DragonbotMetricSource[];
}

// A derived value per the schema's {value, reason, derivation} shape (e.g.
// meanDelta, z-score).
export interface DragonbotDerivedValue {
  value: number | null;
  reason?: string | null;
  derivation?: unknown;
}

// Two-arm (ABBA) comparison: reference vs treatment stats plus derived
// meanDelta/z.
export interface DragonbotArmComparison {
  reference?: DragonbotStatValue | null;
  treatment?: DragonbotStatValue | null;
  meanDelta?: DragonbotDerivedValue | null;
  z?: DragonbotDerivedValue | null;
}

// A batch's per-metric entry is null (not measured, e.g. sg.accuracy before
// analyzer schema 57), a plain stat (control_batch), or an ABBA comparison
// (abba_experiment).
export type DragonbotBatchMetric = DragonbotStatValue | DragonbotArmComparison | null;

export function isArmComparison(m: DragonbotBatchMetric): m is DragonbotArmComparison {
  return !!m && (("reference" in m) || ("treatment" in m));
}

export interface DragonbotGoal {
  id: string;
  title: string;
  controlBatchId?: string;
  metrics: Record<string, DragonbotStatValue | null>;
  reference?: string;
  validityCaveat?: string;
}

export interface DragonbotDecision {
  schema: string;
  metric: string;
  direction: string; // "higher_better" | "lower_better"
  minEffect: number | null;
  referenceValue: number | null;
  treatmentValue: number | null;
  scoreDelta: number | null;
  passed: boolean;
  reason: string | null;
  decision: string;
  source?: DragonbotMetricSource;
}

export type TacticalVerdict = "COMPLIANT" | "DEVIANT" | "INCONCLUSIVE";

export interface DragonbotEval {
  schema: string;
  truthVerdict: string; // "CLEAN" | "SUSPECT"
  tacticalTally: { compliant: number; deviant: number; inconclusive: number };
  byLens: Record<string, Record<TacticalVerdict, number>>;
  evaluatedMatches: string[];
  reportPaths: string[];
  source?: DragonbotMetricSource;
}

export interface DragonbotBatch {
  batchId: string;
  date: string;
  role: string; // "control" | "gate"
  title: string;
  kind: string; // "control_batch" | "abba_experiment"
  arms: string[];
  validMatches: number | Record<string, number>;
  invalidMatches: number | Record<string, number>;
  metrics: Record<string, DragonbotBatchMetric>;
  analyzerSchemaVersion: number | null;
  decision: DragonbotDecision | null;
  eval: DragonbotEval | null;
  notes?: string[];
  analyzerSchemaVersionSource?: DragonbotMetricSource;
}

export interface DragonbotHubFeed {
  schema: string; // "dragonbot.hub_feed.v1"
  goals: DragonbotGoal[];
  batches: DragonbotBatch[];
  /** Build-script metadata — see module docstring. Not part of the upstream schema. */
  fetchedUtc?: string;
}

const PRIMARY_URL = "/demos/records/dragonbot-hub-feed.json";
const FIXTURE_URL = "/botlab/data/dragonbot-hub-feed.example.json";
export const DRAGONBOT_REFRESH_MS = 60 * 60 * 1000; // hourly — matches the build cadence

export function dragonbotDataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("dragonbot_src");
  if (explicit) return explicit;
  return params.get("fixture") === "dragonbot" ? FIXTURE_URL : PRIMARY_URL;
}

// Same override-param convention as ?matches_src=/?versions_src=/?bench_src=,
// applied to the poll cadence rather than the URL: lets a browser test force
// a fast re-poll (to exercise the stale-fallback path) instead of waiting out
// the real hourly cadence. Defaults to DRAGONBOT_REFRESH_MS when absent/invalid.
export function dragonbotRefreshMs(): number {
  const raw = new URLSearchParams(window.location.search).get("dragonbot_refresh_ms");
  const n = raw != null ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : DRAGONBOT_REFRESH_MS;
}

function isValidFeed(d: unknown): d is DragonbotHubFeed {
  if (!d || typeof d !== "object") return false;
  const obj = d as Record<string, unknown>;
  return (
    obj.schema === DRAGONBOT_SCHEMA &&
    Array.isArray(obj.goals) &&
    Array.isArray(obj.batches)
  );
}

export interface DragonbotFeedState {
  /** Last successfully fetched + shape-validated feed, or null if none yet. */
  feed: DragonbotHubFeed | null;
  /** True when the most recent fetch failed/was invalid AND a prior good
   * snapshot exists — the panel renders that snapshot plus a stale banner. */
  stale: boolean;
  /** Human-readable reason for the most recent failure, if any. */
  error: string | null;
}

export function useDragonbotFeed(): DragonbotFeedState {
  const [state, setState] = useState<DragonbotFeedState>({ feed: null, stale: false, error: null });
  const url = dragonbotDataUrl();
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () => {
      fetch(url)
        .then((res) => {
          if (!res.ok) throw new Error(`${url} ${res.status}`);
          return res.json();
        })
        .then((d) => {
          if (cancelled) return;
          if (!isValidFeed(d)) {
            throw new Error(`invalid dragonbot feed shape (schema=${String((d as Record<string, unknown> | null)?.schema)})`);
          }
          setState({ feed: d, stale: false, error: null });
        })
        .catch((exc) => {
          logError("dragonbot feed fetch failed", exc, { url });
          if (cancelled) return;
          // Fail-closed: never clear a previously-good snapshot on failure.
          // `stale` is only meaningful once we HAVE a prior snapshot; a
          // brand-new unreachable feed is an empty state, not a stale one.
          setState((prev) => ({
            feed: prev.feed,
            stale: prev.feed !== null,
            error: String(exc instanceof Error ? exc.message : exc),
          }));
        })
        .finally(() => {
          if (!cancelled) timer = window.setTimeout(load, dragonbotRefreshMs());
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [url]);
  return state;
}

// Build-side staleness: the static file fetch succeeded, but
// dragonbot_hub_feed_build.py has not refreshed it recently (its own GitHub
// fetch has been failing). Independent of (and additive to) fetch-failure
// staleness above.
export function isSnapshotStale(feed: DragonbotHubFeed | null, maxAgeMs = 3 * 60 * 60 * 1000): boolean {
  if (!feed?.fetchedUtc) return false;
  const t = Date.parse(feed.fetchedUtc);
  if (Number.isNaN(t)) return false;
  return Date.now() - t > maxAgeMs;
}

// --- formatting helpers (render nulls honestly — never as 0) ---

export function fmtStat(stat: DragonbotStatValue | null | undefined, digits = 2): string {
  if (!stat) return "—";
  if (stat.mean != null) {
    const sign = stat.mean > 0 ? "+" : "";
    const mean = `${sign}${stat.mean.toFixed(digits)}`;
    if (stat.sigma != null) return `${mean} ± ${stat.sigma.toFixed(digits)}`;
    if (stat.sem != null) return `${mean} ± ${stat.sem.toFixed(digits)} (sem)`;
    return mean;
  }
  if (stat.median != null) {
    const p25 = stat.p25 != null ? stat.p25.toFixed(digits) : "—";
    const p75 = stat.p75 != null ? stat.p75.toFixed(digits) : "—";
    return `${p25} – ${stat.median.toFixed(digits)} – ${p75}`;
  }
  return "—";
}

export function fmtStatN(stat: DragonbotStatValue | null | undefined): string {
  return stat?.n != null ? `n=${stat.n}` : "";
}

export function fmtDerived(d: DragonbotDerivedValue | null | undefined, digits = 3): string {
  if (!d || d.value == null) return "—";
  const sign = d.value > 0 ? "+" : "";
  return `${sign}${d.value.toFixed(digits)}`;
}

export function fmtMatchCount(v: number | Record<string, number> | undefined | null): string {
  if (v == null) return "—";
  if (typeof v === "number") return String(v);
  return Object.entries(v)
    .map(([arm, n]) => `${arm}=${n}`)
    .join(" · ");
}

// GitHub blob link for a report path committed to Xerialen/dragonbot main
// (e.g. "artifacts/baselines/2026-07-13-gateD/EVAL-ref-m02.md").
export const DRAGONBOT_REPO = "Xerialen/dragonbot";

export function dragonbotGithubBlobHref(path: string): string {
  return `https://github.com/${DRAGONBOT_REPO}/blob/main/${path}`;
}
