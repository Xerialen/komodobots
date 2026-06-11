// LD-A1 (#84) / LD-B3 (#89): Live 3D pane — Three.js scene driven by the
// shared TelemetryClient.
//
// LD-B3 refactor: the map-scene setup (scene/camera/renderer/controls/mesh
// loading/resize handling/dispose) is now in mapScene.ts so the Mockup pane
// (LD-C3, #97) can reuse the same rig.  Bot actor management (marker/trail/
// velocity arrow) and the telemetry frame loop remain here — they are specific
// to the live telemetry view.
//
// LD-F4 (#103): Multi-bot support — per-ed name labels (canvas sprite),
// selected-bot follow (click marker or HUD row), overview camera when 2+
// bots are live and none is selected.  Trail budget is per-bot (each bot
// gets MAX_TRAIL_POINTS_PER_BOT so the total scales with bot count; the
// budget is still finite).  onBotClick fires when the user clicks a marker;
// App.tsx tracks the selectedEd and passes it back via selectedEd prop so
// the camera policy and HUD expansion stay in sync.

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { setFromQuake } from "./quakeCoords.ts";
import { createMapScene } from "./mapScene.ts";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

// Per-bot budget: 100 Hz × 2 min (enough for one attempt per bot without
// sharing a fixed pool).  Four bots = 48 000 Float32 positions = 576 kB —
// acceptable for a lab tool.
const MAX_TRAIL_POINTS_PER_BOT = 12000;
const VELOCITY_ARROW_SCALE = 0.25; // qu/s -> qu of arrow length

// One marker/trail color pair per bot, assigned in order of first appearance
// within an attempt (a lab run can spawn several Frogbots — see
// docs/05_HEADLESS_TEST_ENV.md, "/ bro" + "/ goldenboy").
export const BOT_COLORS = [
  { marker: 0xff7722, trail: 0xffaa33 },
  { marker: 0x22aaff, trail: 0x55ccff },
  { marker: 0xff44cc, trail: 0xff88dd },
  { marker: 0xaaff33, trail: 0xccff77 },
];

// Canvas-texture name label: creates a small white-text-on-transparent sprite
// so each bot marker has a readable name without a DOM overlay.
function makeNameSprite(name: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 32;
  const ctx = canvas.getContext("2d")!;
  ctx.font = "bold 18px monospace";
  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.fillText(name, 4, 22);
  const texture = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: texture, depthTest: false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(96, 24, 1);
  sprite.position.set(0, 44, 0); // above the 56-unit-tall marker
  sprite.visible = false;
  return sprite;
}

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
  selectedEd = null,
  onBotClick,
}: {
  client: TelemetryClient;
  mapName: string;
  referencePathUrl: string | null;
  showReferencePath: boolean;
  /** ed of the currently selected bot (controls camera follow); null = auto. */
  selectedEd?: number | null;
  /** Called when the user clicks a bot marker; arg is the ed. */
  onBotClick?: (ed: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const referenceLineRef = useRef<THREE.Line | null>(null);
  const showReferenceRef = useRef(showReferencePath);
  showReferenceRef.current = showReferencePath;

  // Keep live refs for the props that change without remounting
  const selectedEdRef = useRef<number | null>(selectedEd);
  selectedEdRef.current = selectedEd;
  const onBotClickRef = useRef(onBotClick);
  onBotClickRef.current = onBotClick;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    // ── Map scene (shared module, LD-B3) ─────────────────────────────────
    const mapScene = createMapScene(container, mapName);
    const { scene, camera, renderer, controls } = mapScene;

    // ── Per-bot live actors ───────────────────────────────────────────────
    // Keyed by frame.ed (edict number — stable per entity for the lifetime of
    // an attempt).  A telemetry stream interleaves frames from every probed
    // bot, so marker/trail/arrow state must never be shared across bots.
    type BotActor = {
      marker: THREE.Mesh;
      nameSprite: THREE.Sprite;
      trail: THREE.Line;
      trailGeometry: THREE.BufferGeometry;
      trailPositions: Float32Array;
      trailCount: number;
      velocityArrow: THREE.ArrowHelper;
      position: THREE.Vector3;
      ed: number;
      name: string;
    };
    const actors = new Map<number, BotActor>();

    function createActor(ed: number, name: string): BotActor {
      const colors = BOT_COLORS[actors.size % BOT_COLORS.length];

      // Bot marker: player-sized box (32x32x56 qu), origin at center
      const marker = new THREE.Mesh(
        new THREE.BoxGeometry(32, 56, 32),
        new THREE.MeshBasicMaterial({ color: colors.marker }),
      );
      marker.visible = false;
      marker.userData = { ed };
      scene.add(marker);

      // Name label sprite above the marker
      const nameSprite = makeNameSprite(name || `ed ${ed}`);
      marker.add(nameSprite); // child of marker so it moves with it

      // Growing trajectory polyline
      const trailPositions = new Float32Array(MAX_TRAIL_POINTS_PER_BOT * 3);
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
        nameSprite,
        trail,
        trailGeometry,
        trailPositions,
        trailCount: 0,
        velocityArrow,
        position: new THREE.Vector3(),
        ed,
        name,
      };
    }

    function disposeActors() {
      for (const actor of actors.values()) {
        scene.remove(actor.marker);
        scene.remove(actor.trail);
        scene.remove(actor.velocityArrow);
        actor.marker.geometry.dispose();
        (actor.marker.material as THREE.Material).dispose();
        actor.nameSprite.material.dispose();
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
    // LD-F4 (#103): multi-bot overview stores bounding radius so the animate
    // loop can ensure all bots are in-frame.  0 = single-bot / no bounds data.
    let followRadius = 0;
    let hasFrame = false;

    function onFrame(frame: TelemetryFrame) {
      let actor = actors.get(frame.ed);
      if (!actor) {
        actor = createActor(frame.ed, frame.name);
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
      actor.marker.position.copy(actor.position);
      actor.marker.visible = true;
      actor.nameSprite.visible = true;

      if (actor.trailCount < MAX_TRAIL_POINTS_PER_BOT) {
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

      // Camera follow target: selectedEd (explicit user selection) takes
      // precedence; fall back to primaryEd for single-bot; overview (centroid)
      // when 2+ bots are active and no bot is selected.
      const sel = selectedEdRef.current;
      if (sel !== null && sel === frame.ed) {
        followPosition.copy(actor.position);
        hasFrame = true;
      } else if (sel === null) {
        if (actors.size <= 1 && frame.ed === primaryEd) {
          // Single bot: follow as before
          followPosition.copy(actor.position);
          hasFrame = true;
        } else if (actors.size > 1) {
          // Multi-bot overview: centroid + bounding radius so all active bots
          // are framed.  Radius is the max distance from centroid to any actor
          // plus a 128 qu margin (Codex P2 fix: plain centroid-only can crop
          // bots as they diverge — camera must widen to contain all actors).
          let cx = 0, cy = 0, cz = 0;
          for (const a of actors.values()) {
            cx += a.position.x;
            cy += a.position.y;
            cz += a.position.z;
          }
          const n = actors.size;
          const cx_avg = cx / n;
          const cy_avg = cy / n;
          const cz_avg = cz / n;
          followPosition.set(cx_avg, cy_avg, cz_avg);
          // Bounding radius: max actor distance from centroid + margin
          let r = 0;
          for (const a of actors.values()) {
            const dx = a.position.x - cx_avg;
            const dy = a.position.y - cy_avg;
            const dz = a.position.z - cz_avg;
            const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
            if (d > r) r = d;
          }
          followRadius = r + 128; // 128 qu margin keeps bots off the edge
          hasFrame = true;
        }
      }
    }

    function onAttempt() {
      disposeActors();
      primaryEd = null;
      hasFrame = false;
    }

    client.frameListeners.add(onFrame);
    client.attemptListeners.add(onAttempt);

    // ── Raycaster for marker click → bot selection ────────────────────────
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function onPointerDown(ev: PointerEvent) {
      if (!onBotClickRef.current) return;
      const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
      pointer.set(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const meshes = [...actors.values()].map((a) => a.marker);
      const hits = raycaster.intersectObjects(meshes);
      if (hits.length > 0) {
        const ed = hits[0].object.userData.ed as number;
        onBotClickRef.current(ed);
      }
    }

    renderer.domElement.addEventListener("pointerdown", onPointerDown);

    // Local disposed flag
    let disposed = false;

    // ── Render loop ───────────────────────────────────────────────────────
    let animFrameId: number;
    const cameraDelta = new THREE.Vector3();

    // FOV half-angle for camera distance calculation (fov=60 set in createMapScene).
    const FOV_HALF_RAD = (60 / 2) * (Math.PI / 180);

    function animate() {
      if (disposed) return;
      animFrameId = requestAnimationFrame(animate);
      if (hasFrame) {
        cameraDelta.copy(followPosition).sub(controls.target);
        camera.position.add(cameraDelta);
        controls.target.copy(followPosition);

        // LD-F4 (#103): multi-bot overview — ensure camera distance is large
        // enough that all active bots fit in the frustum.  followRadius > 0 only
        // in the multi-bot no-selection path; single-bot and selected-bot paths
        // leave it 0 and this block is skipped.
        if (followRadius > 0) {
          // Minimum distance for the bounding sphere to fit in the vertical FOV.
          const minDist = followRadius / Math.sin(FOV_HALF_RAD);
          const toCamera = camera.position.clone().sub(controls.target);
          const currentDist = toCamera.length();
          if (currentDist < minDist) {
            // Push the camera outward along its current direction.
            camera.position.copy(
              controls.target
                .clone()
                .add(toCamera.normalize().multiplyScalar(minDist)),
            );
          }
        }
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
    return () => {
      disposed = true;
      cancelAnimationFrame(animFrameId);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(onAttempt);
      disposeActors();
      mapScene.dispose();
    };
  }, [client, mapName, referencePathUrl]);

  useEffect(() => {
    if (referenceLineRef.current) {
      referenceLineRef.current.visible = showReferencePath;
    }
  }, [showReferencePath]);

  return <div ref={containerRef} className="w-full h-full min-h-[400px]" />;
}
