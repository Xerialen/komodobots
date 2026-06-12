// LD-E3 (#102): Live attempt metrics vs human reference — arc-local speed %,
// launch-edge callout.
//
// Visible only while context.source === "live".  Collapses to "no live session"
// otherwise.  Resets on new_attempt.
//
// Data sources:
//   - TelemetryClient: ~100 Hz frames (type "frame") carrying origin, vh,
//     onground, dist_to_rl; and "new_attempt" / "hello" events for reset.
//   - routes manifest (komodobots.routes.v1): polyline + gaps for the context
//     route.  Fetched once per (map, route) pair; cached in component state.
//
// Live route context: until per-bot assignment exposure (LD-F1/F3), the live
// route defaults to sng_to_rl on dm3 (today's harness default).  A manual
// override dropdown is shown in the section header.
//
// Pure functions (arc projection, edge detection) are exported for Python
// unit tests that validate correctness against fixture data.
//
// Limitation: the displayed edge speed is for visual monitoring only.  The
// post-run verify_route edge-speed scorer (records_build.py) remains the metric
// of record.  A tooltip says so.

import { useEffect, useRef, useState } from "react";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";
import type { KpiContext } from "./contextStore.ts";

// ---------------------------------------------------------------------------
// Manifest types (subset of komodobots.routes.v1 needed here)
// ---------------------------------------------------------------------------

export type LiveGap = {
  edge: [number, number, number];
  land: [number, number, number];
  required_speed: number | null;
  human_speed_at_edge: number | null;
  hard: boolean;
};

export type LiveRouteData = {
  /** Human route polyline in Quake coords: array of [x, y, z]. */
  polyline: [number, number, number][];
  /** Gaps (launch edges) from the census. */
  gaps: LiveGap[];
  /** Human active-mean speed (qu/s) for the whole route. */
  humanActiveMeanSpeed: number | null;
};

type RouteManifestRaw = {
  schema: string;
  routes: {
    name: string;
    human: { active_mean_speed: number | null };
    polyline: [number, number, number][];
    gaps: {
      edge: [number, number, number];
      land: [number, number, number];
      required_speed: number | null;
      human_speed_at_edge: number | null;
      hard: boolean;
      type: string;
    }[];
  }[];
};

// ---------------------------------------------------------------------------
// Pure geometry helpers (exported for Python unit tests)
// ---------------------------------------------------------------------------

/** Squared distance between two 3D points. */
export function dist3Sq(
  ax: number, ay: number, az: number,
  bx: number, by: number, bz: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const dz = bz - az;
  return dx * dx + dy * dy + dz * dz;
}

/**
 * Project point P onto the segment [A, B].
 * Returns {t: clamp(0,1), distSq: squared distance from P to the projection}.
 * t=0 → nearest to A, t=1 → nearest to B.
 */
export function projectOntoSegment(
  px: number, py: number, pz: number,
  ax: number, ay: number, az: number,
  bx: number, by: number, bz: number,
): { t: number; distSq: number } {
  const abx = bx - ax;
  const aby = by - ay;
  const abz = bz - az;
  const abLenSq = abx * abx + aby * aby + abz * abz;
  if (abLenSq === 0) {
    // Degenerate segment: A === B
    return { t: 0, distSq: dist3Sq(px, py, pz, ax, ay, az) };
  }
  const apx = px - ax;
  const apy = py - ay;
  const apz = pz - az;
  const dot = apx * abx + apy * aby + apz * abz;
  const t = Math.max(0, Math.min(1, dot / abLenSq));
  const projx = ax + t * abx;
  const projy = ay + t * aby;
  const projz = az + t * abz;
  return { t, distSq: dist3Sq(px, py, pz, projx, projy, projz) };
}

/**
 * Find the nearest arc position on a polyline to point P.
 *
 * Returns:
 *   arcFrac  — fraction [0, 1] along the total arc length to the nearest point
 *   distSq   — squared distance from P to the nearest projection
 *   segIndex — index of the nearest segment (0-based, segment i = pts[i]→pts[i+1])
 *   segT     — t within that segment [0, 1]
 *
 * Uses Euclidean 3D distance (Quake coords are 3D — height matters for routes
 * that gain/lose altitude, but 2D projection would over-promote off-axis points;
 * 3D is the right default for arc-local comparison).
 */
export type ArcProjection = {
  arcFrac: number;
  distSq: number;
  segIndex: number;
  segT: number;
};

export function projectOntoPolyline(
  px: number, py: number, pz: number,
  polyline: [number, number, number][],
): ArcProjection | null {
  if (polyline.length < 2) return null;

  // Pre-compute cumulative arc lengths.
  const n = polyline.length;
  const segLens: number[] = new Array(n - 1);
  let totalLen = 0;
  for (let i = 0; i < n - 1; i++) {
    const [ax, ay, az] = polyline[i];
    const [bx, by, bz] = polyline[i + 1];
    const len = Math.sqrt(dist3Sq(ax, ay, az, bx, by, bz));
    segLens[i] = len;
    totalLen += len;
  }

  if (totalLen === 0) return null;

  let bestDistSq = Infinity;
  let bestSeg = 0;
  let bestT = 0;

  for (let i = 0; i < n - 1; i++) {
    const [ax, ay, az] = polyline[i];
    const [bx, by, bz] = polyline[i + 1];
    const { t, distSq } = projectOntoSegment(px, py, pz, ax, ay, az, bx, by, bz);
    if (distSq < bestDistSq) {
      bestDistSq = distSq;
      bestSeg = i;
      bestT = t;
    }
  }

  // Compute arc fraction: (arc length up to start of bestSeg) + bestT * segLen[bestSeg]
  let arcToSeg = 0;
  for (let i = 0; i < bestSeg; i++) {
    arcToSeg += segLens[i];
  }
  const arcPos = arcToSeg + bestT * segLens[bestSeg];
  const arcFrac = arcPos / totalLen;

  return { arcFrac, distSq: bestDistSq, segIndex: bestSeg, segT: bestT };
}

/**
 * Given arc fraction arcFrac [0,1] along a polyline, compute an interpolated
 * speed value from a parallel per-vertex speed array of the same length.
 *
 * The speed array must have the same length as polyline.
 * If arcFrac is past the last point, returns the last speed.
 * If arcFrac is before the first point, returns the first speed.
 */
export function interpolateSpeedAtArc(
  arcFrac: number,
  polyline: [number, number, number][],
  speeds: number[],
): number | null {
  if (polyline.length < 2 || speeds.length !== polyline.length) return null;

  const n = polyline.length;
  // Build cumulative arc-length lookup.
  let totalLen = 0;
  const cumLen: number[] = [0];
  for (let i = 0; i < n - 1; i++) {
    const [ax, ay, az] = polyline[i];
    const [bx, by, bz] = polyline[i + 1];
    const len = Math.sqrt(dist3Sq(ax, ay, az, bx, by, bz));
    totalLen += len;
    cumLen.push(totalLen);
  }
  if (totalLen === 0) return speeds[0];

  const target = arcFrac * totalLen;

  // Binary search for the segment containing `target`.
  let lo = 0;
  let hi = n - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (cumLen[mid] <= target) lo = mid;
    else hi = mid;
  }

  const segLen = cumLen[lo + 1] - cumLen[lo];
  const t = segLen > 0 ? (target - cumLen[lo]) / segLen : 0;
  return speeds[lo] + t * (speeds[lo + 1] - speeds[lo]);
}

/**
 * Check whether a 3D point is within `radius` Quake units of an edge point.
 *
 * Used to detect entry into the launch-edge region of a gap.
 * Returns true if the horizontal (XY) distance is within the radius —
 * we use XY only so that vertical bobbing doesn't prevent detection.
 */
export function isInEdgeRegion(
  px: number, py: number,
  ex: number, ey: number,
  radius: number,
): boolean {
  const dx = px - ex;
  const dy = py - ey;
  return dx * dx + dy * dy <= radius * radius;
}

/**
 * Select the designated launch edge for a route — the single gap to track and
 * freeze on during a live attempt.
 *
 * Strategy: pick the gap with the highest `required_speed`.  For sng_to_rl
 * (gaps at 402.0, 468.7, 525.3) this selects the 525.3 gap, which is the
 * Sprint-1 north-star threshold for #102.  Ties are broken by last-in-array
 * order (i.e. the later gap wins) so the harder, route-terminal gap is always
 * preferred over an earlier gap with equal speed.
 *
 * Returns null if gaps is empty.
 */
export function designatedLaunchEdge(gaps: LiveGap[]): LiveGap | null {
  let best: LiveGap | null = null;
  for (const gap of gaps) {
    if (typeof gap.required_speed !== "number" || !Number.isFinite(gap.required_speed)) {
      continue;
    }
    if (best === null || gap.required_speed >= best.required_speed!) {
      best = gap;
    }
  }
  return best;
}

// Default edge-detection radius (Quake units).
export const EDGE_REGION_RADIUS = 96;

// Maximum off-route distance before flagging "off route" (qu).
// Bot position more than this distance from the nearest polyline point → off route.
export const OFF_ROUTE_DIST = 384;

// Maximum display history for the speed sparkline (number of samples).
const SPARKLINE_MAX = 60;

// Display throttle: ~12 Hz (same as TelemetryHud).
const DISPLAY_INTERVAL_MS = 80;

// Routes-manifest URL template.
const ROUTES_URL = (map: string) => `/botlab/data/routes/${map}.json`;

// Default live route name (harness default for dm3, per #102 limitation note).
const DEFAULT_LIVE_ROUTE = "sng_to_rl";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EdgeCallout = {
  /** Crossing speed recorded at the moment the bot entered the edge region. */
  crossingSpeed: number;
  /** Required speed from the census gap. */
  requiredSpeed: number;
  /** Human reference speed at this edge. */
  humanSpeed: number;
};

type LiveMetricsState = {
  /** Current horizontal speed (qu/s). */
  vh: number;
  /** Whether a live attempt is active. */
  isLive: boolean;
  /** Run ID. */
  runId: string | null;
  /** ed of the bot whose frames are being displayed (null until first frame). */
  activeEd: number | null;
  /** Elapsed time (ms since attempt started, derived from frame timestamps). */
  elapsedMs: number | null;
  /** Distance to RL goal (dist_to_rl from frame; null if not provided). */
  distToGoal: number | null;
  /** Arc-fraction along the route polyline [0,1], or null if off route / no data. */
  arcFrac: number | null;
  /** Whether the bot is considered off route. */
  offRoute: boolean;
  /** Human speed at the same arc position (qu/s), or null if off route / no data. */
  humanSpeedAtArc: number | null;
  /** Percentage of human arc-local speed; null if no data. */
  arcLocalPct: number | null;
  /** Frozen edge callout (cleared on new_attempt). */
  edgeCallout: EdgeCallout | null;
  /** Speed sparkline buffer (recent vh values). */
  sparkline: number[];
};

const INITIAL_STATE: LiveMetricsState = {
  vh: 0,
  isLive: false,
  runId: null,
  activeEd: null,
  elapsedMs: null,
  distToGoal: null,
  arcFrac: null,
  offRoute: false,
  humanSpeedAtArc: null,
  arcLocalPct: null,
  edgeCallout: null,
  sparkline: [],
};

// ---------------------------------------------------------------------------
// Hook: load route data for a (map, route) pair
// ---------------------------------------------------------------------------

function useRouteData(
  map: string,
  route: string | null,
): LiveRouteData | null {
  const [data, setData] = useState<LiveRouteData | null>(null);
  const prevKey = useRef<string | null>(null);

  useEffect(() => {
    if (!route) {
      // Reset prevKey so the next attempt re-fetches even when the same route
      // is used (live session end → live session start with same sng_to_rl).
      // Without this reset, key === prevKey.current on the second attempt and
      // the hook skips the fetch, leaving routeData null for the whole run.
      prevKey.current = null;
      setData(null);
      return;
    }
    const key = `${map}:${route}`;
    if (key === prevKey.current) return; // Already loaded (data is non-null).
    prevKey.current = key;

    let cancelled = false;
    fetch(ROUTES_URL(map))
      .then((r) => {
        if (!r.ok) throw new Error(`routes manifest: HTTP ${r.status}`);
        return r.json() as Promise<RouteManifestRaw>;
      })
      .then((manifest) => {
        if (cancelled) return;
        const found = manifest.routes.find((r) => r.name === route);
        if (!found) {
          setData(null);
          return;
        }
        setData({
          polyline: found.polyline,
          gaps: found.gaps.map((g) => ({
            edge: g.edge,
            land: g.land,
            required_speed: g.required_speed,
            human_speed_at_edge: g.human_speed_at_edge,
            hard: g.hard,
          })),
          humanActiveMeanSpeed: found.human.active_mean_speed,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [map, route]);

  return data;
}

// ---------------------------------------------------------------------------
// Helper: build per-vertex speed array from gaps (census speeds)
//
// The routes manifest stores speed at gap *edge* vertices, not per polyline
// vertex.  We use a simple linear interpolation: at each gap edge we insert
// its human_speed_at_edge; between gap edges we linearly interpolate.
// Where no gap exists the whole-route active_mean_speed is used as fill.
// ---------------------------------------------------------------------------

export function buildVertexSpeeds(
  polyline: [number, number, number][],
  gaps: LiveGap[],
  activeMeanSpeed: number | null,
): number[] | null {
  const n = polyline.length;
  if (n === 0) return [];

  // Find the nearest polyline vertex index for each gap edge.
  const anchors: { idx: number; speed: number }[] = [];
  for (const gap of gaps) {
    if (
      typeof gap.human_speed_at_edge !== "number" ||
      !Number.isFinite(gap.human_speed_at_edge)
    ) {
      continue;
    }
    const [ex, ey, ez] = gap.edge;
    let bestDist = Infinity;
    let bestIdx = 0;
    for (let i = 0; i < n; i++) {
      const [px, py, pz] = polyline[i];
      const d = dist3Sq(px, py, pz, ex, ey, ez);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }
    anchors.push({ idx: bestIdx, speed: gap.human_speed_at_edge });
  }
  anchors.sort((a, b) => a.idx - b.idx);

  // Build vertex-speeds by linear interpolation between anchors.
  const fillSpeed =
    typeof activeMeanSpeed === "number" && Number.isFinite(activeMeanSpeed)
      ? activeMeanSpeed
      : (anchors[0]?.speed ?? null);
  if (fillSpeed === null) return null;

  const speeds: number[] = new Array(n).fill(fillSpeed);

  if (anchors.length === 0) {
    return speeds; // All fill with active_mean_speed.
  }

  // Fill before first anchor.
  for (let i = 0; i <= anchors[0].idx; i++) {
    speeds[i] = anchors[0].speed;
  }
  // Fill after last anchor.
  for (let i = anchors[anchors.length - 1].idx; i < n; i++) {
    speeds[i] = anchors[anchors.length - 1].speed;
  }
  // Interpolate between adjacent anchors.
  for (let k = 0; k < anchors.length - 1; k++) {
    const a = anchors[k];
    const b = anchors[k + 1];
    const span = b.idx - a.idx;
    for (let i = a.idx; i <= b.idx; i++) {
      const t = span > 0 ? (i - a.idx) / span : 0;
      speeds[i] = a.speed + t * (b.speed - a.speed);
    }
  }

  return speeds;
}

// ---------------------------------------------------------------------------
// Hook: process telemetry frames into LiveMetricsState
// ---------------------------------------------------------------------------

function useLiveMetrics(
  client: TelemetryClient | null,
  isLive: boolean,
  routeData: LiveRouteData | null,
  selectedEd: number | null,
): LiveMetricsState {
  const [state, setState] = useState<LiveMetricsState>(INITIAL_STATE);

  // Refs for high-frequency update path (avoid re-render on every frame).
  const bufRef = useRef<number[]>([]); // sparkline buffer
  const lastDisplayRef = useRef<number>(0);
  const edgeCalloutRef = useRef<EdgeCallout | null>(null);
  const attemptStartTRef = useRef<number | null>(null);
  const runIdRef = useRef<string | null>(null);
  const isLiveRef = useRef(isLive);
  const routeDataRef = useRef(routeData);
  const selectedEdRef = useRef(selectedEd);
  // First-seen ed for the current attempt — used when selectedEd is null.
  const firstEdRef = useRef<number | null>(null);
  // Pre-computed vertex speeds for the current route; rebuilt when routeData changes.
  const vertexSpeedsRef = useRef<number[] | null>(null);

  // Keep refs in sync with latest props.
  useEffect(() => {
    isLiveRef.current = isLive;
  }, [isLive]);

  useEffect(() => {
    selectedEdRef.current = selectedEd;
  }, [selectedEd]);

  useEffect(() => {
    routeDataRef.current = routeData;
    if (routeData) {
      vertexSpeedsRef.current = buildVertexSpeeds(
        routeData.polyline,
        routeData.gaps,
        routeData.humanActiveMeanSpeed,
      );
    } else {
      vertexSpeedsRef.current = null;
    }
  }, [routeData]);

  useEffect(() => {
    if (!client) return;

    // Reset on new_attempt.
    const onAttempt = (attempt: { run_id: string | null; type?: string }) => {
      if ((attempt as unknown as { type?: string }).type === "new_attempt") {
        bufRef.current = [];
        edgeCalloutRef.current = null;
        attemptStartTRef.current = null;
        firstEdRef.current = null;
        runIdRef.current = attempt.run_id;
        setState((prev) => ({
          ...INITIAL_STATE,
          isLive: prev.isLive,
        }));
      } else {
        // hello with run_id: just update run id.
        if (attempt.run_id) runIdRef.current = attempt.run_id;
      }
    };

    const onFrame = (frame: TelemetryFrame) => {
      if (!isLiveRef.current) return;

      // Bot identity filter: use the explicit selection or fall back to first-seen.
      // Record first-seen ed when this attempt's first frame arrives.
      if (firstEdRef.current === null) {
        firstEdRef.current = frame.ed;
      }
      const activeEd = selectedEdRef.current ?? firstEdRef.current;
      if (frame.ed !== activeEd) return;

      const now = performance.now();

      // Track elapsed.
      if (attemptStartTRef.current === null) {
        attemptStartTRef.current = frame.t;
      }
      const elapsedMs = (frame.t - attemptStartTRef.current) * 1000;

      // Sparkline: push vh.
      bufRef.current.push(frame.vh);
      if (bufRef.current.length > SPARKLINE_MAX) {
        bufRef.current = bufRef.current.slice(-SPARKLINE_MAX);
      }

      // Arc-local comparison.
      let arcFrac: number | null = null;
      let offRoute = false;
      let humanSpeedAtArc: number | null = null;
      let arcLocalPct: number | null = null;

      const rd = routeDataRef.current;
      const vs = vertexSpeedsRef.current;
      if (rd && rd.polyline.length >= 2 && vs) {
        const proj = projectOntoPolyline(
          frame.origin.x, frame.origin.y, frame.origin.z,
          rd.polyline,
        );
        if (proj) {
          const dist = Math.sqrt(proj.distSq);
          offRoute = dist > OFF_ROUTE_DIST;
          if (!offRoute) {
            arcFrac = proj.arcFrac;
            humanSpeedAtArc = interpolateSpeedAtArc(proj.arcFrac, rd.polyline, vs);
            if (humanSpeedAtArc != null && humanSpeedAtArc > 0) {
              arcLocalPct = (frame.vh / humanSpeedAtArc) * 100;
            }
          }
        }
      }

      // Edge callout: track only the designated launch edge (highest required_speed),
      // not the first gap encountered.  Freeze on first entry into that edge's region.
      if (rd && edgeCalloutRef.current === null) {
        const targetGap = designatedLaunchEdge(rd.gaps);
        if (
          targetGap &&
          typeof targetGap.required_speed === "number" &&
          typeof targetGap.human_speed_at_edge === "number" &&
          isInEdgeRegion(
            frame.origin.x, frame.origin.y,
            targetGap.edge[0], targetGap.edge[1],
            EDGE_REGION_RADIUS,
          )
        ) {
          edgeCalloutRef.current = {
            crossingSpeed: frame.vh,
            requiredSpeed: targetGap.required_speed,
            humanSpeed: targetGap.human_speed_at_edge,
          };
        }
      }

      // Throttle display updates to ~12 Hz.
      if (now - lastDisplayRef.current < DISPLAY_INTERVAL_MS) return;
      lastDisplayRef.current = now;

      setState({
        vh: frame.vh,
        isLive: true,
        runId: runIdRef.current,
        activeEd: frame.ed,
        elapsedMs,
        distToGoal: frame.dist_to_rl,
        arcFrac,
        offRoute,
        humanSpeedAtArc,
        arcLocalPct,
        edgeCallout: edgeCalloutRef.current,
        sparkline: [...bufRef.current],
      });
    };

    client.frameListeners.add(onFrame);
    // Use attemptListeners for new_attempt / hello.
    const untypedOnAttempt = onAttempt as Parameters<typeof client.attemptListeners.add>[0];
    client.attemptListeners.add(untypedOnAttempt);

    return () => {
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(untypedOnAttempt);
    };
  }, [client]);

  // When live ends, update isLive flag in state without clearing other values.
  useEffect(() => {
    if (!isLive) {
      setState((prev) => ({ ...prev, isLive: false }));
    }
  }, [isLive]);

  return state;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Minimal ASCII sparkline for the speed history. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="text-gray-700">…</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;
  // 5-row bar chart using block chars.
  const BARS = " ▁▂▃▄▅▆▇█";
  const chars = values.map((v) => {
    if (range === 0) return "▄";
    const t = (v - min) / range;
    const idx = Math.round(t * (BARS.length - 1));
    return BARS[idx];
  });
  return (
    <span className="font-mono text-[9px] text-amber-400/70 leading-none tracking-tight">
      {chars.join("")}
    </span>
  );
}

/** Format elapsed milliseconds as m:ss or ss.s */
function formatElapsed(ms: number): string {
  const s = ms / 1000;
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }
  return `${s.toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface LiveMetricsPanelProps {
  client: TelemetryClient | null;
  context: KpiContext;
  /** Whether a live attempt is running (from App.tsx connection.live). */
  isLive: boolean;
  /**
   * ed of the selected bot (from App.tsx selectedEd / LD-F4 #103).
   * null = use first-seen bot (single-bot compat, same as TelemetryHud/BotLab3D).
   */
  selectedEd?: number | null;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function LiveMetricsPanel({ client, context, isLive, selectedEd = null }: LiveMetricsPanelProps) {
  // Live route: default to DEFAULT_LIVE_ROUTE on dm3; respect context.route if set.
  // Until LD-F1/F3 assignment exposure, show a manual override dropdown.
  const [routeOverride, setRouteOverride] = useState<string>(DEFAULT_LIVE_ROUTE);

  const effectiveRoute =
    context.source === "live" && context.route
      ? context.route
      : routeOverride;

  const routeData = useRouteData(context.map ?? "dm3", isLive ? effectiveRoute : null);
  const m = useLiveMetrics(client, isLive, routeData, selectedEd);

  // Reset override to default when map changes.
  useEffect(() => {
    setRouteOverride(DEFAULT_LIVE_ROUTE);
  }, [context.map]);

  if (!isLive) {
    return (
      <div
        data-section="live-metrics"
        className="py-2 text-center text-[10px] text-gray-600"
      >
        no live session
      </div>
    );
  }

  const pct = m.arcLocalPct;
  const pctColor =
    pct == null
      ? "text-gray-600"
      : pct >= 100
        ? "text-green-400"
        : pct >= 75
          ? "text-amber-300"
          : "text-red-400";

  return (
    <div data-section="live-metrics" className="flex flex-col gap-y-1">
      {/* ---- Section header: label + tracked-bot badge + route override dropdown ---- */}
      <div className="flex items-center gap-x-1 text-[10px] uppercase tracking-wider text-gray-500">
        <span>Live</span>
        {/* Bot identity badge: shows which ed is being tracked (selectedEd or first-seen).
            Prevents ambiguous readings in multi-bot sessions (LD-F4 #103 / #102 P1). */}
        {m.activeEd != null && (
          <span
            className="font-mono text-[9px] px-1 py-0 rounded bg-slate-800 border border-slate-700 text-amber-400/80 normal-case tracking-normal"
            title={selectedEd != null ? `selected bot ed=${m.activeEd}` : `first-seen bot ed=${m.activeEd} (no selection)`}
          >
            ed={m.activeEd}
          </span>
        )}
        <select
          value={effectiveRoute}
          onChange={(e) => setRouteOverride(e.target.value)}
          title="Live route override — until per-bot assignment exposure (LD-F1/F3), this defaults to the harness default (sng_to_rl)"
          className="ml-auto text-[9px] bg-slate-900 border border-slate-700 rounded text-gray-400 px-0.5 py-0 max-w-[90px] truncate"
        >
          {/* dm3 routes from census ladder (#101). */}
          {[
            "sng_shortcut2", "hilljump", "rl_to_ya", "ring_to_mega", "ra_jumps",
            "mega_to_rl", "rl_to_bridge", "sng_shortcut", "sng_to_rl",
            "mega_to_window", "sng_jumps",
          ].map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </div>

      {/* ---- Speed line: current vh + sparkline ---- */}
      <div className="flex items-baseline gap-x-1.5">
        <span className="font-mono text-sm text-amber-300">
          {Math.round(m.vh)}
        </span>
        <span className="text-[10px] text-gray-600">qu/s</span>
        <div className="ml-auto overflow-hidden max-w-[60px]">
          <Sparkline values={m.sparkline} />
        </div>
      </div>

      {/* ---- Arc-local human comparison ---- */}
      <div className="px-1.5 py-1 rounded bg-slate-900/60 border border-slate-800">
        <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-0.5">
          arc-local vs human
        </div>
        {m.offRoute ? (
          <span className="text-[10px] text-amber-500/80 font-mono">off route</span>
        ) : m.humanSpeedAtArc != null && pct != null ? (
          <div className="flex items-baseline gap-x-1.5 font-mono text-xs">
            <span className={pctColor}>{pct.toFixed(0)}%</span>
            <span className="text-gray-700">·</span>
            <span className="text-amber-300">{Math.round(m.vh)}</span>
            <span className="text-gray-600">vs</span>
            <span className="text-cyan-700">{Math.round(m.humanSpeedAtArc)}</span>
            <span className="text-[9px] text-gray-700 font-sans">qu/s</span>
          </div>
        ) : (
          <span className="text-[10px] text-gray-600">
            {routeData ? "approaching route…" : "loading route…"}
          </span>
        )}
      </div>

      {/* ---- Launch-edge callout (frozen once entered; cleared on new_attempt) ---- */}
      {m.edgeCallout && (
        <div className="px-1.5 py-1 rounded bg-slate-900/80 border border-slate-700">
          <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-0.5">
            edge{" "}
            <span
              className="normal-case text-gray-700"
              title="Display only — the post-run verify_route edge-speed scorer is the metric of record"
            >
              (display only ⓘ)
            </span>
          </div>
          <div className="flex items-baseline gap-x-1.5 font-mono text-xs">
            <span
              className={
                m.edgeCallout.crossingSpeed >= m.edgeCallout.requiredSpeed
                  ? "text-green-400"
                  : "text-red-400"
              }
            >
              {Math.round(m.edgeCallout.crossingSpeed)}
            </span>
            <span className="text-gray-600">/</span>
            <span className="text-gray-500">
              needs {Math.ceil(m.edgeCallout.requiredSpeed)}
            </span>
            <span className="text-gray-700">·</span>
            <span className="text-[9px] text-cyan-800 font-sans">
              human {Math.round(m.edgeCallout.humanSpeed)}
            </span>
          </div>
        </div>
      )}

      {/* ---- Attempt meta line ---- */}
      <div className="flex items-center gap-x-1.5 text-[9px] font-mono text-gray-600">
        {m.runId && (
          <span className="truncate max-w-[120px]" title={m.runId}>
            {m.runId}
          </span>
        )}
        {m.elapsedMs != null && (
          <span>{formatElapsed(m.elapsedMs)}</span>
        )}
        {m.distToGoal != null && (
          <span className="ml-auto text-gray-700">
            {Math.round(m.distToGoal)} qu
          </span>
        )}
      </div>
    </div>
  );
}
