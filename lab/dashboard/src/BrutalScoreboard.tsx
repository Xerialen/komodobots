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
//   4. Eye Test      — latest human verdict (pass | close | fail)
//
// Data sources:
//   - records.json  (RECORDS_URL, same path as DemoPane)
//   - verdicts.json (VERDICTS_URL, lives beside records.json)
//
// Update cadence: fetch on mount + on every `onRequestRefetch` call
// (the dock calls this when an attempt ends or a verdict is submitted).
//
// Rail-mode numbers: the parent (KpiDock) renders four micro-glyphs in rail
// mode; export RailScoreboard for that case.

import { useCallback, useEffect, useState } from "react";
import type { KpiContext } from "./contextStore.ts";

// ---------------------------------------------------------------------------
// Types — records schema (komodobots.records.v1), partial
// ---------------------------------------------------------------------------

type RecordKind = "fastest_time" | "first_completion" | "peak_speed" | "edge_speed";

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
// Types — verdicts schema (komodobots.verdicts.v1)
// ---------------------------------------------------------------------------

type EyeVerdict = "pass" | "close" | "fail";

interface VerdictEntry {
  verdict: EyeVerdict;
  note?: string | null;
  run_id?: string | null;
  date?: string;
}

interface VerdictsJson {
  schema: string;
  routes: Record<string, VerdictEntry>;
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
  /** The Race: finishes/attempts for the context route (or overall), ×human median. */
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
    /** Bot peak_speed value (qu/s), best run, or null. */
    botSpeed: number | null;
    /** Human active_mean_speed from census (best available human ref). */
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
  /** Eye Test: latest verdict for the context route. */
  eyeTest: {
    verdict: EyeVerdict | null;
    /** Human-readable label for the verdict. */
    label: string;
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
    eyeTest: { verdict: null, label: "no verdict yet" },
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
    // Overall median multiple: weighted average across routes that have data.
    const multiples: number[] = [];
    for (const routeData of Object.values(dm3MapData.routes)) {
      const agg = routeData.aggregates;
      if (agg.finishes > 0 && agg.median_time_s != null && agg.human_time_s > 0) {
        multiples.push(agg.median_time_s / agg.human_time_s);
      }
    }
    if (multiples.length > 0) {
      raceMultiple = multiples.reduce((a, b) => a + b, 0) / multiples.length;
    }
  }

  // ---- Speedometer ---------------------------------------------------------
  let botSpeed: number | null = null;
  let humanSpeed: number | null = null;
  let speedPct: number | null = null;
  let edgeInfo: ScoreboardState["speedometer"]["edge"] = null;

  if (context.route && dm3MapData.routes[context.route]) {
    const routeData = dm3MapData.routes[context.route];

    // Bot speed: use peak_speed record value (best ever on-route peak).
    const peakRec = routeData.records?.peak_speed;
    if (peakRec) {
      botSpeed = peakRec.value;
      if (peakRec.human_ref) {
        humanSpeed = peakRec.human_ref.value;
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
  let verdict: EyeVerdict | null = null;
  let verdictLabel = "no verdict yet";

  if (verdicts && context.route) {
    const entry = verdicts.routes[context.route];
    if (entry) {
      verdict = entry.verdict;
      verdictLabel =
        verdict === "pass"
          ? "could be human"
          : verdict === "close"
            ? "hesitates"
            : "obviously a bot";
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
    eyeTest: { verdict, label: verdictLabel },
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
    eyeTest: { verdict: null, label: "no verdict yet" },
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
          // Verdicts file may not exist yet (404 = no verdicts entered).
          return null as VerdictsJson | null;
        }
        return r.json() as Promise<VerdictsJson>;
      }).catch(() => null as VerdictsJson | null),
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

/** Verdict badge for Eye Test and generic pass/fail framing. */
function VerdictBadge({ verdict }: { verdict: EyeVerdict | null }) {
  if (verdict === "pass") {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-green-900/60 text-green-300 border border-green-700">
        pass
      </span>
    );
  }
  if (verdict === "close") {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-900/60 text-amber-300 border border-amber-700">
        close
      </span>
    );
  }
  if (verdict === "fail") {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-red-900/60 text-red-300 border border-red-700">
        fail
      </span>
    );
  }
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-gray-600 border border-slate-700">
      ?
    </span>
  );
}

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
// Main scoreboard component (expanded dock)
// ---------------------------------------------------------------------------

interface BrutalScoreboardProps {
  context: KpiContext;
  /** External refresh trigger — incremented when an attempt ends. */
  refreshKey?: number;
}

export function BrutalScoreboard({ context, refreshKey = 0 }: BrutalScoreboardProps) {
  const sb = useScoreboardData(context, refreshKey);

  if (!sb.loaded) {
    return (
      <div
        data-section="scoreboard"
        className="py-2 text-[10px] text-gray-600 animate-pulse text-center"
      >
        loading scoreboard…
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

  // Race: v1 target is 16/20 attempts · ≤×1.25; today honest is 6/10 · ×3.9
  const RACE_TARGET_MULTIPLE = 1.25;
  const raceMultipleFail =
    race.multipleOfHuman != null && race.multipleOfHuman > RACE_TARGET_MULTIPLE * 2;
  const raceMultipleClose =
    race.multipleOfHuman != null &&
    race.multipleOfHuman > RACE_TARGET_MULTIPLE &&
    !raceMultipleFail;

  // Speedometer: ≥80% is target
  const SPEED_TARGET_PCT = 80;

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

        {/* ×human line */}
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
                ×{race.multipleOfHuman.toFixed(1)}
              </span>
              <span className="text-[10px] text-gray-600">
                median vs human ·{" "}
                <span className="text-gray-500">target ≤×{RACE_TARGET_MULTIPLE}</span>
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
              {jumpCount.contextRouteCompleted ? "✓" : "✗"}
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
            target: 1/11 then climb → 11/11
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
                      speedometer.pct >= SPEED_TARGET_PCT
                        ? "text-green-400"
                        : speedometer.pct >= 60
                          ? "text-amber-300"
                          : "text-red-400"
                    }`}
                  >
                    {speedometer.pct.toFixed(0)}%
                  </span>
                  <span className="text-[10px] text-gray-600">
                    of human speed ·{" "}
                    <span className="text-gray-500">target ≥{SPEED_TARGET_PCT}%</span>
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
                <span className="font-sans">qu/s peak</span>
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
                    <span className="text-gray-600">—</span>
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
                      <span className="text-gray-700">·</span>
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
        <div className="flex items-center gap-x-2">
          <VerdictBadge verdict={eyeTest.verdict} />
          <span className="text-xs text-gray-400">{eyeTest.label}</span>
        </div>
        {!hasRoute && eyeTest.verdict == null && (
          <span className="text-[10px] text-gray-600">select a route for verdict</span>
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
// Rail-mode micro scoreboard — four glyphs in a vertical strip
// ---------------------------------------------------------------------------

/** Compact vertical scoreboard for the KPI dock rail mode. */
export function RailScoreboard({ context, refreshKey = 0 }: BrutalScoreboardProps) {
  const sb = useScoreboardData(context, refreshKey);

  if (!sb.loaded) {
    return (
      <div className="flex flex-col items-center gap-y-1 text-[9px] text-gray-700">
        <span>…</span>
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
        title={`Race: ${race.finishes}/${race.attempts} finishes${race.multipleOfHuman != null ? ` ×${race.multipleOfHuman.toFixed(1)}` : ""}`}
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
              : speedometer.pct >= 80
                ? "text-green-400"
                : speedometer.pct >= 60
                  ? "text-amber-400"
                  : "text-red-400"
          }
        >
          {speedometer.pct != null ? `${speedometer.pct.toFixed(0)}%` : "~%"}
        </span>
      </div>

      {/* Eye Test: verdict glyph */}
      <div
        title={`Eye Test: ${eyeTest.verdict ?? "no verdict"} — ${eyeTest.label}`}
        className="flex flex-col items-center"
      >
        <span
          className={
            eyeTest.verdict === "pass"
              ? "text-green-400"
              : eyeTest.verdict === "close"
                ? "text-amber-400"
                : eyeTest.verdict === "fail"
                  ? "text-red-400"
                  : "text-gray-700"
          }
        >
          {eyeTest.verdict === "pass"
            ? "P"
            : eyeTest.verdict === "close"
              ? "~"
              : eyeTest.verdict === "fail"
                ? "F"
                : "?"}
        </span>
      </div>
    </div>
  );
}
