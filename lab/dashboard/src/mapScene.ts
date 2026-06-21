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
import { logWarn } from "./logger.ts";

// Default opacity for the map mesh — "quite transparent" per SPEC §6.3 / #99.
const FILL_OPACITY = 0.3;

// TAG strings set by bsp_to_mesh.py in material extras (quake_tag field);
// values are lowercase "sky" / "skip" matching lab/tools/bsp_to_mesh.py
// TAG_SKY = "sky" / TAG_SKIP = "skip" (locked by tests/test_bsp_to_mesh.py).
const TAG_SKY = "sky";
const TAG_SKIP = "skip";

// Map-name aliases: telemetry may report a map name that differs from the
// committed GLB asset name.  E.g. the server runs "ztricks" but the committed
// asset is "trick".  Normalize before building the GLB URL so GLTFLoader never
// requests a missing asset and falls back to a non-crashing state instead.
// Add new entries here when a new alias is encountered in telemetry.
const MAP_ALIASES: Readonly<Record<string, string>> = {
  ztricks: "trick",
};

// Committed GLB asset names (the set present in public/maps/).  If a telemetry
// map name (after alias expansion) is not in this set, we skip the GLB load
// and call onMeshLoaded without a scene root so the 3D pane shows an empty but
// non-crashing scene.
const COMMITTED_MAPS = new Set(["dm2", "dm3", "frobodm2", "trick"]);

/**
 * Normalise a raw telemetry/user map name to the committed GLB asset name.
 * Returns null if the name cannot be resolved to a committed asset.
 */
export function normalizeMapName(rawName: string): string | null {
  const expanded = MAP_ALIASES[rawName] ?? rawName;
  return COMMITTED_MAPS.has(expanded) ? expanded : null;
}

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
  //
  // Resolve the committed GLB asset name: telemetry may report a map name that
  // differs from the committed asset (e.g. "ztricks" -> "trick").  If the name
  // cannot be resolved to a committed asset, skip the load to avoid a crashing
  // GLTFLoader request that returns HTML (Codex P1, HEAD d9a42d1).
  const resolvedName = normalizeMapName(mapName);
  const glbUrl = resolvedName != null ? `/botlab/maps/${resolvedName}.glb` : null;

  let disposed = false;

  function processGLTF(gltf: { scene: THREE.Group }) {
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

    // Collect all original map meshes in a separate pass BEFORE mutating the
    // scene graph.  THREE.Object3D.traverse visits children that are appended
    // during the walk (because it iterates the live children array), which
    // would cause infinite recursion if we called child.add(wireMesh) inside
    // the same traversal (Codex P1, HEAD d9a42d1:
    //   "RangeError: Maximum call stack size exceeded" from mapScene.ts:87).
    const mapMeshes: THREE.Mesh[] = [];
    root.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        mapMeshes.push(child);
      }
    });

    for (const child of mapMeshes) {
      const mats = Array.isArray(child.material)
        ? (child.material as THREE.Material[])
        : [child.material as THREE.Material];

      let isHidden = false;
      for (const mat of mats) {
        // bsp_to_mesh.py embeds quake_tag in material extras (GLTF extras path).
        // GLTFLoader places extras under material.userData (Three.js convention);
        // key is "quake_tag" with lowercase values "sky" / "skip" / "regular" /
        // "liquid" (see lab/tools/bsp_to_mesh.py TAG_* constants, locked by
        // tests/test_bsp_to_mesh.py test_material_extras_quake_tag_present).
        const extras =
          (mat as { userData?: { quake_tag?: string; extras?: { quake_tag?: string } } }).userData
            ?? {};
        // Check direct userData.quake_tag first (Three.js GLTFLoader flattens
        // GLTF material extras into userData), then fall back to nested .extras.
        const tag: string =
          (extras as { quake_tag?: string }).quake_tag ??
          (extras as { extras?: { quake_tag?: string } }).extras?.quake_tag ??
          "";

        if (tag === TAG_SKY || tag === TAG_SKIP) {
          // Hide sky / clip / trigger / tool faces.
          child.visible = false;
          isHidden = true;
          break;
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

      if (!isHidden) {
        // Add wireframe overlay AFTER the traversal loop is complete (see above).
        // Respect wireframeActive in case setWireframe(true) was called before
        // the GLB finished loading.  Without this, a pre-enabled wireframe would
        // never show because the later setWireframe(true) calls
        // `if (enabled === wireframeActive) return` and exits early (Codex P2).
        const wireMesh = new THREE.Mesh(child.geometry, wireMaterial);
        wireMesh.visible = wireframeActive; // honor pre-load toggle
        wireMesh.frustumCulled = false;
        child.add(wireMesh);
        wireMeshes.push(wireMesh);
      }
    }

    scene.add(root);
    onMeshLoaded?.(root);
  }

  if (glbUrl != null) {
    const loader = new GLTFLoader();
    loader.load(glbUrl, processGLTF);
  }
  // If glbUrl is null (unresolvable map name), the scene stays empty — no
  // crash, no spurious HTML-as-GLTF errors in the browser console.

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
  } catch (err: unknown) {
    logWarn("map center lookup failed; using dm3 default", err);
    return DM3_DEFAULT;
  }
}
