// List View — every recent lab match from the komodobots2 feed
// (komodobots.kb2_matches.v2): when it ran, game duration, per-team frags,
// frag margin, winner, the feature configuration it ran with (filterable) and
// which configuration holds the record. KomodoBots design language (same
// tokens/components as the evidence Match View).

import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Badge, TeamTag } from "./FourVFourEvidence.tsx";
import {
  fmtDuration,
  fmtMargin,
  fmtUtc,
  useKb2Feed,
} from "./kb2Feed.ts";
import type { Kb2Aggregate, Kb2Feed, Kb2Match } from "./kb2Feed.ts";

function fmtOrDash(v: number | null | undefined): string {
  return v == null ? "—" : `${v}`;
}

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

function marginColor(margin: number | null): string {
  if (margin == null) return "var(--text-muted)";
  if (margin > 0) return "var(--pos-500)";
  if (margin < 0) return "var(--neg-500)";
  return "var(--flat-500)";
}

// A feature-filter chip. Selected = brand-filled, unselected = outline.
export function FeatureChip({
  tag,
  count,
  selected,
  isRecord,
  onClick,
}: {
  tag: string;
  count?: number;
  selected?: boolean;
  isRecord?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      data-kb2-chip={tag}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-mono)",
        fontSize: "var(--t-2xs)",
        fontWeight: 700,
        letterSpacing: "var(--ls-label)",
        textTransform: "uppercase",
        padding: "4px 9px",
        borderRadius: "var(--r-2)",
        cursor: onClick ? "pointer" : "default",
        whiteSpace: "nowrap",
        background: selected ? "var(--komodo-700)" : "var(--surface-inset)",
        color: selected ? "var(--paper-100)" : "var(--text-body)",
        border: `1px solid ${selected ? "var(--komodo-500)" : "var(--border-line)"}`,
      }}
    >
      {isRecord && <span title="record holder">🏆</span>}
      {tag}
      {count != null && (
        <span style={{ color: selected ? "var(--komodo-300)" : "var(--text-muted)" }}>{count}</span>
      )}
    </button>
  );
}

// Jump-lane progress strip: per built jump (lane), attempts vs lands across
// all included matches (owner requirement 2026-07-07: track jump success
// over time). land_rate colors green as it climbs.
function rateColor(rate: number | null): string {
  if (rate == null) return "var(--text-muted)";
  if (rate >= 0.5) return "var(--pos-500)";
  if (rate >= 0.2) return "var(--flat-500)";
  return "var(--neg-500)";
}

function JumpLanes({ feed }: { feed: Kb2Feed }) {
  const lanes = Object.entries(feed.jump_lanes ?? {}).sort(
    (a, b) => b[1].attempts - a[1].attempts,
  );
  if (lanes.length === 0) return null;
  return (
    <div data-kb2-jumplanes style={{ ...panelStyle, display: "flex", gap: "var(--sp-7)", flexWrap: "wrap" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, justifyContent: "center" }}>
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          jump lanes
        </span>
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
          landed / attempts
        </span>
      </div>
      {lanes.map(([lane, a]) => (
        <div key={lane} data-kb2-lane={lane} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "var(--font-display)", fontSize: "var(--t-h3)", fontWeight: 700, color: "var(--text-strong)" }}>
            {lane}
          </span>
          <span style={{ ...mono, fontSize: "var(--t-xs)" }}>
            <b style={{ color: rateColor(a.land_rate) }}>{a.lands}</b>
            <span style={{ color: "var(--text-muted)" }}>/{a.attempts}</span>
            {a.land_rate != null && (
              <b style={{ color: rateColor(a.land_rate), marginLeft: 6 }}>
                {Math.round(a.land_rate * 100)}%
              </b>
            )}
          </span>
          <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
            {a.declines} declined · {a.matches} matches
          </span>
        </div>
      ))}
    </div>
  );
}

// Record-holder strip: the best-performing feature tag and config stamp
// (mean frag margin, min 3 matches) + the counted-ledger leader.
function RecordHolders({ feed }: { feed: Kb2Feed }) {
  const rows: Array<{ label: string; key: string; agg: Kb2Aggregate }> = [];
  const rhF = feed.record_holder.feature;
  const rhC = feed.record_holder.config;
  if (rhF) rows.push({ label: "Best feature", key: rhF.key, agg: rhF });
  if (rhC) rows.push({ label: "Best config", key: rhC.key, agg: rhC });
  if (rows.length === 0) return null;
  return (
    <div data-kb2-recordholder style={{ ...panelStyle, display: "flex", gap: "var(--sp-7)", flexWrap: "wrap" }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
            🏆 {r.label}
          </span>
          <span style={{ fontFamily: "var(--font-display)", fontSize: "var(--t-h2)", fontWeight: 700, color: "var(--text-strong)" }}>
            {r.key}
          </span>
          <span style={{ ...mono, fontSize: "var(--t-xs)", color: marginColor(r.agg.margin_mean) }}>
            {r.agg.margin_mean != null && r.agg.margin_mean > 0 ? "+" : ""}
            {r.agg.margin_mean} avg margin · {r.agg.wins}W {r.agg.losses}L {r.agg.draws}D · {r.agg.matches} matches
          </span>
        </div>
      ))}
    </div>
  );
}

function MatchRow({
  m,
  expanded,
  onToggle,
  onOpen,
}: {
  m: Kb2Match;
  expanded: boolean;
  onToggle: () => void;
  onOpen?: () => void;
}) {
  const candTeam = m.candidate.team ?? "?";
  const ctrlTeam = m.control.team ?? "?";
  const candFrags = m.team_frags[candTeam] ?? null;
  const ctrlFrags = m.team_frags[ctrlTeam] ?? null;
  const winnerSquad = m.winner === candTeam ? "leap" : m.winner === ctrlTeam ? "frog" : null;
  const tdStyle: CSSProperties = { padding: "7px 10px", borderBottom: "1px solid var(--border-line)", verticalAlign: "middle" };
  const jumps = m.jumps ?? null;
  return (
    <>
      <tr
        data-kb2-run={m.run_id}
        onClick={onOpen ?? onToggle}
        title={onOpen ? "open in Match View" : undefined}
        style={{ cursor: "pointer", background: expanded ? "var(--surface-inset)" : "transparent" }}
      >
        <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>
          <button
            data-kb2-expand={m.run_id}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            title={expanded ? "hide details" : "show cvars + player stats"}
            style={{
              ...mono,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "var(--text-muted)",
              fontSize: "var(--t-xs)",
              padding: "0 2px",
            }}
          >
            {expanded ? "▾" : "▸"}
          </button>
        </td>
        <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-xs)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
          {fmtUtc(m.started_utc)}
        </td>
        <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-xs)" }}>{m.map}</td>
        <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-xs)" }}>{fmtDuration(m.duration_s)}</td>
        <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <TeamTag team="leap" label={candTeam} size="sm" outline={m.winner !== candTeam} />
            <span style={{ ...mono, fontWeight: 700, color: "var(--text-strong)" }}>
              {candFrags ?? "—"}–{ctrlFrags ?? "—"}
            </span>
            <TeamTag team="frog" label={ctrlTeam} size="sm" outline={m.winner !== ctrlTeam} />
          </span>
        </td>
        <td style={{ ...tdStyle, ...mono, fontWeight: 700, color: marginColor(m.frag_margin), textAlign: "right" }}>
          {fmtMargin(m.frag_margin)}
        </td>
        <td style={tdStyle}>
          {winnerSquad ? (
            <TeamTag team={winnerSquad} label={m.winner ?? ""} size="sm" />
          ) : (
            <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
              {m.winner === "draw" ? "DRAW" : "—"}
            </span>
          )}
        </td>
        <td style={{ ...tdStyle, maxWidth: 260 }}>
          <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
            {m.features.map((f) => (
              <FeatureChip key={f} tag={f} />
            ))}
          </span>
        </td>
        <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", maxWidth: 190, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {m.candidate.version}
        </td>
        <td style={{ ...tdStyle, ...mono, fontSize: "var(--t-xs)", textAlign: "right", whiteSpace: "nowrap" }}>
          {jumps && jumps.attempts > 0 ? (
            <span title={`${jumps.lands} landed of ${jumps.attempts} attempts (${jumps.fails} failed, ${jumps.declines} declined)`}>
              <b style={{ color: jumps.lands > 0 ? "var(--pos-500)" : "var(--text-muted)" }}>{jumps.lands}</b>
              <span style={{ color: "var(--text-muted)" }}>/{jumps.attempts}</span>
            </span>
          ) : (
            <span style={{ color: "var(--text-muted)" }}>—</span>
          )}
        </td>
        <td style={tdStyle}>
          {m.in_ledger ? <Badge tone="komodo">counted</Badge> : <Badge tone="neutral">scratch</Badge>}
        </td>
        <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>
          {m.demo.url && (
            <a
              href={`/demo-player/?demoUrl=${encodeURIComponent(m.demo.url)}&map=${m.map}${m.duration_s ? `&duration=${m.duration_s}` : ""}`}
              target="_blank"
              rel="noopener"
              onClick={(e) => e.stopPropagation()}
              style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--accent)", textDecoration: "none" }}
            >
              ▶ demo
            </a>
          )}
          {m.demo.url && (
            <a
              href={`/mvd/?demoUrl=${encodeURIComponent(m.demo.url)}`}
              target="_blank"
              rel="noopener"
              onClick={(e) => e.stopPropagation()}
              style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--accent)", textDecoration: "none", marginLeft: 10 }}
            >
              ⊞ analyze
            </a>
          )}
        </td>
      </tr>
      {expanded && (
        <tr data-kb2-run-detail={m.run_id}>
          <td colSpan={12} style={{ padding: "10px 14px", background: "var(--surface-inset)", borderBottom: "1px solid var(--border-line)" }}>
            <div style={{ display: "flex", gap: "var(--sp-7)", flexWrap: "wrap", alignItems: "flex-start" }}>
              <div>
                <div style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 6 }}>
                  cvars
                </div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap", maxWidth: 460 }}>
                  {Object.entries(m.cvars).length === 0 && (
                    <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>none (stock)</span>
                  )}
                  {Object.entries(m.cvars).map(([k, v]) => (
                    <span key={k} style={{ ...mono, fontSize: "var(--t-2xs)", padding: "2px 6px", background: "var(--surface-raised)", border: "1px solid var(--border-line)", borderRadius: "var(--r-1)" }}>
                      {k}=<b style={{ color: "var(--text-strong)" }}>{v}</b>
                    </span>
                  ))}
                </div>
              </div>
              {m.players.length > 0 && (
                <table style={{ borderCollapse: "collapse", fontSize: "var(--t-xs)" }}>
                  <thead>
                    <tr>
                      {[
                        "player", "team", "frags", "deaths", "dmg+", "dmg−",
                        "quad", "pent", "ring", "rl", "lg", "rl dir", "to-die",
                      ].map((h) => (
                        <th key={h} title={{
                          quad: "quad pickups", pent: "pent pickups", ring: "ring pickups",
                          rl: "RL pickups", lg: "LG pickups",
                          "rl dir": "direct rocket hits / rockets fired",
                          "to-die": "avg damage taken to die",
                        }[h] ?? h}
                          style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", padding: "2px 8px", textAlign: "left" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...m.players]
                      .sort((a, b) => b.frags - a.frags)
                      .map((p, pi) => (
                        <tr key={`${p.name}-${pi}`}>
                          <td style={{ padding: "2px 8px", color: "var(--text-body)" }}>{p.name}</td>
                          <td style={{ padding: "2px 8px" }}>
                            <TeamTag team={p.team === m.candidate.team ? "leap" : "frog"} label={p.team} size="sm" outline />
                          </td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right", color: "var(--text-strong)" }}>{p.frags}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{p.deaths}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{p.dmg_given}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{p.dmg_taken}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right", color: (p.quad ?? 0) > 0 ? "var(--text-strong)" : undefined }}>{fmtOrDash(p.quad)}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right", color: (p.pent ?? 0) > 0 ? "var(--text-strong)" : undefined }}>{fmtOrDash(p.pent)}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right", color: (p.ring ?? 0) > 0 ? "var(--text-strong)" : undefined }}>{fmtOrDash(p.ring)}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{fmtOrDash(p.rl_pickups)}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{fmtOrDash(p.lg_pickups)}</td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>
                            {p.rl_direct_hits == null ? "—" : `${p.rl_direct_hits}/${p.rl_attacks ?? "?"}`}
                          </td>
                          <td style={{ ...mono, padding: "2px 8px", textAlign: "right" }}>{fmtOrDash(p.taken_to_die)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function Kb2ListView({ onOpenMatch }: { onOpenMatch?: (runId: string) => void }) {
  const feed = useKb2Feed();
  const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());
  const [mapFilter, setMapFilter] = useState<string | null>(null);
  const [countedOnly, setCountedOnly] = useState(false);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const matches = feed?.matches ?? [];
  const maps = useMemo(() => [...new Set(matches.map((m) => m.map))].sort(), [matches]);

  const filtered = useMemo(
    () =>
      matches.filter((m) => {
        if (countedOnly && !m.in_ledger) return false;
        if (mapFilter && m.map !== mapFilter) return false;
        for (const f of selectedFeatures) if (!m.features.includes(f)) return false;
        return true;
      }),
    [matches, selectedFeatures, mapFilter, countedOnly],
  );

  if (!feed) {
    return (
      <div data-kb2-list-state="loading" style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>
        loading match history… (kb2-matches.json)
      </div>
    );
  }

  const toggleFeature = (tag: string) => {
    setSelectedFeatures((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  const featureTags = Object.entries(feed.features).sort((a, b) => b[1].matches - a[1].matches);
  const recordFeature = feed.record_holder.feature?.key;
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

  return (
    <div data-kb2-list style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <RecordHolders feed={feed} />
      <JumpLanes feed={feed} />

      <div style={{ ...panelStyle, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          filter
        </span>
        {featureTags.map(([tag, agg]) => (
          <FeatureChip
            key={tag}
            tag={tag}
            count={agg.matches}
            selected={selectedFeatures.has(tag)}
            isRecord={tag === recordFeature}
            onClick={() => toggleFeature(tag)}
          />
        ))}
        <span style={{ width: 12 }} />
        {maps.length > 1 &&
          maps.map((mp) => (
            <FeatureChip key={mp} tag={mp} selected={mapFilter === mp} onClick={() => setMapFilter(mapFilter === mp ? null : mp)} />
          ))}
        <FeatureChip tag="counted only" selected={countedOnly} onClick={() => setCountedOnly(!countedOnly)} />
        <span style={{ flex: 1 }} />
        <span data-kb2-list-count style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
          {filtered.length} / {matches.length} matches
        </span>
      </div>

      <div style={{ ...panelStyle, padding: 0, overflowX: "auto", maxHeight: "68vh", overflowY: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              {["", "started", "map", "length", "score", "margin", "winner", "features", "version", "jumps", "ledger", "links"].map((h, i) => (
                <th key={h || `col-${i}`} title={h === "jumps" ? "gapjumps landed / attempted" : undefined} style={thStyle}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <MatchRow
                key={m.run_id}
                m={m}
                expanded={expandedRun === m.run_id}
                onToggle={() => setExpandedRun(expandedRun === m.run_id ? null : m.run_id)}
                onOpen={onOpenMatch ? () => onOpenMatch(m.run_id) : undefined}
              />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={12} style={{ ...mono, padding: 20, color: "var(--text-muted)", textAlign: "center" }}>
                  no matches for this filter
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
