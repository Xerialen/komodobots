// LD-D3 (#98): Demo view — records/archive picker + click-to-play + seek-to-event.
//
// Integrates the standalone demo.html FTE pane (LD-D2, #94) into the shell as
// the first (leftmost) view. The picker header provides two source tabs:
//
//   Records  — records.json (komodobots.records.v1) grouped by route → kind,
//              with per-record human reference value beside each bot value.
//              Clicking a record fires openDemo with the record's event_t_s
//              (2 s pre-roll is applied inside demo.html, SPEC §6.5).
//
//   Archive  — /v2/demos.json filtered to the lab tree
//              ["non-games","lab","Komodobots"], map-filterable, newest-first,
//              plus the human/ subtree.  Clicking plays from the start (t=null).
//
// Shell-level openDemo({demo_url, map, t?, track?}):
//   - Exported as the single entry point LD-E4's record clicks will reuse.
//   - If the Demo view is closed it toggles it on (row reflows, SPEC §4.2/§6.5).
//   - Posts {cmd:"load"} to the demo.html iframe (same-origin, SPEC §3.2).
//
// Context emission:
//   While a demo plays, the pane emits {map, route?} up to the shell via the
//   onContext callback; the shell wires this to the shared context store (LD-E3).
//
// Error states (SPEC §3.2):
//   - demo.html missing/404            -> pane shows an explicit error state
//   - records.json unreachable         -> Records tab shows explicit error; Archive unaffected
//   - individual demo 404              -> postMessage error from demo.html propagates
//
// postMessage API used (inbound from demo.html, same-origin):
//   {evt:"status", state}      — reflects loading/playing/ended/error in the chip
//   {evt:"time",   t}          — 1 Hz clock update while playing
//   {evt:"ended"}              — demo finished

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

// --------------------------------------------------------------------------
// Public types
// --------------------------------------------------------------------------

/** Parameters for the openDemo shell action (SPEC §6.5). */
export interface OpenDemoParams {
  /** Full URL of the .mvd or .qwd demo file. */
  demo_url: string;
  /** Map name (e.g. "dm3") — used to resolve the .bsp. */
  map: string;
  /** Optional seek target in demo-relative seconds; 2 s pre-roll applied inside demo.html. */
  t?: number | null;
  /** Optional userid to track (bot's POV). */
  track?: string | null;
  /** Optional human-readable label for the transport bar. */
  name?: string;
  /** Route this demo belongs to, if known (sets context). */
  route?: string | null;
}

/** Minimal demo context emitted while playing. */
export interface DemoContext {
  map: string;
  route: string | null;
}

// --------------------------------------------------------------------------
// Records schema types (komodobots.records.v1 — partial, what the UI needs)
// --------------------------------------------------------------------------

type RecordKind = "fastest_time" | "first_completion" | "peak_speed" | "edge_speed";

interface HumanRef {
  value: number;
  source: string;
  demo_url: string;
}

interface RecordEntry {
  value: number;
  units: string;
  run_id: string;
  demo_url: string;
  demo_archived: boolean | null;
  event_t_s: number | null;
  set_at: string;
  human_ref: HumanRef | null;
}

interface RouteRecords {
  records: Partial<Record<RecordKind, RecordEntry | null>>;
  aggregates: {
    attempts: number;
    finishes: number;
    median_time_s: number | null;
    human_time_s: number;
  };
}

interface RecordsJson {
  schema: string;
  maps: Record<string, { routes: Record<string, RouteRecords> }>;
}

// --------------------------------------------------------------------------
// Archive schema types (v2/demos.json partial)
// --------------------------------------------------------------------------

interface DemoNode {
  name: string;
  path: string[];
  is_dir: boolean;
  demo_url?: string;
  children?: DemoNode[];
  date?: string;
}

// --------------------------------------------------------------------------
// Constants
// --------------------------------------------------------------------------

const RECORDS_URL = "/demos/records/records.json";
// v2 API: the flat list endpoint is /v2/demos.json; we filter to the lab tree.
const DEMOS_V2_URL = "/v2/demos.json";
// Lab tree path prefix that archive demos live under.
const LAB_TREE_PATH = ["non-games", "lab", "Komodobots"];

const KIND_LABELS: Record<RecordKind, string> = {
  fastest_time: "fastest time",
  first_completion: "first completion",
  peak_speed: "peak speed",
  edge_speed: "edge speed",
};

const KIND_UNITS_FMT: Record<RecordKind, (v: number) => string> = {
  fastest_time: (v) => `${v.toFixed(2)} s`,
  first_completion: (v) => `${v.toFixed(2)} s`,
  peak_speed: (v) => `${Math.round(v)} qu/s`,
  edge_speed: (v) => `${Math.round(v)} qu/s`,
};

const RECORD_KINDS: RecordKind[] = [
  "fastest_time",
  "first_completion",
  "peak_speed",
  "edge_speed",
];

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

/** Extract a flat list of demo entries from the v2 tree, newest-first. */
function extractDemosFromTree(
  node: DemoNode,
  path: string[],
  labPath: string[],
): { url: string; label: string; map: string | null; date: string | null }[] {
  const results: { url: string; label: string; map: string | null; date: string | null }[] = [];

  // Only collect leaves that are inside (or at) the lab path.
  const inLab = labPath.every((seg, i) => path[i] === seg);

  if (!node.is_dir && node.demo_url && inLab) {
    // Infer map from the name (e.g. "20260605T201217Z_dm3.mvd" -> "dm3")
    const mapMatch = node.name.match(/_(\w+)\.(mvd|qwd)$/i);
    results.push({
      url: node.demo_url,
      label: node.name,
      map: mapMatch ? mapMatch[1].toLowerCase() : null,
      date: node.date ?? null,
    });
  }

  if (node.children) {
    for (const child of node.children) {
      const childPath = [...path, child.name];
      results.push(...extractDemosFromTree(child, childPath, labPath));
    }
  }

  return results;
}

/** Traverse the v2 tree to find nodes matching labPath then extract demos. */
function collectLabDemos(
  tree: DemoNode,
): { url: string; label: string; map: string | null; date: string | null }[] {
  // Walk to the lab subtree root, then extract all leaves.
  function walk(
    node: DemoNode,
    depth: number,
  ): { url: string; label: string; map: string | null; date: string | null }[] {
    if (depth === LAB_TREE_PATH.length) {
      // We are at the Komodobots node; collect all leaves from here.
      return extractDemosFromTree(node, LAB_TREE_PATH, LAB_TREE_PATH);
    }
    if (!node.children) return [];
    const want = LAB_TREE_PATH[depth];
    const child = node.children.find((c) => c.name === want && c.is_dir);
    if (!child) return [];
    return walk(child, depth + 1);
  }
  return walk(tree, 0);
}

// --------------------------------------------------------------------------
// Sub-components
// --------------------------------------------------------------------------

function StatusChip({
  state,
}: {
  state: "empty" | "loading" | "playing" | "ended" | "error" | "seeking";
}) {
  const cls =
    state === "playing" || state === "seeking"
      ? "bg-green-900/60 text-green-300 border-green-700 animate-pulse"
      : state === "loading"
        ? "bg-slate-800 text-gray-400 border-slate-600"
        : state === "error"
          ? "bg-red-900/60 text-red-300 border-red-700"
          : state === "ended"
            ? "bg-slate-800 text-gray-400 border-slate-600"
            : "bg-slate-900 text-gray-600 border-slate-800";
  return (
    <span
      className={`ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono border ${cls}`}
    >
      {state}
    </span>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2 py-0.5 text-xs rounded border transition-colors ${
        active
          ? "border-sky-500 bg-sky-900/40 text-sky-200"
          : "border-slate-700 text-gray-400 hover:border-slate-500 hover:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------
// Records tab
// --------------------------------------------------------------------------

function RecordsTab({
  map,
  onPlay,
}: {
  map: string;
  onPlay: (p: OpenDemoParams) => void;
}) {
  const [data, setData] = useState<RecordsJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(RECORDS_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`records.json: HTTP ${r.status}`);
        return r.json() as Promise<RecordsJson>;
      })
      .then((j) => {
        setData(j);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setError(String(e instanceof Error ? e.message : e));
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="p-3 text-xs text-gray-500 animate-pulse">
        loading records…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-xs text-red-400 border border-red-900/50 rounded m-2 bg-red-950/20">
        records unavailable: {error}
      </div>
    );
  }

  if (!data) return null;

  const mapData = data.maps[map];
  if (!mapData) {
    return (
      <div className="p-3 text-xs text-gray-500">
        no records for map <span className="font-mono text-gray-400">{map}</span>
      </div>
    );
  }

  const routes = Object.entries(mapData.routes);
  if (routes.length === 0) {
    return (
      <div className="p-3 text-xs text-gray-500">
        no censused routes for {map} yet
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      {routes.map(([route, routeData]) => (
        <div key={route} className="border-b border-slate-800 last:border-b-0">
          {/* Route header */}
          <div className="px-3 py-1.5 bg-slate-900/40 text-[11px] font-mono text-sky-300 flex items-center gap-x-2">
            <span>{route}</span>
            <span className="text-gray-600 font-sans">
              {routeData.aggregates.attempts} attempts ·{" "}
              {routeData.aggregates.finishes} finishes
            </span>
          </div>

          {/* Records for this route */}
          <div className="divide-y divide-slate-800/50">
            {RECORD_KINDS.map((kind) => {
              const rec = routeData.records[kind];
              const hasDemo = rec && rec.demo_url;
              return (
                <div
                  key={kind}
                  className={`px-3 py-1.5 text-xs flex items-center gap-x-2 ${
                    hasDemo
                      ? "hover:bg-slate-800/60 cursor-pointer group"
                      : "opacity-40"
                  }`}
                  onClick={
                    hasDemo
                      ? () => {
                          onPlay({
                            demo_url: rec.demo_url,
                            map,
                            t: rec.event_t_s,
                            name: `${route} · ${KIND_LABELS[kind]}`,
                            route,
                          });
                        }
                      : undefined
                  }
                >
                  <span className="text-gray-500 w-28 shrink-0">
                    {KIND_LABELS[kind]}
                  </span>
                  {rec ? (
                    <>
                      <span className="font-mono text-amber-300">
                        {KIND_UNITS_FMT[kind](rec.value)}
                      </span>
                      {rec.human_ref && (
                        <span className="text-gray-600 font-mono">
                          vs{" "}
                          <span className="text-cyan-700">
                            {KIND_UNITS_FMT[kind](rec.human_ref.value)}
                          </span>
                        </span>
                      )}
                      <span className="text-gray-600 ml-auto text-[10px]">
                        {rec.set_at}
                      </span>
                      {hasDemo && (
                        <span className="text-sky-500 opacity-0 group-hover:opacity-100 text-[10px] transition-opacity">
                          ▶ play
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-gray-600">no record yet</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// Archive tab
// --------------------------------------------------------------------------

function ArchiveTab({
  onPlay,
}: {
  onPlay: (p: OpenDemoParams) => void;
}) {
  type Demo = { url: string; label: string; map: string | null; date: string | null };

  const [demos, setDemos] = useState<Demo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [mapFilter, setMapFilter] = useState<string>("all");

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(DEMOS_V2_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`demos API: HTTP ${r.status}`);
        return r.json() as Promise<DemoNode>;
      })
      .then((tree) => {
        const collected = collectLabDemos(tree);
        // Sort newest-first by label (ISO run ids sort lexicographically).
        collected.sort((a, b) => b.label.localeCompare(a.label));
        setDemos(collected);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setError(String(e instanceof Error ? e.message : e));
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="p-3 text-xs text-gray-500 animate-pulse">
        loading archive…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-xs text-red-400 border border-red-900/50 rounded m-2 bg-red-950/20">
        archive unavailable: {error}
      </div>
    );
  }

  const maps = Array.from(new Set(demos.map((d) => d.map).filter(Boolean))) as string[];
  const filtered =
    mapFilter === "all" ? demos : demos.filter((d) => d.map === mapFilter);

  return (
    <div className="flex flex-col h-full">
      {/* Map filter */}
      <div className="flex items-center gap-x-1.5 px-3 py-1.5 border-b border-slate-800 shrink-0">
        <span className="text-[10px] text-gray-600 mr-1">map</span>
        <button
          type="button"
          onClick={() => setMapFilter("all")}
          className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
            mapFilter === "all"
              ? "border-sky-600 bg-sky-900/40 text-sky-300"
              : "border-slate-700 text-gray-500 hover:border-slate-500"
          }`}
        >
          all
        </button>
        {maps.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMapFilter(m)}
            className={`px-1.5 py-0.5 text-[10px] rounded border font-mono transition-colors ${
              mapFilter === m
                ? "border-sky-600 bg-sky-900/40 text-sky-300"
                : "border-slate-700 text-gray-500 hover:border-slate-500"
            }`}
          >
            {m}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-gray-600">
          {filtered.length} demo{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Demo list */}
      <div className="overflow-y-auto grow">
        {filtered.length === 0 ? (
          <div className="p-3 text-xs text-gray-500">
            no archived demos{mapFilter !== "all" ? ` for ${mapFilter}` : ""}
          </div>
        ) : (
          filtered.map((demo) => (
            <div
              key={demo.url}
              className="px-3 py-1.5 text-xs font-mono text-gray-300 hover:bg-slate-800/60 cursor-pointer flex items-center gap-x-2 border-b border-slate-800/60 last:border-b-0 group"
              onClick={() =>
                onPlay({
                  demo_url: demo.url,
                  map: demo.map ?? "dm3",
                  t: null,
                  name: demo.label,
                  route: null,
                })
              }
            >
              <span className="truncate grow">{demo.label}</span>
              {demo.map && (
                <span className="shrink-0 text-[10px] text-gray-600">
                  {demo.map}
                </span>
              )}
              <span className="text-sky-500 opacity-0 group-hover:opacity-100 text-[10px] transition-opacity shrink-0">
                ▶
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Main DemoPane component
// --------------------------------------------------------------------------

/** Tab choice: "records" or "archive". */
type TabId = "records" | "archive";

type DemoStatus = "empty" | "loading" | "playing" | "ended" | "error" | "seeking";

interface DemoState {
  /** Currently loaded demo params (null = pane empty). */
  current: OpenDemoParams | null;
}

export interface DemoPaneHandle {
  /**
   * Shell-level openDemo action (SPEC §6.5).
   * Posts {cmd:"load"} to the demo.html iframe.
   * Exported for LD-E4 record clicks to reuse.
   */
  openDemo: (params: OpenDemoParams) => void;
}

interface DemoPaneProps {
  /** Current context map name (used as default map for the records tab). */
  contextMap: string;
  /**
   * Callback fired while a demo is playing, emitting {map, route?} context.
   * The shell wires this to the shared context store (LD-E3).
   */
  onContext?: (ctx: DemoContext | null) => void;
  /**
   * Ref populated with the openDemo handle so the parent (App.tsx) can expose
   * it as the shell-level openDemo action.
   */
  handleRef?: React.MutableRefObject<DemoPaneHandle | null>;
}

export function DemoPane({ contextMap, onContext, handleRef }: DemoPaneProps) {
  const [tab, setTab] = useState<TabId>("records");
  const [demoState, setDemoState] = useState<DemoState>({ current: null });
  const [demoStatus, setDemoStatus] = useState<DemoStatus>("empty");
  const iframeRef = useRef<HTMLIFrameElement>(null);
  // Track the last-posted params so the iframe onLoad can re-post reliably
  // (same timing-race fix as qtv.html, PR #137).
  const loadParamsRef = useRef<OpenDemoParams | null>(null);

  // ------------------------------------------------------------------
  // openDemo: post {cmd:"load"} to the iframe (or set the initial src).
  // ------------------------------------------------------------------
  const openDemo = useCallback(
    (params: OpenDemoParams) => {
      setDemoState({ current: params });
      setDemoStatus("loading");
      if (onContext) {
        onContext({ map: params.map, route: params.route ?? null });
      }
      loadParamsRef.current = params;
      const iframe = iframeRef.current;
      if (!iframe || !iframe.contentWindow) return;
      iframe.contentWindow.postMessage(
        {
          cmd: "load",
          demo: params.demo_url,
          map: params.map,
          t: params.t ?? undefined,
          track: params.track ?? undefined,
          name: params.name ?? undefined,
        },
        window.location.origin,
      );
    },
    [onContext],
  );

  // Wire the handle ref so App.tsx can call openDemo from outside.
  useEffect(() => {
    if (handleRef) {
      handleRef.current = { openDemo };
    }
  }, [handleRef, openDemo]);

  // ------------------------------------------------------------------
  // Listen for postMessage events from demo.html (same-origin).
  // ------------------------------------------------------------------
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.origin !== window.location.origin) return;
      const m = ev.data as
        | { evt?: string; state?: string; t?: number }
        | null;
      if (!m || typeof m !== "object") return;
      if (m.evt === "status") {
        const s = m.state as DemoStatus | undefined;
        if (s) setDemoStatus(s);
        if (s === "playing" && demoState.current && onContext) {
          onContext({
            map: demoState.current.map,
            route: demoState.current.route ?? null,
          });
        }
      } else if (m.evt === "ended") {
        setDemoStatus("ended");
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [demoState, onContext]);

  // ------------------------------------------------------------------
  // Picker header height: when there is a loaded demo we shrink the
  // picker to a compact strip so the player area dominates.
  // ------------------------------------------------------------------
  const pickerFull = !demoState.current;

  // Build the iframe src from the loaded params, or blank when empty.
  const iframeSrc = "/botlab/panes/demo.html";

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* ---- Picker header ---- */}
      <div
        className={`shrink-0 flex flex-col border-b border-slate-800 transition-all ${
          pickerFull ? "grow min-h-0 overflow-hidden" : "h-44 overflow-hidden"
        }`}
      >
        {/* Tab bar */}
        <div className="flex items-center gap-x-1.5 px-2 py-1 border-b border-slate-800 bg-slate-900/60 shrink-0">
          <TabButton active={tab === "records"} onClick={() => setTab("records")}>
            Records
          </TabButton>
          <TabButton active={tab === "archive"} onClick={() => setTab("archive")}>
            Archive
          </TabButton>
          <StatusChip state={demoStatus} />
        </div>

        {/* Tab body */}
        <div className="grow min-h-0 overflow-y-auto">
          {tab === "records" ? (
            <RecordsTab map={contextMap} onPlay={openDemo} />
          ) : (
            <ArchiveTab onPlay={openDemo} />
          )}
        </div>
      </div>

      {/* ---- Player area (iframe) ---- */}
      {/*
        The iframe is always mounted (even when no demo is loaded) so that
        the FTE engine does not need to restart between demos — the {cmd:"load"}
        postMessage triggers a same-page location.replace inside demo.html which
        reinitializes state without a React re-mount.

        When empty, demo.html receives no ?demo= param and will show its own
        "no ?demo= given" error state (which is fine — the picker is shown
        prominently when empty). We render the iframe only once a demo has been
        loaded to avoid booting FTE for a pane the user hasn't engaged with yet.
      */}
      {demoState.current ? (
        <div className="grow min-h-0 relative">
          <iframe
            ref={iframeRef}
            src={iframeSrc}
            title="demo player"
            className="block w-full h-full border-0"
            onLoad={() => {
              // Re-send load params after iframe navigation (timing-race fix).
              const params = loadParamsRef.current;
              const iframe = iframeRef.current;
              if (!params || !iframe || !iframe.contentWindow) return;
              iframe.contentWindow.postMessage(
                {
                  cmd: "load",
                  demo: params.demo_url,
                  map: params.map,
                  t: params.t ?? undefined,
                  track: params.track ?? undefined,
                  name: params.name ?? undefined,
                },
                window.location.origin,
              );
            }}
          />
        </div>
      ) : (
        <div className="grow min-h-0 flex items-center justify-center text-xs text-gray-600 border-t border-slate-800">
          pick a demo above to begin
        </div>
      )}
    </div>
  );
}
