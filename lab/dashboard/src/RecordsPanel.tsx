// LD-E4 (#104): Records panel — context-sensitive records section for the KPI dock.
//
// Two modes driven by the KpiContext:
//   route-context  — shows the four record-kind rows for the selected route, each
//                    with the bot value + human_ref, click-to-play via openDemo.
//   overall/fallback — per-route best table (one row per dm3 route, sorted by
//                      human_time_s ascending) when context.route is null.
//
// Fetch: /demos/records/records.json (same path as DemoPane; shares the same SSD
// publish step from records_build.py --publish).  404 → explicit "no records yet";
// app does not crash.
//
// Click-through: each set record row calls shell.openDemo({demo_url, map, t:event_t_s,
// route, name}) via ShellActionsContext (wired in App.tsx LD-D3 #98).  The Demo view
// opens (or focuses) and seeks to event_t_s. Rows whose demo_url is absent or whose
// record is null are non-clickable (cursor-default).
//
// Freshness: a "new record" dot appears when a record's value improves between two
// refetches triggered by refreshKey (incremented on attempt-end in App.tsx).
//
// Rail mode: this section is hidden in the KPI dock rail (numbers-only per #100/#101
// design).  The parent KpiDock only renders RecordsPanel in expanded mode.
//
// See tests/test_records_panel.py for the pure-logic contract tests.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { KpiContext } from "./contextStore.ts";
import { useShellActions } from "./App.tsx";

// ---- Types ------------------------------------------------------------------

/** Single record entry from komodobots.records.v1 */
interface RecordEntry {
  value: number;
  units: "s" | "qu/s";
  run_id: string;
  demo_url: string;
  demo_archived: boolean | null;
  event_t_s: number | null;
  set_at: string;
  human_ref: {
    value: number;
    source: string;
    demo_url: string;
  } | null;
}

/** One route's four records + aggregates from records.json */
interface RouteEntry {
  records: {
    fastest_time: RecordEntry | null;
    first_completion: RecordEntry | null;
    peak_speed: RecordEntry | null;
    edge_speed: RecordEntry | null;
  };
  aggregates: {
    attempts: number;
    finishes: number;
    median_time_s: number | null;
    human_time_s: number;
  };
}

/** Full records.json structure (partial — only what the panel consumes) */
interface RecordsJson {
  schema: string;
  maps: Record<string, { routes: Record<string, RouteEntry> }>;
}

// ---- Constants --------------------------------------------------------------

const RECORD_KINDS_ORDERED = [
  "fastest_time",
  "first_completion",
  "peak_speed",
  "edge_speed",
] as const;

type RecordKind = (typeof RECORD_KINDS_ORDERED)[number];

const RECORD_LABELS: Record<RecordKind, string> = {
  fastest_time: "Fastest",
  first_completion: "First completion",
  peak_speed: "Peak speed",
  edge_speed: "Edge speed",
};

const RECORD_UNITS: Record<RecordKind, "s" | "qu/s"> = {
  fastest_time: "s",
  first_completion: "s",
  peak_speed: "qu/s",
  edge_speed: "qu/s",
};

const RECORDS_URL = "/demos/records/records.json";

// ---- Helpers ----------------------------------------------------------------

function fmtValue(value: number | null | undefined, units: "s" | "qu/s"): string {
  if (value == null) return "—";
  if (units === "s") return value.toFixed(2) + " s";
  return Math.round(value) + " qu/s";
}

function fmtHumanRef(ref: RecordEntry["human_ref"]): string {
  if (!ref || ref.value == null) return "—";
  const src = ref.source ?? "";
  if (src.includes("speed") || src.includes("qu")) {
    return Math.round(ref.value) + " qu/s";
  }
  return ref.value.toFixed(2) + " s";
}

function isFreshRecord(prev: RecordEntry | null | undefined, curr: RecordEntry | null | undefined): boolean {
  if (prev == null || curr == null) return false;
  return prev.value !== curr.value;
}

// ---- Sub-components ---------------------------------------------------------

function RecordRow({
  kind,
  record,
  isFresh,
  onClickRecord,
}: {
  kind: RecordKind;
  record: RecordEntry | null;
  isFresh: boolean;
  onClickRecord: ((rec: RecordEntry, kind: RecordKind) => void) | null;
}) {
  const clickable = record !== null && onClickRecord !== null;
  return (
    <div
      data-record-kind={kind}
      className={`flex flex-col gap-y-0.5 px-2 py-1.5 rounded text-xs ${
        clickable
          ? "cursor-pointer hover:bg-slate-800/70 active:bg-slate-800"
          : "cursor-default opacity-80"
      }`}
      onClick={clickable ? () => onClickRecord(record!, kind) : undefined}
      title={clickable ? `Click to open demo at this record event` : undefined}
    >
      {/* Kind label + freshness dot */}
      <div className="flex items-center gap-x-1">
        <span className="text-gray-500 uppercase text-[10px] tracking-wide flex-1">
          {RECORD_LABELS[kind]}
        </span>
        {isFresh && (
          <span
            title="New record since last refresh"
            className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"
            aria-label="new record"
          />
        )}
      </div>

      {record ? (
        <div className="flex items-baseline gap-x-2">
          {/* Bot value */}
          <span className="font-mono font-semibold text-sky-300">
            {fmtValue(record.value, RECORD_UNITS[kind])}
          </span>
          {/* Human ref comparison */}
          {record.human_ref && (
            <span className="text-gray-500 font-mono text-[10px]">
              {"vs "}
              {fmtHumanRef(record.human_ref)}
            </span>
          )}
          {/* Archive badge */}
          {record.demo_archived === false && (
            <span
              title="Demo not yet archived on the SSD"
              className="ml-auto text-[9px] text-amber-600/80 font-mono"
            >
              no backup
            </span>
          )}
        </div>
      ) : (
        <span className="font-mono text-gray-600 text-[11px]">no record yet</span>
      )}
    </div>
  );
}

function RouteContextPanel({
  routeEntry,
  prevRouteEntry,
  map,
  route,
  onClickRecord,
}: {
  routeEntry: RouteEntry;
  prevRouteEntry: RouteEntry | null;
  map: string;
  route: string;
  onClickRecord: (rec: RecordEntry, kind: RecordKind, map: string, route: string) => void;
}) {
  const agg = routeEntry.aggregates;
  return (
    <div data-records-mode="route-context" className="flex flex-col gap-y-0.5">
      {/* Aggregates summary line */}
      <div className="flex items-center gap-x-2 px-2 py-1 text-[10px] text-gray-500 font-mono border-b border-slate-800 mb-1">
        <span>{agg.attempts} attempts</span>
        <span>·</span>
        <span>{agg.finishes} finishes</span>
        {agg.median_time_s != null && (
          <>
            <span>·</span>
            <span>median {agg.median_time_s.toFixed(2)} s</span>
          </>
        )}
      </div>

      {RECORD_KINDS_ORDERED.map((kind) => {
        const rec = routeEntry.records[kind] ?? null;
        const prevRec = prevRouteEntry?.records[kind] ?? null;
        return (
          <RecordRow
            key={kind}
            kind={kind}
            record={rec}
            isFresh={isFreshRecord(prevRec, rec)}
            onClickRecord={
              rec
                ? (r, k) => onClickRecord(r, k, map, route)
                : null
            }
          />
        );
      })}
    </div>
  );
}

function OverallSummaryPanel({
  allRoutes,
  onClickRoute,
}: {
  allRoutes: Array<{ route: string; entry: RouteEntry }>;
  onClickRoute: (route: string) => void;
}) {
  return (
    <div data-records-mode="overall" className="flex flex-col gap-y-0.5">
      <div className="px-2 py-1 text-[10px] text-gray-500 border-b border-slate-800 mb-1">
        All dm3 routes · fastest finish vs human
      </div>
      {allRoutes.map(({ route, entry }) => {
        const ft = entry.records.fastest_time;
        const humanT = entry.aggregates.human_time_s;
        const hasAny = Object.values(entry.records).some((r) => r !== null);
        return (
          <div
            key={route}
            data-route-row={route}
            className={`flex items-center gap-x-1 px-2 py-1 rounded text-[11px] ${
              hasAny
                ? "cursor-pointer hover:bg-slate-800/70"
                : "cursor-default opacity-60"
            }`}
            onClick={hasAny ? () => onClickRoute(route) : undefined}
            title={hasAny ? `Select ${route} in context` : undefined}
          >
            <span className="font-mono text-gray-400 flex-1 truncate">{route}</span>
            {ft ? (
              <span className="font-mono text-sky-300 text-[10px]">
                {ft.value.toFixed(2)} s
              </span>
            ) : (
              <span className="font-mono text-gray-600 text-[10px]">—</span>
            )}
            <span className="font-mono text-gray-600 text-[10px]">
              / {humanT.toFixed(2)} s
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---- Main component ---------------------------------------------------------

interface RecordsPanelProps {
  context: KpiContext;
  /** Incremented by App.tsx when an attempt ends (triggers a refetch). */
  refreshKey?: number;
}

export function RecordsPanel({ context, refreshKey = 0 }: RecordsPanelProps) {
  const shell = useShellActions();

  const [recordsJson, setRecordsJson] = useState<RecordsJson | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [loading, setLoading] = useState(true);

  // Snapshot of previous records for freshness detection (per-refresh diff)
  const prevRecordsRef = useRef<RecordsJson | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFetchError(false);

    fetch(RECORDS_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`records.json ${res.status}`);
        return res.json() as Promise<RecordsJson>;
      })
      .then((data) => {
        if (cancelled) return;
        prevRecordsRef.current = recordsJson; // snapshot for freshness
        setRecordsJson(data);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setFetchError(true);
        setLoading(false);
      });

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const handleRecordClick = useCallback(
    (rec: RecordEntry, kind: RecordKind, map: string, route: string) => {
      if (!shell) return;
      shell.openDemo({
        demo_url: rec.demo_url,
        map,
        t: rec.event_t_s,
        route,
        name: `${map}·${route}·${kind}`,
      });
    },
    [shell],
  );

  // --- Loading / error states ---

  if (loading) {
    return (
      <div
        data-section="records"
        className="px-2 py-2 text-[10px] text-gray-600 animate-pulse"
      >
        loading records…
      </div>
    );
  }

  if (fetchError || !recordsJson) {
    return (
      <div
        data-section="records"
        data-records-state="error"
        className="px-2 py-2 text-[10px] text-amber-700"
      >
        records unavailable
      </div>
    );
  }

  // --- Determine rendering mode ---

  const mapName = context.map ?? "dm3";
  const route = context.route ?? null;

  const mapData = recordsJson.maps[mapName] ?? { routes: {} };
  const prevMapData = prevRecordsRef.current?.maps[mapName] ?? { routes: {} };

  if (route !== null && mapData.routes[route] != null) {
    // Route-context mode
    const routeEntry = mapData.routes[route];
    const prevRouteEntry = prevMapData.routes[route] ?? null;

    return (
      <div data-section="records" className="flex flex-col">
        <div className="px-2 py-1 text-[10px] text-gray-500 font-mono truncate border-b border-slate-800">
          {mapName} · {route}
        </div>
        <RouteContextPanel
          routeEntry={routeEntry}
          prevRouteEntry={prevRouteEntry}
          map={mapName}
          route={route}
          onClickRecord={handleRecordClick}
        />
      </div>
    );
  }

  // Overall / no-route-context fallback: per-route best table
  const allRoutes = Object.entries(mapData.routes)
    .sort(([, a], [, b]) => a.aggregates.human_time_s - b.aggregates.human_time_s)
    .map(([routeName, entry]) => ({ route: routeName, entry }));

  if (allRoutes.length === 0) {
    return (
      <div
        data-section="records"
        data-records-state="empty"
        className="px-2 py-2 text-[10px] text-gray-600"
      >
        no records yet
      </div>
    );
  }

  return (
    <div data-section="records" className="flex flex-col">
      <OverallSummaryPanel
        allRoutes={allRoutes}
        onClickRoute={(selectedRoute) => {
          // Clicking a route row in overall mode triggers openDemo for its
          // fastest_time record (the most compelling first-click target).
          const entry = mapData.routes[selectedRoute];
          const ft = entry?.records.fastest_time;
          if (ft && shell) {
            handleRecordClick(ft, "fastest_time", mapName, selectedRoute);
          }
        }}
      />
    </div>
  );
}
