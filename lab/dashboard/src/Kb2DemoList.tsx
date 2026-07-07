// Demo List — every successful gapjump from the lab feed
// (komodobots.kb2_matches.v1 jumps[]), with a ▶ watch deep link into the hub
// demo player (5 s pre-roll before the landing). Filterable by lane and
// player. KomodoBots design language.

import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { FeatureChip } from "./Kb2ListView.tsx";
import { TeamTag } from "./FourVFourEvidence.tsx";
import { fmtUtc, useKb2Feed } from "./kb2Feed.ts";

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

function fmtClock(t_s: number): string {
  const m = Math.floor(t_s / 60);
  const s = t_s % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function Kb2DemoList() {
  const feed = useKb2Feed();
  const [laneFilter, setLaneFilter] = useState<string | null>(null);
  const [playerFilter, setPlayerFilter] = useState<string | null>(null);
  const [watchableOnly, setWatchableOnly] = useState(false);

  const jumps = feed?.jumps ?? [];
  const startedByRun = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const m of feed?.matches ?? []) map.set(m.run_id, m.started_utc);
    return map;
  }, [feed]);

  const lanes = useMemo(
    () => [...new Set(jumps.map((j) => j.lane))].sort(),
    [jumps],
  );
  const players = useMemo(
    () => [...new Set(jumps.map((j) => j.name).filter(Boolean) as string[])].sort(),
    [jumps],
  );

  const filtered = useMemo(
    () =>
      jumps.filter((j) => {
        if (laneFilter && j.lane !== laneFilter) return false;
        if (playerFilter && j.name !== playerFilter) return false;
        if (watchableOnly && !j.watch_url) return false;
        return true;
      }),
    [jumps, laneFilter, playerFilter, watchableOnly],
  );

  if (!feed) {
    return (
      <div data-kb2-demos-state="loading" style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>
        loading jump list… (kb2-matches.json)
      </div>
    );
  }

  const thStyle: CSSProperties = {
    ...mono,
    fontSize: "var(--t-2xs)",
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    textAlign: "left",
    padding: "6px 10px",
    borderBottom: "1px solid var(--border-strong)",
    position: "sticky",
    top: 0,
    background: "var(--surface-raised)",
  };
  const tdStyle: CSSProperties = {
    padding: "6px 10px",
    borderBottom: "1px solid var(--border-line)",
    verticalAlign: "middle",
  };

  // Per-lane attempt accounting (feed jump_lanes, v2) so the list reads as
  // "how many attempts did this jump take" — chips show lands/attempts.
  const laneAgg = feed.jump_lanes ?? {};

  return (
    <div data-kb2-demos style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {Object.keys(laneAgg).length > 0 && (
        <div data-kb2-demos-lanes style={{ ...panelStyle, display: "flex", gap: "var(--sp-7)", flexWrap: "wrap" }}>
          {Object.entries(laneAgg)
            .sort((a, b) => b[1].attempts - a[1].attempts)
            .map(([lane, a]) => (
              <div key={lane} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontFamily: "var(--font-display)", fontSize: "var(--t-h3)", fontWeight: 700, color: "var(--text-strong)" }}>
                  {lane}
                </span>
                <span style={{ ...mono, fontSize: "var(--t-xs)" }} title={`${a.lands} landed of ${a.attempts} launched attempts (${a.declines} approaches declined) across ${a.matches} matches`}>
                  <b style={{ color: a.land_rate != null && a.land_rate >= 0.5 ? "var(--pos-500)" : "var(--text-strong)" }}>{a.lands}</b>
                  <span style={{ color: "var(--text-muted)" }}>/{a.attempts} attempts</span>
                  {a.land_rate != null && (
                    <b style={{ marginLeft: 6, color: a.land_rate >= 0.5 ? "var(--pos-500)" : "var(--flat-500)" }}>
                      {Math.round(a.land_rate * 100)}%
                    </b>
                  )}
                </span>
              </div>
            ))}
        </div>
      )}
      <div style={{ ...panelStyle, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          lane
        </span>
        {lanes.map((l) => (
          <FeatureChip key={l} tag={l} selected={laneFilter === l} onClick={() => setLaneFilter(laneFilter === l ? null : l)} />
        ))}
        <span style={{ width: 12 }} />
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          player
        </span>
        {players.map((p) => (
          <FeatureChip key={p} tag={p} selected={playerFilter === p} onClick={() => setPlayerFilter(playerFilter === p ? null : p)} />
        ))}
        <FeatureChip tag="watchable" selected={watchableOnly} onClick={() => setWatchableOnly(!watchableOnly)} />
        <span style={{ flex: 1 }} />
        <span data-kb2-demos-count style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
          {filtered.length} / {jumps.length} landed jumps
        </span>
      </div>

      <div style={{ ...panelStyle, padding: 0, overflowX: "auto", maxHeight: "72vh", overflowY: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              {["run", "match clock", "lane", "player", "team", "hdist", "peak speed", "air", "watch"].map((h) => (
                <th key={h} style={thStyle}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((j, i) => (
              <tr key={`${j.run_id}-${j.t_s}-${i}`} data-kb2-jump={`${j.run_id}@${j.t_s}`}>
                <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                  {fmtUtc(startedByRun.get(j.run_id) ?? null)} · {j.map}
                </td>
                <td style={{ ...tdStyle, ...mono, fontWeight: 700, color: "var(--text-strong)" }}>{fmtClock(j.t_s)}</td>
                <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-xs)" }}>{j.lane}</td>
                <td style={{ ...tdStyle, color: "var(--text-body)" }}>{j.name ?? "—"}</td>
                <td style={tdStyle}>{j.team && <TeamTag team="leap" label={j.team} size="sm" outline />}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: "right" }}>{j.hdist}</td>
                <td style={{ ...tdStyle, ...mono, textAlign: "right", color: "var(--text-strong)" }}>{j.peak_speed} ups</td>
                <td style={{ ...tdStyle, ...mono, textAlign: "right" }}>{j.tair.toFixed(2)}s</td>
                <td style={tdStyle}>
                  {j.watch_url ? (
                    <a
                      href={j.watch_url}
                      target="_blank"
                      rel="noopener"
                      style={{ ...mono, fontSize: "var(--t-xs)", color: "var(--accent)", textDecoration: "none", fontWeight: 700 }}
                    >
                      ▶ watch
                    </a>
                  ) : (
                    <span title="demo not published on the hub" style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
                      no demo
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} style={{ ...mono, padding: 20, color: "var(--text-muted)", textAlign: "center" }}>
                  no landed jumps for this filter
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
