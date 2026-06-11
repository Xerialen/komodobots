// Shell layout state for the Lab Dashboard view shell (LD-B1, #87).
//
// The four main views render left->right in a FIXED order regardless of the
// order they were toggled on (SPEC §2/§4.1): Demo -> Mockup -> Live 3D ->
// Live Game. Any subset (0–4) may be open. The open set, the KPI-dock
// collapsed flag, and the control-drawer open flag persist to localStorage;
// the open set is also reflected in the URL as `?views=demo,live3d` so
// layouts are shareable. URL params win over localStorage on load (SPEC §4.2).
//
// LD-C5 (#99): mapOpacity (0.05–1.0, default 0.3 "quite transparent") and
// wireframe (default false) are shared across both 3D views (SPEC §6.3).

export const VIEW_ORDER = ["demo", "mockup", "live3d", "game"] as const;

export type ViewId = (typeof VIEW_ORDER)[number];

export const VIEW_LABELS: Record<ViewId, string> = {
  demo: "Demo",
  mockup: "Mockup",
  live3d: "Live 3D",
  game: "Live Game",
};

export type LayoutState = {
  /** Open views, always kept in VIEW_ORDER order. */
  views: ViewId[];
  dockCollapsed: boolean;
  drawerOpen: boolean;
  /**
   * Map mesh opacity shared across both 3D views (Mockup + Live 3D).
   * Range 0.05–1.0; default 0.3 ("quite transparent") per SPEC §6.3 / #99.
   */
  mapOpacity: number;
  /**
   * Wireframe overlay toggle for both 3D views. Default false (textures on).
   * Per SPEC §6.3 / #99.
   */
  wireframe: boolean;
};

// Phase 1 default: the two views that exist today (SPEC §3.4, §3.5).
export const DEFAULT_VIEWS: ViewId[] = ["live3d", "game"];

/** Default map opacity ("quite transparent", SPEC §6.3 / #99). */
export const DEFAULT_MAP_OPACITY = 0.3;

const STORAGE_KEY = "komodobots.botlab.layout.v1";

function isViewId(value: string): value is ViewId {
  return (VIEW_ORDER as readonly string[]).includes(value);
}

/** Normalize any iterable of view ids to the fixed left->right order. */
export function orderViews(views: Iterable<ViewId>): ViewId[] {
  const open = new Set(views);
  return VIEW_ORDER.filter((view) => open.has(view));
}

/** Parse a `?views=` value ("demo,live3d"); unknown tokens are dropped. */
export function parseViewsParam(raw: string): ViewId[] {
  const tokens = raw
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(isViewId);
  return orderViews(tokens);
}

function readStoredLayout(): Partial<LayoutState> | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // storage disabled — fall back to defaults
  }
  if (!raw) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  const result: Partial<LayoutState> = {};
  if (Array.isArray(record.views)) {
    result.views = orderViews(
      record.views.filter(
        (view): view is ViewId => typeof view === "string" && isViewId(view),
      ),
    );
  }
  if (typeof record.dockCollapsed === "boolean") {
    result.dockCollapsed = record.dockCollapsed;
  }
  if (typeof record.drawerOpen === "boolean") {
    result.drawerOpen = record.drawerOpen;
  }
  if (
    typeof record.mapOpacity === "number" &&
    record.mapOpacity >= 0.05 &&
    record.mapOpacity <= 1.0
  ) {
    result.mapOpacity = record.mapOpacity;
  }
  if (typeof record.wireframe === "boolean") {
    result.wireframe = record.wireframe;
  }
  return result;
}

/**
 * Resolve the initial layout: localStorage restores the last layout, but an
 * explicit `?views=` URL param wins (including `?views=` -> zero views open).
 */
export function loadLayout(search: string): LayoutState {
  const stored = readStoredLayout();
  const state: LayoutState = {
    views: stored?.views ?? DEFAULT_VIEWS,
    dockCollapsed: stored?.dockCollapsed ?? false,
    drawerOpen: stored?.drawerOpen ?? false,
    mapOpacity: stored?.mapOpacity ?? DEFAULT_MAP_OPACITY,
    wireframe: stored?.wireframe ?? false,
  };
  const viewsParam = new URLSearchParams(search).get("views");
  if (viewsParam !== null) {
    state.views = parseViewsParam(viewsParam);
  }
  return state;
}

/**
 * Persist the layout to localStorage and mirror the open set into the URL
 * (`?views=…`, replaceState — no history spam, other params preserved).
 */
export function persistLayout(state: LayoutState): void {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        views: state.views,
        dockCollapsed: state.dockCollapsed,
        drawerOpen: state.drawerOpen,
        mapOpacity: state.mapOpacity,
        wireframe: state.wireframe,
      }),
    );
  } catch {
    // storage disabled — the URL still carries the layout
  }
  const url = new URL(window.location.href);
  url.searchParams.set("views", state.views.join(","));
  window.history.replaceState(null, "", url);
}
