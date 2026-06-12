// LD-F3 (#105): Control side panels.
//
// Provides:
//  - Session block: start/stop, map selector, lock-state badge (harness /
//    dashboard / free).  Stale-lock takeover requires an explicit confirm.
//  - Game controls: allowlisted KTX game mode, DMM, powerups, ready/break.
//  - Bot roster: live rows from control_event broadcasts and lock state.
//    Add-bot / remove-bot buttons.  Per-bot route assignment and behavior
//    buttons; trickjumps are represented as normal routes.
//  - Assignment display shows what the SERVER reports (ASSIGN rows from
//    telemetry), never optimistic state.
//  - Separate Cvar console panel with command history and response rendering.
//    Supports @<slot> prefix for per-slot cvars.
//
// Disabled states (every mutating control):
//  - bridge disconnected
//  - harness lock fresh
//  - no session running (except session_start)
//
// Non-modal: panes keep streaming underneath.  Esc closes side panels (App.tsx).
//
// Security: all validation and enforcement lives in control_bridge.py (#96).
// The UI is a courtesy layer only.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ControlClient, ControlEvent, ControlResponse, LockState } from "./controlClient.ts";
import type { TelemetryAssign, TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

// ---- Types ------------------------------------------------------------------

type BotSlot = {
  slot: number;
  name: string;
  assignedRoute: string | null;   // what the server reports (never optimistic)
  pendingRoute: string | null;    // set while awaiting read-back from server
  draftName?: string;
  draftTopColor?: string;
  draftBottomColor?: string;
  draftTeam?: string;
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

const MAPS = ["dm3", "dm2", "frobodm2", "trick", "ztricks"] as const;
type MapName = (typeof MAPS)[number];

type RouteControl = {
  mode?: number;
  fixed_goal?: number;
  spawn_origin?: string;
  replay_file?: string;
  cvars?: Record<string, string | number>;
};

// Per-route metadata: spawn_origin derived from the first polyline point unless
// the route declares a control override.
// Loaded once per map from /data/routes/{map}.json (the committed manifest).
type RouteMetadata = {
  /** spawn_origin as a space-separated "x y z" string (cvar format). */
  spawn_origin: string;
  control?: RouteControl;
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
    routes: Array<{ name: string; polyline: number[][]; control?: RouteControl }>;
  };
  const result = new Map<string, RouteMetadata>();
  for (const route of json.routes ?? []) {
    const pt = route.polyline?.[0];
    const controlSpawn = typeof route.control?.spawn_origin === "string" ? route.control.spawn_origin : null;
    if (controlSpawn || (pt && pt.length >= 3)) {
      // Round to 3 decimal places; KTX parses the cvar string on the fly so
      // we can pass any precision — 3 dp is well within its float tolerance.
      result.set(route.name, {
        spawn_origin: controlSpawn ?? `${pt[0].toFixed(3)} ${pt[1].toFixed(3)} ${pt[2].toFixed(3)}`,
        control: route.control,
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
  ztricks: ["distance_standstill"],
};

const PRACTICE_IDLE_MODE = "24";
const DEFAULT_REPLAY_MODE = "10";
const REPLAY_LOOP_CVAR = "k_fb_moveprobe_replay_loop";
const BOT_COLORS = Array.from({ length: 14 }, (_, i) => String(i));
const FRAME_SUPPRESS_MS = 2_500;
const SPAWN_REARM_WAIT_MS = 400;

let _consoleCounter = 0;

function controlDelay(ms: number, detail: string): Promise<ControlResponse> {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve({ re: null, ok: true, detail }), ms);
  });
}

function pruneUnassignedPlaceholders(rows: BotSlot[]): BotSlot[] {
  const hasRealRow = rows.some((bot) => bot.slot !== -1);
  if (!hasRealRow) return rows;
  return rows.filter((bot) =>
    bot.slot !== -1 || bot.assignedRoute !== null || bot.pendingRoute !== null,
  );
}

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
  consoleOpen: boolean;
  onConsoleToggle: () => void;
  onClose: () => void;
};

export function ControlDrawer({
  client,
  telemetryClient,
  wsConnected,
  consoleOpen,
  onConsoleToggle,
  onClose,
}: ControlDrawerProps) {
  // Lock + session state
  const [lockState, setLockState] = useState<LockState | null>(null);
  const [lockOwner, setLockOwner] = useState<string | null>(null);
  const [session, setSession] = useState<DrawerSession>({ running: false, port: null, map: null });

  // UI state
  const [selectedMap, setSelectedMap] = useState<MapName>("dm3");
  const [bots, setBots] = useState<BotSlot[]>([]);
  const [busy, setBusy] = useState(false);
  const [staleTakeoverPending, setStaleTakeoverPending] = useState(false);
  const [panelMessage, setPanelMessage] = useState<string | null>(null);
  const [weaponLocked, setWeaponLocked] = useState(false);
  const [prewarActive, setPrewarActive] = useState(false);
  const suppressedFrameSlotsRef = useRef<Map<number, number>>(new Map());

  const suppressLiveFrameSlots = useCallback((rows: BotSlot[]) => {
    const until = Date.now() + FRAME_SUPPRESS_MS;
    rows.forEach((bot) => {
      if (bot.slot !== -1) {
        suppressedFrameSlotsRef.current.set(bot.slot, until);
      }
    });
  }, []);

  // Derived: are mutating controls disabled?
  const bridgeOk = wsConnected && client.connected;
  const isHarnessLocked = lockState?.state === "fresh" && lockOwner === "harness";
  const isDashboardSession = session.running;
  const sessionMap = session.map ?? selectedMap;

  // Refresh lock status on open and whenever a control event arrives.
  const refreshLock = useCallback(async () => {
    if (!bridgeOk) return;
    const resp = await client.lockStatus();
    if (!resp.ok) {
      setPanelMessage(`lock_status failed: ${resp.detail}`);
      return;
    }
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
          suppressedFrameSlotsRef.current.clear();
          setBots([]);
          setPrewarActive(false);
          setWeaponLocked(false);
          break;
        }
        case "session_stop": {
          setSession({ running: false, port: null, map: null });
          setLockOwner(null);
          setLockState({ state: "free", lock: null });
          suppressedFrameSlotsRef.current.clear();
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
            setBots((prev) => {
              suppressLiveFrameSlots(prev);
              return [];
            });
          } else {
            // KTX removebot is not reliably slot-addressable in this build.
            // Clear the UI roster and let live telemetry frames repopulate the
            // actual survivors instead of trusting the requested slot.
            setBots([]);
          }
          break;
        }
        case "game_command": {
          const action = typeof event.action === "string" ? event.action : "";
          if (action === "trick_pause") {
            setBots((prev) => {
              suppressLiveFrameSlots(prev);
              return [];
            });
          } else if (action === "bot_respawn") {
            setBots((prev) => {
              suppressLiveFrameSlots(prev);
              return [{ slot: -1, name: "...", assignedRoute: null, pendingRoute: null }];
            });
          } else if (action === "bot_weapon_lock") {
            setWeaponLocked(true);
          } else if (action === "bot_weapon_unlock") {
            setWeaponLocked(false);
          } else if (action === "prewar") {
            setPrewarActive(true);
          } else if (action === "start") {
            setPrewarActive(false);
          }
          break;
        }
      }
    }
    client.eventListeners.add(onEvent);
    return () => {
      client.eventListeners.delete(onEvent);
    };
  }, [client, suppressLiveFrameSlots]);

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
          return pruneUnassignedPlaceholders(
            prev.map((b) =>
              b.slot === ed
                ? {
                    ...b,
                    name: assign.name,
                    assignedRoute: routeId ?? b.pendingRoute ?? b.assignedRoute,
                    pendingRoute: null,
                  }
                : b,
            ),
          );
        }
        // No row yet — adopt the first provisional placeholder (slot=-1), or
        // append a new row if no placeholder exists (page reload / existing session).
        const placeholderIdx = prev.findIndex((b) => b.slot === -1);
        if (placeholderIdx !== -1) {
          return prev.map((b, i) =>
            i === placeholderIdx
              ? {
                  slot: ed,
                  name: assign.name,
                  assignedRoute: routeId ?? b.pendingRoute ?? b.assignedRoute,
                  pendingRoute: null,
                }
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

  // ztricks/global presets do not always emit an ASSIGN row because they use
  // global moveprobe cvars, but every live command frame carries the real ed.
  // Use frames as a roster identity fallback so row actions become reachable.
  useEffect(() => {
    if (!telemetryClient) return;
    function onFrame(frame: TelemetryFrame) {
      setBots((prev) => {
        const suppressedUntil = suppressedFrameSlotsRef.current.get(frame.ed);
        if (suppressedUntil !== undefined) {
          if (Date.now() < suppressedUntil) {
            return prev;
          }
          suppressedFrameSlotsRef.current.delete(frame.ed);
        }
        const existing = prev.findIndex((b) => b.slot === frame.ed);
        if (existing !== -1) {
          if (prev[existing].name === frame.name) {
            return pruneUnassignedPlaceholders(prev);
          }
          return pruneUnassignedPlaceholders(
            prev.map((b) =>
              b.slot === frame.ed
                ? { ...b, name: frame.name }
                : b,
            ),
          );
        }
        const placeholderIdx = prev.findIndex((b) => b.slot === -1);
        if (placeholderIdx !== -1) {
          return prev.map((b, i) =>
            i === placeholderIdx
              ? {
                  slot: frame.ed,
                  name: frame.name,
                  assignedRoute: b.pendingRoute ?? b.assignedRoute,
                  pendingRoute: null,
                }
              : b,
          );
        }
        return [
          ...prev,
          { slot: frame.ed, name: frame.name, assignedRoute: null, pendingRoute: null },
        ];
      });
    }
    telemetryClient.frameListeners.add(onFrame);
    return () => {
      telemetryClient.frameListeners.delete(onFrame);
    };
  }, [telemetryClient]);

  // ---- Action helpers -------------------------------------------------------

  function addPanelMessage(text: string) {
    setPanelMessage(text);
  }

  async function handleSessionStart() {
    if (busy) return;
    const force = lockState?.state === "stale" && staleTakeoverPending;
    if (lockState?.state === "stale" && !staleTakeoverPending) {
      setStaleTakeoverPending(true);
      return;
    }
    setStaleTakeoverPending(false);
    setPanelMessage(`starting ${selectedMap}...`);
    setBusy(true);
    const resp = await client.sessionStart(selectedMap, force);
    setBusy(false);
    if (!resp.ok) {
      addPanelMessage(`session_start failed: ${resp.detail}`);
    } else {
      addPanelMessage(resp.detail);
    }
    await refreshLock();
  }

  async function handleSessionStop() {
    if (busy) return;
    setBusy(true);
    const resp = await client.sessionStop();
    setBusy(false);
    if (!resp.ok) {
      addPanelMessage(`session_stop failed: ${resp.detail}`);
    }
    await refreshLock();
  }

  async function handleAddBot() {
    if (busy) return;
    setBusy(true);
    const resp = await client.addBot(1);
    setBusy(false);
    if (!resp.ok) {
      addPanelMessage(`addbot failed: ${resp.detail}`);
    }
  }

  async function handleRemoveBot(slot?: number | "all") {
    if (busy) return;
    setBusy(true);
    const resp = await client.removeBot(slot);
    setBusy(false);
    if (!resp.ok) {
      addPanelMessage(`removebot failed: ${resp.detail}`);
    }
  }

  async function configureBotRoute(
    bot: BotSlot,
    route: string,
    mode: "idle" | "try" | "loop",
  ) {
    if (!route) return;
    // Guard: provisional rows (slot=-1) have not been resolved to a real ed yet.
    // The ASSIGN upsert will set the real slot; the user should wait for it.
    if (bot.slot === -1) {
      addPanelMessage("bot slot not yet resolved - waiting for server ASSIGN row");
      return;
    }
    // Per-slot assignment: set the route description as one atomic group.
    // Selecting a route keeps the bot idle (mode 24); the per-bot try/loop
    // buttons switch that slot into the route's controller mode.
    //
    // assignedRoute is updated only when the server broadcasts an ASSIGN row
    // (server-truth display); pendingRoute shows "pending…" until then.
    setBots((prev) =>
      prev.map((b) => (b.slot === bot.slot ? { ...b, pendingRoute: route } : b)),
    );
    const slot = bot.slot;

    // Load spawn_origin and optional control overrides from the route manifest.
    // Missing metadata is a hard failure: the #95/#105 assignment contract
    // requires all four per-slot cvars.  Silently omitting spawn_origin would
    // leave the bot at the global spawn, breaking the two-bots-two-routes path.
    let spawnOrigin: string;
    let control: RouteControl | undefined;
    try {
      const meta = await loadRouteMetadata(sessionMap as MapName);
      const routeMeta = meta.get(route);
      if (!routeMeta) {
        addPanelMessage(`no spawn_origin in manifest for route "${route}" on ${sessionMap} - assignment aborted`);
        setBots((prev) =>
          prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
        );
        return;
      }
      spawnOrigin = routeMeta.spawn_origin;
      control = routeMeta.control;
    } catch (err) {
      // Manifest fetch failed — abort rather than send a partial assignment.
      addPanelMessage(`route manifest unavailable for ${sessionMap} - assignment aborted (${String(err)})`);
      setBots((prev) =>
        prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
      );
      return;
    }

    const routeMode = String(control?.mode ?? DEFAULT_REPLAY_MODE);
    const replayFile = typeof control?.replay_file === "string"
      ? control.replay_file
      : `${sessionMap}_${route}.cmds`;
    const fixedGoal = String(control?.fixed_goal ?? 0);
    const cvars = Object.entries(control?.cvars ?? {});

    const ops: Array<() => Promise<ControlResponse>> = [
      // First force a hold so a repeated try re-arms one-shot controllers such
      // as ztricks mode 23 before route-specific state is rewritten.
      () => client.setCvar("k_fb_moveprobe_mode", PRACTICE_IDLE_MODE, slot),
      () => client.setCvar("k_fb_moveprobe_replay_file", replayFile, slot),
      // fixed_goal=0 means "no fixed goal" for replay routes.
      () => client.setCvar("k_fb_moveprobe_fixed_goal", fixedGoal, slot),
      // Clear first so repeated tries of the same route still produce a
      // spawn-origin assignment edge for KTX's one-shot snap latch.
      () => client.setCvar("k_fb_moveprobe_spawn_origin", "", slot),
      () => controlDelay(SPAWN_REARM_WAIT_MS, "spawn-origin rearm wait"),
      // spawn_origin is required (hard failure above if missing) so no guard needed.
      () => client.setCvar("k_fb_moveprobe_spawn_origin", spawnOrigin, slot),
      () => client.setCvar(REPLAY_LOOP_CVAR, mode === "loop" ? "1" : "0"),
      ...cvars.map(([name, value]) => () => client.setCvar(name, String(value))),
      // Mode must be last: KTX reads mode immediately in BotSetCommand(), so
      // flipping it before fixed_goal/spawn/controller cvars can hold the bot.
      () => client.setCvar("k_fb_moveprobe_mode", mode === "idle" ? PRACTICE_IDLE_MODE : routeMode, slot),
    ];

    const results: ControlResponse[] = [];
    for (const op of ops) {
      const result = await op();
      results.push(result);
      if (!result.ok) break;
    }
    const allOk = results.every((r) => r.ok);
    if (!allOk) {
      const errors = results
        .filter((r) => !r.ok)
        .map((r) => r.detail)
        .join("; ");
      addPanelMessage(`assign route failed: ${errors}`);
      // Clear pending state on failure.
      setBots((prev) =>
        prev.map((b) => (b.slot === slot ? { ...b, pendingRoute: null } : b)),
      );
      return;
    }
    if (mode === "idle") {
      addPanelMessage(`route ${route} selected - bot is standing still until try`);
    } else {
      addPanelMessage(`${mode === "loop" ? "looping" : "trying"} ${route}`);
    }
    if (replayFile === "") {
      setBots((prev) =>
        prev.map((b) =>
          b.slot === slot ? { ...b, assignedRoute: route, pendingRoute: null } : b,
        ),
      );
    }
    // On success: assignedRoute is updated when the telemetry sidecar emits an
    // ASSIGN row — the server-truth subscriber above clears pendingRoute.
  }

  async function handleAssignRoute(bot: BotSlot, route: string) {
    await configureBotRoute(bot, route, "idle");
  }

  async function handleBotTry(bot: BotSlot, loop = false) {
    const route = bot.pendingRoute ?? bot.assignedRoute;
    if (!route) {
      addPanelMessage("select a route for this bot first");
      return;
    }
    await configureBotRoute(bot, route, loop ? "loop" : "try");
  }

  async function handleBotStandStill(bot: BotSlot) {
    if (bot.slot === -1) {
      addPanelMessage("bot slot not yet resolved - waiting for server ASSIGN row");
      return;
    }
    const results = await Promise.all([
      client.setCvar("k_fb_moveprobe_mode", PRACTICE_IDLE_MODE, bot.slot),
      client.setCvar(REPLAY_LOOP_CVAR, "0"),
    ]);
    const failed = results.find((r) => !r.ok);
    if (failed) {
      addPanelMessage(`stand still failed: ${failed.detail}`);
    }
  }

  async function handleGameCommand(action: string, value?: string) {
    if (!canMutate || busy) return;
    setBusy(true);
    const resp = await client.gameCommand(action, value);
    setBusy(false);
    setPanelMessage(resp.ok ? resp.detail : `game command failed: ${resp.detail}`);
  }

  async function handleBotRespawn(bot: BotSlot) {
    if (bot.slot === -1) {
      addPanelMessage("bot slot not yet resolved - waiting for server ASSIGN row");
      return;
    }
    const resolvedBots = bots.filter((b) => b.slot !== -1);
    if (resolvedBots.length > 1) {
      addPanelMessage("respawn is precise only with one live bot in this KTX build");
      return;
    }
    await handleGameCommand("bot_respawn", String(bot.slot));
  }

  async function handleWeaponLockToggle() {
    await handleGameCommand(weaponLocked ? "bot_weapon_unlock" : "bot_weapon_lock");
  }

  function handleBotProfileChange(bot: BotSlot, patch: Partial<BotSlot>) {
    setBots((prev) =>
      prev.map((b) => (b.slot === bot.slot ? { ...b, ...patch } : b)),
    );
  }

  async function handleApplyBotProfile(bot: BotSlot) {
    if (bot.slot === -1) {
      addPanelMessage("bot slot not yet resolved - waiting for server ASSIGN row");
      return;
    }
    const nextName = (bot.draftName ?? bot.name).trim();
    const topColor = (bot.draftTopColor ?? "13").trim();
    const bottomColor = (bot.draftBottomColor ?? topColor).trim();
    const team = (bot.draftTeam ?? "").trim();
    const safeName = nextName.replace(/[^A-Za-z0-9_.-]/g, "").slice(0, 15);
    const safeTeam = team.replace(/[^A-Za-z0-9_.-]/g, "").slice(0, 15);

    if (!safeName) {
      addPanelMessage("bot name needs at least one safe character");
      return;
    }

    // Current KTX exposes Frogbot names as spawn-time cvars. Live color/team
    // mutation needs a server command hook; until that exists we keep the draft
    // visible and write the name cvar for the next bot spawn only.
    const resp = await client.console(`set k_fb_name_${Math.max(0, bot.slot - 1)} ${safeName}`);
    setBots((prev) =>
      prev.map((b) =>
        b.slot === bot.slot
          ? {
              ...b,
              draftName: safeName,
              draftTopColor: topColor,
              draftBottomColor: bottomColor,
              draftTeam: safeTeam,
            }
          : b,
      ),
    );
    addPanelMessage(
      resp.ok
        ? "profile saved for next spawn; live color/team changes need a KTX bot-userinfo hook"
        : `profile save failed: ${resp.detail}`,
    );
  }

  // ---- Disable rules -------------------------------------------------------

  const canStart = bridgeOk && !isDashboardSession && !isHarnessLocked && !busy;
  const canStop = bridgeOk && isDashboardSession && !busy;
  const canMutate = bridgeOk && isDashboardSession && !isHarnessLocked && !busy;

  const mapRoutes = ROUTES_BY_MAP[sessionMap as MapName] ?? ROUTES_BY_MAP.dm3;
  const gameModes = ["4on4", "2on2", "1on1", "ffa"] as const;
  const dmmModes = ["1", "2", "3", "4"] as const;

  // ---- Render ---------------------------------------------------------------

  return (
    <div
      data-drawer="control"
      className="relative shrink-0 w-[320px] min-w-[280px] max-w-[34vw] border-l border-slate-800 bg-slate-950"
    >
      <div className="h-full overflow-y-auto px-4 py-3 flex flex-col gap-y-4 text-xs">
        {/* ---- SESSION BLOCK ---- */}
        <div className="flex flex-col gap-y-2">
          <div className="flex items-center gap-x-2 pr-5 text-gray-400 uppercase tracking-wide font-semibold">
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
          {panelMessage && (
            <div className="font-mono text-[10px] text-gray-400 bg-black/30 border border-slate-800 rounded px-2 py-1 break-words">
              {panelMessage}
            </div>
          )}
        </div>

        {/* ---- GAME CONTROLS ---- */}
        <div className="flex flex-col gap-y-2 border-t border-slate-800 pt-3">
          <div className="flex items-center gap-x-2 text-gray-400 uppercase tracking-wide font-semibold">
            <span>Game</span>
            <span className="ml-auto text-[10px] text-gray-600 normal-case font-normal">
              {canMutate ? "ready" : "disabled"}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-1">
            {gameModes.map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={!canMutate}
                onClick={() => handleGameCommand("gamemode", mode)}
                className="px-1.5 py-1 rounded bg-slate-800 text-gray-200 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {mode.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-4 gap-1">
            {dmmModes.map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={!canMutate}
                onClick={() => handleGameCommand("deathmatch", mode)}
                className="px-1.5 py-1 rounded bg-slate-800 text-gray-200 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                DMM {mode}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-1">
            <button
              type="button"
              disabled={!canMutate}
              onClick={() => handleGameCommand("powerups", "on")}
              className="px-2 py-1 rounded bg-slate-800 text-gray-200 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              powerups on
            </button>
            <button
              type="button"
              disabled={!canMutate}
              onClick={() => handleGameCommand("powerups", "off")}
              className="px-2 py-1 rounded bg-slate-800 text-gray-200 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              powerups off
            </button>
          </div>

          <div className="grid grid-cols-2 gap-1">
            <button
              type="button"
              disabled={!canMutate}
              onClick={() => handleGameCommand("start")}
              className="px-2 py-1 rounded bg-green-900 text-green-100 hover:bg-green-800 border border-green-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              start game
            </button>
            <button
              type="button"
              disabled={!canMutate}
              onClick={() => handleGameCommand("stop")}
              className="px-2 py-1 rounded bg-red-950 text-red-100 hover:bg-red-900 border border-red-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              stop game
            </button>
          </div>

          <div className="grid grid-cols-2 gap-1">
            <button
              type="button"
              disabled={!canMutate}
              aria-pressed={prewarActive}
              onClick={() => handleGameCommand("prewar")}
              className={`px-2 py-1 rounded border disabled:opacity-40 disabled:cursor-not-allowed ${
                prewarActive
                  ? "bg-amber-900 text-amber-100 border-amber-700"
                  : "bg-slate-800 text-gray-200 hover:bg-slate-700 border-slate-600"
              }`}
            >
              prewar
            </button>
            <button
              type="button"
              disabled={!canMutate}
              aria-pressed={weaponLocked}
              onClick={handleWeaponLockToggle}
              className={`px-2 py-1 rounded border disabled:opacity-40 disabled:cursor-not-allowed ${
                weaponLocked
                  ? "bg-amber-900 text-amber-100 border-amber-700"
                  : "bg-slate-800 text-gray-200 hover:bg-slate-700 border-slate-600"
              }`}
            >
              {weaponLocked ? "axe only" : "weapons free"}
            </button>
          </div>

          <button
            type="button"
            aria-pressed={consoleOpen}
            onClick={onConsoleToggle}
            className={`px-2 py-1 rounded border text-gray-300 ${
              consoleOpen
                ? "bg-slate-700 border-slate-500"
                : "bg-slate-900 border-slate-700 hover:border-slate-500"
            }`}
          >
            cvar console
          </button>
        </div>

        {/* ---- BOT ROSTER ---- */}
        <div className="flex flex-col gap-y-2 border-t border-slate-800 pt-3">
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
                <button
                  type="button"
                  disabled={!canMutate || bots.length === 0}
                  onClick={() => handleRemoveBot("all")}
                  className="px-1.5 py-0.5 rounded bg-red-950 text-red-200 hover:bg-red-900 border border-red-800 disabled:opacity-40 disabled:cursor-not-allowed normal-case"
                >
                  clear
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
                  onTry={() => handleBotTry(bot)}
                  onLoop={() => handleBotTry(bot, true)}
                  onStandStill={() => handleBotStandStill(bot)}
                  onRespawn={() => handleBotRespawn(bot)}
                  onRemove={() => handleRemoveBot(bot.slot === -1 ? undefined : bot.slot)}
                  onProfileChange={(patch) => handleBotProfileChange(bot, patch)}
                  onApplyProfile={() => handleApplyBotProfile(bot)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Close button */}
      <button
        type="button"
        aria-label="close control panel"
        onClick={onClose}
        className="absolute top-2 right-3 text-gray-500 hover:text-gray-300 text-sm"
      >
        ✕
      </button>
    </div>
  );
}

export type CvarConsolePanelProps = {
  client: ControlClient;
  wsConnected: boolean;
  onClose: () => void;
};

export function CvarConsolePanel({ client, wsConnected, onClose }: CvarConsolePanelProps) {
  const [consoleLine, setConsoleLine] = useState("");
  const [consoleLog, setConsoleLog] = useState<ConsoleEntry[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const sentHistoryRef = useRef<string[]>([]);
  const consoleEndRef = useRef<HTMLDivElement>(null);
  const bridgeOk = wsConnected && client.connected;
  const canConsole = bridgeOk;

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [consoleLog]);

  function addConsole(kind: ConsoleEntry["kind"], text: string) {
    setConsoleLog((prev) => [...prev, { id: ++_consoleCounter, kind, text }]);
  }

  async function handleConsoleSend() {
    const line = consoleLine.trim();
    if (!line) return;
    addConsole("sent", `> ${line}`);
    sentHistoryRef.current = [line, ...sentHistoryRef.current].slice(0, 100);
    setConsoleLine("");
    setHistoryIdx(-1);
    const resp = await client.console(line);
    addConsole(resp.ok ? "ok" : "error", resp.detail);
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
    }
  }

  return (
    <div
      data-drawer="console"
      className="relative shrink-0 w-[320px] min-w-[280px] max-w-[34vw] border-l border-slate-800 bg-slate-950"
    >
      <div className="h-full px-4 py-3 flex flex-col gap-y-3 text-xs">
        <div className="flex items-center gap-x-2 pr-5 text-gray-400 uppercase tracking-wide font-semibold">
          <span>Cvar console</span>
          {!bridgeOk && <span className="ml-auto text-[10px] text-red-400 normal-case">disconnected</span>}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto font-mono text-[10px] bg-black/30 border border-slate-800 rounded px-2 py-2 flex flex-col gap-y-0.5">
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

        <div className="flex gap-x-1">
          <input
            type="text"
            value={consoleLine}
            disabled={!canConsole}
            onChange={(e) => setConsoleLine(e.target.value)}
            onKeyDown={handleConsoleKeyDown}
            placeholder={!bridgeOk ? "bridge disconnected" : "cvar val  or  @2 k_fb_... val"}
            className="flex-1 min-w-0 bg-slate-800 border border-slate-600 rounded px-1.5 py-1 font-mono text-[11px] text-gray-200 disabled:opacity-40 disabled:cursor-not-allowed placeholder:text-gray-600"
          />
          <button
            type="button"
            disabled={!canConsole || !consoleLine.trim()}
            onClick={handleConsoleSend}
            className="px-2 py-1 rounded bg-slate-700 text-gray-300 hover:bg-slate-600 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            send
          </button>
        </div>
      </div>

      <button
        type="button"
        aria-label="close cvar console"
        onClick={onClose}
        className="absolute top-2 right-3 text-gray-500 hover:text-gray-300 text-sm"
      >
        x
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
  onTry: () => void;
  onLoop: () => void;
  onStandStill: () => void;
  onRespawn: () => void;
  onRemove: () => void;
  onProfileChange: (patch: Partial<BotSlot>) => void;
  onApplyProfile: () => void;
};

function BotRow({
  bot,
  routes,
  canMutate,
  onAssign,
  onTry,
  onLoop,
  onStandStill,
  onRespawn,
  onRemove,
  onProfileChange,
  onApplyProfile,
}: BotRowProps) {
  const displayRoute = bot.pendingRoute
    ? `${bot.pendingRoute} (pending…)`
    : (bot.assignedRoute ?? "unassigned");

  // slot=-1 is a provisional placeholder (addbot fired, ASSIGN not yet received).
  const slotLabel = bot.slot === -1 ? "??" : `s${bot.slot}`;
  const profileName = bot.draftName ?? bot.name;
  const topColor = bot.draftTopColor ?? "13";
  const bottomColor = bot.draftBottomColor ?? topColor;
  const team = bot.draftTeam ?? "";

  return (
    <div className="flex flex-col gap-y-2 rounded border border-slate-800 bg-black/20 px-2 py-2 text-[10px]">
      <div className="flex items-center gap-x-2">
        <span className="shrink-0 font-mono text-gray-400 w-8">{slotLabel}</span>
        <input
          type="text"
          value={profileName}
          disabled={!canMutate}
          onChange={(e) => onProfileChange({ draftName: e.target.value })}
          className="min-w-0 flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-gray-200 disabled:opacity-50"
          title="bot name"
        />
        <button
          type="button"
          disabled={!canMutate}
          onClick={onApplyProfile}
          className="shrink-0 px-1.5 py-0.5 rounded bg-slate-800 text-gray-300 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
          title="apply bot profile"
        >
          save
        </button>
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

      <div className="grid grid-cols-[1fr_56px_56px] gap-1">
        <input
          type="text"
          value={team}
          disabled={!canMutate}
          onChange={(e) => onProfileChange({ draftTeam: e.target.value })}
          placeholder="team"
          className="min-w-0 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-gray-200 disabled:opacity-50 placeholder:text-gray-600"
          title="team"
        />
        <select
          value={topColor}
          disabled={!canMutate}
          onChange={(e) => onProfileChange({ draftTopColor: e.target.value })}
          className="bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-gray-200 disabled:opacity-50"
          title="top color"
        >
          {BOT_COLORS.map((color) => (
            <option key={color} value={color}>
              top {color}
            </option>
          ))}
        </select>
        <select
          value={bottomColor}
          disabled={!canMutate}
          onChange={(e) => onProfileChange({ draftBottomColor: e.target.value })}
          className="bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-gray-200 disabled:opacity-50"
          title="bottom color"
        >
          {BOT_COLORS.map((color) => (
            <option key={color} value={color}>
              bot {color}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-x-1">
        <select
          value={bot.assignedRoute ?? ""}
          disabled={!canMutate || !!bot.pendingRoute || routes.length === 0}
          onChange={(e) => {
            if (e.target.value) onAssign(e.target.value);
          }}
          title={displayRoute}
          className="flex-1 min-w-0 bg-slate-800 border border-slate-600 rounded px-1 py-0.5 text-gray-200 disabled:opacity-50"
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
          disabled={!canMutate || !(bot.pendingRoute ?? bot.assignedRoute)}
          onClick={onTry}
          className="shrink-0 px-1.5 py-0.5 rounded bg-sky-950 text-sky-100 hover:bg-sky-900 border border-sky-800 disabled:opacity-40 disabled:cursor-not-allowed"
          title="try selected route"
        >
          try
        </button>
        <button
          type="button"
          disabled={!canMutate || !(bot.pendingRoute ?? bot.assignedRoute)}
          onClick={onLoop}
          className="shrink-0 px-1.5 py-0.5 rounded bg-slate-800 text-gray-200 hover:bg-slate-700 border border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
          title="loop selected route"
        >
          loop
        </button>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <button
          type="button"
          disabled={!canMutate}
          onClick={onStandStill}
          className="px-1.5 py-0.5 rounded bg-slate-900 text-gray-300 hover:bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
          title="hold this bot still"
        >
          stand still
        </button>
        <button
          type="button"
          disabled={!canMutate}
          onClick={onRespawn}
          className="px-1.5 py-0.5 rounded bg-slate-900 text-gray-300 hover:bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
          title="respawn this bot"
        >
          respawn
        </button>
      </div>
    </div>
  );
}
