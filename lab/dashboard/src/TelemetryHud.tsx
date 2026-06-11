// LD-F4 (#103): Multi-bot HUD — per-bot rows (vh, onground, hops) for up to
// ~4 bots; the selected bot's row is expanded with full detail (velocity,
// yaw/pitch, strafe diagnostics, dir_speed, dist_to_rl, air time).
// When selectedEd is null the first-seen bot acts as the expanded row
// (single-bot behaviour matches the pre-F4 display exactly).
//
// The stream interleaves frames from every probed bot; each ed gets its
// own accumulator for hop count and air time.  React state is throttled
// to HUD_UPDATE_MS; per-ed accumulators live in a ref and update at frame
// rate.

import { useEffect, useRef, useState } from "react";
import type { TelemetryClient, TelemetryFrame } from "./telemetryClient.ts";

const STRAFE_K = 26;
const HUD_UPDATE_MS = 80; // ~12 Hz display

// Maximum number of distinct bots shown; additional eds are ignored.
export const MAX_HUD_BOTS = 4;

type PerEdAcc = {
  prevFrame: TelemetryFrame | null;
  hopCount: number;
  airborneSince: number | null;
  lastPush: number;
};

type BotHudState = {
  frame: TelemetryFrame;
  yawRate: number;
  hopCount: number;
  airTime: number;
  strafeOffset: number | null;
  strafeOptimal: number | null;
};

function angleDelta(a: number, b: number): number {
  let delta = (a - b) % 360;
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  return delta;
}

export function TelemetryHud({
  client,
  selectedEd = null,
  onBotClick,
}: {
  client: TelemetryClient;
  /** ed of the selected bot (expanded row); null = first-seen bot. */
  selectedEd?: number | null;
  /** Called when the user clicks a compact HUD row. */
  onBotClick?: (ed: number) => void;
}) {
  // Map from ed -> HudState, ordered by first-seen
  const [bots, setBots] = useState<Map<number, BotHudState>>(new Map());
  // Track insertion order
  const orderRef = useRef<number[]>([]);

  const accumRef = useRef<Map<number, PerEdAcc>>(new Map());
  const selectedEdRef = useRef(selectedEd);
  selectedEdRef.current = selectedEd;

  useEffect(() => {
    function onFrame(frame: TelemetryFrame) {
      const accMap = accumRef.current;
      if (!accMap.has(frame.ed)) {
        if (accMap.size >= MAX_HUD_BOTS) return; // cap at MAX_HUD_BOTS
        accMap.set(frame.ed, {
          prevFrame: null,
          hopCount: 0,
          airborneSince: null,
          lastPush: 0,
        });
        orderRef.current.push(frame.ed);
      }
      const acc = accMap.get(frame.ed)!;

      let yawRate = 0;
      if (acc.prevFrame && frame.t > acc.prevFrame.t) {
        yawRate = angleDelta(frame.yaw, acc.prevFrame.yaw) / (frame.t - acc.prevFrame.t);
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
      if (now - acc.lastPush < HUD_UPDATE_MS) return;
      acc.lastPush = now;

      let strafeOffset: number | null = null;
      let strafeOptimal: number | null = null;
      const { fwd, side } = frame.move;
      if ((fwd !== 0 || side !== 0) && frame.vh > 1) {
        const wishYaw = frame.yaw - (Math.atan2(side, fwd) * 180) / Math.PI;
        const velocityYaw = (Math.atan2(frame.vel.y, frame.vel.x) * 180) / Math.PI;
        strafeOffset = Math.abs(angleDelta(wishYaw, velocityYaw));
      }
      if (frame.vh > STRAFE_K) {
        strafeOptimal = (Math.acos(STRAFE_K / frame.vh) * 180) / Math.PI;
      }

      setBots((prev) => {
        const next = new Map(prev);
        next.set(frame.ed, {
          frame,
          yawRate,
          hopCount: acc.hopCount,
          airTime: acc.airborneSince !== null ? frame.t - acc.airborneSince : 0,
          strafeOffset,
          strafeOptimal,
        });
        return next;
      });
    }

    function onAttempt() {
      accumRef.current.clear();
      orderRef.current = [];
      setBots(new Map());
    }

    client.frameListeners.add(onFrame);
    client.attemptListeners.add(onAttempt);
    return () => {
      client.frameListeners.delete(onFrame);
      client.attemptListeners.delete(onAttempt);
    };
  }, [client]);

  if (bots.size === 0) {
    return (
      <div className="font-mono text-xs text-gray-500 p-2">
        no telemetry frames yet
      </div>
    );
  }

  // Display order: insertion order; expanded bot first if not already first
  const order = orderRef.current.filter((ed) => bots.has(ed));
  const expandedEd = selectedEdRef.current ?? order[0] ?? null;

  return (
    <div className="font-mono text-xs bg-black/70">
      {order.map((ed) => {
        const state = bots.get(ed);
        if (!state) return null;
        const expanded = ed === expandedEd;
        return (
          <BotHudRow
            key={ed}
            state={state}
            expanded={expanded}
            onClick={onBotClick ? () => onBotClick(ed) : undefined}
          />
        );
      })}
    </div>
  );
}

function BotHudRow({
  state,
  expanded,
  onClick,
}: {
  state: BotHudState;
  expanded: boolean;
  onClick?: () => void;
}) {
  const { frame } = state;
  const label = frame.name || `ed ${frame.ed}`;

  if (!expanded) {
    // Compact row: name | speed | hops | onground
    return (
      <div
        className={`flex gap-x-4 px-2 py-0.5 border-t border-slate-800 cursor-pointer hover:bg-slate-900/50 ${onClick ? "" : "pointer-events-none"}`}
        onClick={onClick}
        aria-label={`select bot ${label}`}
      >
        <span className="text-amber-400 font-bold w-16 truncate">{label}</span>
        <span className="text-gray-400">
          <span className="text-gray-500">vh </span>{frame.vh.toFixed(0)}
        </span>
        <span className="text-gray-400">
          <span className="text-gray-500">hops </span>{state.hopCount}
        </span>
        <span className={frame.onground ? "text-gray-400" : "text-green-400"}>
          {frame.onground ? "ground" : "air"}
        </span>
      </div>
    );
  }

  // Expanded row: full detail (matches pre-F4 display, with bot name first)
  return (
    <div
      className={`p-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 border-t border-slate-700 ${onClick ? "cursor-pointer hover:bg-slate-900/30" : ""}`}
      onClick={onClick}
      aria-label={`selected bot ${label}`}
    >
      <Cell label="bot" value={label} highlight />
      <Cell label="speed (vh)" value={frame.vh.toFixed(0)} highlight />
      <Cell
        label="vel x/y/z"
        value={`${frame.vel.x.toFixed(0)} ${frame.vel.y.toFixed(0)} ${frame.vel.z.toFixed(0)}`}
      />
      <Cell
        label="yaw / pitch"
        value={`${frame.yaw.toFixed(1)} / ${frame.pitch.toFixed(1)}`}
      />
      <Cell label="yaw rate" value={`${state.yawRate.toFixed(0)}°/s`} />
      <Cell
        label="move f/s/u"
        value={`${frame.move.fwd} ${frame.move.side} ${frame.move.up}`}
      />
      <Cell
        label="onground"
        value={frame.onground ? "yes" : "air"}
        highlight={!frame.onground}
      />
      <Cell label="hops" value={String(state.hopCount)} />
      <Cell label="air time" value={`${state.airTime.toFixed(2)}s`} />
      <Cell
        label="strafe ∠ (now/opt)"
        value={
          state.strafeOffset !== null && state.strafeOptimal !== null
            ? `${state.strafeOffset.toFixed(1)}° / ${state.strafeOptimal.toFixed(1)}°`
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
