// LD-A1 (#84) / LD-B3 (#89): Live 3D pane — Three.js scene driven by the
// shared TelemetryClient.
//
// LD-B3 refactor: the map-scene setup (scene/camera/renderer/controls/mesh
// loading/resize handling/dispose) is now in mapScene.ts so the Mockup pane
// (LD-C3, #97) can reuse the same rig.  Bot actor management (marker/trail/
// velocity arrow) and the telemetry frame loop remain here — they are specific
// to the live telemetry view.
//
// LD-C5 (#99): mapScene now loads the textured GLB; opacity and wireframe
// props are forwarded to mapScene.setOpacity / mapScene.setWireframe so the
// live view inherits the shared 3D controls from the top bar.

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { setFromQuake } from "./quakeCoords.ts";
import { createMapScene } from "./mapScene.ts";
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
  mapOpacity,
  wireframe,
}: {
  client: TelemetryClient;
  mapName: string;
  referencePathUrl: string | null;
  showReferencePath: boolean;
  /** Map mesh opacity (0.05–1.0). Passed to mapScene.setOpacity on change. */
  mapOpacity: number;
  /** Wireframe overlay toggle. Passed to mapScene.setWireframe on change. */
  wireframe: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const referenceLineRef = useRef<THREE.Line | null>(null);
  const showReferenceRef = useRef(showReferencePath);
  showReferenceRef.current = showReferencePath;
  // Ref to the live mapScene so opacity/wireframe effects can call setters
  // without re-running the heavy scene-setup effect.
  const mapSceneRef = useRef<ReturnType<typeof createMapScene> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    // ── Map scene (shared module, LD-B3/LD-C5) ───────────────────────────
    // createMapScene handles: scene + camera + renderer + OrbitControls +
    // GLB mesh loading + resize observer + GPU dispose.
    // dm3 AABB center used as default overview point (matches maps.json).
    const mapScene = createMapScene(container, mapName);
    mapSceneRef.current = mapScene;
    // Apply initial opacity/wireframe in case they differ from defaults.
    mapScene.setOpacity(mapOpacity);
    mapScene.setWireframe(wireframe);
    const { scene, camera, renderer, controls } = mapScene;

    // ── Per-bot live actors ───────────────────────────────────────────────
    // Keyed by frame.ed (edict number — stable per entity for the lifetime of
    // an attempt).  A telemetry stream interleaves frames from every probed
    // bot, so marker/trail/arrow state must never be shared across bots.
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

    // Local disposed flag — mirrors the internal flag inside mapScene so
    // async fetches can bail out before touching a disposed scene.
    let disposed = false;

    // ── Render loop ───────────────────────────────────────────────────────
    let animFrameId: number;
    const cameraDelta = new THREE.Vector3();

    function animate() {
      if (disposed) return;
      animFrameId = requestAnimationFrame(animate);
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

    // ── Human reference path ──────────────────────────────────────────────
    referenceLineRef.current = null;
    if (referencePathUrl) {
      fetch(referencePathUrl)
        .then((response) => (response.ok ? response.text() : Promise.reject()))
        .then((text) => {
          if (disposed) return;
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
          scene.add(line);
        })
        .catch(() => undefined);
    }

    // ── Cleanup ───────────────────────────────────────────────────────────
    // Set disposed first so any in-flight fetches bail out.  Then cancel the
    // render loop, remove telemetry listeners, dispose bot actors (which
    // reference the scene), and finally call mapScene.dispose() which
    // traverses the full scene, frees the renderer, and removes the canvas.
    return () => {
      disposed = true;
      cancelAnimationFrame(animFrameId);
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(onAttempt);
      disposeActors();
      // Reference line geometry/material cleanup is handled by mapScene.dispose()
      // scene traversal (Line instances are traversed along with Meshes).
      mapSceneRef.current = null;
      mapScene.dispose();
    };
  // mapOpacity / wireframe intentionally excluded: they are applied via
  // dedicated effects below so the heavy scene-setup effect is not re-run.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, mapName, referencePathUrl]);

  useEffect(() => {
    if (referenceLineRef.current) {
      referenceLineRef.current.visible = showReferencePath;
    }
  }, [showReferencePath]);

  // LD-C5 (#99): forward opacity / wireframe changes to the live scene.
  useEffect(() => {
    mapSceneRef.current?.setOpacity(mapOpacity);
  }, [mapOpacity]);

  useEffect(() => {
    mapSceneRef.current?.setWireframe(wireframe);
  }, [wireframe]);

  return <div ref={containerRef} className="w-full h-full min-h-[400px]" />;
}
