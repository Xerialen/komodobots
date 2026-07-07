// Version History — every merge to main, in owner language: what it was
// meant to do (no jargon), what it did to the frag margin, and how many
// matches it has played (counted bench + scratch/test). Reads
// komodobots.kb2_versions.v1 (/demos/records/kb2-versions.json, built by
// lab/server/version_history_build.py). KomodoBots design language.

import type { CSSProperties } from "react";
import { Badge } from "./FourVFourEvidence.tsx";
import { useKb2Versions } from "./kb2Feed.ts";

const mono: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
};

const panelStyle: CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--r-3)",
  padding: "16px 18px",
};

function marginColor(margin: number | null): string {
  if (margin == null) return "var(--text-muted)";
  if (margin > 0) return "var(--pos-500)";
  if (margin < 0) return "var(--neg-500)";
  return "var(--flat-500)";
}

export function Kb2VersionHistory() {
  const feed = useKb2Versions();

  if (!feed) {
    return (
      <div data-kb2-versions-state="loading" style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>
        loading version history… (kb2-versions.json)
      </div>
    );
  }

  const versions = [...feed.versions].sort((a, b) => (b.merged_at || "").localeCompare(a.merged_at || ""));

  return (
    <div data-kb2-versions style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
        {versions.length} merge(s) to main · {feed.repo} · margins from the counted bench ledger
      </div>
      {versions.map((v) => (
        <div key={`${v.pr}-${v.merged_at}`} data-kb2-version={v.pr ?? v.name} style={{ ...panelStyle, display: "flex", gap: "var(--sp-7)", alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 380px", display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h2)", color: "var(--text-strong)" }}>
                {v.name}
              </span>
              <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
                {v.merged_at?.slice(0, 10)}
                {v.pr != null && ` · PR #${v.pr}`}
              </span>
            </div>
            <p style={{ margin: 0, color: "var(--text-body)", fontSize: "var(--t-sm)", lineHeight: 1.5, maxWidth: 640 }}>{v.summary}</p>
            {v.stamps.length > 0 && (
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {v.stamps.map((s) => (
                  <span key={s} style={{ ...mono, fontSize: "var(--t-2xs)", padding: "2px 6px", background: "var(--surface-inset)", border: "1px solid var(--border-line)", borderRadius: "var(--r-1)", color: "var(--text-muted)" }}>
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: "var(--sp-7)", alignItems: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
              <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)", textTransform: "uppercase" }}>frag margin</span>
              <span style={{ ...mono, fontWeight: 700, fontSize: "var(--t-stat-lg, 28px)", color: marginColor(v.bench?.margin_mean ?? null) }}>
                {v.bench?.margin_mean == null ? "—" : `${v.bench.margin_mean > 0 ? "+" : ""}${v.bench.margin_mean}`}
              </span>
              {v.bench && (
                <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
                  {v.bench.wins}W {v.bench.losses}L
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
              <Badge tone="komodo">{v.bench?.games ?? 0} counted</Badge>
              <Badge tone="neutral">{v.test_matches} test</Badge>
            </div>
          </div>
        </div>
      ))}
      {versions.length === 0 && (
        <div style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>no merges recorded yet</div>
      )}
    </div>
  );
}
