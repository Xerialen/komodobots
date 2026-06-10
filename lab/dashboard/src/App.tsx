import { useEffect, useMemo, useState } from "react";
import { BotLab3D } from "./BotLab3D.tsx";
import { TelemetryHud } from "./TelemetryHud.tsx";
import { type TelemetryAttempt, TelemetryClient } from "./telemetryClient.ts";

// v1 defaults: dm3 lab on servexeri (LAN). Override per-instance with
// ?port=28600&ws=ws://localhost:8770&game=http://... (e.g. through ssh -L
// tunnels).
//
// LD-A1 absorption note: the original local-hub page rendered the live game
// panel with the hub fork's FteQtvPlayer (@qwhub/*) and drove qtvplay/retry
// itself. That dependency is gone — the panel temporarily embeds the deployed
// /qtv/ page in an iframe; the proper standalone same-origin postMessage QTV
// pane lands in LD-B2 (#88).
const DEFAULT_LAB_PORT = 28599;
const DEFAULT_TELEMETRY_WS = "ws://192.168.86.33:8770";
const DEFAULT_GAME_VIEW_URL = "http://192.168.86.33:8095/qtv/";

function getParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

export function App() {
  const wsUrl = useMemo(() => getParam("ws") ?? DEFAULT_TELEMETRY_WS, []);
  const gameViewUrl = useMemo(
    () => getParam("game") ?? DEFAULT_GAME_VIEW_URL,
    [],
  );
  const fallbackPort = useMemo(() => {
    const port = Number(getParam("port"));
    return Number.isInteger(port) && port > 0 ? port : DEFAULT_LAB_PORT;
  }, []);

  const [client, setClient] = useState<TelemetryClient | null>(null);
  const [attempt, setAttempt] = useState<TelemetryAttempt | null>(null);
  const [connection, setConnection] = useState({ connected: false, live: false });
  const [showReference, setShowReference] = useState(true);

  useEffect(() => {
    const telemetry = new TelemetryClient(wsUrl);
    telemetry.attemptListeners.add(setAttempt);
    telemetry.stateListeners.add(setConnection);
    setClient(telemetry);
    return () => {
      telemetry.close();
      setClient(null);
    };
  }, [wsUrl]);

  const labPort = attempt?.port ?? fallbackPort;
  const runId = attempt?.run_id ?? null;
  const mapName = attempt?.map ?? "dm3";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex items-center gap-x-4 px-4 py-2 text-sm border-b border-slate-800">
        <span className="font-bold">bot lab</span>
        <span className="font-mono text-gray-400">
          {mapName} · port {labPort} · {runId ?? "no attempt yet"}
        </span>
        <span
          className={
            connection.live
              ? "text-green-400"
              : connection.connected
                ? "text-amber-400"
                : "text-red-400"
          }
        >
          {connection.live
            ? "live"
            : connection.connected
              ? "waiting for attempt"
              : "telemetry disconnected"}
        </span>
        <label className="ml-auto flex items-center gap-x-2 text-gray-400">
          <input
            type="checkbox"
            checked={showReference}
            onChange={(event) => setShowReference(event.target.checked)}
          />
          human path
        </label>
      </header>

      <div className="grow grid grid-cols-1 xl:grid-cols-2">
        <div className="relative min-h-[50vh]">
          {client && (
            <BotLab3D
              client={client}
              mapName={mapName}
              referencePathUrl={
                mapName === "dm3" ? "/botlab/dm3_sng_to_rl.cmds" : null
              }
              showReferencePath={showReference}
            />
          )}
          {!connection.live && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60 pointer-events-none">
              <span className="animate-pulse text-gray-400">
                {connection.connected
                  ? "waiting for attempt…"
                  : `connecting to ${wsUrl}…`}
              </span>
            </div>
          )}
          <div className="absolute bottom-0 inset-x-0">
            {client && <TelemetryHud client={client} />}
          </div>
        </div>

        <div className="min-h-[50vh]">
          <iframe
            src={gameViewUrl}
            title="live game view"
            className="block w-full h-full min-h-[50vh] border-0"
          />
        </div>
      </div>
    </div>
  );
}

export default App;
