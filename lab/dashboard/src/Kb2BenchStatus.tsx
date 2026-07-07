// Bench Status — the hub view for what is running on the bench RIGHT NOW.
// Reads /v2/servers/bench (written by the local-hub poller when the lanister
// bench servers answer the QW status probe). Each live match is a card; SPEC
// opens the FTE-WASM QTV pane (public/panes/qtv.html) inline, attached to
// that match's QTV stream through the hub relay. KomodoBots design language.

import { useState } from "react";
import type { CSSProperties } from "react";
import { Badge, TeamTag } from "./FourVFourEvidence.tsx";
import { benchIsLive, useBenchServers } from "./kb2Feed.ts";
import type { BenchServer } from "./kb2Feed.ts";

const mono: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
};

const panelStyle: CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--r-3)",
  padding: "14px 16px",
};

function fmtRemaining(time?: BenchServer["time"]): string | null {
  const r = time?.remaining;
  if (r == null || !Number.isFinite(r)) return null;
  const m = Math.floor(r / 60);
  const s = Math.round(r % 60);
  return `${m}:${s.toString().padStart(2, "0")} left`;
}

// qtv.html attaches via ?port= against upstream host 127.0.0.1 by default;
// an explicit upstream (host:port on the lab LAN) is passed via ?upstream=.
function spectateSrc(s: BenchServer): string {
  const [host, port] = s.address.split(":");
  const params = new URLSearchParams();
  params.set("port", port ?? "28599");
  if (s.map) params.set("map", s.map);
  if (s.qtv_upstream) params.set("upstream", s.qtv_upstream);
  else params.set("upstream", `tcp:${host}:${port}`);
  return `/botlab/panes/qtv.html?${params.toString()}`;
}

function ServerCard({
  s,
  active,
  onSpectate,
}: {
  s: BenchServer;
  active: boolean;
  onSpectate: () => void;
}) {
  const live = (s.players?.length ?? 0) > 0;
  const teams = Object.entries(s.team_frags ?? {});
  const remaining = fmtRemaining(s.time);
  return (
    <div
      data-kb2-bench-server={s.address}
      style={{
        ...panelStyle,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        borderColor: active ? "var(--brand)" : "var(--border-line)",
        minWidth: 260,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h3)", color: "var(--text-strong)" }}>
          {s.hostname ?? s.address}
        </span>
        <span style={{ flex: 1 }} />
        {live ? <Badge live>LIVE</Badge> : <Badge tone="neutral">idle</Badge>}
      </div>
      <div style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", display: "flex", gap: 14, flexWrap: "wrap" }}>
        <span>
          map <b style={{ color: "var(--text-body)" }}>{s.map ?? "—"}</b>
        </span>
        <span>{s.address}</span>
        {s.status && <span>{s.status}</span>}
        {remaining && <span style={{ color: "var(--amber-300)" }}>{remaining}</span>}
      </div>
      {teams.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {teams.map(([team, frags], idx) => (
            <span key={team} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {idx > 0 && <span style={{ ...mono, color: "var(--text-muted)" }}>vs</span>}
              <TeamTag team={idx === 0 ? "leap" : "frog"} label={team} size="sm" />
              <span style={{ ...mono, fontWeight: 700, fontSize: "var(--t-h3)", color: "var(--text-strong)" }}>{frags}</span>
            </span>
          ))}
        </div>
      )}
      {live && (
        <div style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-body)", display: "flex", gap: 6, flexWrap: "wrap" }}>
          {s.players.map((p) => (
            <span key={p.name} style={{ padding: "2px 6px", background: "var(--surface-inset)", borderRadius: "var(--r-1)", border: "1px solid var(--border-line)" }}>
              {p.name}
              {p.frags != null && <b style={{ color: "var(--text-strong)", marginLeft: 4 }}>{p.frags}</b>}
            </span>
          ))}
        </div>
      )}
      <div>
        <button
          data-kb2-spectate={s.address}
          onClick={onSpectate}
          disabled={!live}
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 700,
            fontSize: "var(--t-sm)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            padding: "7px 16px",
            borderRadius: "var(--r-2)",
            cursor: live ? "pointer" : "not-allowed",
            background: active ? "var(--brand)" : live ? "var(--komodo-700)" : "var(--surface-inset)",
            color: live ? "var(--paper-100)" : "var(--text-muted)",
            border: `1px solid ${live ? "var(--komodo-500)" : "var(--border-line)"}`,
          }}
        >
          {active ? "▶ spectating" : "▶ spectate live"}
        </button>
      </div>
    </div>
  );
}

export function Kb2BenchStatus() {
  const servers = useBenchServers();
  const [spectating, setSpectating] = useState<BenchServer | null>(null);
  const anyLive = benchIsLive(servers);

  return (
    <div data-kb2-bench style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ ...panelStyle, display: "flex", alignItems: "center", gap: 12 }}>
        {anyLive ? (
          <Badge live>BENCH RUNNING</Badge>
        ) : (
          <Badge tone="neutral" dot>
            BENCH IDLE
          </Badge>
        )}
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
          {servers.length === 0
            ? "no bench servers reachable — feed /v2/servers/bench is empty or not deployed"
            : `${servers.filter((s) => (s.players?.length ?? 0) > 0).length} live / ${servers.length} bench server(s) · lanister`}
        </span>
      </div>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        {servers.map((s) => (
          <ServerCard
            key={s.address}
            s={s}
            active={spectating?.address === s.address}
            onSpectate={() => setSpectating(spectating?.address === s.address ? null : s)}
          />
        ))}
      </div>

      {spectating && (
        <div data-kb2-bench-viewer style={{ ...panelStyle, padding: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 8px 8px" }}>
            <Badge live>SPECTATING {spectating.address}</Badge>
            <span style={{ flex: 1 }} />
            <button
              onClick={() => setSpectating(null)}
              style={{ ...mono, fontSize: "var(--t-2xs)", background: "transparent", border: "1px solid var(--border-line)", borderRadius: "var(--r-1)", color: "var(--text-muted)", padding: "3px 10px", cursor: "pointer" }}
            >
              close
            </button>
          </div>
          <iframe
            title={`bench spectate ${spectating.address}`}
            src={spectateSrc(spectating)}
            style={{ width: "100%", aspectRatio: "16 / 9", border: "none", borderRadius: "var(--r-2)", background: "#000" }}
            allow="autoplay; fullscreen"
          />
        </div>
      )}
    </div>
  );
}
