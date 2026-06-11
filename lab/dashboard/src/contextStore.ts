// LD-E1 (#100): Shell-level KPI context store.
//
// Tracks which map/route the user is currently browsing or has most recently
// interacted with, and which source produced that context.  The precedence
// rule is:
//
//   live attempt (source="live")   — highest priority while a live run is active
//   most recent user selection     — either "mockup" or "demo" (last touched)
//   none                           — initial state, nothing selected
//
// Producers that update the store:
//   1. Telemetry client (LD-B3): live attempt start/end → source live/none
//   2. MockupPane (LD-C3, #97): MockupSelection {map, route} → source "mockup"
//   3. Demo context (stub, LD-D3 #98 will fill): {map, route} → source "demo"
//
// The context is exported as a plain object; the React wiring lives in App.tsx
// (useReducer / useState) so this file stays free of React imports and can be
// exercised from Python unit tests that validate the schema contract.

// ---- Types -------------------------------------------------------------------

export type ContextSource = "live" | "mockup" | "demo" | "none";

/** The KPI dock context: which map/route is currently "active". */
export type KpiContext = {
  /** Currently active map name (e.g. "dm3"). Always non-empty. */
  map: string;
  /** Currently active route name, or null if no route selected. */
  route: string | null;
  /**
   * Which producer set this context last:
   *   "live"   — telemetry reported an active attempt
   *   "mockup" — user is browsing in the Mockup pane
   *   "demo"   — user clicked a demo record (LD-D3 will set this)
   *   "none"   — no producer has set context yet
   */
  source: ContextSource;
};

/** An update from the telemetry live-state producer. */
export type LiveContextUpdate = {
  kind: "live";
  map: string;         // attempt map name
  live: boolean;       // true = attempt active; false = ended/disconnected
};

/** An update from the Mockup pane (MockupSelection). */
export type MockupContextUpdate = {
  kind: "mockup";
  map: string;
  route: string | null;
};

/** An update from the Demo pane (LD-D3 will produce these). */
export type DemoContextUpdate = {
  kind: "demo";
  map: string;
  route: string | null;
};

export type ContextUpdate =
  | LiveContextUpdate
  | MockupContextUpdate
  | DemoContextUpdate;

// ---- Initial state -----------------------------------------------------------

export const INITIAL_KPI_CONTEXT: KpiContext = {
  map: "dm3",
  route: null,
  source: "none",
};

// ---- Reducer -----------------------------------------------------------------

/**
 * Pure reducer: apply a ContextUpdate to the current KpiContext and return
 * the new state.  Never mutates the input.
 *
 * Precedence:
 *   - A live update with live=true always wins and sets source="live".
 *   - A live update with live=false (attempt ended) falls back to the last
 *     user selection if one exists; otherwise source becomes "none" with the
 *     same map retained.
 *   - Mockup and demo updates always update the stored user selection AND
 *     update the active context UNLESS source is currently "live".  If live
 *     is active the selection is stored in lastUserSelection (below) and will
 *     surface when live ends.
 *
 * Because this is a pure function, the "last user selection" memory must be
 * threaded through callers as a second piece of state.  See App.tsx for the
 * useReducer wrapper that maintains both KpiContext and lastUserContext.
 */
export function applyContextUpdate(
  current: KpiContext,
  lastUser: KpiContext,
  update: ContextUpdate,
): { context: KpiContext; lastUser: KpiContext } {
  switch (update.kind) {
    case "live": {
      if (update.live) {
        // Live attempt started: override active context with live source.
        return {
          context: { map: update.map, route: null, source: "live" },
          lastUser,
        };
      } else {
        // Live attempt ended: surface the last user selection (if any) or
        // fall back to "none" keeping the last known map.
        const fallback: KpiContext =
          lastUser.source !== "none"
            ? lastUser
            : { map: current.map, route: null, source: "none" };
        return { context: fallback, lastUser };
      }
    }

    case "mockup": {
      const next: KpiContext = {
        map: update.map,
        route: update.route,
        source: "mockup",
      };
      // Always update lastUser so that "return to last selection" works.
      if (current.source === "live") {
        // Live is active — save as pending selection, don't override active.
        return { context: current, lastUser: next };
      }
      return { context: next, lastUser: next };
    }

    case "demo": {
      const next: KpiContext = {
        map: update.map,
        route: update.route,
        source: "demo",
      };
      if (current.source === "live") {
        return { context: current, lastUser: next };
      }
      return { context: next, lastUser: next };
    }
  }
}
