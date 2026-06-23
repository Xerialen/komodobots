// LD-E2 (#101): The brutal scoreboard — four metric rows rendered inside the
// KPI dock.  Each row shows a value vs its target/reference with a clear
// pass / close / fail verdict framing.  "Brutal" = honest zeros everywhere,
// never hides a bad number, never celebrates prematurely.
//
// The four KPIs, per lab/SPEC.md §7:
//   1. The Race      — finishes/attempts + median_time as ×human
//   2. Jump Count    — N / 11 censused dm3 routes completed, ever
//   3. Speedometer   — bot record active-mean speed as % of human speed
//                      + decisive edge sub-line
//   4. Eye Test      — data-suggested state + latest user certification
//                      (LD-F5 #106: user decision 2026-06-10: no pass/close/fail
//                       — user certifies human-level reached, rarely, passively)
//
// Data sources:
//   - records.json  (RECORDS_URL, same path as DemoPane)
//   - verdicts.json (VERDICTS_URL, lives beside records.json)
//
// Update cadence: fetch on mount + on every `refreshKey` change.
//
// Rail-mode numbers: the parent (KpiDock) renders four micro-glyphs in rail
// mode; export RailScoreboard for that case.

import { useCallback, useEffect, useRef, useState } from "react";
import type { KpiContext } from "./contextStore.ts";
import type { ControlClient } from "./controlClient.ts";
import { logError, logWarn } from "./logger.ts";

// ---------------------------------------------------------------------------
// Types — records schema (komodobots.records.v1), partial
// ---------------------------------------------------------------------------

type RecordKind = "fastest_time" | "first_completion" | "peak_speed" | "edge_speed" | "active_mean_speed";

interface HumanRef {
  value: number;
  source: string;
}

interface RecordEntry {
  value: number;
  units: string;
  run_id: string;
  human_ref: HumanRef | null;
}

interface RouteAggregates {
  attempts: number;
  finishes: number;
  median_time_s: number | null;
  human_time_s: number;
}

interface RouteRecords {
  records: Partial<Record<RecordKind, RecordEntry | null>>;
  aggregates: RouteAggregates;
}

interface RecordsJson {
  schema: string;
  maps: Record<string, { routes: Record<string, RouteRecords> }>;
}

// ---------------------------------------------------------------------------
// Types — verdicts schema (komodobots.verdicts.v2)
// LD-F5 (#106) user decision 2026-06-10: sparse certifications, not three-state.
// ---------------------------------------------------------------------------

interface CertificationEntry {
  date: string;  // ISO date YYYY-MM-DD
  note?: string | null;
}

interface VerdictsJson {
  schema: string;
  /** route -> list of dated certifications (sparse, append-only). */
  certifications: Record<string, CertificationEntry[]>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RECORDS_URL = "/demos/records/records.json";
const VERDICTS_URL = "/demos/records/verdicts.json";

/** The 11 censused dm3 routes in difficulty order (rung 1 = easiest). */
const DM3_ROUTES_ORDERED = [
  "sng_shortcut2",
  "hilljump",
  "rl_to_ya",
  "ring_to_mega",
  "ra_jumps",
  "mega_to_rl",
  "rl_to_bridge",
  "sng_shortcut",
  "sng_to_rl",
  "mega_to_window",
  "sng_jumps",
] as const;

const TOTAL_DM3_ROUTES = DM3_ROUTES_ORDERED.length; // 11

// ---------------------------------------------------------------------------
// Derived scoreboard state
// ---------------------------------------------------------------------------

/** All four KPI values derived from records + verdicts. */
interface ScoreboardState {
  /** The Race: finishes/attempts for the context route (or overall), xhuman median. */
  race: {
    finishes: number;
    attempts: number;
    /** Median finish time as a multiple of the human census time; null if no finishes. */
    multipleOfHuman: number | null;
  };
  /** Jump Count: how many of the 11 dm3 routes the bot has EVER completed. */
  jumpCount: {
    completed: number; // N
    total: number;     // 11
    /** Whether the CONTEXT route specifically has been completed. */
    contextRouteCompleted: boolean | null;
  };
  /** Speedometer: bot's best active-mean speed as % of human on context route. */
  speedometer: {
    /** Bot active_mean_speed record value (qu/s), best run, or null. */
    botSpeed: number | null;
    /** Human active_mean_speed from census. */
    humanSpeed: number | null;
    /** Percentage, or null if either number is missing. */
    pct: number | null;
    /** For the decisive edge sub-line: edge_speed record vs human edge speed ref. */
    edge: {
      botEdgeSpeed: number | null;
      humanEdgeSpeed: number | null;
      pct: number | null;
    } | null;
  };
  /**
   * Eye Test: latest user certification + data-suggested state.
   * LD-F5 (#106): certification (user declares human-level reached) or null.
   */
  eyeTest: {
    /** Most recent certification, or null if never certified. */
    latestCertification: CertificationEntry | null;
    /** Data-suggested state derived from the other scoreboard numbers. */
    suggestedLabel: string;
  };
  /** Freshness: when was data last fetched (ISO string). */
  fetchedAt: string | null;
  /** Whether the data has been fetched at least once. */
  loaded: boolean;
  /** Fetch error, if any. */
  error: string | null;
}

// ---------------------------------------------------------------------------
// Data fetching hook
// ---------------------------------------------------------------------------

/** Derive scoreboard state from records + verdicts for the given context. */
function deriveScoreboard(
  records: RecordsJson | null,
  verdicts: VerdictsJson | null,
  context: KpiContext,
): ScoreboardState {
  const base: ScoreboardState = {
    race: { finishes: 0, attempts: 0, multipleOfHuman: null },
    jumpCount: { completed: 0, total: TOTAL_DM3_ROUTES, contextRouteCompleted: null },
    speedometer: { botSpeed: null, humanSpeed: null, pct: null, edge: null },
    eyeTest: { latestCertification: null, suggestedLabel: "no data yet" },
    fetchedAt: null,
    loaded: false,
    error: null,
  };

  if (!records) return base;

  const dm3MapData = records.maps["dm3"];
  if (!dm3MapData) return { ...base, loaded: true };

  // ---- Jump Count (always dm3-scope, regardless of context route) -----------
  let completedCount = 0;
  let contextRouteCompleted: boolean | null = null;

  for (const routeName of DM3_ROUTES_ORDERED) {
    const routeData = dm3MapData.routes[routeName];
    const hasCompletion =
      routeData?.records?.first_completion != null;
    if (hasCompletion) completedCount++;
    if (routeName === context.route) {
      contextRouteCompleted = hasCompletion;
    }
  }

  // ---- The Race ------------------------------------------------------------
  let raceFinishes = 0;
  let raceAttempts = 0;
  let raceMultiple: number | null = null;

  if (context.route && dm3MapData.routes[context.route]) {
    // Route-context: single route aggregates.
    const agg = dm3MapData.routes[context.route].aggregates;
    raceFinishes = agg.finishes;
    raceAttempts = agg.attempts;
    if (agg.finishes > 0 && agg.median_time_s != null && agg.human_time_s > 0) {
      raceMultiple = agg.median_time_s / agg.human_time_s;
    }
  } else {
    // Overall mode: sum across all dm3 routes.
    for (const routeData of Object.values(dm3MapData.routes)) {
      raceFinishes += routeData.aggregates.finishes;
      raceAttempts += routeData.aggregates.attempts;
    }
    // Overall median multiple: median across routes that have data (per #101).
    const multiples: number[] = [];
    for (const routeData of Object.values(dm3MapData.routes)) {
      const agg = routeData.aggregates;
      if (agg.finishes > 0 && agg.median_time_s != null && agg.human_time_s > 0) {
        multiples.push(agg.median_time_s / agg.human_time_s);
      }
    }
    if (multiples.length > 0) {
      const sorted = [...multiples].sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      raceMultiple =
        sorted.length % 2 === 1
          ? sorted[mid]
          : (sorted[mid - 1] + sorted[mid]) / 2;
    }
  }

  // ---- Speedometer ---------------------------------------------------------
  let botSpeed: number | null = null;
  let humanSpeed: number | null = null;
  let speedPct: number | null = null;
  let edgeInfo: ScoreboardState["speedometer"]["edge"] = null;

  if (context.route && dm3MapData.routes[context.route]) {
    const routeData = dm3MapData.routes[context.route];

    // Bot speed: use active_mean_speed record (whole-route active-mean, per SPEC §7.3).
    // edge_speed is the decisive-edge sub-line only; peak_speed is not the Speedometer KPI.
    const amsRec = routeData.records?.active_mean_speed;
    if (amsRec) {
      botSpeed = amsRec.value;
      if (amsRec.human_ref) {
        humanSpeed = amsRec.human_ref.value;
      }
    }
    if (botSpeed != null && humanSpeed != null && humanSpeed > 0) {
      speedPct = (botSpeed / humanSpeed) * 100;
    }

    // Decisive edge sub-line: edge_speed record.
    const edgeRec = routeData.records?.edge_speed;
    if (edgeRec) {
      const botEdgeSpeed = edgeRec.value;
      const humanEdgeSpeed = edgeRec.human_ref?.value ?? null;
      const edgePct =
        botEdgeSpeed != null && humanEdgeSpeed != null && humanEdgeSpeed > 0
          ? (botEdgeSpeed / humanEdgeSpeed) * 100
          : null;
      edgeInfo = { botEdgeSpeed, humanEdgeSpeed, pct: edgePct };
    }
  }

  // ---- Eye Test ------------------------------------------------------------
  // Data-suggested state: derived from the quantitative scoreboard numbers.
  let suggestedLabel = "data: not yet suggested";
  if (speedPct != null && raceMultiple != null) {
    if (speedPct >= 100 && raceMultiple <= 1.0) {
      suggestedLabel = "data suggests: human-level";
    } else if (speedPct >= 80 && raceMultiple <= 1.25) {
      suggestedLabel = "data suggests: close";
    } else {
      suggestedLabel = "data suggests: not yet";
    }
  }

  // Latest user certification for this route.
  let latestCertification: CertificationEntry | null = null;
  if (verdicts?.certifications && context.route) {
    const certs = verdicts.certifications[context.route];
    if (Array.isArray(certs) && certs.length > 0) {
      latestCertification = certs[certs.length - 1];
    }
  }

  return {
    race: { finishes: raceFinishes, attempts: raceAttempts, multipleOfHuman: raceMultiple },
    jumpCount: {
      completed: completedCount,
      total: TOTAL_DM3_ROUTES,
      contextRouteCompleted,
    },
    speedometer: { botSpeed, humanSpeed, pct: speedPct, edge: edgeInfo },
    eyeTest: { latestCertification, suggestedLabel },
    fetchedAt: new Date().toISOString(),
    loaded: true,
    error: null,
  };
}

/** Fetch records + verdicts and derive the scoreboard state for the given context. */
function useScoreboardData(
  context: KpiContext,
  refreshKey: number,
): ScoreboardState & { refetch: () => void } {
  const [state, setState] = useState<ScoreboardState>({
    race: { finishes: 0, attempts: 0, multipleOfHuman: null },
    jumpCount: { completed: 0, total: TOTAL_DM3_ROUTES, contextRouteCompleted: null },
    speedometer: { botSpeed: null, humanSpeed: null, pct: null, edge: null },
    eyeTest: { latestCertification: null, suggestedLabel: "no data yet" },
    fetchedAt: null,
    loaded: false,
    error: null,
  });

  const [localKey, setLocalKey] = useState(0);

  const refetch = useCallback(() => setLocalKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      fetch(RECORDS_URL).then((r) => {
        if (!r.ok) throw new Error(`records.json: HTTP ${r.status}`);
        return r.json() as Promise<RecordsJson>;
      }),
      fetch(VERDICTS_URL).then((r) => {
        if (!r.ok) {
          // Verdicts file may not exist yet (404 = no certifications entered).
          return null as VerdictsJson | null;
        }
        return r.json() as Promise<VerdictsJson>;
      }).catch((err: unknown) => {
        logWarn("verdicts feed unavailable", { url: VERDICTS_URL, error: err });
        return null as VerdictsJson | null;
      }),
    ])
      .then(([records, verdicts]) => {
        if (cancelled) return;
        setState({
          ...deriveScoreboard(records, verdicts, context),
          loaded: true,
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        logError("scoreboard fetch failed", err, { recordsUrl: RECORDS_URL, verdictsUrl: VERDICTS_URL });
        setState((prev) => ({
          ...prev,
          loaded: true,
          error: String(err instanceof Error ? err.message : err),
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [context.map, context.route, refreshKey, localKey]);

  return { ...state, refetch };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** A single metric row in the scoreboard. */
function MetricRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-y-0.5 py-2 border-b border-slate-800 last:border-b-0">
      <span className="text-[10px] uppercase tracking-wider text-gray-600">
        {label}
      </span>
      <div className="flex flex-col gap-y-0.5">{children}</div>
    </div>
  );
}

/** Positive/negative delta indicator. */
function Delta({ value, goodDirection }: { value: number; goodDirection: "up" | "down" }) {
  const positive = value >= 0;
  const good = goodDirection === "up" ? positive : !positive;
  const color = good ? "text-green-400" : "text-red-400";
  const sign = positive ? "+" : "";
  return (
    <span className={`font-mono text-xs ${color}`}>
      {sign}{value.toFixed(1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// LD-F5 (#106): Certify Human-Level control
// ---------------------------------------------------------------------------

interface CertifyHumanLevelProps {
  context: KpiContext;
  controlClient: ControlClient;
  onSuccess: () => void;
}

/**
 * Passive, user-initiated certification control for the Eye Test KPI.
 *
 * User decision 2026-06-10 (issue #106): no nag prompts, no pass/close/fail.
 * The user declares human-level reached manually: one "certify human-level"
 * button, optional note, rarely used.  Requires a route in context.
 */
function CertifyHumanLevel({ context, controlClient, onSuccess }: CertifyHumanLevelProps) {
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastCertDate, setLastCertDate] = useState<string | null>(null);

  // Reset when route changes.
  const routeKey = context.route ?? "__none__";
  const prevRouteRef = useRef(routeKey);
  if (prevRouteRef.current !== routeKey) {
    prevRouteRef.current = routeKey;
    setExpanded(false);
    setNote("");
    setError(null);
    setLastCertDate(null);
  }

  const hasRoute = context.route != null;

  const handleCertify = async () => {
    if (!hasRoute || !context.route) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await controlClient.verdict(
        context.map,
        context.route,
        note.trim() || undefined,
      );
      if (res.ok) {
        const date = (res as { date?: string }).date ?? new Date().toISOString().slice(0, 10);
        setLastCertDate(date);
        setExpanded(false);
        setNote("");
        onSuccess();
      } else {
        setError(res.detail ?? "certification failed");
      }
    } catch (err: unknown) {
      logError("human-level certification request failed", err, { map: context.map, route: context.route });
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!hasRoute) {
    return (
      <div className="mt-1.5 text-[10px] text-gray-700 italic">
        select a route to certify
      </div>
    );
  }

  if (!controlClient.connected) {
    return (
      <div className="mt-1.5 text-[10px] text-gray-700 italic">
        bridge disconnected — connect to certify
      </div>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-y-1.5" data-certify-form>
      {lastCertDate && !expanded && (
        <div className="text-[10px] text-green-400 font-mono">
          certified {lastCertDate}
        </div>
      )}
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full px-2 py-1 rounded text-[10px] font-mono bg-slate-900/40 text-gray-500 border border-dashed border-slate-700 hover:border-slate-500 hover:text-gray-300 text-left"
        >
          certify human-level…
        </button>
      ) : (
        <>
          <div className="text-[10px] text-amber-300 font-mono">
            declare: {context.route} has reached human-level
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="optional note (max 200 chars)..."
            maxLength={200}
            rows={2}
            disabled={submitting}
            className="w-full text-[10px] font-mono bg-slate-900/60 border border-slate-700 rounded px-1.5 py-1 text-gray-300 placeholder-gray-700 resize-none focus:outline-none focus:border-slate-500 disabled:opacity-40"
          />
          <div className="flex gap-x-1">
            <button
              type="button"
              disabled={submitting}
              onClick={handleCertify}
              className="flex-1 px-2 py-1 rounded text-[10px] font-mono bg-green-900/50 text-green-300 border border-green-700 hover:bg-green-900/70 disabled:opacity-40"
            >
              {submitting ? "saving..." : "certify"}
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={() => { setExpanded(false); setNote(""); setError(null); }}
              className="px-2 py-1 rounded text-[10px] font-mono bg-slate-900/40 text-gray-500 border border-slate-700 hover:border-slate-500 disabled:opacity-40"
            >
              cancel
            </button>
          </div>
        </>
      )}
      {error && (
        <div className="text-[10px] text-red-400 border border-red-900/40 rounded px-1.5 py-0.5 bg-red-950/10">
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main scoreboard component (expanded dock)
// ---------------------------------------------------------------------------

interface BrutalScoreboardProps {
  context: KpiContext;
  /** External refresh trigger -- incremented when an attempt ends. */
  refreshKey?: number;
  /**
   * LD-F5 (#106): control bridge client for the eye-test certification control.
   * Optional: when absent the certification control is not rendered (e.g. rail mode,
   * or tests that don't need it).
   */
  controlClient?: ControlClient;
}

export function BrutalScoreboard({
  context,
  refreshKey = 0,
  controlClient,
}: BrutalScoreboardProps) {
  const sb = useScoreboardData(context, refreshKey);

  if (!sb.loaded) {
    return (
      <div
        data-section="scoreboard"
        className="py-2 text-[10px] text-gray-600 animate-pulse text-center"
      >
        loading scoreboard...
      </div>
    );
  }

  if (sb.error) {
    return (
      <div
        data-section="scoreboard"
        className="py-2 px-2 text-[10px] text-red-400 border border-red-900/40 rounded bg-red-950/10"
      >
        scoreboard error: {sb.error}
      </div>
    );
  }

  const { race, jumpCount, speedometer, eyeTest } = sb;
  const hasRoute = context.route != null;

  // Race: north-star target <=x1.0; v1 milestone <=x1.25 (SPEC §7 table, #101)
  const RACE_NS_TARGET = 1.0;      // end state: match human
  const RACE_V1_TARGET = 1.25;     // v1 milestone: first-usable
  const raceMultipleFail =
    race.multipleOfHuman != null && race.multipleOfHuman > RACE_V1_TARGET * 2;
  const raceMultipleClose =
    race.multipleOfHuman != null &&
    race.multipleOfHuman > RACE_V1_TARGET &&
    !raceMultipleFail;

  // Speedometer: north-star >=100%; v1 milestone >=80% (SPEC §7 table, #101)
  const SPEED_NS_TARGET = 100;
  const SPEED_V1_TARGET = 80;

  return (
    <div data-section="scoreboard" className="flex flex-col">
      {/* ---- 1. The Race ---- */}
      <MetricRow label="The Race">
        <div className="flex items-baseline gap-x-2">
          <span className="font-mono text-base text-gray-200">
            {race.finishes}
            <span className="text-gray-500 text-xs">/{race.attempts}</span>
          </span>
          <span className="text-[10px] text-gray-600">
            {hasRoute ? "finishes on route" : "total finishes"}
          </span>
          {race.attempts === 0 && (
            <span className="ml-auto text-[10px] text-gray-600">no data yet</span>
          )}
        </div>

        {/* xhuman line */}
        <div className="flex items-baseline gap-x-2">
          {race.multipleOfHuman != null ? (
            <>
              <span
                className={`font-mono text-sm ${
                  raceMultipleFail
                    ? "text-red-400"
                    : raceMultipleClose
                      ? "text-amber-300"
                      : "text-green-400"
                }`}
              >
                x{race.multipleOfHuman.toFixed(1)}
              </span>
              <span className="text-[10px] text-gray-600">
                {"median vs human · "}
                <span className="text-gray-500">{"target ≤×"}{RACE_NS_TARGET.toFixed(1)}</span>
                <span className="text-gray-700">{" (v1 ≤×"}{RACE_V1_TARGET}{")"}</span>
              </span>
            </>
          ) : (
            <span className="text-[10px] text-gray-600">
              {race.finishes === 0 ? "no finishes yet" : "time data unavailable"}
            </span>
          )}
        </div>
      </MetricRow>

      {/* ---- 2. Jump Count ---- */}
      <MetricRow label="Jump Count">
        <div className="flex items-baseline gap-x-2">
          <span className="font-mono text-base text-gray-200">
            {jumpCount.completed}
            <span className="text-gray-500 text-xs">/{jumpCount.total}</span>
          </span>
          <span className="text-[10px] text-gray-600">dm3 routes completed ever</span>
          {jumpCount.completed === 0 && (
            <span className="ml-auto text-[10px] text-red-400 font-mono">0/11</span>
          )}
        </div>

        {/* Context-route indicator */}
        {hasRoute && jumpCount.contextRouteCompleted != null && (
          <div className="flex items-center gap-x-1.5">
            <span
              className={`text-[10px] font-mono ${
                jumpCount.contextRouteCompleted ? "text-green-400" : "text-red-400"
              }`}
            >
              {jumpCount.contextRouteCompleted ? "v" : "x"}
            </span>
            <span className="text-[10px] text-gray-600">
              {context.route}
              {jumpCount.contextRouteCompleted ? " completed" : " never completed"}
            </span>
          </div>
        )}

        {/* Progress bar: N/11 */}
        <div className="mt-0.5">
          <div className="flex gap-x-0.5">
            {DM3_ROUTES_ORDERED.map((name) => {
              const isDone = (() => {
                // We can't know per-route completion without re-fetching here;
                // use context route as a hint.
                if (jumpCount.contextRouteCompleted && name === context.route) return true;
                return false;
              })();
              return (
                <div
                  key={name}
                  title={name}
                  className={`h-1 flex-1 rounded-sm ${isDone ? "bg-green-500" : "bg-slate-700"}`}
                />
              );
            })}
          </div>
          <div className="text-[9px] text-gray-600 mt-0.5">
            target: 1/11 then climb to 11/11
          </div>
        </div>
      </MetricRow>

      {/* ---- 3. Speedometer ---- */}
      <MetricRow label="Speedometer">
        {hasRoute ? (
          <>
            <div className="flex items-baseline gap-x-2">
              {speedometer.pct != null ? (
                <>
                  <span
                    className={`font-mono text-base ${
                      speedometer.pct >= SPEED_NS_TARGET
                        ? "text-green-400"
                        : speedometer.pct >= SPEED_V1_TARGET
                          ? "text-amber-300"
                          : "text-red-400"
                    }`}
                  >
                    {speedometer.pct.toFixed(0)}%
                  </span>
                  <span className="text-[10px] text-gray-600">
                    {"active-mean vs human · "}
                    <span className="text-gray-500">{"target ≥"}{SPEED_NS_TARGET}{"%"}</span>
                    <span className="text-gray-700">{" (v1 ≥"}{SPEED_V1_TARGET}{"%)"}</span>
                  </span>
                </>
              ) : (
                <span className="text-[10px] text-gray-600">no speed data yet</span>
              )}
            </div>

            {/* Bot vs human speeds */}
            {speedometer.botSpeed != null && (
              <div className="flex items-center gap-x-1 text-[10px] text-gray-600 font-mono">
                <span className="text-amber-300">{Math.round(speedometer.botSpeed)}</span>
                <span>vs</span>
                <span className="text-cyan-700">
                  {speedometer.humanSpeed != null ? Math.round(speedometer.humanSpeed) : "?"}
                </span>
                <span className="font-sans">qu/s active-mean</span>
              </div>
            )}

            {/* Decisive edge sub-line */}
            {speedometer.edge && (
              <div className="mt-0.5 px-1.5 py-1 rounded bg-slate-900/60 border border-slate-800">
                <div className="text-[10px] text-gray-600 mb-0.5 uppercase tracking-wider">
                  decisive edge
                </div>
                <div className="flex items-baseline gap-x-1.5 font-mono text-xs">
                  {speedometer.edge.botEdgeSpeed != null ? (
                    <span
                      className={
                        speedometer.edge.humanEdgeSpeed != null &&
                        speedometer.edge.botEdgeSpeed >= speedometer.edge.humanEdgeSpeed
                          ? "text-green-400"
                          : "text-red-400"
                      }
                    >
                      {Math.round(speedometer.edge.botEdgeSpeed)}
                    </span>
                  ) : (
                    <span className="text-gray-600">-</span>
                  )}
                  {speedometer.edge.humanEdgeSpeed != null && (
                    <>
                      <span className="text-gray-600">/</span>
                      <span className="text-gray-500">
                        needs {Math.round(speedometer.edge.humanEdgeSpeed)}
                      </span>
                    </>
                  )}
                  {speedometer.edge.pct != null && (
                    <>
                      <span className="text-gray-700">.</span>
                      <Delta
                        value={speedometer.edge.pct - 100}
                        goodDirection="up"
                      />
                    </>
                  )}
                </div>
              </div>
            )}
          </>
        ) : (
          <span className="text-[10px] text-gray-600">select a route for speed data</span>
        )}
      </MetricRow>

      {/* ---- 4. Eye Test ---- */}
      <MetricRow label="Eye Test">
        {/* Data-suggested state line */}
        <div className="text-[10px] text-gray-500 font-mono">{eyeTest.suggestedLabel}</div>

        {/* Latest user certification */}
        {eyeTest.latestCertification ? (
          <div className="flex items-center gap-x-1.5">
            <span className="text-[10px] font-mono text-green-400">*</span>
            <span className="text-[10px] text-gray-400">
              certified human-level
              <span className="text-gray-600"> on {eyeTest.latestCertification.date}</span>
            </span>
          </div>
        ) : (
          <div className="text-[10px] text-gray-600">not certified</div>
        )}

        {!hasRoute && (
          <span className="text-[10px] text-gray-600">select a route for eye test</span>
        )}

        {/* LD-F5 (#106): passive certification control -- only when a controlClient is
            provided (expanded dock only; rail mode + tests do not pass it). */}
        {controlClient && (
          <CertifyHumanLevel
            context={context}
            controlClient={controlClient}
            onSuccess={sb.refetch}
          />
        )}
      </MetricRow>

      {/* Fetch timestamp */}
      {sb.fetchedAt && (
        <div className="pt-1 text-[9px] text-gray-700 text-right">
          fetched {new Date(sb.fetchedAt).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rail-mode micro scoreboard -- four glyphs in a vertical strip
// ---------------------------------------------------------------------------

/** Compact vertical scoreboard for the KPI dock rail mode. */
export function RailScoreboard({ context, refreshKey = 0 }: BrutalScoreboardProps) {
  const sb = useScoreboardData(context, refreshKey);

  if (!sb.loaded) {
    return (
      <div className="flex flex-col items-center gap-y-1 text-[9px] text-gray-700">
        <span>...</span>
      </div>
    );
  }

  const { race, jumpCount, speedometer, eyeTest } = sb;

  return (
    <div
      data-section="scoreboard-rail"
      className="flex flex-col items-center gap-y-2 text-[9px] font-mono text-gray-500"
    >
      {/* Race: finishes fraction */}
      <div
        title={`Race: ${race.finishes}/${race.attempts} finishes${race.multipleOfHuman != null ? ` x${race.multipleOfHuman.toFixed(1)}` : ""}`}
        className="flex flex-col items-center"
      >
        <span
          className={
            race.finishes > 0 ? "text-amber-400" : "text-red-500"
          }
        >
          {race.finishes}/{race.attempts}
        </span>
      </div>

      {/* Jump Count: N/11 */}
      <div
        title={`Jump Count: ${jumpCount.completed}/11 routes completed`}
        className="flex flex-col items-center"
      >
        <span
          className={
            jumpCount.completed > 0 ? "text-green-400" : "text-red-500"
          }
        >
          {jumpCount.completed}/{jumpCount.total}
        </span>
      </div>

      {/* Speedometer: % */}
      <div
        title={`Speedometer: ${speedometer.pct != null ? speedometer.pct.toFixed(0) + "%" : "no data"}`}
        className="flex flex-col items-center"
      >
        <span
          className={
            speedometer.pct == null
              ? "text-gray-700"
              : speedometer.pct >= 100
                ? "text-green-400"
                : speedometer.pct >= 80
                  ? "text-amber-400"
                  : "text-red-400"
          }
        >
          {speedometer.pct != null ? `${speedometer.pct.toFixed(0)}%` : "~%"}
        </span>
      </div>

      {/* Eye Test: certified glyph */}
      <div
        title={`Eye Test: ${eyeTest.latestCertification ? "certified " + eyeTest.latestCertification.date : "not certified"}`}
        className="flex flex-col items-center"
      >
        <span
          className={
            eyeTest.latestCertification ? "text-green-400" : "text-gray-700"
          }
        >
          {eyeTest.latestCertification ? "*" : "-"}
        </span>
      </div>
    </div>
  );
}
