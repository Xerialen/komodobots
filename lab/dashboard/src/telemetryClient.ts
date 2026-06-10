// Client for the komodobots lab telemetry sidecar (scripts/telemetry_ws.py).
// One JSON message per websocket text frame; see the sidecar docstring for the
// protocol. Frame rate is the server command rate (~100 Hz), so consumers that
// render with React state must throttle — subscribe with raw callbacks here.

export type Vec3 = { x: number; y: number; z: number };

export type TelemetryFrame = {
  type: "frame";
  run_id: string;
  t: number;
  ed: number;
  name: string;
  origin: Vec3;
  vel: Vec3;
  vh: number;
  yaw: number;
  pitch: number;
  move: { fwd: number; side: number; up: number };
  buttons: number;
  onground: 0 | 1;
  dir_speed: number | null;
  dist_to_rl: number | null;
};

export type TelemetryAttempt = {
  run_id: string | null;
  port: number | null;
  map: string | null;
};

type TelemetryMessage =
  | TelemetryFrame
  | ({ type: "hello"; live: boolean } & TelemetryAttempt)
  | ({ type: "new_attempt" } & TelemetryAttempt)
  | { type: "status"; live: boolean };

const RECONNECT_DELAY_MS = 2000;

export class TelemetryClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private closed = false;

  readonly url: string;
  frameListeners = new Set<(frame: TelemetryFrame) => void>();
  attemptListeners = new Set<(attempt: TelemetryAttempt) => void>();
  stateListeners = new Set<(state: { connected: boolean; live: boolean }) => void>();

  private connected = false;
  private live = false;

  constructor(url: string) {
    this.url = url;
    this.connect();
  }

  private connect() {
    if (this.closed) {
      return;
    }
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch {
      // malformed ?ws= URL — the constructor throws; retrying won't fix it
      this.connected = false;
      this.live = false;
      this.emitState();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.connected = true;
      this.emitState();
    };
    socket.onmessage = (event) => {
      let message: TelemetryMessage;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "frame") {
        if (!this.live) {
          this.live = true;
          this.emitState();
        }
        for (const listener of this.frameListeners) {
          listener(message);
        }
      } else if (message.type === "new_attempt") {
        this.live = true;
        this.emitState();
        for (const listener of this.attemptListeners) {
          listener(message);
        }
      } else if (message.type === "hello") {
        this.live = message.live;
        this.emitState();
        if (message.run_id) {
          for (const listener of this.attemptListeners) {
            listener(message);
          }
        }
      } else if (message.type === "status") {
        if (this.live !== message.live) {
          this.live = message.live;
          this.emitState();
        }
      }
    };
    socket.onclose = () => {
      this.connected = false;
      this.live = false;
      this.emitState();
      this.scheduleReconnect();
    };
    socket.onerror = () => {
      socket.close();
    };
  }

  private scheduleReconnect() {
    if (this.closed || this.reconnectTimer !== null) {
      return;
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY_MS);
  }

  private emitState() {
    for (const listener of this.stateListeners) {
      listener({ connected: this.connected, live: this.live });
    }
  }

  close() {
    this.closed = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.frameListeners.clear();
    this.attemptListeners.clear();
    this.stateListeners.clear();
  }
}
