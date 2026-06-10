import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { setFromQuake } from "./quakeCoords.ts";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

// 100 Hz x 2 min of trajectory is plenty for one attempt
const MAX_TRAIL_POINTS = 12000;
const VELOCITY_ARROW_SCALE = 0.25; // qu/s -> qu of arrow length

// One marker/trail color pair per bot, assigned in order of first appearance
// within an attempt (a lab run can spawn several Frogbots — see
// docs/05_HEADLESS_TEST_ENV.md, "/ bro" + "/ goldenboy").
const BOT_COLORS = [
  { marker: 0xff7722, trail: 0xffaa33 },
  { marker: 0x22aaff, trail: 0x55ccff },
  { marker: 0xff44cc, trail: 0xff88dd },
  { marker: 0xaaff33, trail: 0xccff77 },
];

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

    // Per-bot live actors, keyed by frame.ed (edict number — stable per
    // entity for the lifetime of an attempt). A telemetry stream interleaves
    // frames from every probed bot, so marker/trail/arrow state must never be
    // shared across bots.
    type BotActor = {
      marker: THREE.Mesh;
      trail: THREE.Line;
      trailGeometry: THREE.BufferGeometry;
      trailPositions: Float32Array;
      trailCount: number;
      velocityArrow: THREE.ArrowHelper;
      position: THREE.Vector3;
    };
    const actors = new Map<number, BotActor>();

    function createActor(): BotActor {
      const colors = BOT_COLORS[actors.size % BOT_COLORS.length];

      // Bot marker: player-sized box (32x32x56 qu), origin at center
      const marker = new THREE.Mesh(
        new THREE.BoxGeometry(32, 56, 32),
        new THREE.MeshBasicMaterial({ color: colors.marker }),
      );
      marker.visible = false;
      scene.add(marker);

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
        new THREE.LineBasicMaterial({ color: colors.trail }),
      );
      trail.frustumCulled = false;
      scene.add(trail);

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

      return {
        marker,
        trail,
        trailGeometry,
        trailPositions,
        trailCount: 0,
        velocityArrow,
        position: new THREE.Vector3(),
      };
    }

    function disposeActors() {
      for (const actor of actors.values()) {
        scene.remove(actor.marker);
        scene.remove(actor.trail);
        scene.remove(actor.velocityArrow);
        actor.marker.geometry.dispose();
        (actor.marker.material as THREE.Material).dispose();
        actor.trailGeometry.dispose();
        (actor.trail.material as THREE.Material).dispose();
        actor.velocityArrow.dispose();
      }
      actors.clear();
    }

    const velocityDir = new THREE.Vector3();
    // Camera follows the attempt's first-seen bot (same bot the HUD locks to)
    let primaryEd: number | null = null;
    const followPosition = new THREE.Vector3();
    let hasFrame = false;

    function onFrame(frame: TelemetryFrame) {
      let actor = actors.get(frame.ed);
      if (!actor) {
        actor = createActor();
        actors.set(frame.ed, actor);
      }
      if (primaryEd === null) {
        primaryEd = frame.ed;
      }

      setFromQuake(
        actor.position,
        frame.origin.x,
        frame.origin.y,
        frame.origin.z,
      );
      // marker origin is mid-body; telemetry origin is quake player origin
      // (24 qu above feet for the 56-tall hull) — close enough at this scale
      actor.marker.position.copy(actor.position);
      actor.marker.visible = true;

      if (actor.trailCount < MAX_TRAIL_POINTS) {
        actor.trailPositions[actor.trailCount * 3] = actor.position.x;
        actor.trailPositions[actor.trailCount * 3 + 1] = actor.position.y;
        actor.trailPositions[actor.trailCount * 3 + 2] = actor.position.z;
        actor.trailCount += 1;
        actor.trailGeometry.setDrawRange(0, actor.trailCount);
        actor.trailGeometry.attributes.position.needsUpdate = true;
      }

      setFromQuake(velocityDir, frame.vel.x, frame.vel.y, frame.vel.z);
      const speed = velocityDir.length();
      if (speed > 1) {
        velocityDir.normalize();
        actor.velocityArrow.position.copy(actor.position);
        actor.velocityArrow.setDirection(velocityDir);
        actor.velocityArrow.setLength(
          Math.max(32, speed * VELOCITY_ARROW_SCALE),
          24,
          12,
        );
        actor.velocityArrow.visible = true;
      } else {
        actor.velocityArrow.visible = false;
      }

      if (frame.ed === primaryEd) {
        followPosition.copy(actor.position);
        hasFrame = true;
      }
    }

    function onAttempt() {
      disposeActors();
      primaryEd = null;
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
        cameraDelta.copy(followPosition).sub(controls.target);
        camera.position.add(cameraDelta);
        controls.target.copy(followPosition);
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
