import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { BotLab3D } from "./BotLab3D.tsx";
import { TelemetryHud } from "./TelemetryHud.tsx";
import { type TelemetryAttempt, TelemetryClient } from "./telemetryClient.ts";
import {
  type LayoutState,
  loadLayout,
  orderViews,
  persistLayout,
  VIEW_LABELS,
  VIEW_ORDER,
  type ViewId,
} from "./layoutState.ts";
import {
  DemoPane,
  type DemoContext,
  type DemoPaneHandle,
  type OpenDemoParams,
} from "./DemoPane.tsx";
import { MockupPane, type MockupSelection } from "./MockupPane.tsx";
import { KpiDock } from "./KpiDock.tsx";
import {
  applyContextUpdate,
  INITIAL_KPI_CONTEXT,
  type KpiContext,
} from "./contextStore.ts";
// LD-F3 (#105): control drawer
import { ControlClient } from "./controlClient.ts";
import { ControlDrawer } from "./ControlDrawer.tsx";

// Re-export openDemo type for LD-E4 (#104) to import.
export type { OpenDemoParams } from "./DemoPane.tsx";

// LD-D3 (#98): Shell context — exposes the openDemo action to the KPI dock
// (LD-E4, #104) and any future child without prop drilling.
// The context is populated in App and consumed in the dock record rows.

export interface ShellActions {
  /** Shell-level openDemo: opens Demo view if closed, then loads the demo. */
  openDemo: (params: OpenDemoParams) => void;
}

export const ShellActionsContext = createContext<ShellActions | null>(null);

/** Hook for child components to call shell-level actions (e.g. KPI dock #104). */
export function useShellActions(): ShellActions | null {
  return useContext(ShellActionsContext);
}

// v1 defaults: dm3 lab on servexeri (LAN). Override per-instance with
// ?port=28600&ws=ws://localhost:8770&relay=ws://... (e.g. through ssh -L
// tunnels).
//
// LD-A1 absorption note: the original local-hub page rendered the live game
// panel with the hub fork's FteQtvPlayer (@qwhub/*) and drove qtvplay/retry
// itself. That dependency is gone.
//
// LD-B1 (#87): view shell — top-bar toggles + fixed-order pane grid
// (Demo -> Mockup -> Live 3D -> Live Game). Demo/Mockup are labeled
// placeholders until LD-D3 (#94/#98) / LD-C3 (#97); the control drawer
// renders as a labeled placeholder until LD-F3 (#105). Layout state persists
// per lab/dashboard/src/layoutState.ts.
//
// LD-E1 (#100): KPI dock built — KpiDock component replaces the placeholder
// <aside>.  Context store (contextStore.ts) tracks {map, route, source}
// with precedence live > last-user-selection > none.  Three producers wired:
// telemetry live-state (map from attempt, source live/none), MockupPane
// selection (source mockup), Demo context stub (LD-D3 #98 will feed this).
//
// LD-B2 (#88): Live Game pane = standalone qtv.html iframe. The iframe boots
// FTE WASM once and re-issues qtvplay on every new attempt via postMessage
// {cmd:"attach", port, map}. The retry/attach loop is driven from here (same
// pattern as the old hub App.tsx) so the shell can coordinate with telemetry.
//
// LD-B3 (#89): single shared TelemetryClient at shell scope — one WebSocket
// connection per page.  The client instance is created in the App effect below
// and passed as a prop into BotLab3D / TelemetryHud.  Future consumers (KPI
// dock LD-E1, context store LD-E3) read the same client from a context or
// prop.  Closing and reopening the Live 3D pane disposes and rebuilds the
// Three.js scene without closing the shared socket (BotLab3D only registers
// frameListeners on the client — it does not own the connection).  The
// map-scene setup (scene/camera/renderer/controls/mesh/resize) is factored
// into src/mapScene.ts for reuse by the Mockup pane (LD-C3, #97).
//
// LD-C5 (#99): mapOpacity and wireframe layout state wired to BotLab3D and
// MockupPane so both 3D views share the top-bar opacity slider / wireframe
// toggle.  Controls persist via layoutState.ts.
//
// LD-F4 (#103): selectedEd state — tracks which bot is followed by the
// camera and which HUD row is expanded.  null = first-seen bot (single-bot
// compat).  Set by clicking a marker in BotLab3D or a compact row in
// TelemetryHud; reset on new_attempt.
const DEFAULT_LAB_PORT = 28599;
const DEFAULT_TELEMETRY_WS = "ws://192.168.86.33:8770";
const DEFAULT_QTV_RELAY = "ws://192.168.86.33:27599";

// Status values emitted by qtv.html via postMessage {evt:"status", state}.
type QtvStatus = "loading" | "connected" | "retrying" | "disconnected";

function getParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

function Pane({ id, header, children }: {
  id: ViewId;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      data-pane={id}
      className="flex flex-col min-w-0 border-r border-slate-800 last:border-r-0"
    >
      <div className="flex items-center gap-x-3 px-2 py-1 text-xs uppercase tracking-wide text-gray-400 border-b border-slate-800 bg-slate-900/60">
        {header}
      </div>
      <div className="relative grow min-h-0">{children}</div>
    </section>
  );
}

export function App() {
  const wsUrl = useMemo(() => getParam("ws") ?? DEFAULT_TELEMETRY_WS, []);
  const qtvRelay = useMemo(() => getParam("relay") ?? DEFAULT_QTV_RELAY, []);
  const fallbackPort = useMemo(() => {
    const port = Number(getParam("port"));
    return Number.isInteger(port) && port > 0 ? port : DEFAULT_LAB_PORT;
  }, []);

  const [client, setClient] = useState<TelemetryClient | null>(null);
  const [attempt, setAttempt] = useState<TelemetryAttempt | null>(null);
  const [connection, setConnection] = useState({ connected: false, live: false });

  // LD-F3 (#105): single ControlClient instance — stable ref, not recreated
  // on reconnects (the telemetry effect wires/unwires it via onConnectionChange).
  const controlClientRef = useRef<ControlClient>(
    new ControlClient(
      new URLSearchParams(window.location.search).get("ctoken") ?? undefined,
    ),
  );
  const [showReference, setShowReference] = useState(true);
  const [layout, setLayout] = useState<LayoutState>(() =>
    loadLayout(window.location.search),
  );

  // LD-E1 (#100): KPI context store — useReducer holds {context, lastUser}
  // together so applyContextUpdate always sees consistent paired state.
  type ContextPair = { context: KpiContext; lastUser: KpiContext };
  const [ctxPair, dispatchContext] = useReducer(
    (
      state: ContextPair,
      update: Parameters<typeof applyContextUpdate>[2],
    ): ContextPair => applyContextUpdate(state.context, state.lastUser, update),
    { context: INITIAL_KPI_CONTEXT, lastUser: INITIAL_KPI_CONTEXT },
  );
  const kpiContext = ctxPair.context;

  // LD-E2 (#101) + LD-E4 (#104): shared refresh key — incremented when an
  // attempt ends (live true→false) so the KPI dock's BrutalScoreboard
  // (LD-E2) and RecordsPanel (LD-E4) both refetch their data after each run.
  // Unified at merge time per the LD-E4 PR note: same increment event,
  // one source of truth.
  const [refreshKey, setRefreshKey] = useState(0);
  const prevLiveRef = useRef(false);

  // LD-F4 (#103): selected bot ed — drives BotLab3D camera follow and
  // TelemetryHud expanded row.  null = first-seen bot (single-bot compat).
  // Reset on new_attempt so camera re-locks to the first bot automatically.
  const [selectedEd, setSelectedEd] = useState<number | null>(null);

  // LD-B2 (#88): QTV iframe ref + status chip state.
  const qtvIframeRef = useRef<HTMLIFrameElement>(null);
  const [qtvStatus, setQtvStatus] = useState<QtvStatus>("loading");
  // Tracks the latest attach params so the iframe onLoad handler can reliably
  // send the initial attach even if the effect fires before the iframe listener
  // is installed (race condition fix per Codex PR #137 review).
  const qtvAttachRef = useRef<{ port: number; relay: string; map: string } | null>(null);

  // LD-D3 (#98): Demo pane handle (openDemo shell action) + demo context.
  // The handle ref is populated by DemoPane via its handleRef prop so App.tsx
  // can call openDemo from the KPI dock record clicks (LD-E4, #104).
  const demoPaneHandleRef = useRef<DemoPaneHandle | null>(null);
  const [demoContext, setDemoContext] = useState<DemoContext | null>(null);

  // LD-D3 (#98): pending demo params queue.
  // When openDemo is called while the Demo view is closed, DemoPane has not
  // yet mounted and demoPaneHandleRef.current is null. We park the params here
  // and flush them in onDemoPaneHandleReady (called by DemoPane's mount effect)
  // so the iframe receives the {cmd:"load"} postMessage once the pane exists.
  const pendingDemoRef = useRef<OpenDemoParams | null>(null);

  /**
   * openDemo — shell-level entry point (SPEC §6.5).
   * Opens/focuses the Demo view if closed, then loads the demo in the pane.
   * Exported via demoPaneHandleRef for LD-E4 (#104) to reuse.
   */
  const openDemo = useCallback(
    (params: OpenDemoParams) => {
      // Ensure the Demo view is open (toggles it on if closed).
      setLayout((state) => {
        if (state.views.includes("demo")) return state;
        return { ...state, views: orderViews([...state.views, "demo"]) };
      });
      if (demoPaneHandleRef.current) {
        // Pane is already mounted — deliver immediately.
        demoPaneHandleRef.current.openDemo(params);
      } else {
        // Pane not yet mounted (view was closed); park params for flush in
        // onDemoPaneHandleReady, which fires once DemoPane's mount effect runs.
        pendingDemoRef.current = params;
      }
    },
    [],
  );

  /**
   * onDemoPaneHandleReady — called by DemoPane immediately after it wires its
   * handle into demoPaneHandleRef (mount effect). Flushes any queued params so
   * a click-to-play that arrived before the pane existed is delivered.
   */
  const onDemoPaneHandleReady = useCallback(() => {
    const params = pendingDemoRef.current;
    if (params && demoPaneHandleRef.current) {
      pendingDemoRef.current = null;
      demoPaneHandleRef.current.openDemo(params);
    }
  }, []);

  useEffect(() => {
    const ctrl = controlClientRef.current;
    const telemetry = new TelemetryClient(wsUrl);
    telemetry.attemptListeners.add(setAttempt);
    telemetry.stateListeners.add(setConnection);

    // LD-F3 (#105): wire the ControlClient to the telemetry socket.
    // Raw message listener routes bridge responses/events to the control client.
    function onRawMessage(text: string) {
      ctrl.onMessage(text);
    }
    telemetry.rawMessageListeners.add(onRawMessage);

    // State listener to keep ControlClient's connection flag in sync.
    function onConnState(state: { connected: boolean }) {
      ctrl.onConnectionChange(state.connected, state.connected ? (t) => telemetry.sendText(t) : null);
    }
    telemetry.stateListeners.add(onConnState);

    // LD-F4 (#103): reset bot selection on new_attempt only — not on hello
    // reconnects.  telemetryClient.attemptListeners fires for both new_attempt
    // and hello (when run_id is set).  On a transient WebSocket reconnect the
    // hello delivers the SAME run_id for the ongoing attempt; resetting there
    // would drop the user's camera selection mid-attempt (Codex inline P2
    // discussion_r3395550280).  Guard: check the type field on the raw message
    // (present at runtime even though TelemetryAttempt does not include it).
    const resetSelectedEd = (attempt: TelemetryAttempt) => {
      if ((attempt as unknown as { type?: string }).type === "new_attempt") {
        setSelectedEd(null);
      }
    };
    telemetry.attemptListeners.add(resetSelectedEd);

    setClient(telemetry);
    return () => {
      telemetry.rawMessageListeners.delete(onRawMessage);
      telemetry.stateListeners.delete(onConnState);
      telemetry.attemptListeners.delete(resetSelectedEd);
      ctrl.onConnectionChange(false, null);
      telemetry.close();
      setClient(null);
    };
  }, [wsUrl]);

  useEffect(() => {
    persistLayout(layout);
  }, [layout]);

  // LD-B2 (#88): listen for postMessage status events from qtv.html.
  // Same-origin guard: the iframe is served from the same origin as the shell.
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.origin !== window.location.origin) return;
      const m = ev.data as { evt?: string; state?: string } | null;
      if (!m || typeof m !== "object" || m.evt !== "status") return;
      const s = m.state;
      if (s === "loading" || s === "connected" || s === "retrying" || s === "disconnected") {
        setQtvStatus(s as QtvStatus);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // LD-E1 (#100): telemetry live-state producer — when a live attempt starts,
  // push source="live" with the current attempt map.  When it ends, push
  // live=false so the context falls back to the last user selection.
  // The map in the live update comes from `attempt.map` (may be null on initial
  // connection before the first attempt; guard with ?? "dm3").
  useEffect(() => {
    if (connection.live) {
      dispatchContext({ kind: "live", map: attempt?.map ?? "dm3", live: true });
    } else {
      dispatchContext({ kind: "live", map: attempt?.map ?? "dm3", live: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection.live, attempt?.map]);

  // LD-E2 (#101) + LD-E4 (#104): detect live true→false (attempt ended) and
  // increment the shared refreshKey so BrutalScoreboard (LD-E2) and
  // RecordsPanel (LD-E4) both refetch after each run.
  useEffect(() => {
    if (prevLiveRef.current && !connection.live) {
      // live just went false — attempt ended.
      setRefreshKey((k) => k + 1);
    }
    prevLiveRef.current = connection.live;
  }, [connection.live]);

  // LD-B2 (#88): send {cmd:"attach"} to qtv.html whenever the lab port or run
  // changes (i.e. new attempt), mirroring the hub App.tsx attach/retry pattern.
  // labPort and mapName are derived below; keep the effect after their declarations.

  // Esc closes the control drawer (SPEC §6.1).
  // Click outside the drawer header area also closes (non-modal, SPEC §3.7).
  useEffect(() => {
    if (!layout.drawerOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setLayout((state) => ({ ...state, drawerOpen: false }));
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (!target) return;
      // Close if the click lands outside the drawer element itself.
      const drawer = document.querySelector('[data-drawer="control"]');
      if (drawer && !drawer.contains(target)) {
        setLayout((state) => ({ ...state, drawerOpen: false }));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [layout.drawerOpen]);

  // LD-E1 (#100): "[" toggles the KPI dock (non-conflicting; no modifier needed).
  // Guard: skip when focus is inside an input, textarea, or select so normal
  // typing is unaffected.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "[") return;
      const tag = (event.target as HTMLElement | null)?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      setLayout((state) => ({ ...state, dockCollapsed: !state.dockCollapsed }));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const toggleView = (view: ViewId) => {
    setLayout((state) => ({
      ...state,
      views: state.views.includes(view)
        ? state.views.filter((open) => open !== view)
        : orderViews([...state.views, view]),
    }));
  };

  const labPort = attempt?.port ?? fallbackPort;
  const runId = attempt?.run_id ?? null;
  const mapName = attempt?.map ?? "dm3";
  const openViews = layout.views;

  // LD-B2 (#88): send {cmd:"attach"} to the qtv.html iframe whenever the lab
  // port or run_id changes (covers: initial load, new attempt, port change).
  // The iframe drives its own ~3 s retry loop on disconnect; this effect only
  // fires on explicit port/run changes from telemetry, not on every retry cycle.
  //
  // The attach params are also stored in qtvAttachRef so the iframe onLoad
  // handler can resend them reliably if the iframe document has not yet installed
  // its message listener when this effect first fires (timing race on cold load,
  // or on ssh-tunnel/?port= override paths where non-default params are in use).
  useEffect(() => {
    const params = { port: labPort, relay: qtvRelay, map: mapName };
    qtvAttachRef.current = params;
    const iframe = qtvIframeRef.current;
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { cmd: "attach", ...params },
      window.location.origin,
    );
  }, [labPort, runId, qtvRelay, mapName]);

  // LD-E1 (#100): Stable mockup-selection callback — memoized so MockupPane's
  // useEffect (which lists onSelect as a dep) does not re-run on every App render.
  // An inline arrow would get a new identity each render, causing dispatchContext
  // → new state object → re-render → new arrow → loop (Codex inline P1).
  const onMockupSelect = useCallback(
    (sel: MockupSelection) => {
      dispatchContext({ kind: "mockup", map: sel.map, route: sel.route });
    },
    [], // dispatchContext is the useReducer dispatch — always stable
  );

  const paneContent: Record<ViewId, ReactNode> = {
    // LD-D3 (#98): Demo view — records/archive picker + FTE demo iframe.
    // DemoPane manages the FTE iframe and picker; App.tsx wires openDemo and
    // context. The pane header stays minimal (label + status chip is inside the
    // picker bar) to keep the DemoPane layout self-contained.
    demo: (
      <Pane key="demo" id="demo" header={<span>Demo</span>}>
        <DemoPane
          contextMap={mapName}
          onContext={(ctx: DemoContext | null) => {
            // LD-E1 (#100): wire demo context to the KPI reducer (P1 fix).
            // Set local preview state (used in the status-bar line) AND
            // dispatch to the shared context store so the KPI dock reflects
            // demo playback.  When ctx is null (demo ended/unloaded), we do
            // not dispatch a reset — the last selection persists per
            // applyContextUpdate precedence rules.
            setDemoContext(ctx);
            if (ctx !== null) {
              dispatchContext({ kind: "demo", map: ctx.map, route: ctx.route });
            }
          }}
          handleRef={demoPaneHandleRef}
          onHandleReady={onDemoPaneHandleReady}
        />
      </Pane>
    ),
    mockup: (
      <Pane
        key="mockup"
        id="mockup"
        header={
          <>
            <span>Mockup</span>
            {kpiContext.source === "mockup" && kpiContext.route !== null && (
              <span className="ml-2 text-gray-500 font-mono">
                {kpiContext.map} · {kpiContext.route}
              </span>
            )}
          </>
        }
      >
        {/* LD-C3 (#97): offline map/route browser. Emits MockupSelection to the
            shell so the KPI dock (LD-E1, #100) reacts to map/route context
            changes from the Mockup pane.
            LD-C5 (#99): mapOpacity / wireframe forwarded from shared layout
            state so both 3D panes react to the top-bar shared controls. */}
        <MockupPane
          onSelect={onMockupSelect}
          mapOpacity={layout.mapOpacity}
          wireframe={layout.wireframe}
        />
      </Pane>
    ),
    live3d: (
      <Pane
        key="live3d"
        id="live3d"
        header={
          <>
            <span>Live 3D</span>
            {/* LD-C5 (#99): shared opacity slider + wireframe toggle for
                both 3D panes; values live in layout state (persisted). */}
            <label className="ml-2 flex items-center gap-x-1 normal-case tracking-normal text-gray-400 text-[10px]">
              opacity
              <input
                type="range"
                min={0.05}
                max={1.0}
                step={0.05}
                value={layout.mapOpacity}
                onChange={(event) =>
                  setLayout((state) => ({
                    ...state,
                    mapOpacity: Number(event.target.value),
                  }))
                }
                className="w-16 accent-sky-400"
                title={`Map opacity: ${Math.round(layout.mapOpacity * 100)}%`}
              />
              <span className="w-6 text-right font-mono">
                {Math.round(layout.mapOpacity * 100)}%
              </span>
            </label>
            <label className="flex items-center gap-x-1 normal-case tracking-normal text-gray-400 text-[10px]">
              <input
                type="checkbox"
                checked={layout.wireframe}
                onChange={(event) =>
                  setLayout((state) => ({
                    ...state,
                    wireframe: event.target.checked,
                  }))
                }
              />
              wire
            </label>
            <label className="flex items-center gap-x-1 normal-case tracking-normal text-gray-400">
              <input
                type="checkbox"
                checked={showReference}
                onChange={(event) => setShowReference(event.target.checked)}
              />
              human path
            </label>
          </>
        }
      >
        {client && (
          <BotLab3D
            client={client}
            mapName={mapName}
            referencePathUrl={
              mapName === "dm3" ? "/botlab/dm3_sng_to_rl.cmds" : null
            }
            showReferencePath={showReference}
            mapOpacity={layout.mapOpacity}
            wireframe={layout.wireframe}
            selectedEd={selectedEd}
            onBotClick={setSelectedEd}
          />
        )}
        {!connection.live && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60 pointer-events-none">
            <span className="animate-pulse text-gray-400">
              {connection.connected
                ? "waiting for attempt…"
                : `connecting to ${wsUrl}…`}
            </span>
          </div>
        )}
        <div className="absolute bottom-0 inset-x-0">
          {client && (
            <TelemetryHud
              client={client}
              selectedEd={selectedEd}
              onBotClick={setSelectedEd}
            />
          )}
        </div>
      </Pane>
    ),
    game: (
      <Pane
        key="game"
        id="game"
        header={
          <>
            <span>Live Game</span>
            <span
              className={`ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono ${
                qtvStatus === "connected"
                  ? "bg-green-900/60 text-green-300 border border-green-700"
                  : qtvStatus === "retrying"
                    ? "bg-amber-900/60 text-amber-300 border border-amber-700 animate-pulse"
                    : qtvStatus === "loading"
                      ? "bg-slate-800 text-gray-400 border border-slate-600"
                      : "bg-slate-800 text-gray-500 border border-slate-700"
              }`}
            >
              {qtvStatus}
            </span>
          </>
        }
      >
        {/* LD-B2 (#88): standalone qtv.html — FTE WASM QTV spectate pane.
            The iframe boots once; the shell re-attaches on every new attempt via
            postMessage {cmd:"attach"}. The pane drives its own ~3 s retry loop.
            src is fixed (no port in the URL) so the iframe never reloads; port
            changes are communicated via postMessage only.
            onLoad resends the current attach params once the iframe document is
            parsed and its message listener is installed — this is the reliable
            handshake that closes the timing race on initial load / tunnel paths. */}
        <iframe
          ref={qtvIframeRef}
          src="/botlab/panes/qtv.html"
          title="live game view"
          className="block w-full h-full border-0"
          onLoad={() => {
            const iframe = qtvIframeRef.current;
            const params = qtvAttachRef.current;
            if (!iframe || !iframe.contentWindow || !params) return;
            iframe.contentWindow.postMessage(
              { cmd: "attach", ...params },
              window.location.origin,
            );
          }}
        />
      </Pane>
    ),
  };

  // LD-D3 (#98): build the shell actions value; stable reference via useMemo.
  const shellActions = useMemo(() => ({ openDemo }), [openDemo]);

  return (
    <ShellActionsContext.Provider value={shellActions}>
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="relative z-20 flex items-center gap-x-4 px-4 py-2 text-sm border-b border-slate-800">
        <span className="font-bold">bot lab</span>

        <div className="flex items-center gap-x-1" role="group" aria-label="view toggles">
          {VIEW_ORDER.map((view) => {
            const open = openViews.includes(view);
            return (
              <button
                key={view}
                type="button"
                aria-pressed={open}
                onClick={() => toggleView(view)}
                className={`px-2 py-0.5 rounded border text-xs ${
                  open
                    ? "border-sky-500 bg-sky-900/60 text-sky-200"
                    : "border-slate-700 text-gray-400 hover:border-slate-500"
                }`}
              >
                {VIEW_LABELS[view]}
              </button>
            );
          })}
        </div>

        <button
          type="button"
          aria-pressed={layout.dockCollapsed}
          aria-keyshortcuts="["
          title="KPI dock — toggle with [ key (LD-E1 #100)"
          onClick={() =>
            setLayout((state) => ({
              ...state,
              dockCollapsed: !state.dockCollapsed,
            }))
          }
          className="px-2 py-0.5 rounded border border-dashed border-slate-700 text-xs text-gray-500 hover:border-slate-500"
        >
          KPI {layout.dockCollapsed ? "▸" : "◂"}
        </button>
        <button
          type="button"
          aria-pressed={layout.drawerOpen}
          title="Control drawer — built in LD-F3 (#105); this button persists the open state"
          onClick={() =>
            setLayout((state) => ({ ...state, drawerOpen: !state.drawerOpen }))
          }
          className={`px-2 py-0.5 rounded border border-dashed text-xs ${
            layout.drawerOpen
              ? "border-slate-500 text-gray-300"
              : "border-slate-700 text-gray-500 hover:border-slate-500"
          }`}
        >
          Control
        </button>

        {/* LD-D3 (#98): demo context line — emitted by DemoPane while playing;
            wired to the shared context store in LD-E3 (#100). Shown in the
            status bar as a preview until the KPI dock context line (LD-E1) lands. */}
        {demoContext && !connection.live && (
          <span className="font-mono text-sky-600 text-xs">
            {demoContext.map}
            {demoContext.route ? ` · ${demoContext.route}` : ""}
            {" · demo"}
          </span>
        )}
        <span className="ml-auto font-mono text-gray-400">
          {mapName} · port {labPort} · {runId ?? "no attempt yet"}
        </span>
        <span
          className={
            connection.live
              ? "text-green-400"
              : connection.connected
                ? "text-amber-400"
                : "text-red-400"
          }
        >
          {connection.live
            ? "live"
            : connection.connected
              ? "waiting for attempt"
              : "telemetry disconnected"}
        </span>

        {/* LD-F3 (#105): real control drawer — session/map/roster/assignment/console */}
        {layout.drawerOpen && (
          <ControlDrawer
            client={controlClientRef.current}
            telemetryClient={client}
            wsConnected={connection.connected}
            onClose={() => setLayout((state) => ({ ...state, drawerOpen: false }))}
          />
        )}
      </header>

      <div className="grow min-h-0 flex">
        {/* LD-E1 (#100): KPI dock — real component replaces the placeholder aside.
            LD-E2 (#101): refreshKey triggers BrutalScoreboard refetch on attempt end.
            LD-E3 (#102): client + isLive wire the live metrics panel.
            LD-E4 (#104): same refreshKey also triggers RecordsPanel refetch. */}
        <KpiDock
          context={kpiContext}
          collapsed={layout.dockCollapsed}
          onToggle={() =>
            setLayout((state) => ({ ...state, dockCollapsed: !state.dockCollapsed }))
          }
          refreshKey={refreshKey}
          client={client}
          isLive={connection.live}
          selectedEd={selectedEd}
        />

        <main className="grow min-w-0 overflow-x-auto">
          {openViews.length === 0 ? (
            <div className="h-full flex items-center justify-center text-gray-500">
              toggle a view to begin
            </div>
          ) : (
            <div
              className="h-full grid"
              style={{
                gridTemplateColumns: `repeat(${openViews.length}, minmax(280px, 1fr))`,
              }}
            >
              {openViews.map((view) => paneContent[view])}
            </div>
          )}
        </main>
      </div>
    </div>
    </ShellActionsContext.Provider>
  );
}

export default App;
