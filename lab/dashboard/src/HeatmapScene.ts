// 3D heatmap layer for the 4v4 dashboard (issue: dashboard-3d-heatmap).
//
// Builds the "where the bots have been" density grid + "where they died" markers
// as geometry added INTO an existing createMapScene() scene (mapScene.ts) — it
// does NOT own the renderer/camera/controls. The density layer is one
// InstancedMesh of boxes (one instance per summed grid cell, height/colour by
// count); deaths are a second InstancedMesh of small spheres. Both use
// setFromQuake() so they line up with the textured dm3 GLB.
//
// Lifecycle mirrors BotLab3D.tsx exactly: addLayer() attaches meshes to the
// scene and returns a disposer that removes them and frees their GPU geometry/
// material. The shared mapScene.dispose() handles renderer/canvas teardown.

import * as THREE from "three";
import { setFromQuake } from "./quakeCoords.ts";
import type { MapScene } from "./mapScene.ts";

// One [ix, iy, count] grid cell.
export type HeatBin = [number, number, number];

export interface HeatmapGrid {
  nx: number;
  ny: number;
  // bottom-left corner in Quake [x, y]
  origin: [number, number];
  // box size in Quake units [x, y]
  extent: [number, number];
}

export interface HeatmapPlayer {
  slot: number;
  name: string;
  team: string;
  bins: HeatBin[];
  // death origins in Quake [x, y, z]
  deaths: Array<[number, number, number]>;
}

export interface HeatmapData {
  grid: HeatmapGrid;
  players: HeatmapPlayer[];
}

// Density box floor Z (Quake): the dm3 AABB min Z is -416, but spawns/routes sit
// well above the floor; place the columns at a fixed low Z so they read as a
// "carpet" on the map. Height grows upward with count.
const DENSITY_BASE_Z = -380;
const DENSITY_MAX_HEIGHT = 420; // qu, tallest column at the densest cell
const DEATH_MARKER_RADIUS = 18; // qu

// Low→high density ramp (cool blue → hot orange-red). Matches the dark console
// palette; opacity scales with normalised count so sparse cells stay faint.
const COLD = new THREE.Color(0x2a4a8a);
const HOT = new THREE.Color(0xff5a2a);

// A subset of the heatmap (already filtered to the selected subjects).
export interface HeatmapAddResult {
  /** Remove all added meshes from the scene and free their GPU resources. */
  dispose: () => void;
}

// Aggregate the selected players' bins into one summed grid (Map keyed by
// ix*ny+iy) so overlapping players' cells stack, and collect their deaths.
function aggregate(
  players: HeatmapPlayer[],
  grid: HeatmapGrid,
): { cells: Map<number, number>; deaths: Array<[number, number, number]>; maxCount: number } {
  const cells = new Map<number, number>();
  const deaths: Array<[number, number, number]> = [];
  let maxCount = 0;
  for (const player of players) {
    for (const [ix, iy, count] of player.bins) {
      if (ix < 0 || iy < 0 || ix >= grid.nx || iy >= grid.ny) continue;
      const key = ix * grid.ny + iy;
      const next = (cells.get(key) ?? 0) + count;
      cells.set(key, next);
      if (next > maxCount) maxCount = next;
    }
    for (const d of player.deaths) deaths.push(d);
  }
  return { cells, deaths, maxCount };
}

// Quake world-space centre of grid cell (ix, iy).
function cellCenterQuake(ix: number, iy: number, grid: HeatmapGrid): [number, number] {
  const x = grid.origin[0] + ((ix + 0.5) / grid.nx) * grid.extent[0];
  const y = grid.origin[1] + ((iy + 0.5) / grid.ny) * grid.extent[1];
  return [x, y];
}

/**
 * Add the density layer + death markers for `players` into `mapScene.scene`.
 * Returns a disposer; call it before re-adding a new selection (filter change)
 * and on unmount, exactly like BotLab3D disposes its actors.
 */
export function addHeatmapLayer(mapScene: MapScene, data: HeatmapData, players: HeatmapPlayer[]): HeatmapAddResult {
  const scene = mapScene.scene;
  const grid = data.grid;
  const { cells, deaths, maxCount } = aggregate(players, grid);

  const added: THREE.Object3D[] = [];
  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];

  // ── Density columns (one InstancedMesh of unit boxes) ─────────────────────
  const cellW = grid.extent[0] / grid.nx;
  const cellD = grid.extent[1] / grid.ny;
  if (cells.size > 0) {
    const boxGeo = new THREE.BoxGeometry(cellW * 0.9, 1, cellD * 0.9);
    const boxMat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false });
    const mesh = new THREE.InstancedMesh(boxGeo, boxMat, cells.size);
    mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cells.size * 3), 3);
    mesh.frustumCulled = false;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    const base = new THREE.Vector3();
    let i = 0;
    for (const [key, count] of cells) {
      const ix = Math.floor(key / grid.ny);
      const iy = key % grid.ny;
      const [qx, qy] = cellCenterQuake(ix, iy, grid);
      const norm = maxCount > 0 ? count / maxCount : 0;
      const height = Math.max(8, norm * DENSITY_MAX_HEIGHT);
      // Quake column centre sits at DENSITY_BASE_Z + height/2; map to three.js.
      setFromQuake(base, qx, qy, DENSITY_BASE_Z + height / 2);
      dummy.position.copy(base);
      // Box is built unit-tall on three.js Y; scale Y to the column height.
      dummy.scale.set(1, height, 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      color.copy(COLD).lerp(HOT, norm);
      mesh.setColorAt(i, color);
      i += 1;
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    boxMat.opacity = 0.6;
    scene.add(mesh);
    added.push(mesh);
    geometries.push(boxGeo);
    materials.push(boxMat);
  }

  // ── Death markers (one InstancedMesh of small spheres) ────────────────────
  if (deaths.length > 0) {
    const sphereGeo = new THREE.SphereGeometry(DEATH_MARKER_RADIUS, 10, 8);
    const sphereMat = new THREE.MeshBasicMaterial({
      color: 0xffe14d,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    });
    const mesh = new THREE.InstancedMesh(sphereGeo, sphereMat, deaths.length);
    mesh.frustumCulled = false;
    const dummy = new THREE.Object3D();
    const pos = new THREE.Vector3();
    deaths.forEach(([dx, dy, dz], idx) => {
      setFromQuake(pos, dx, dy, dz);
      dummy.position.copy(pos);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(idx, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
    added.push(mesh);
    geometries.push(sphereGeo);
    materials.push(sphereMat);
  }

  return {
    dispose() {
      for (const obj of added) scene.remove(obj);
      for (const geo of geometries) geo.dispose();
      for (const mat of materials) mat.dispose();
    },
  };
}
