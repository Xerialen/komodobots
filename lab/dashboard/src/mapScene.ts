// Reusable Three.js map-scene module for the Lab Dashboard (LD-B3, #89).
//
// Encapsulates the scene/camera/renderer/controls lifecycle that both the
// Live 3D pane (BotLab3D.tsx) and the Mockup pane (LD-C3, #97) need.
// The module owns setup, mesh loading, resize handling, and GPU disposal.
//
// LD-C5 (#99): OBJ loader replaced by GLTFLoader for textured .glb assets
// (committed by LD-C4, #92).  Map materials are transparent by default
// (FILL_OPACITY ~0.3 "quite transparent") with a setOpacity() control so
// both views share a consistent opacity setter.  Sky / tool-texture materials
// (tagged TAG_SKY / TAG_SKIP in the GLB extras) are hidden by default.
// Wireframe is a toggle (default off once textures land; setWireframe() API).
// depthWrite is left false on all map materials so trails/markers/lines remain
// visible through the geometry at every opacity level.
//
// Quake coordinate convention: Z-up right-handed -> three.js Y-up right-handed.
// The loaded GLTF scene root is rotated -90deg around X so the same
// quakeToThree transform used for telemetry points also maps the mesh correctly.
// See quakeCoords.ts.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { setFromQuake } from "./quakeCoords.ts";

// Default opacity for the map mesh — "quite transparent" per SPEC §6.3 / #99.
const FILL_OPACITY = 0.3;

// TAG strings set by bsp_to_mesh.py in material extras.quake_tag; used to
// hide sky / tool textures by default (#92).
// These must match bsp_to_mesh.TAG_SKY / TAG_SKIP ("sky" / "skip").
// GLTFLoader merges glTF material extras directly into material.userData
// (Object.assign), so the key is material.userData.quake_tag.
const TAG_SKY = "sky";
const TAG_SKIP = "skip";

export type MapScene = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  /**
   * Set the map mesh opacity uniformly across all non-sky/non-skip materials.
   * Range 0.0–1.0; transparent materials already have depthWrite:false so
   * overlays stay readable at every value.
   */
  setOpacity: (value: number) => void;
  /**
   * Enable/disable a wireframe overlay on all visible map meshes.
   * Default: false (textures land first).
   */
  setWireframe: (enabled: boolean) => void;
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
 * @param mapName - Quake map name ("dm3", "dm2", …); used to build the GLB URL
 *   `/botlab/maps/<mapName>.glb` (LD-C4 canonical path).
 * @param qCenter - Quake-space AABB center `[x, y, z]`; used for the initial
 *   overview camera.  Defaults to dm3's center `[532, 88, 40]`.
 * @param onMeshLoaded - Optional callback fired once the GLB scene root is
 *   added to the scene.  Useful for consumers that need to add geometry after
 *   the mesh.
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

  // ── Material state ───────────────────────────────────────────────────────
  // Collect visible (non-sky/non-skip) MeshStandardMaterials loaded from the
  // GLB so setOpacity / setWireframe can update them after load.
  let currentOpacity = FILL_OPACITY;
  // The GLB may produce MeshStandardMaterial (textured) or MeshBasicMaterial
  // (fallback); keep a heterogeneous list.
  type MapMaterial = THREE.MeshStandardMaterial | THREE.MeshBasicMaterial;
  const visibleMaterials: MapMaterial[] = [];
  // Wire-overlay meshes added on top of each visible map mesh when wireframe
  // mode is on; kept separate so the textured material is unchanged.
  const wireMeshes: THREE.Mesh[] = [];
  let wireframeActive = false;
  const wireMaterial = new THREE.MeshBasicMaterial({
    color: 0x4a5a80,
    wireframe: true,
    transparent: true,
    opacity: 0.35,
  });

  function setOpacity(value: number): void {
    currentOpacity = value;
    for (const mat of visibleMaterials) {
      mat.opacity = value;
      mat.transparent = value < 1.0;
    }
  }

  function setWireframe(enabled: boolean): void {
    if (enabled === wireframeActive) return;
    wireframeActive = enabled;
    for (const wm of wireMeshes) {
      wm.visible = enabled;
    }
  }

  // ── Overview camera helper ────────────────────────────────────────────────
  const mapCenter = new THREE.Vector3();
  function setOverviewCamera(qx: number, qy: number, qz: number): void {
    setFromQuake(mapCenter, qx, qy, qz);
    camera.position.copy(mapCenter).add(new THREE.Vector3(0, 1900, 1600));
    controls.target.copy(mapCenter);
  }
  setOverviewCamera(...qCenter);

  // ── Mesh loading ─────────────────────────────────────────────────────────
  // LD-C4 (#92) canonical GLB path; glb/ is present in public/maps/ and
  // shipped by Vite.
  const glbUrl = `/botlab/maps/${mapName}.glb`;

  let disposed = false;
  const loader = new GLTFLoader();
  loader.load(glbUrl, (gltf) => {
    if (disposed) {
      // Late load after dispose: free GPU resources immediately.
      gltf.scene.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose();
          const mats = Array.isArray(child.material)
            ? child.material
            : [child.material];
          for (const mat of mats) (mat as THREE.Material).dispose();
        }
      });
      return;
    }

    const root = gltf.scene;

    // Apply Quake Z-up → three.js Y-up rotation: -90deg around X
    // maps (x,y,z) -> (x,z,-y), matching quakeToThree for telemetry points.
    root.rotation.x = -Math.PI / 2;

    // Iterate all meshes to:
    //  1. Mark sky/skip materials invisible (hidden by default per #92/#99).
    //  2. Tune visible materials for the default opacity + depthWrite.
    //  3. Add wireframe overlay meshes (hidden by default).
    root.traverse((child) => {
      if (!(child instanceof THREE.Mesh)) return;

      const mats = Array.isArray(child.material)
        ? (child.material as THREE.Material[])
        : [child.material as THREE.Material];

      for (const mat of mats) {
        // bsp_to_mesh.py sets quake_tag in glTF material extras.
        // GLTFLoader (three.js) merges extras directly into material.userData
        // via Object.assign, so the key is material.userData.quake_tag.
        const tag: string =
          (mat as { userData?: { quake_tag?: string } }).userData
            ?.quake_tag ?? "";

        if (tag === TAG_SKY || tag === TAG_SKIP) {
          // Hide sky / clip / trigger / tool faces.
          child.visible = false;
          return; // skip further processing for this mesh
        }

        // Tune the visible map material.
        const typedMat = mat as MapMaterial;
        typedMat.transparent = currentOpacity < 1.0;
        typedMat.opacity = currentOpacity;
        // depthWrite false: keeps trails/markers/lines readable through the map
        // at any opacity.  Side effect at opacity=1.0: z-fighting is possible
        // in rare face-on-face cases but acceptable for this tool view.
        typedMat.depthWrite = false;
        typedMat.side = THREE.DoubleSide;
        visibleMaterials.push(typedMat);
      }

      // Add wireframe overlay (hidden until setWireframe(true)).
      const wireMesh = new THREE.Mesh(child.geometry, wireMaterial);
      wireMesh.visible = false;
      wireMesh.frustumCulled = false;
      child.add(wireMesh);
      wireMeshes.push(wireMesh);
    });

    scene.add(root);
    onMeshLoaded?.(root);
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
          (mat as THREE.Material).dispose();
        }
      }
    });
    wireMaterial.dispose();
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
    setOpacity,
    setWireframe,
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
