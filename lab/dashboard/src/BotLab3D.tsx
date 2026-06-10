import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { setFromQuake } from "./quakeCoords.ts";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

// 100 Hz x 2 min of trajectory is plenty for one attempt
const MAX_TRAIL_POINTS = 12000;
const VELOCITY_ARROW_SCALE = 0.25; // qu/s -> qu of arrow length

// .cmds replay line: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons
function parseCmdsPath(text: string): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (const line of text.split("\n")) {
    if (line.startsWith("#") || !line.trim()) {
      continue;
    }
    const cols = line.trim().split(/\s+/);
    if (cols.length < 4) {
      continue;
    }
    const [x, y, z] = [Number(cols[1]), Number(cols[2]), Number(cols[3])];
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) {
      points.push(setFromQuake(new THREE.Vector3(), x, y, z));
    }
  }
  return points;
}

export function BotLab3D({
  client,
  mapName,
  referencePathUrl,
  showReferencePath,
}: {
  client: TelemetryClient;
  mapName: string;
  referencePathUrl: string | null;
  showReferencePath: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const referenceLineRef = useRef<THREE.Line | null>(null);
  const showReferenceRef = useRef(showReferencePath);
  showReferenceRef.current = showReferencePath;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a14);

    const camera = new THREE.PerspectiveCamera(
      60,
      container.clientWidth / container.clientHeight,
      1,
      20000,
    );
    // start on a whole-map overview (dm3 world AABB center, from above-south);
    // once frames arrive the camera follows the bot
    const mapCenter = setFromQuake(new THREE.Vector3(), 514, 88, 32);
    camera.position.copy(mapCenter).add(new THREE.Vector3(0, 1900, 1600));

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.copy(mapCenter);

    let disposed = false;

    // Map mesh: translucent fill + wireframe overlay (MeshBasicMaterial — the
    // exported OBJ has no normals and we want the readability, not lighting).
    const loader = new OBJLoader();
    loader.load(`/botlab/${mapName}.obj`, (obj) => {
      if (disposed) {
        // late load after unmount: the cleanup traversal already ran, so
        // free the parsed geometry instead of adding it to a dead scene
        obj.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.geometry.dispose();
          }
        });
        return;
      }
      const fill = new THREE.MeshBasicMaterial({
        color: 0x2a3550,
        transparent: true,
        opacity: 0.28,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const wire = new THREE.MeshBasicMaterial({
        color: 0x4a5a80,
        wireframe: true,
        transparent: true,
        opacity: 0.35,
      });
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
      // Rotate the whole map from Quake Z-up to three.js Y-up instead of
      // rewriting vertices: -90deg around X maps (x,y,z) -> (x,z,-y),
      // matching quakeToThree for telemetry points.
      obj.rotation.x = -Math.PI / 2;
      scene.add(obj);
    });

    // Bot marker: player-sized box (32x32x56 qu), origin at center
    const botMarker = new THREE.Mesh(
      new THREE.BoxGeometry(32, 56, 32),
      new THREE.MeshBasicMaterial({ color: 0xff7722 }),
    );
    botMarker.visible = false;
    scene.add(botMarker);

    // Growing trajectory polyline
    const trailPositions = new Float32Array(MAX_TRAIL_POINTS * 3);
    const trailGeometry = new THREE.BufferGeometry();
    trailGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(trailPositions, 3),
    );
    trailGeometry.setDrawRange(0, 0);
    const trail = new THREE.Line(
      trailGeometry,
      new THREE.LineBasicMaterial({ color: 0xffaa33 }),
    );
    trail.frustumCulled = false;
    scene.add(trail);
    let trailCount = 0;

    // Velocity arrow
    const velocityArrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(),
      100,
      0x33ff66,
      24,
      12,
    );
    velocityArrow.visible = false;
    scene.add(velocityArrow);

    const botPosition = new THREE.Vector3();
    const velocityDir = new THREE.Vector3();
    let hasFrame = false;

    function onFrame(frame: TelemetryFrame) {
      setFromQuake(botPosition, frame.origin.x, frame.origin.y, frame.origin.z);
      // marker origin is mid-body; telemetry origin is quake player origin
      // (24 qu above feet for the 56-tall hull) — close enough at this scale
      botMarker.position.copy(botPosition);
      botMarker.visible = true;

      if (trailCount < MAX_TRAIL_POINTS) {
        trailPositions[trailCount * 3] = botPosition.x;
        trailPositions[trailCount * 3 + 1] = botPosition.y;
        trailPositions[trailCount * 3 + 2] = botPosition.z;
        trailCount += 1;
        trailGeometry.setDrawRange(0, trailCount);
        trailGeometry.attributes.position.needsUpdate = true;
      }

      setFromQuake(velocityDir, frame.vel.x, frame.vel.y, frame.vel.z);
      const speed = velocityDir.length();
      if (speed > 1) {
        velocityDir.normalize();
        velocityArrow.position.copy(botPosition);
        velocityArrow.setDirection(velocityDir);
        velocityArrow.setLength(
          Math.max(32, speed * VELOCITY_ARROW_SCALE),
          24,
          12,
        );
        velocityArrow.visible = true;
      } else {
        velocityArrow.visible = false;
      }
      hasFrame = true;
    }

    function onAttempt() {
      trailCount = 0;
      trailGeometry.setDrawRange(0, 0);
      hasFrame = false;
    }

    client.frameListeners.add(onFrame);
    client.attemptListeners.add(onAttempt);

    const cameraDelta = new THREE.Vector3();
    function animate() {
      if (disposed) {
        return;
      }
      requestAnimationFrame(animate);
      if (hasFrame) {
        // follow: shift camera by the same delta as the orbit target so the
        // user-chosen viewing angle/distance is preserved
        cameraDelta.copy(botPosition).sub(controls.target);
        camera.position.add(cameraDelta);
        controls.target.copy(botPosition);
      }
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    function onResize() {
      if (!container) {
        return;
      }
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(container);

    const sceneForReference = scene;
    referenceLineRef.current = null;
    if (referencePathUrl) {
      fetch(referencePathUrl)
        .then((response) => (response.ok ? response.text() : Promise.reject()))
        .then((text) => {
          if (disposed) {
            return;
          }
          const points = parseCmdsPath(text);
          if (!points.length) {
            return;
          }
          const line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(points),
            new THREE.LineBasicMaterial({
              color: 0x33ccff,
              transparent: true,
              opacity: 0.7,
            }),
          );
          line.frustumCulled = false;
          line.visible = showReferenceRef.current;
          referenceLineRef.current = line;
          sceneForReference.add(line);
        })
        .catch(() => undefined);
    }

    return () => {
      disposed = true;
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(onAttempt);
      resizeObserver.disconnect();
      controls.dispose();
      // free GPU buffers — StrictMode double-mounts this effect in dev
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material)
            ? object.material
            : [object.material];
          for (const material of materials) {
            material.dispose();
          }
        }
      });
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, [client, mapName, referencePathUrl]);

  useEffect(() => {
    if (referenceLineRef.current) {
      referenceLineRef.current.visible = showReferencePath;
    }
  }, [showReferencePath]);

  return <div ref={containerRef} className="w-full h-full min-h-[400px]" />;
}
