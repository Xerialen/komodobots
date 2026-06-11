import { useEffect, useMemo, useState, type ReactNode } from "react";
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

// v1 defaults: dm3 lab on servexeri (LAN). Override per-instance with
// ?port=28600&ws=ws://localhost:8770&game=http://... (e.g. through ssh -L
// tunnels).
//
// LD-A1 absorption note: the original local-hub page rendered the live game
// panel with the hub fork's FteQtvPlayer (@qwhub/*) and drove qtvplay/retry
// itself. That dependency is gone — the panel temporarily embeds the deployed
// /qtv/ page in an iframe; the proper standalone same-origin postMessage QTV
// pane lands in LD-B2 (#88).
//
// LD-B1 (#87): view shell — top-bar toggles + fixed-order pane grid
// (Demo -> Mockup -> Live 3D -> Live Game). Demo/Mockup are labeled
// placeholders until LD-D3 (#94/#98) / LD-C3 (#97); the KPI dock and the
// control drawer render as labeled placeholders until LD-E1 (#100) /
// LD-F3 (#105). Layout state persists per lab/dashboard/src/layoutState.ts.
const DEFAULT_LAB_PORT = 28599;
const DEFAULT_TELEMETRY_WS = "ws://192.168.86.33:8770";
const DEFAULT_GAME_VIEW_URL = "http://192.168.86.33:8095/qtv/";

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

function PlaceholderPane({ title, note }: { title: string; note: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-y-2 text-center px-4">
      <span className="text-gray-400">{title}</span>
      <span className="text-xs text-gray-600">{note}</span>
    </div>
  );
}

export function App() {
  const wsUrl = useMemo(() => getParam("ws") ?? DEFAULT_TELEMETRY_WS, []);
  const gameViewUrl = useMemo(
    () => getParam("game") ?? DEFAULT_GAME_VIEW_URL,
    [],
  );
  const fallbackPort = useMemo(() => {
    const port = Number(getParam("port"));
    return Number.isInteger(port) && port > 0 ? port : DEFAULT_LAB_PORT;
  }, []);

  const [client, setClient] = useState<TelemetryClient | null>(null);
  const [attempt, setAttempt] = useState<TelemetryAttempt | null>(null);
  const [connection, setConnection] = useState({ connected: false, live: false });
  const [showReference, setShowReference] = useState(true);
  const [layout, setLayout] = useState<LayoutState>(() =>
    loadLayout(window.location.search),
  );

  useEffect(() => {
    const telemetry = new TelemetryClient(wsUrl);
    telemetry.attemptListeners.add(setAttempt);
    telemetry.stateListeners.add(setConnection);
    setClient(telemetry);
    return () => {
      telemetry.close();
      setClient(null);
    };
  }, [wsUrl]);

  useEffect(() => {
    persistLayout(layout);
  }, [layout]);

  // Esc closes the control drawer (SPEC §6.1) — placeholder drawer included.
  useEffect(() => {
    if (!layout.drawerOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setLayout((state) => ({ ...state, drawerOpen: false }));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [layout.drawerOpen]);

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

  const paneContent: Record<ViewId, ReactNode> = {
    demo: (
      <Pane key="demo" id="demo" header={<span>Demo</span>}>
        <PlaceholderPane
          title="Demo view"
          note="placeholder — in-engine demo playback lands in LD-D3 (#94, #98)"
        />
      </Pane>
    ),
    mockup: (
      <Pane key="mockup" id="mockup" header={<span>Mockup</span>}>
        <PlaceholderPane
          title="Mockup view"
          note="placeholder — offline 3D map/route browser lands in LD-C3 (#97)"
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
            <label className="ml-auto flex items-center gap-x-1 normal-case tracking-normal text-gray-400">
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
          {client && <TelemetryHud client={client} />}
        </div>
      </Pane>
    ),
    game: (
      <Pane key="game" id="game" header={<span>Live Game</span>}>
        <iframe
          src={gameViewUrl}
          title="live game view"
          className="block w-full h-full border-0"
        />
      </Pane>
    ),
  };

  return (
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
          title="KPI dock — built in LD-E1 (#100); this button persists the collapse state"
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

        {layout.drawerOpen && (
          <div
            data-drawer="control"
            className="absolute top-full inset-x-0 border-b border-slate-700 bg-slate-900/95 px-4 py-3 text-xs text-gray-500"
          >
            Control drawer — placeholder; session/bot/cvar controls land in
            LD-F3 (#105). Esc closes.
          </div>
        )}
      </header>

      <div className="grow min-h-0 flex">
        <aside
          data-dock={layout.dockCollapsed ? "rail" : "expanded"}
          className={`shrink-0 border-r border-dashed border-slate-800 text-gray-600 ${
            layout.dockCollapsed
              ? "w-7 flex items-start justify-center pt-3"
              : "w-52 p-3"
          }`}
        >
          {layout.dockCollapsed ? (
            <span className="text-[10px] [writing-mode:vertical-rl]">KPI</span>
          ) : (
            <span className="text-xs">
              KPI dock — placeholder; scoreboard lands in LD-E1 (#100).
            </span>
          )}
        </aside>

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
  );
}

export default App;
