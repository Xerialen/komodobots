// LD-C3 (#97): Mockup view -- offline 3D map/route browser pane.
//
// Shows the committed map meshes (OBJ) and human route data from the committed
// routes manifests (komodobots.routes.v1).  No live telemetry.  Selecting a
// map or route emits a MockupSelection context event to the parent via the
// onSelect callback so the future KPI dock (LD-E1, #100) can react.
//
// Data flow:
//   maps.json                  -> map selector (dm3 / dm2 / frobodm2 / trick)
//   data/routes/<map>.json     -> route browser (11 dm3 routes; others: empty)
//   maps/<map>.obj             -> Three.js scene via the shared mapScene module
//
// Quake <-> Three.js coordinate transform: see quakeCoords.ts (x,y,z)_quake ->
// (x,z,-y)_three.  All polyline / gap marker geometry is built from census
// coords using setFromQuake().
//
// Multiple routes may be selected simultaneously (distinct colors).  A second
// click on a selected route deselects it.  Switching maps resets selection.
//
// Context events:  The parent receives MockupSelection { map, route } whenever
// either changes.  route is null when zero routes are selected; it is the most
// recently selected route name otherwise.  (LD-E1 will subscribe to this to
// drive the KPI dock context line.)

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { setFromQuake } from "./quakeCoords.ts";
import { createMapScene, fetchMapCenter } from "./mapScene.ts";

// ---- Public types -----------------------------------------------------------

/** Context event emitted on map or route selection changes (consumed by LD-E1). */
export type MockupSelection = {
  map: string;
  route: string | null;
};

// ---- Manifest types (komodobots.routes.v1) -----------------------------------

type ManifestGap = {
  edge: [number, number, number];
  land: [number, number, number];
  required_speed: number;
  human_speed_at_edge: number;
  hard: boolean;
  type: string;
};

type ManifestTeleport = {
  enter: [number, number, number];
  exit: [number, number, number];
};

type ManifestRoute = {
  name: string;
  human: {
    duration_s: number;
    active_mean_speed: number;
    peak_speed: number;
  };
  polyline: [number, number, number][];
  gaps: ManifestGap[];
  teleports?: ManifestTeleport[];
};

type RouteManifest = {
  schema: string;
  v: number;
  map: string;
  routes: ManifestRoute[];
};

// ---- Constants ---------------------------------------------------------------

const MAPS = ["dm3", "dm2", "frobodm2", "trick"] as const;
type MapName = (typeof MAPS)[number];

// One color per route selection slot (assigned in selection order).
const ROUTE_PALETTE = [
  0x22aaff, // sky blue
  0xff7722, // orange
  0xaaff33, // lime
  0xff44cc, // pink
  0xffcc00, // amber
  0x44ffee, // cyan
  0xff3344, // red
  0x8844ff, // violet
];

function routeColor(slotIndex: number): number {
  return ROUTE_PALETTE[slotIndex % ROUTE_PALETTE.length];
}

// ---- Geometry helpers --------------------------------------------------------

/**
 * Build a Three.js Line from Quake-space points.
 * Returns null for lists with fewer than 2 points.
 */
function buildPolyline(
  points: [number, number, number][],
  color: number,
): THREE.Line | null {
  if (points.length < 2) return null;
  const positions = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    const v = setFromQuake(new THREE.Vector3(), points[i][0], points[i][1], points[i][2]);
    positions[i * 3] = v.x;
    positions[i * 3 + 1] = v.y;
    positions[i * 3 + 2] = v.z;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const mat = new THREE.LineBasicMaterial({ color });
  return new THREE.Line(geo, mat);
}

/** Build a small sphere marker at a Quake-space position. */
function buildMarker(
  qx: number,
  qy: number,
  qz: number,
  color: number,
  radius: number,
): THREE.Mesh {
  const geo = new THREE.SphereGeometry(radius, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color });
  const mesh = new THREE.Mesh(geo, mat);
  setFromQuake(mesh.position, qx, qy, qz);
  return mesh;
}

// ---- Component ---------------------------------------------------------------

export function MockupPane({
  onSelect,
}: {
  /**
   * Called whenever the active map or route selection changes.
   * Consumed by the shell to populate the future KPI dock context store (LD-E1).
   */
  onSelect?: (sel: MockupSelection) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<ReturnType<typeof createMapScene> | null>(null);
  const animIdRef = useRef<number | null>(null);
  // THREE objects for each currently-selected route, keyed by route name.
  const routeObjectsRef = useRef<Map<string, THREE.Object3D[]>>(new Map());
  // Slot index for each selected route (determines the palette color).
  const slotIndexRef = useRef<Map<string, number>>(new Map());

  const [activeMap, setActiveMap] = useState<MapName>("dm3");
  const [manifest, setManifest] = useState<RouteManifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  // Ordered selection list (insertion-order stable, drives slotIndex colors).
  const [selectedRoutes, setSelectedRoutes] = useState<string[]>([]);

  // ---- Scene lifecycle -------------------------------------------------------

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    if (animIdRef.current !== null) {
      cancelAnimationFrame(animIdRef.current);
      animIdRef.current = null;
    }
    sceneRef.current?.dispose();
    sceneRef.current = null;
    routeObjectsRef.current.clear();
    slotIndexRef.current.clear();

    let disposed = false;

    fetchMapCenter(activeMap).then((center) => {
      if (disposed || !containerRef.current) return;

      const mapScene = createMapScene(containerRef.current, activeMap, center);
      sceneRef.current = mapScene;

      function animate() {
        animIdRef.current = requestAnimationFrame(animate);
        mapScene.controls.update();
        mapScene.renderer.render(mapScene.scene, mapScene.camera);
      }
      animate();
    });

    return () => {
      disposed = true;
      if (animIdRef.current !== null) {
        cancelAnimationFrame(animIdRef.current);
        animIdRef.current = null;
      }
      sceneRef.current?.dispose();
      sceneRef.current = null;
      routeObjectsRef.current.clear();
      slotIndexRef.current.clear();
    };
  }, [activeMap]);

  // ---- Manifest fetching ----------------------------------------------------

  useEffect(() => {
    setManifest(null);
    setSelectedRoutes([]);
    setLoadingManifest(true);
    fetch(`/botlab/data/routes/${activeMap}.json`)
      .then((r) =>
        r.ok
          ? (r.json() as Promise<RouteManifest>)
          : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then(setManifest)
      .catch(() => setManifest(null))
      .finally(() => setLoadingManifest(false));
  }, [activeMap]);

  // ---- Context events --------------------------------------------------------

  useEffect(() => {
    const route =
      selectedRoutes.length > 0
        ? selectedRoutes[selectedRoutes.length - 1]
        : null;
    onSelect?.({ map: activeMap, route });
  }, [activeMap, selectedRoutes, onSelect]);

  // ---- Route geometry --------------------------------------------------------

  const removeRouteGeometry = useCallback((routeName: string) => {
    const scene = sceneRef.current?.scene;
    if (!scene) return;
    const objects = routeObjectsRef.current.get(routeName);
    if (!objects) return;
    for (const obj of objects) {
      scene.remove(obj);
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh || child instanceof THREE.Line) {
          child.geometry.dispose();
          const mats = Array.isArray(child.material)
            ? child.material
            : [child.material];
          for (const mat of mats) mat.dispose();
        }
      });
    }
    routeObjectsRef.current.delete(routeName);
    slotIndexRef.current.delete(routeName);
  }, []);

  const addRouteGeometry = useCallback(
    (route: ManifestRoute, slotIndex: number) => {
      const scene = sceneRef.current?.scene;
      if (!scene) return;
      const color = routeColor(slotIndex);
      const objects: THREE.Object3D[] = [];

      const line = buildPolyline(route.polyline, color);
      if (line) {
        scene.add(line);
        objects.push(line);
      }

      for (const gap of route.gaps) {
        const edgeMark = buildMarker(gap.edge[0], gap.edge[1], gap.edge[2], color, 16);
        const landMark = buildMarker(gap.land[0], gap.land[1], gap.land[2], 0x888888, 10);
        scene.add(edgeMark);
        scene.add(landMark);
        objects.push(edgeMark, landMark);
      }

      for (const tp of route.teleports ?? []) {
        const tpMark = buildMarker(tp.enter[0], tp.enter[1], tp.enter[2], 0x44ffee, 20);
        scene.add(tpMark);
        objects.push(tpMark);
      }

      routeObjectsRef.current.set(route.name, objects);
      slotIndexRef.current.set(route.name, slotIndex);
    },
    [],
  );

  // ---- Toggle selection ------------------------------------------------------

  const toggleRoute = useCallback(
    (routeName: string) => {
      setSelectedRoutes((prev) => {
        if (prev.includes(routeName)) {
          removeRouteGeometry(routeName);
          return prev.filter((n) => n !== routeName);
        }
        const slotIndex = prev.length;
        const route = manifest?.routes.find((r) => r.name === routeName);
        if (route) addRouteGeometry(route, slotIndex);
        return [...prev, routeName];
      });
    },
    [manifest, addRouteGeometry, removeRouteGeometry],
  );

  const switchMap = useCallback((map: MapName) => {
    setSelectedRoutes([]);
    setActiveMap(map);
  }, []);

  // ---- Render ----------------------------------------------------------------

  const routes = manifest?.routes ?? [];
  const hasRoutes = routes.length > 0;
  const lastSelected =
    selectedRoutes.length > 0 ? selectedRoutes[selectedRoutes.length - 1] : null;
  const lastSelectedRoute = lastSelected
    ? (manifest?.routes.find((r) => r.name === lastSelected) ?? null)
    : null;

  return (
    <div className="h-full flex min-h-0 overflow-hidden">
      <aside
        data-mockup-sidebar
        className="w-48 shrink-0 flex flex-col border-r border-slate-800 bg-slate-950/60 overflow-y-auto text-xs"
      >
        <section className="px-2 py-1 border-b border-slate-800">
          <span className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Map
          </span>
          <div className="flex flex-col gap-y-0.5">
            {MAPS.map((map) => (
              <button
                key={map}
                type="button"
                onClick={() => switchMap(map)}
                data-map={map}
                aria-pressed={map === activeMap}
                className={`text-left px-1.5 py-0.5 rounded ${
                  map === activeMap
                    ? "bg-sky-900/60 text-sky-200 border border-sky-600"
                    : "text-gray-400 hover:text-gray-200 hover:bg-slate-800/60"
                }`}
              >
                {map}
              </button>
            ))}
          </div>
        </section>

        <section className="px-2 py-1 flex-1">
          <span className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Routes
          </span>

          {loadingManifest && (
            <span className="text-gray-600 animate-pulse">loading...</span>
          )}

          {!loadingManifest && !hasRoutes && (
            <span className="text-gray-600 italic">no censused routes yet</span>
          )}

          {!loadingManifest && hasRoutes && (
            <div className="flex flex-col gap-y-0.5">
              {routes.map((route, idx) => {
                const selected = selectedRoutes.includes(route.name);
                const slotIdx = selected
                  ? (slotIndexRef.current.get(route.name) ?? idx)
                  : idx;
                const colorHex = `#${routeColor(slotIdx).toString(16).padStart(6, "0")}`;
                return (
                  <button
                    key={route.name}
                    type="button"
                    onClick={() => toggleRoute(route.name)}
                    data-route={route.name}
                    aria-pressed={selected}
                    title={`${route.name} - peak ${route.human.peak_speed.toFixed(0)} qu/s - ${route.gaps.length} gap(s)`}
                    className={`text-left px-1.5 py-0.5 rounded leading-tight ${
                      selected
                        ? "bg-slate-700/60 text-white"
                        : "text-gray-400 hover:text-gray-200 hover:bg-slate-800/40"
                    }`}
                  >
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-1 align-middle"
                      style={{
                        background: selected ? colorHex : "transparent",
                        border: `1px solid ${colorHex}`,
                      }}
                    />
                    {route.name}
                    <span className="block pl-3 text-[10px] text-gray-600 font-mono">
                      {route.human.active_mean_speed.toFixed(0)} mu{" "}
                      {route.human.peak_speed.toFixed(0)} pk
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {lastSelectedRoute !== null && (
          <section
            data-route-detail={lastSelectedRoute.name}
            className="px-2 py-1 border-t border-slate-800 text-[10px] text-gray-500 font-mono"
          >
            <div className="font-bold text-gray-400 text-xs mb-0.5 truncate">
              {lastSelectedRoute.name}
            </div>
            <div>dur {lastSelectedRoute.human.duration_s.toFixed(2)} s</div>
            <div>mean {lastSelectedRoute.human.active_mean_speed.toFixed(0)} qu/s</div>
            <div>peak {lastSelectedRoute.human.peak_speed.toFixed(0)} qu/s</div>
            {lastSelectedRoute.gaps.map((g, i) => (
              <div key={i} className="mt-0.5 border-t border-slate-800 pt-0.5">
                gap {i + 1}: {g.type}{g.hard ? " [hard]" : ""}
                <br />
                req {g.required_speed.toFixed(0)} hu {g.human_speed_at_edge.toFixed(0)}
              </div>
            ))}
          </section>
        )}
      </aside>

      <div
        ref={containerRef}
        data-mockup-canvas
        className="flex-1 min-w-0 min-h-0"
      />
    </div>
  );
}