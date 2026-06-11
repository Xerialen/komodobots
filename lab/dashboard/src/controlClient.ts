// LD-F3 (#105): Control bridge client — wraps the JSON command channel
// (lab/server/control_bridge.py) hosted on the same WebSocket as telemetry.
//
// Protocol recap (see control_bridge.py docstring):
//   client -> server  { op, req_id, ...op-specific args }
//   server -> client  { re: req_id, ok, detail, ...result }   (response)
//   server -> all     { type: "control_event", event, ... }   (broadcast on success)
//
// Security note: this client sends commands on the SAME websocket as the
// telemetry stream.  Loopback peers are trusted automatically by the bridge;
// non-loopback callers need a token in each mutating request (the bridge
// enforces this server-side — we carry the token when configured but the
// browser accessing from LAN is already loopback-trusted).  The UI is a
// courtesy layer; the bridge is the real authority (#96 / Codex P1 #129).

export type LockState =
  | { state: "free"; lock: null }
  | { state: "fresh" | "stale"; lock: Record<string, unknown> };

export type ControlResponse = {
  re: string | null;
  ok: boolean;
  detail: string;
  [key: string]: unknown;
};

export type ControlEvent = {
  type: "control_event";
  event: string;
  [key: string]: unknown;
};

type PendingResolve = (response: ControlResponse) => void;

// How long to wait for a bridge response before timing out.
const RESPONSE_TIMEOUT_MS = 15_000;

let _reqCounter = 0;

function nextReqId(): string {
  return `ctrl_${++_reqCounter}_${Date.now()}`;
}

export class ControlClient {
  // Shared with TelemetryClient: this client does NOT open its own WebSocket.
  // Instead, App.tsx passes incoming text frames here via `onMessage` and
  // outgoing frames go through the provided `sendFn`.
  //
  // This design avoids a second WebSocket connection to the sidecar and keeps
  // the telemetry + control streams multiplexed on one connection, exactly
  // as the bridge expects.

  private pending = new Map<string, PendingResolve>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();

  readonly eventListeners = new Set<(event: ControlEvent) => void>();
  readonly connectionListeners = new Set<(connected: boolean) => void>();

  private _connected = false;
  private _sendFn: ((text: string) => void) | null = null;
  /** Optional per-deploy control token (from ?token= URL param).
   *  For LAN use the loopback trust path covers it; supply only for remote. */
  private _token: string | null = null;

  constructor(token?: string) {
    this._token = token ?? null;
  }

  /** Called by App.tsx when the telemetry WebSocket opens/closes. */
  onConnectionChange(connected: boolean, sendFn: ((text: string) => void) | null): void {
    this._connected = connected;
    this._sendFn = sendFn;
    if (!connected) {
      // Reject all pending calls.
      for (const [reqId, resolve] of this.pending) {
        clearTimeout(this.timers.get(reqId));
        this.timers.delete(reqId);
        resolve({ re: reqId, ok: false, detail: "bridge disconnected" });
      }
      this.pending.clear();
    }
    for (const listener of this.connectionListeners) {
      listener(connected);
    }
  }

  /** Called by App.tsx for every incoming text WebSocket frame. */
  onMessage(text: string): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(text) as Record<string, unknown>;
    } catch {
      return;
    }
    // Control event broadcast.
    if (msg.type === "control_event" && typeof msg.event === "string") {
      for (const listener of this.eventListeners) {
        listener(msg as ControlEvent);
      }
      return;
    }
    // Response to a pending request.
    const re = msg.re;
    if (typeof re === "string" && this.pending.has(re)) {
      const resolve = this.pending.get(re)!;
      this.pending.delete(re);
      clearTimeout(this.timers.get(re));
      this.timers.delete(re);
      resolve(msg as ControlResponse);
    }
  }

  get connected(): boolean {
    return this._connected;
  }

  /** Send an op and wait for its response. Rejects on timeout or disconnect. */
  async send(op: string, args: Record<string, unknown> = {}): Promise<ControlResponse> {
    if (!this._connected || !this._sendFn) {
      return { re: null, ok: false, detail: "bridge not connected" };
    }
    const req_id = nextReqId();
    const payload: Record<string, unknown> = { op, req_id, ...args };
    if (this._token) {
      payload.token = this._token;
    }
    return new Promise<ControlResponse>((resolve) => {
      this.pending.set(req_id, resolve);
      const timer = setTimeout(() => {
        this.pending.delete(req_id);
        this.timers.delete(req_id);
        resolve({ re: req_id, ok: false, detail: "request timed out" });
      }, RESPONSE_TIMEOUT_MS);
      this.timers.set(req_id, timer);
      this._sendFn!(JSON.stringify(payload));
    });
  }

  // ---- Convenience wrappers matching the bridge op schema ------------------

  async lockStatus(): Promise<ControlResponse> {
    return this.send("lock_status");
  }

  async sessionStart(map: string, force = false): Promise<ControlResponse> {
    return this.send("session_start", { map, ...(force ? { force: true } : {}) });
  }

  async sessionStop(force = false): Promise<ControlResponse> {
    return this.send("session_stop", ...(force ? [{ force: true }] : []));
  }

  async addBot(count = 1): Promise<ControlResponse> {
    return this.send("addbot", { count });
  }

  async removeBot(slot?: number | "all"): Promise<ControlResponse> {
    const args: Record<string, unknown> = {};
    if (slot !== undefined) args.slot = slot;
    return this.send("removebot", args);
  }

  /** set_cvar with optional per-slot expansion (_s<N>). */
  async setCvar(name: string, value: string, slot?: number): Promise<ControlResponse> {
    const args: Record<string, unknown> = { name, value };
    if (slot !== undefined) args.slot = slot;
    return this.send("set_cvar", args);
  }

  /** Raw console line. Supports @<N> shorthand prefix for per-slot. */
  async console(line: string): Promise<ControlResponse> {
    // @<slot> <cvar> <value>  ->  set_cvar with slot
    const atMatch = line.match(/^@(\d+)\s+(\S+)\s*(.*)/);
    if (atMatch) {
      const slot = parseInt(atMatch[1], 10);
      const name = atMatch[2];
      const value = atMatch[3].trim();
      return this.setCvar(name, value, slot);
    }
    return this.send("console", { line });
  }
}
