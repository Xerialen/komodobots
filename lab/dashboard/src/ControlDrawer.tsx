// LD-F3 (#105): Control drawer — slide-down overlay from the top bar.
//
// Provides:
//  - Session block: start/stop, map selector, lock-state badge (harness /
//    dashboard / free).  Stale-lock takeover requires an explicit confirm.
//  - Bot roster: live rows from control_event broadcasts and lock state.
//    Add-bot / remove-bot buttons.  Per-bot route assignment dropdowns.
//  - Assignment display shows what the SERVER reports (ASSIGN rows from
//    telemetry), never optimistic state.
//  - Cvar console with command history (↑/↓) and inline rejection rendering.
//    Supports @<slot> prefix for per-slot cvars.
//
// Disabled states (every mutating control):
//  - bridge disconnected
//  - harness lock fresh
//  - no session running (except session_start)
//
// Non-modal: panes keep streaming underneath.  Esc closes (wired in App.tsx).
//
// Security: all validation and enforcement lives in control_bridge.py (#96).
// The UI is a courtesy layer only.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ControlClient, ControlEvent, LockState } from "./controlClient.ts";
import type { TelemetryAssign, TelemetryClient } from "./telemetryClient.ts";

// ---- Types ------------------------------------------------------------------

type BotSlot = {
  slot: number;
  name: string;
  assignedRoute: string | null;   // what the server reports (never optimistic)
  pendingRoute: string | null;    // set while awaiting read-back from server
};

type DrawerSession = {
  running: boolean;
  port: number | null;
  map: string | null;
};

type ConsoleEntry = {
  id: number;
  kind: "sent" | "ok" | "error";
  text: string;
};

// ---- Constants --------------------------------------------------------------

const MAPS = ["dm3", "dm2", "frobodm2", "trick"] as const;
type MapName = (typeof MAPS)[number];

// Per-route metadata: spawn_origin derived from the first polyline point.
// Loaded once per map from /data/routes/{map}.json (the committed manifest).
type RouteMetadata = {
  /** spawn_origin as a space-separated "x y z" string (cvar format). */
  spawn_origin: string;
};

// Cache loaded manifest metadata so we don't re-fetch on every assignment.
const _routeMetadataCache = new Map<string, Map<string, RouteMetadata>>();

/** Load route metadata (spawn_origin) for all routes in a map manifest.
 *  Returns a Map<routeName, RouteMetadata>. Cached after the first fetch.
 *  Rejects on network error; callers must treat failure as a hard assignment
 *  error — do NOT silently proceed without spawn_origin (P1 fix, Codex #145).
 *
 *  Path: /botlab/data/routes/<map>.json — the same deployed path that
 *  MockupPane uses.  The vite config has base="/botlab/" so assets are
 *  served under that prefix; using "/" without the prefix returns 404 in
 *  the deployed app. */
async function loadRouteMetadata(map: MapName): Promise<Map<string, RouteMetadata>> {
  const cached = _routeMetadataCache.get(map);
  if (cached) return cached;
  const resp = await fetch(`/botlab/data/routes/${map}.json`);
  if (!resp.ok) throw new Error(`route manifest fetch failed: ${resp.status}`);
  const json = await resp.json() as {
    routes: Array<{ name: string; polyline: number[][] }>;
  };
  const result = new Map<string, RouteMetadata>();
  for (const route of json.routes ?? []) {
    const pt = route.polyline?.[0];
    if (pt && pt.length >= 3) {
      // Round to 3 decimal places; KTX parses the cvar string on the fly so
      // we can pass any precision — 3 dp is well within its float tolerance.
      result.set(route.name, {
        spawn_origin: `${pt[0].toFixed(3)} ${pt[1].toFixed(3)} ${pt[2].toFixed(3)}`,
      });
    }
  }
  _routeMetadataCache.set(map, result);
  return result;
}

// Per-map route name lists.  Derived from the manifests — keep in sync with
// /data/routes/*.json.  These are used to populate route dropdowns; the full
// assignment metadata (spawn_origin) is fetched lazily from the manifest.
const ROUTES_BY_MAP: Record<MapName, string[]> = {
  dm3: [
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
  ],
  dm2: [],
  frobodm2: [],
  trick: [],
};

let _consoleCounter = 0;

// ---- Helpers ----------------------------------------------------------------

function lockBadge(state: LockState["state"] | null) {
  switch (state) {
    case "free":
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-900/60 text-green-300 border border-green-700">
          free
        </span>
      );
    case "fresh":
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-900/60 text-amber-300 border border-amber-700">
          locked
        </span>
      );
    case "stale":
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-red-900/60 text-red-300 border border-red-700">
          stale lock
        </span>
      );
    default:
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-gray-500 border border-slate-700">
          unknown
        </span>
      );
  }
}

// ---- Component --------------------------------------------------------------

export type ControlDrawerProps = {
  client: ControlClient;
  /** TelemetryClient — used to subscribe to ASSIGN rows for server-truth
   *  assignment display (LD-F3 P1 fix: roster reflects what the server says). */
  telemetryClient: TelemetryClient | null;
  wsConnected: boolean;
  onClose: () => void;
};

export function ControlDrawer({ client, telemetryClient, wsConnected, onClose }: ControlDrawerProps) {
  // Lock + session state
  const [lockState, setLockState] = useState<LockState | null>(null);
  const [lockOwner, setLockOwner] = useState<string | null>(null);
  const [session, setSession] = useState<DrawerSession>({ running: false, port: null, map: null });

  // UI state
  const [selectedMap, setSelectedMap] = useState<MapName>("dm3");
  const [bots, setBots] = useState<BotSlot[]>([]);
  const [busy, setBusy] = useState(false);
  const [staleTakeoverPending, setStaleTakeoverPending] = useState(false);

  // Console state
  const [consoleLine, setConsoleLine] = useState("");
  const [consoleLog, setConsoleLog] = useState<ConsoleEntry[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const sentHistoryRef = useRef<string[]>([]);
  const consoleEndRef = useRef<HTMLDivElement>(null);
  const consoleInputRef = useRef<HTMLInputElement>(null);

  // Derived: are mutating controls disabled?
  const bridgeOk = wsConnected && client.connected;
  const isHarnessLocked = lockState?.state === "fresh" && lockOwner === "harness";
  const isDashboardSession = session.running;
  const sessionMap = session.map ?? selectedMap;

  // Refresh lock status on open and whenever a control event arrives.
  const refreshLock = useCallback(async () => {
    if (!bridgeOk) return;
    const resp = await client.lockStatus();
    if (!resp.ok) return;
    const state = (resp as { state?: string }).state as string | undefined;
    const lock = (resp as { lock?: Record<string, unknown> }).lock;
    if (state === "free") {
      setLockState({ state: "free", lock: null });
      setLockOwner(null);
      setSession({ running: false, port: null, map: null });
    } else if (state === "fresh" || state === "stale") {
      const owner = (lock?.owner as string) ?? null;
      setLockState({ state, lock: lock ?? {} });
      setLockOwner(owner);
      if (owner === "dashboard") {
        const port = typeof lock?.port === "number" ? lock.port : null;
        const map = typeof lock?.map === "string" ? lock.map : null;
        setSession({ running: true, port, map });
        if (map && MAPS.includes(map as MapName)) {
          setSelectedMap(map as MapName);
        }
      } else {
        setSession({ running: false, port: null, map: null });
      }
    }
  }, [bridgeOk, client]);

  // On mount / reconnect: fetch initial lock state.
  useEffect(() => {
    if (bridgeOk) {
      refreshLock();
    }
  }, [bridgeOk, refreshLock]);

  // Subscribe to control events.
  useEffect(() => {
    function onEvent(event: ControlEvent) {
      switch (event.event) {
        case "session_start": {
          const port = typeof event.port === "number" ? event.port : null;
          const map = typeof event.map === "string" ? event.map : null;
          setSession({ running: true, port, map });
          setLockOwner("dashboard");
          setLockState({ state: "fresh", lock: { owner: "dashboard", port, map } });
          if (map && MAPS.includes(map as MapName)) {
            setSelectedMap(map as MapName);
          }
          break;
        }
        case "session_stop": {
          setSession({ running: false, port: null, map: null });
          setLockOwner(null);
          setLockState({ state: "free", lock: null });
          setBots([]);
          break;
        }
        case "addbot": {
          // We don't know the real edict number from the bridge event alone —
          // the real ed is printed in the FBMOVEPROBE_ASSIGN row once KTX
          // processes the bot.  Add a provisional placeholder whose slot=-1
          // marks it as unresolved; the ASSIGN upsert below will replace it
          // (keyed by ed) when the server truth arrives.
          setBots((prev) => [
            ...prev,
            { slot: -1, name: "…", assignedRoute: null, pendingRoute: null },
          ]);
          break;
        }
        case "removebot": {
          const slot = event.slot;
          if (slot === "all") {
            setBots([]);
          } else if (typeof slot === "number") {
            setBots((prev) => prev.filter((b) => b.slot !== slot));
          } else {
            // removebot with no slot = remove last
            setBots((prev) => (prev.length > 0 ? prev.slice(0, -1) : prev));
          }
          break;
        }
      }
    }
    client.eventListeners.add(onEvent);
    return () => {
      client.eventListeners.delete(onEvent);
    };
  }, [client]);

  // LD-F3 (#105) P1 fix: subscribe to ASSIGN rows from the telemetry sidecar
  // for server-truth assignment display.  assignedRoute is updated ONLY from
  // FBMOVEPROBE_ASSIGN rows (not from bridge set_cvar confirmations) so the
  // roster reflects what KTX actually resolved, not what we sent.
  //
  // Upsert semantics: if the ed is not yet present in the roster (e.g. page
  // reload, existing session, or ASSIGN arrived before the addbot event settled)
  // we create a new row.  The provisional slot=-1 placeholder left by addbot is
  // adopted: replace the first unresolved slot=-1 placeholder if one exists and
  // no row with this ed has been seen yet.  This handles the normal flow
  // (addbot → placeholder → ASSIGN → real row) without duplicating.
  //
  // Route name round-trip: the server's replay_file is "dm3_sng_to_rl.cmds";
  // strip the leading "<map>_" and trailing ".cmds" to recover the route id.
  // Using lastIndexOf("_") is wrong for underscored names like "sng_to_rl" —
  // instead strip the fixed "<map>_" prefix.
  useEffect(() => {
    if (!telemetryClient) return;
    function onAssign(assign: TelemetryAssign) {
      // Strip "<map>_" prefix (any known map) and ".cmds" suffix to recover route id.
      // e.g. "dm3_sng_to_rl.cmds" → "sng_to_rl"; "dm2_foo.cmds" → "foo"
      // null replay_file means the bot has no route assigned yet — still upsert
      // so the roster row appears with "unassigned" state.
      let routeId: string | null = null;
      if (assign.replay_file) {
        let id = assign.replay_file.replace(/\.cmds$/, "");
        for (const map of MAPS) {
          const prefix = `${map}_`;
          if (id.startsWith(prefix)) {
            id = id.slice(prefix.length);
            break;
          }
        }
        routeId = id;
      }
      // ed IS the per-slot cvar suffix (_s<N>) in KTX (NUM_FOR_EDICT(self)).
      const ed = assign.ed;
      setBots((prev) => {
        // Find an existing row with this ed.
        const existing = prev.findIndex((b) => b.slot === ed);
        if (existing !== -1) {
          // Update in place.
          return prev.map((b) =>
            b.slot === ed
              ? { ...b, name: assign.name, assignedRoute: routeId, pendingRoute: null }
              : b,
          );
        }
        // No row yet — adopt the first provisional placeholder (slot=-1), or
        // append a new row if no placeholder exists (page reload / existing session).
        const placeholderIdx = prev.findIndex((b) => b.slot === -1);
        if (placeholderIdx !== -1) {
          return prev.map((b, i) =>
            i === placeholderIdx
              ? { slot: ed, name: assign.name, assignedRoute: routeId, pendingRoute: null }
              : b,
          );
        }
        // No placeholder — append (e.g. session was already running when we connected).
        return [
          ...prev,
          { slot: ed, name: assign.name, assignedRoute: routeId, pendingRoute: null },
        ];
      });
    }
    telemetryClient.assignListeners.add(onAssign);
    return () => {
      telemetryClient.assignListeners.delete(onAssign);
    };
  }, [telemetryClient]);

  // Auto-scroll console.
  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [consoleLog]);

  // ---- Action helpers -------------------------------------------------------

  function addConsole(kind: ConsoleEntry["kind"], text: string) {
    setConsoleLog((prev) => [...prev, { id: ++_consoleCounter, kind, text }]);
  }

  async function handleSessionStart() {
    if (busy) return;
    const force = lockState?.state === "stale" && staleTakeoverPending;
    if (lockState?.state === "stale" && !staleTakeoverPending) {
      setStaleTakeoverPending(true);
      return;
    }
    setStaleTakeoverPending(false);
    setBusy(true);
    const resp = await client.sessionStart(selectedMap, force);
    setBusy(false);
    if (!resp.ok) {
      addConsole("error", `session_start failed: ${resp.detail}`);
    }
    await refreshLock();
  }

  async function handleSessionStop() {
    if (busy) return;
    setBusy(true);
    const resp = await client.sessionStop();
    setBusy(false);
    if (!resp.ok) {
      addConsole("error", `session_stop failed: ${resp.detail}`);
    }
    await refreshLock();
  }

  async function handleAddBot() {
    if (busy) return;
    setBusy(true);
    const resp = await client.addBot(1);
    setBusy(false);
    if (!resp.ok) {
      addConsole("error", `addbot failed: ${resp.detail}`);
    }
  }

  async function handleRemoveBot(slot?: number) {
    if (busy) return;
    setBusy(true);
    const resp = await client.removeBot(slot);
    setBusy(false);
    if (!resp.ok) {
      addConsole("error", `removebot failed: ${resp.detail}`);
    }
  }

  async function handleAssignRoute(bot: BotSlot, route: string) {
    if (!route) return;
    // Guard: provisional rows (slot=-1) have not been resolved to a real ed yet.
    // The ASSIGN upsert will set the real slot; the user should wait for it.
    if (bot.slot === -1) {
      addConsole("error", "bot slot not yet resolved — waiting for server ASSIGN row");
      return;
    }
    // Per-slot assignment: set all four per-slot cvars as one atomic group.
    // This matches the #95/#105 contract: replay_file + mode + fixed_goal +
    // spawn_origin must all be written together so KTX resolves the full
    // assignment in one ASSIGN row.
    //
    // assignedRoute is updated only when the server broadcasts an ASSIGN row
    // (server-truth display); pendingRoute shows "pending…" until then.
    setBots((prev) =>
      prev.map((b) => (b.slot === bot.slot ? { ...b, pendingRoute: route } : b)),
    );
    const mapRouteFile = `${sessionMap}_${route}.cmds`;
    const slot = bot.slot;

    // Load spawn_origin from the route manifest for this map.
    // Missing metadata is a hard failure: the #95/#105 assignment contract
    // requires all four per-slot cvars.  Silently omitting spawn_origin would
    // leave the bot at the global spawn, breaking the two-bots-two-routes path.
    let spawnOrigin: string;
    try {
      const meta = await loadRouteMetadata(sessionMap as MapName);
      const routeMeta = meta.get(route);
      if (!routeMeta) {
        addConsole("error", `no spawn_origin in manifest for route "${route}" on ${sessionMap} — assignment aborted`);
        setBots((prev) =>
          prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
        );
        return;
      }
      spawnOrigin = routeMeta.spawn_origin;
    } catch (err) {
      // Manifest fetch failed — abort rather than send a partial assignment.
      addConsole("error", `route manifest unavailable for ${sessionMap} — assignment aborted (${String(err)})`);
      setBots((prev) =>
        prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
      );
      return;
    }

    const ops: Promise<import("./controlClient.ts").ControlResponse>[] = [
      client.setCvar("k_fb_moveprobe_replay_file", mapRouteFile, slot),
      client.setCvar("k_fb_moveprobe_mode", "10", slot),
      // fixed_goal=0 means "no fixed goal" — replay mode does not need a marker.
      client.setCvar("k_fb_moveprobe_fixed_goal", "0", slot),
      // spawn_origin is required (hard failure above if missing) so no guard needed.
      client.setCvar("k_fb_moveprobe_spawn_origin", spawnOrigin, slot),
    ];

    const results = await Promise.all(ops);
    const allOk = results.every((r) => r.ok);
    if (!allOk) {
      const errors = results
        .filter((r) => !r.ok)
        .map((r) => r.detail)
        .join("; ");
      addConsole("error", `assign route failed: ${errors}`);
      // Clear pending state on failure.
      setBots((prev) =>
        prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
      );
    }
    // On success: assignedRoute is updated when the telemetry sidecar emits an
    // ASSIGN row — the server-truth subscriber above clears pendingRoute.
  }

  async function handleConsoleSend() {
    const line = consoleLine.trim();
    if (!line) return;
    addConsole("sent", `> ${line}`);
    sentHistoryRef.current = [line, ...sentHistoryRef.current].slice(0, 100);
    setConsoleLine("");
    setHistoryIdx(-1);
    const resp = await client.console(line);
    if (resp.ok) {
      addConsole("ok", resp.detail);
    } else {
      addConsole("error", resp.detail);
    }
  }

  function handleConsoleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleConsoleSend();
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(historyIdx + 1, sentHistoryRef.current.length - 1);
      setHistoryIdx(next);
      setConsoleLine(sentHistoryRef.current[next] ?? "");
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.max(historyIdx - 1, -1);
      setHistoryIdx(next);
      setConsoleLine(next === -1 ? "" : (sentHistoryRef.current[next] ?? ""));
      return;
    }
  }

  // ---- Disable rules -------------------------------------------------------

  const canStart = bridgeOk && !isDashboardSession && !isHarnessLocked && !busy;
  const canStop = bridgeOk && isDashboardSession && !busy;
  const canMutate = bridgeOk && isDashboardSession && !isHarnessLocked && !busy;
  const canConsole = canMutate;

  const mapRoutes = ROUTES_BY_MAP[sessionMap as MapName] ?? ROUTES_BY_MAP.dm3;

  // ---- Render ---------------------------------------------------------------

  return (
    <div
      data-drawer="control"
      className="absolute top-full inset-x-0 z-10 border-b border-slate-700 bg-slate-950/97 shadow-lg"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-4 py-3 grid grid-cols-[1fr_1fr_1fr] gap-x-6 gap-y-3 text-xs">
        {/* ---- SESSION BLOCK ---- */}
        <div className="flex flex-col gap-y-2">
          <div className="flex items-center gap-x-2 text-gray-400 uppercase tracking-wide font-semibold">
            <span>Session</span>
            {lockBadge(lockState?.state ?? null)}
            {lockOwner && lockState?.state !== "free" && (
              <span className="text-gray-500 normal-case">{lockOwner}</span>
            )}
          </div>

          {/* harness lock warning */}
          {isHarnessLocked && (
            <div className="text-amber-400 text-[10px] bg-amber-900/20 border border-amber-800 rounded px-2 py-1">
              experiment harness owns the lab — controls disabled
            </div>
          )}

          {/* stale lock takeover */}
          {lockState?.state === "stale" && (
            <div className="text-red-400 text-[10px] bg-red-900/20 border border-red-800 rounded px-2 py-1">
              stale lock detected
              {!staleTakeoverPending ? (
                <button
                  type="button"
                  className="ml-2 underline text-red-300 hover:text-red-100"
                  onClick={() => setStaleTakeoverPending(true)}
                >
                  force takeover
                </button>
              ) : (
                <button
                  type="button"
                  className="ml-2 font-bold text-red-200 underline hover:text-white"
                  onClick={handleSessionStart}
                >
                  confirm takeover
                </button>
              )}
            </div>
          )}

          {/* Map selector */}
          <label className="flex items-center gap-x-2 text-gray-400">
            <span className="shrink-0">Map</span>
            <select
              value={isDashboardSession ? (session.map ?? selectedMap) : selectedMap}
              disabled={isDashboardSession}
              onChange={(e) => setSelectedMap(e.target.value as MapName)}
              className="flex-1 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 text-gray-200 text-xs disabled:opacity-50"
            >
              {MAPS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          {/* Start/stop buttons */}
          <div className="flex gap-x-2">
            {!isDashboardSession ? (
              <button
                type="button"
                disabled={!canStart}
                onClick={handleSessionStart}
                className="flex-1 px-2 py-1 rounded bg-green-800 text-green-100 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy ? "starting…" : "start session"}
              </button>
            ) : (
              <button
                type="button"
                disabled={!canStop}
                onClick={handleSessionStop}
                className="flex-1 px-2 py-1 rounded bg-red-900 text-red-100 hover:bg-red-800 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy ? "stopping…" : "stop session"}
              </button>
            )}
          </div>

          {/* Session status */}
          {isDashboardSession && session.port && (
            <div className="text-gray-500 font-mono">
              port {session.port} · {session.map}
            </div>
          )}
        </div>

        {/* ---- BOT ROSTER ---- */}
        <div className="flex flex-col gap-y-2">
          <div className="flex items-center gap-x-2 text-gray-400 uppercase tracking-wide font-semibold">
            <span>Bots</span>
            {isDashboardSession && (
              <div className="ml-auto flex gap-x-1">
                <button
                  type="button"
                  disabled={!canMutate}
                  onClick={handleAddBot}
                  className="px-1.5 py-0.5 rounded bg-sky-900 text-sky-200 hover:bg-sky-800 border border-sky-700 disabled:opacity-40 disabled:cursor-not-allowed normal-case"
                >
                  + add
                </button>
                <button
                  type="button"
                  disabled={!canMutate || bots.length === 0}
                  onClick={() => handleRemoveBot()}
                  className="px-1.5 py-0.5 rounded bg-slate-800 text-gray-300 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed normal-case"
                >
                  - remove
                </button>
              </div>
            )}
          </div>

          {!isDashboardSession && (
            <div className="text-gray-600 italic">start a session to manage bots</div>
          )}

          {isDashboardSession && bots.length === 0 && (
            <div className="text-gray-600 italic">no bots — click + add</div>
          )}

          {isDashboardSession && bots.length > 0 && (
            <div className="flex flex-col gap-y-1">
              {bots.map((bot, idx) => (
                <BotRow
                  key={bot.slot === -1 ? `provisional-${idx}` : bot.slot}
                  bot={bot}
                  routes={mapRoutes}
                  canMutate={canMutate && bot.slot !== -1}
                  onAssign={(route) => handleAssignRoute(bot, route)}
                  onRemove={() => handleRemoveBot(bot.slot === -1 ? undefined : bot.slot)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ---- CVAR CONSOLE ---- */}
        <div className="flex flex-col gap-y-2">
          <div className="text-gray-400 uppercase tracking-wide font-semibold">Cvar console</div>
          {!bridgeOk && (
            <div className="text-red-400 text-[10px]">bridge disconnected</div>
          )}
          {bridgeOk && !isDashboardSession && (
            <div className="text-gray-600 text-[10px] italic">start a session to send cvars</div>
          )}

          {/* Log */}
          <div className="flex-1 overflow-y-auto max-h-24 font-mono text-[10px] bg-black/30 border border-slate-800 rounded px-1.5 py-1 flex flex-col gap-y-0.5">
            {consoleLog.map((entry) => (
              <div
                key={entry.id}
                className={
                  entry.kind === "error"
                    ? "text-red-400"
                    : entry.kind === "sent"
                      ? "text-gray-300"
                      : "text-green-400"
                }
              >
                {entry.text}
              </div>
            ))}
            <div ref={consoleEndRef} />
          </div>

          {/* Input */}
          <div className="flex gap-x-1">
            <input
              ref={consoleInputRef}
              type="text"
              value={consoleLine}
              disabled={!canConsole}
              onChange={(e) => setConsoleLine(e.target.value)}
              onKeyDown={handleConsoleKeyDown}
              placeholder={
                !bridgeOk
                  ? "bridge disconnected"
                  : !isDashboardSession
                    ? "no session"
                    : "cvar val  or  @2 k_fb_… val"
              }
              className="flex-1 bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 font-mono text-[11px] text-gray-200 disabled:opacity-40 disabled:cursor-not-allowed placeholder:text-gray-600"
            />
            <button
              type="button"
              disabled={!canConsole || !consoleLine.trim()}
              onClick={handleConsoleSend}
              className="px-2 py-0.5 rounded bg-slate-700 text-gray-300 hover:bg-slate-600 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              send
            </button>
          </div>
          <div className="text-gray-600 text-[9px]">
            ↑/↓ history · @2 k_fb_… val → per-slot
          </div>
        </div>
      </div>

      {/* Close button */}
      <button
        type="button"
        aria-label="close control drawer"
        onClick={onClose}
        className="absolute top-2 right-3 text-gray-500 hover:text-gray-300 text-sm"
      >
        ✕
      </button>
    </div>
  );
}

// ---- BotRow sub-component ---------------------------------------------------

type BotRowProps = {
  bot: BotSlot;
  routes: string[];
  canMutate: boolean;
  onAssign: (route: string) => void;
  onRemove: () => void;
};

function BotRow({ bot, routes, canMutate, onAssign, onRemove }: BotRowProps) {
  const displayRoute = bot.pendingRoute
    ? `${bot.pendingRoute} (pending…)`
    : (bot.assignedRoute ?? "unassigned");

  // slot=-1 is a provisional placeholder (addbot fired, ASSIGN not yet received).
  const slotLabel = bot.slot === -1 ? "??" : `s${bot.slot}`;

  return (
    <div className="flex items-center gap-x-1.5 text-[10px]">
      <span className="shrink-0 font-mono text-gray-400 w-12">
        {slotLabel} {bot.name.slice(0, 6)}
      </span>
      <select
        value={bot.assignedRoute ?? ""}
        disabled={!canMutate || !!bot.pendingRoute}
        onChange={(e) => {
          if (e.target.value) onAssign(e.target.value);
        }}
        title={displayRoute}
        className="flex-1 min-w-0 bg-slate-800 border border-slate-600 rounded px-1 py-0.5 text-gray-200 text-[10px] disabled:opacity-50"
      >
        <option value="">— {bot.pendingRoute ? "pending…" : "route"}</option>
        {routes.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!canMutate}
        onClick={onRemove}
        className="shrink-0 px-1 py-0.5 rounded text-gray-500 hover:text-red-300 hover:bg-red-900/30 disabled:opacity-40 disabled:cursor-not-allowed"
        title="remove this bot"
      >
        ✕
      </button>
    </div>
  );
}
