// Reusable Three.js map-scene module for the Lab Dashboard (LD-B3, #89).
//
// Encapsulates the scene/camera/renderer/controls lifecycle that both the
// Live 3D pane (BotLab3D.tsx) and the future Mockup pane (LD-C3, #97) need.
// The module owns setup, mesh loading, resize handling, and GPU disposal.
//
// Quake coordinate convention: Z-up right-handed -> three.js Y-up right-handed.
// The loaded OBJ is rotated -90deg around X (obj.rotation.x = -Math.PI / 2)
// so the same quakeToThree transform used for telemetry points also maps
// the mesh correctly. See quakeCoords.ts.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { setFromQuake } from "./quakeCoords.ts";

// Fill and wireframe material defaults for the map mesh.  Opacity and
// wireframe state can be changed after construction via the returned handles.
const FILL_OPACITY = 0.28;

export type MapSceneMaterials = {
  fill: THREE.MeshBasicMaterial;
  wire: THREE.MeshBasicMaterial;
};

export type MapScene = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  materials: MapSceneMaterials;
  /**
   * Move the camera to a whole-map overview point centered on the given Quake
   * AABB center (x, y, z in Quake coords).  Called automatically from
   * createMapScene; callers can call it again when the map changes (Mockup).
   */
  setOverviewCamera: (qx: number, qy: number, qz: number) => void;
  /** Free all GPU resources. Call when the React component unmounts. */
  dispose: () => void;
};

/**
 * Create a Map scene attached to `container`.
 *
 * @param container - The DOM element the renderer canvas is appended to.
 * @param mapName - Quake map name ("dm3", "dm2", …); used to build the OBJ URL
 *   `/botlab/maps/<mapName>.obj` (LD-C2 canonical path; no legacy fallback).
 * @param qCenter - Quake-space AABB center `[x, y, z]`; used for the initial
 *   overview camera.  Defaults to dm3's center `[532, 88, 40]`.
 * @param onMeshLoaded - Optional callback fired once the OBJ is added to the
 *   scene.  Useful for consumers that need to add geometry after the mesh.
 */
export function createMapScene(
  container: HTMLDivElement,
  mapName: string,
  qCenter: [number, number, number] = [532, 88, 40],
  onMeshLoaded?: (obj: THREE.Object3D) => void,
): MapScene {
  // ── Scene ────────────────────────────────────────────────────────────────
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0a14);

  // ── Camera ───────────────────────────────────────────────────────────────
  const camera = new THREE.PerspectiveCamera(
    60,
    container.clientWidth / container.clientHeight,
    1,
    20000,
  );

  // ── Renderer ─────────────────────────────────────────────────────────────
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  // ── Controls ─────────────────────────────────────────────────────────────
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // ── Materials ────────────────────────────────────────────────────────────
  const fill = new THREE.MeshBasicMaterial({
    color: 0x2a3550,
    transparent: true,
    opacity: FILL_OPACITY,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const wire = new THREE.MeshBasicMaterial({
    color: 0x4a5a80,
    wireframe: true,
    transparent: true,
    opacity: 0.35,
  });

  // ── Overview camera helper ────────────────────────────────────────────────
  const mapCenter = new THREE.Vector3();
  function setOverviewCamera(qx: number, qy: number, qz: number): void {
    setFromQuake(mapCenter, qx, qy, qz);
    camera.position.copy(mapCenter).add(new THREE.Vector3(0, 1900, 1600));
    controls.target.copy(mapCenter);
  }
  setOverviewCamera(...qCenter);

  // ── Mesh loading ─────────────────────────────────────────────────────────
  // LD-C2 (#91) canonical path; maps/ is present in public/ and shipped by Vite.
  const objUrl = `/botlab/maps/${mapName}.obj`;

  let disposed = false;
  const loader = new OBJLoader();
  loader.load(objUrl, (obj) => {
    if (disposed) {
      // Late load after dispose: free GPU resources immediately.
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose();
        }
      });
      return;
    }
    // collect first — adding children during traverse() recurses into them
    const meshes: THREE.Mesh[] = [];
    obj.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        meshes.push(child);
      }
    });
    for (const mesh of meshes) {
      mesh.material = fill;
      mesh.add(new THREE.Mesh(mesh.geometry, wire));
    }
    // Rotate the whole map from Quake Z-up to three.js Y-up: -90deg around X
    // maps (x,y,z) -> (x,z,-y), matching quakeToThree for telemetry points.
    obj.rotation.x = -Math.PI / 2;
    scene.add(obj);
    onMeshLoaded?.(obj);
  });

  // ── Resize observer ──────────────────────────────────────────────────────
  function onResize(): void {
    if (!container) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  }
  const resizeObserver = new ResizeObserver(onResize);
  resizeObserver.observe(container);

  // ── Dispose ──────────────────────────────────────────────────────────────
  function dispose(): void {
    disposed = true;
    resizeObserver.disconnect();
    controls.dispose();
    scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
        object.geometry.dispose();
        const materials = Array.isArray(object.material)
          ? object.material
          : [object.material];
        for (const mat of materials) {
          mat.dispose();
        }
      }
    });
    fill.dispose();
    wire.dispose();
    renderer.dispose();
    if (container.contains(renderer.domElement)) {
      container.removeChild(renderer.domElement);
    }
  }

  return {
    scene,
    camera,
    renderer,
    controls,
    materials: { fill, wire },
    setOverviewCamera,
    dispose,
  };
}

/**
 * Resolve the Quake AABB center for a known map from the committed maps.json.
 * Returns the dm3 default if the map is not found or fetch fails.
 * This is a best-effort helper — consumers may also pass the center directly.
 */
export async function fetchMapCenter(
  mapName: string,
): Promise<[number, number, number]> {
  const DM3_DEFAULT: [number, number, number] = [532, 88, 40];
  try {
    const response = await fetch("/botlab/maps/maps.json");
    if (!response.ok) return DM3_DEFAULT;
    const data = (await response.json()) as {
      maps?: Record<string, { aabb?: { center?: number[] } }>;
    };
    const center = data.maps?.[mapName]?.aabb?.center;
    if (
      Array.isArray(center) &&
      center.length >= 3 &&
      center.every((v) => typeof v === "number")
    ) {
      return [center[0], center[1], center[2]];
    }
    return DM3_DEFAULT;
  } catch {
    return DM3_DEFAULT;
  }
}
