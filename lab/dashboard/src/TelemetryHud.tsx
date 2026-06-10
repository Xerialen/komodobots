import { useEffect, useRef, useState } from "react";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

// Air-strafe constant from the komodobots lab finding: optimal offset between
// velocity heading and wishdir is acos(K/speed), K ~= 26 qu/s.
const STRAFE_K = 26;
const HUD_UPDATE_MS = 80; // ~12 Hz display; frames arrive at ~100 Hz

type HudState = {
  frame: TelemetryFrame;
  yawRate: number;
  hopCount: number;
  airTime: number;
  strafeOffset: number | null;
  strafeOptimal: number | null;
};

function angleDelta(a: number, b: number): number {
  let delta = (a - b) % 360;
  if (delta > 180) {
    delta -= 360;
  }
  if (delta < -180) {
    delta += 360;
  }
  return delta;
}

export function TelemetryHud({ client }: { client: TelemetryClient }) {
  const [hud, setHud] = useState<HudState | null>(null);

  // derived-state accumulators live in refs: they update at frame rate,
  // React state only at HUD_UPDATE_MS
  const accumulator = useRef({
    ed: null as number | null,
    prevFrame: null as TelemetryFrame | null,
    hopCount: 0,
    airborneSince: null as number | null,
    lastPush: 0,
  });

  useEffect(() => {
    function onFrame(frame: TelemetryFrame) {
      const acc = accumulator.current;
      // The stream interleaves frames from every probed bot; derived values
      // (yaw rate, hops, air time) are only meaningful within one bot's frame
      // sequence, so lock onto the attempt's first-seen bot and ignore the
      // rest. Same bot the 3D view follows.
      if (acc.ed === null) {
        acc.ed = frame.ed;
      } else if (frame.ed !== acc.ed) {
        return;
      }
      let yawRate = 0;
      if (acc.prevFrame && frame.t > acc.prevFrame.t) {
        yawRate =
          angleDelta(frame.yaw, acc.prevFrame.yaw) / (frame.t - acc.prevFrame.t);
      }
      if (acc.prevFrame?.onground === 1 && frame.onground === 0) {
        acc.hopCount += 1;
        acc.airborneSince = frame.t;
      }
      if (frame.onground === 1) {
        acc.airborneSince = null;
      }
      acc.prevFrame = frame;

      const now = performance.now();
      if (now - acc.lastPush < HUD_UPDATE_MS) {
        return;
      }
      acc.lastPush = now;

      // current strafe offset: angle between wishdir heading and velocity heading
      let strafeOffset: number | null = null;
      let strafeOptimal: number | null = null;
      const { fwd, side } = frame.move;
      if ((fwd !== 0 || side !== 0) && frame.vh > 1) {
        const wishYaw =
          frame.yaw - (Math.atan2(side, fwd) * 180) / Math.PI;
        const velocityYaw =
          (Math.atan2(frame.vel.y, frame.vel.x) * 180) / Math.PI;
        strafeOffset = Math.abs(angleDelta(wishYaw, velocityYaw));
      }
      if (frame.vh > STRAFE_K) {
        strafeOptimal = (Math.acos(STRAFE_K / frame.vh) * 180) / Math.PI;
      }

      setHud({
        frame,
        yawRate,
        hopCount: acc.hopCount,
        airTime: acc.airborneSince !== null ? frame.t - acc.airborneSince : 0,
        strafeOffset,
        strafeOptimal,
      });
    }

    function onAttempt() {
      accumulator.current = {
        ed: null,
        prevFrame: null,
        hopCount: 0,
        airborneSince: null,
        lastPush: 0,
      };
      setHud(null);
    }

    client.frameListeners.add(onFrame);
    client.attemptListeners.add(onAttempt);
    return () => {
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(onAttempt);
    };
  }, [client]);

  if (!hud) {
    return (
      <div className="font-mono text-xs text-gray-500 p-2">
        no telemetry frames yet
      </div>
    );
  }

  const { frame } = hud;
  return (
    <div className="font-mono text-xs p-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 bg-black/70">
      <Cell label="bot" value={frame.name || `ed ${frame.ed}`} highlight />
      <Cell label="speed (vh)" value={frame.vh.toFixed(0)} highlight />
      <Cell
        label="vel x/y/z"
        value={`${frame.vel.x.toFixed(0)} ${frame.vel.y.toFixed(0)} ${frame.vel.z.toFixed(0)}`}
      />
      <Cell
        label="yaw / pitch"
        value={`${frame.yaw.toFixed(1)} / ${frame.pitch.toFixed(1)}`}
      />
      <Cell label="yaw rate" value={`${hud.yawRate.toFixed(0)}°/s`} />
      <Cell
        label="move f/s/u"
        value={`${frame.move.fwd} ${frame.move.side} ${frame.move.up}`}
      />
      <Cell
        label="onground"
        value={frame.onground ? "yes" : "air"}
        highlight={!frame.onground}
      />
      <Cell label="hops" value={String(hud.hopCount)} />
      <Cell label="air time" value={`${hud.airTime.toFixed(2)}s`} />
      <Cell
        label="strafe ∠ (now/opt)"
        value={
          hud.strafeOffset !== null && hud.strafeOptimal !== null
            ? `${hud.strafeOffset.toFixed(1)}° / ${hud.strafeOptimal.toFixed(1)}°`
            : "—"
        }
      />
      <Cell
        label="dir_speed"
        value={frame.dir_speed !== null ? frame.dir_speed.toFixed(0) : "—"}
      />
      <Cell
        label="dist to RL"
        value={frame.dist_to_rl !== null ? frame.dist_to_rl.toFixed(0) : "—"}
      />
      <Cell label="t" value={`${frame.t.toFixed(2)}s`} />
    </div>
  );
}

function Cell({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <span className="text-gray-500">{label}: </span>
      <span className={highlight ? "text-amber-400 font-bold" : "text-gray-200"}>
        {value}
      </span>
    </div>
  );
}
