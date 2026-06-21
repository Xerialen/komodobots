// LD-C3 (#97): Mockup view -- offline 3D map/route browser pane.
//
// Shows the committed map meshes (GLB) and human route data from the committed
// routes manifests (komodobots.routes.v1).  No live telemetry.  Selecting a
// map or route emits a MockupSelection context event to the parent via the
// onSelect callback so the future KPI dock (LD-E1, #100) can react.
//
// Data flow:
//   maps.json                  -> map selector (dm3 / dm2 / frobodm2 / trick / ztricks)
//   data/routes/<map>.json     -> route browser (11 dm3 routes; others: empty)
//   data/map_entities/<map>.json -> static item/spawn/teleporter context
//   maps/<map>.glb             -> Three.js scene via the shared mapScene module
//                                 (LD-C4 textured GLB assets, LD-C5 #99)
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
//
// LD-C5 (#99): accepts mapOpacity and wireframe props forwarded from the shell
// layout state; applies them to the mapScene via setOpacity / setWireframe.

import { useCallback, useEffect, useRef, useState } from "react";
import { logWarn } from "./logger.ts";
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
  required_speed: number | null;
  human_speed_at_edge: number | null;
  hard: boolean;
  type: string;
};

type ManifestTeleport = {
  // Field names match komodobots.routes.v1 manifest schema ("from"/"to").
  from: [number, number, number];
  to: [number, number, number];
};

type ManifestRoute = {
  name: string;
  human: {
    duration_s: number | null;
    active_mean_speed: number | null;
    peak_speed: number | null;
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

// ---- Map entity types (komodobots.map_entities.v1) -------------------------

type MapEntityBounds = {
  min: [number, number, number];
  max: [number, number, number];
};

type MapEntity = {
  type: string;
  class: string;
  kind?: string;
  name?: string;
  loc?: string;
  x: number;
  y: number;
  z: number;
  target?: string;
  targetName?: string;
  bounds?: MapEntityBounds;
};

type MapEntitiesManifest = {
  map: string;
  version: number;
  entities: MapEntity[];
};

// ---- Constants ---------------------------------------------------------------

const MAPS = ["dm3", "dm2", "frobodm2", "trick", "ztricks"] as const;
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

function metricText(value: number | null | undefined, decimals = 0): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(decimals)
    : "n/a";
}

function entityColor(entity: MapEntity): number {
  if (entity.type === "teleportDst") return 0x66e7ff;
  if (entity.type === "teleportSrc") return 0x14b8a6;
  if (entity.type === "spawn") return 0xe5e7eb;
  if (entity.type === "door") return 0x94a3b8;
  if (entity.type === "button") return 0xfacc15;
  if (entity.kind === "rl") return 0xef4444;
  if (entity.kind === "lg") return 0xf59e0b;
  if (entity.kind === "ra") return 0xdc2626;
  if (entity.kind === "ya") return 0xeab308;
  if (entity.kind === "quad" || entity.kind === "pent" || entity.kind === "ring") return 0xa855f7;
  if (entity.type === "item") return 0x22c55e;
  return 0x94a3b8;
}

function entityDisplayName(entity: MapEntity): string {
  return entity.name ?? entity.loc ?? entity.kind ?? entity.class;
}

function dist3(a: [number, number, number], b: [number, number, number]): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const dz = b[2] - a[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function nearestEntity(
  point: [number, number, number] | undefined,
  entities: MapEntity[],
): { entity: MapEntity; distance: number } | null {
  if (!point || entities.length === 0) return null;
  let best: { entity: MapEntity; distance: number } | null = null;
  for (const entity of entities) {
    const distance = dist3(point, [entity.x, entity.y, entity.z]);
    if (best === null || distance < best.distance) {
      best = { entity, distance };
    }
  }
  return best;
}

function entityTypeCounts(entities: MapEntity[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const entity of entities) {
    counts[entity.type] = (counts[entity.type] ?? 0) + 1;
  }
  return counts;
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

function buildBoundsBox(bounds: MapEntityBounds, color: number): THREE.Mesh {
  const min = bounds.min;
  const max = bounds.max;
  const center: [number, number, number] = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const sizeX = Math.max(1, Math.abs(max[0] - min[0]));
  const sizeY = Math.max(1, Math.abs(max[2] - min[2]));
  const sizeZ = Math.max(1, Math.abs(max[1] - min[1]));
  const geo = new THREE.BoxGeometry(sizeX, sizeY, sizeZ);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.18,
    wireframe: true,
  });
  const mesh = new THREE.Mesh(geo, mat);
  setFromQuake(mesh.position, center[0], center[1], center[2]);
  return mesh;
}

function buildEntityObject(entity: MapEntity): THREE.Object3D {
  const color = entityColor(entity);
  const group = new THREE.Group();
  group.userData = {
    type: "mapEntity",
    entityType: entity.type,
    entityName: entityDisplayName(entity),
  };

  if (entity.bounds) {
    group.add(buildBoundsBox(entity.bounds, color));
  }

  const radius =
    entity.type === "teleportDst"
      ? 20
      : entity.type === "teleportSrc"
        ? 10
        : entity.type === "spawn"
          ? 14
          : 8;
  const geo =
    entity.type === "teleportDst"
      ? new THREE.OctahedronGeometry(radius)
      : new THREE.SphereGeometry(radius, 8, 8);
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: entity.type === "item" ? 0.75 : 0.9,
  });
  const marker = new THREE.Mesh(geo, mat);
  setFromQuake(marker.position, entity.x, entity.y, entity.z);
  group.add(marker);
  return group;
}

// ---- Component ---------------------------------------------------------------

export function MockupPane({
  onSelect,
  mapOpacity,
  wireframe,
}: {
  /**
   * Called whenever the active map or route selection changes.
   * Consumed by the shell to populate the future KPI dock context store (LD-E1).
   */
  onSelect?: (sel: MockupSelection) => void;
  /**
   * Map mesh opacity (0.05–1.0, default 0.3).  Forwarded from the shell
   * layout state; persisted there (SPEC §6.3 / #99).
   */
  mapOpacity: number;
  /**
   * Wireframe overlay toggle (default false).  Forwarded from the shell
   * layout state (SPEC §6.3 / #99).
   */
  wireframe: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<ReturnType<typeof createMapScene> | null>(null);
  const animIdRef = useRef<number | null>(null);
  // THREE objects for each currently-selected route, keyed by route name.
  const routeObjectsRef = useRef<Map<string, THREE.Object3D[]>>(new Map());
  const entityObjectsRef = useRef<THREE.Object3D[]>([]);
  // Slot index for each selected route (determines the palette color).
  const slotIndexRef = useRef<Map<string, number>>(new Map());

  const [activeMap, setActiveMap] = useState<MapName>("dm3");
  const [manifest, setManifest] = useState<RouteManifest | null>(null);
  const [entityManifest, setEntityManifest] = useState<MapEntitiesManifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [loadingEntities, setLoadingEntities] = useState(false);
  const [sceneGeneration, setSceneGeneration] = useState(0);
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
    entityObjectsRef.current = [];
    slotIndexRef.current.clear();

    let disposed = false;

    fetchMapCenter(activeMap).then((center) => {
      if (disposed || !containerRef.current) return;

      const mapScene = createMapScene(containerRef.current, activeMap, center);
      sceneRef.current = mapScene;
      setSceneGeneration((n) => n + 1);
      // Apply current opacity/wireframe to the new scene immediately.
      mapScene.setOpacity(mapOpacity);
      mapScene.setWireframe(wireframe);

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
      entityObjectsRef.current = [];
      slotIndexRef.current.clear();
    };
  }, [activeMap]);

  // ---- Opacity / wireframe sync (LD-C5, #99) --------------------------------
  // Applied separately from the scene lifecycle effect so map switches and
  // opacity changes are independent; the scene-lifecycle effect applies them
  // once on scene creation, these keep them in sync on subsequent changes.

  useEffect(() => {
    sceneRef.current?.setOpacity(mapOpacity);
  }, [mapOpacity]);

  useEffect(() => {
    sceneRef.current?.setWireframe(wireframe);
  }, [wireframe]);

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
      .catch((err: unknown) => {
        logWarn("route manifest fetch failed in mockup pane", { map: activeMap, error: err });
        setManifest(null);
      })
      .finally(() => setLoadingManifest(false));
  }, [activeMap]);

  useEffect(() => {
    setEntityManifest(null);
    setLoadingEntities(true);
    fetch(`/botlab/data/map_entities/${activeMap}.json`)
      .then((r) =>
        r.ok
          ? (r.json() as Promise<MapEntitiesManifest>)
          : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then(setEntityManifest)
      .catch((err: unknown) => {
        logWarn("map entities fetch failed in mockup pane", { map: activeMap, error: err });
        setEntityManifest(null);
      })
      .finally(() => setLoadingEntities(false));
  }, [activeMap]);

  // ---- Context events --------------------------------------------------------

  useEffect(() => {
    const route =
      selectedRoutes.length > 0
        ? selectedRoutes[selectedRoutes.length - 1]
        : null;
    onSelect?.({ map: activeMap, route });
  }, [activeMap, selectedRoutes, onSelect]);

  // ---- Static map entity geometry ------------------------------------------

  useEffect(() => {
    const scene = sceneRef.current?.scene;
    if (!scene) return;

    for (const obj of entityObjectsRef.current) {
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
    entityObjectsRef.current = [];

    if (!entityManifest) return;

    const objects = entityManifest.entities.map(buildEntityObject);
    for (const obj of objects) {
      scene.add(obj);
    }
    entityObjectsRef.current = objects;
  }, [entityManifest, sceneGeneration]);

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
        const tpMark = buildMarker(tp.from[0], tp.from[1], tp.from[2], 0x44ffee, 20);
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
  const entities = entityManifest?.entities ?? [];
  const entityCounts = entityTypeCounts(entities);
  const finalGap =
    lastSelectedRoute && lastSelectedRoute.gaps.length > 0
      ? lastSelectedRoute.gaps[lastSelectedRoute.gaps.length - 1]
      : null;
  const routeEntityContext =
    lastSelectedRoute && entities.length > 0
      ? {
          start: nearestEntity(lastSelectedRoute.polyline[0], entities),
          edge: nearestEntity(finalGap?.edge, entities),
          land: nearestEntity(finalGap?.land, entities),
        }
      : null;

  function nearestLine(
    label: string,
    nearest: { entity: MapEntity; distance: number } | null,
  ) {
    if (!nearest) return null;
    const entity = nearest.entity;
    return (
      <div>
        {label} {entityDisplayName(entity)}{" "}
        <span className="text-gray-700">
          {entity.type} {Math.round(nearest.distance)}q
        </span>
      </div>
    );
  }

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
                    title={`${route.name} - peak ${metricText(route.human.peak_speed)} qu/s - ${route.gaps.length} gap(s)`}
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
                      {metricText(route.human.active_mean_speed)} mu{" "}
                      {metricText(route.human.peak_speed)} pk
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section
          data-map-entity-summary={activeMap}
          className="px-2 py-1 border-t border-slate-800 text-[10px] text-gray-500 font-mono"
        >
          <div className="font-bold text-gray-400 text-xs mb-0.5">Entities</div>
          {loadingEntities && <div className="text-gray-600">loading...</div>}
          {!loadingEntities && entityManifest === null && (
            <div className="text-gray-600 italic">none</div>
          )}
          {entityManifest !== null && (
            <>
              <div>{entities.length} total</div>
              {Object.entries(entityCounts).map(([type, count]) => (
                <div key={type}>
                  {type} {count}
                </div>
              ))}
            </>
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
            <div>dur {metricText(lastSelectedRoute.human.duration_s, 2)} s</div>
            <div>mean {metricText(lastSelectedRoute.human.active_mean_speed)} qu/s</div>
            <div>peak {metricText(lastSelectedRoute.human.peak_speed)} qu/s</div>
            {lastSelectedRoute.gaps.map((g, i) => (
              <div key={i} className="mt-0.5 border-t border-slate-800 pt-0.5">
                gap {i + 1}: {g.type}{g.hard ? " [hard]" : ""}
                <br />
                req {metricText(g.required_speed)} hu {metricText(g.human_speed_at_edge)}
              </div>
            ))}
            {routeEntityContext && (
              <div
                data-route-entity-context={lastSelectedRoute.name}
                className="mt-0.5 border-t border-slate-800 pt-0.5"
              >
                {nearestLine("start", routeEntityContext.start)}
                {nearestLine("edge", routeEntityContext.edge)}
                {nearestLine("land", routeEntityContext.land)}
              </div>
            )}
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
