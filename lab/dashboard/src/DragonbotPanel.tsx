// Dragonbot goals & metrics — issue #483. Reads dragonbot.hub_feed.v1
// (/demos/records/dragonbot-hub-feed.json, built by
// lab/server/dragonbot_hub_feed_build.py from Xerialen/dragonbot's committed
// artifacts/hub/goals-metrics.json). KomodoBots design language (same
// tokens/components as the other kb2 views).
//
// Three stacked panels per the ticket:
//   1. Goal ladder — G1 frag margin vs target (± band), G2 elite bands +
//      the outcome-confounded validity caveat rendered VERBATIM.
//   2. Metrics timeline — one row per batch-of-record: fragMargin, dmgDiff,
//      sg.accuracy (control_batch = a single stat; abba_experiment = ref vs
//      treatment + meanDelta/z), the ABBA decision badge.
//   3. Eval-loop panel — per batch with eval data: truth CLEAN/SUSPECT badge,
//      tactical C/D/I tally per lens, links to the EVAL-*.md reports on
//      GitHub.
//
// Every null/absent value renders as "—", never 0 — the upstream feed is
// explicit that missing stats (e.g. sg.accuracy before analyzer schema 57)
// are honest gaps, not zeroes.

import type { CSSProperties } from "react";
import { Badge } from "./FourVFourEvidence.tsx";
import {
  dragonbotGithubBlobHref,
  fmtDerived,
  fmtMatchCount,
  fmtStat,
  fmtStatN,
  isArmComparison,
  isSnapshotStale,
  useDragonbotFeed,
  type DragonbotBatch,
  type DragonbotBatchMetric,
  type DragonbotEval,
  type DragonbotGoal,
} from "./dragonbotFeed.ts";

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

const sectionTitleStyle: CSSProperties = {
  fontFamily: "var(--font-display)",
  fontWeight: 700,
  fontSize: "var(--t-h2)",
  color: "var(--text-strong)",
  letterSpacing: "var(--ls-display)",
  margin: 0,
};

const labelStyle: CSSProperties = {
  ...mono,
  fontSize: "var(--t-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

function StaleBanner({ reason }: { reason: string | null }) {
  return (
    <div
      data-dragonbot-stale-banner
      style={{
        ...mono,
        fontSize: "var(--t-xs)",
        color: "var(--amber-300)",
        background: "var(--amber-900)",
        border: "1px solid var(--amber-600)",
        borderRadius: "var(--r-2)",
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <span>⚠</span>
      <span>
        showing last-good snapshot — the dragonbot feed is currently unreachable or stale
        {reason ? ` (${reason})` : ""}
      </span>
    </div>
  );
}

// --- Goal ladder ---

function marginColor(mean: number | null | undefined): string {
  if (mean == null) return "var(--text-muted)";
  if (mean > 0) return "var(--pos-500)";
  if (mean < 0) return "var(--neg-500)";
  return "var(--flat-500)";
}

function GoalCard({ goal }: { goal: DragonbotGoal }) {
  const isG1 = goal.id === "G1";
  return (
    <div data-dragonbot-goal={goal.id} style={{ ...panelStyle, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <Badge tone="komodo">{goal.id}</Badge>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h3)", color: "var(--text-strong)" }}>
          {goal.title}
        </span>
      </div>

      {isG1 ? (
        <div style={{ display: "flex", gap: "var(--sp-8)", flexWrap: "wrap" }}>
          {Object.entries(goal.metrics).map(([key, stat]) => (
            <div key={key} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={labelStyle}>{key}</span>
              <span style={{ ...mono, fontWeight: 700, fontSize: "var(--t-stat-md)", color: marginColor(stat?.mean) }}>
                {fmtStat(stat)}
              </span>
              <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>{fmtStatN(stat)}</span>
            </div>
          ))}
          <div style={{ display: "flex", flexDirection: "column", gap: 2, justifyContent: "flex-end" }}>
            <span style={labelStyle}>target</span>
            <span style={{ ...mono, fontSize: "var(--t-sm)", color: "var(--text-body)" }}>
              frag margin &gt; 0 (win the match)
            </span>
          </div>
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "var(--t-xs)" }}>
            <thead>
              <tr>
                {["metric", "p25", "median", "p75", "n"].map((h) => (
                  <th key={h} style={{ ...labelStyle, textAlign: "left", padding: "2px 10px 4px 0" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(goal.metrics).map(([key, stat]) => (
                <tr key={key}>
                  <td style={{ padding: "2px 10px 2px 0", color: "var(--text-body)" }}>{key}</td>
                  <td style={{ ...mono, padding: "2px 10px 2px 0" }}>{stat?.p25 ?? "—"}</td>
                  <td style={{ ...mono, padding: "2px 10px 2px 0", fontWeight: 700, color: "var(--text-strong)" }}>{stat?.median ?? "—"}</td>
                  <td style={{ ...mono, padding: "2px 10px 2px 0" }}>{stat?.p75 ?? "—"}</td>
                  <td style={{ ...mono, padding: "2px 10px 2px 0", color: "var(--text-muted)" }}>{stat?.n ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {goal.validityCaveat && (
        <div
          data-dragonbot-validity-caveat
          style={{
            ...mono,
            fontSize: "var(--t-2xs)",
            color: "var(--amber-300)",
            background: "var(--amber-900)",
            border: "1px solid var(--amber-600)",
            borderRadius: "var(--r-2)",
            padding: "8px 10px",
            lineHeight: 1.5,
          }}
        >
          {/* Rendered verbatim from the feed — do not paraphrase (owner requirement). */}
          {goal.validityCaveat}
        </div>
      )}

      {goal.reference && (
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "var(--t-2xs)", lineHeight: 1.5 }}>{goal.reference}</p>
      )}
    </div>
  );
}

function GoalLadder({ goals }: { goals: DragonbotGoal[] }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h2 style={sectionTitleStyle}>Goal Ladder</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {goals.map((g) => (
          <GoalCard key={g.id} goal={g} />
        ))}
        {goals.length === 0 && <div style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>no goals in feed</div>}
      </div>
    </section>
  );
}

// --- Metrics timeline ---

function MetricCell({ metric }: { metric: DragonbotBatchMetric }) {
  if (!metric) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  if (isArmComparison(metric)) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ ...mono, fontSize: "var(--t-xs)" }}>
          <span style={{ color: "var(--text-muted)" }}>ref </span>
          {fmtStat(metric.reference)}
        </span>
        <span style={{ ...mono, fontSize: "var(--t-xs)" }}>
          <span style={{ color: "var(--text-muted)" }}>trt </span>
          {fmtStat(metric.treatment)}
        </span>
        {(metric.meanDelta || metric.z) && (
          <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
            {metric.meanDelta && `Δ ${fmtDerived(metric.meanDelta)}`}
            {metric.meanDelta && metric.z && " · "}
            {metric.z && `z ${fmtDerived(metric.z)}`}
          </span>
        )}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ ...mono, fontSize: "var(--t-sm)" }}>{fmtStat(metric)}</span>
      <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>{fmtStatN(metric)}</span>
    </div>
  );
}

function DecisionBadge({ batch }: { batch: DragonbotBatch }) {
  const decision = batch.decision;
  if (!decision) return <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>no ABBA decision</span>;
  const metric = batch.metrics[decision.metric];
  const z = isArmComparison(metric) ? metric.z : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
      <Badge tone={decision.passed ? "komodo" : "neg"}>{decision.passed ? "PASS" : "BLOCK"}</Badge>
      <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
        {decision.metric} {decision.direction === "higher_better" ? "↑" : decision.direction === "lower_better" ? "↓" : ""}
        {z && z.value != null && ` · z ${fmtDerived(z)}`}
      </span>
      {decision.reason && (
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>{decision.reason}</span>
      )}
    </div>
  );
}

function BatchRow({ batch }: { batch: DragonbotBatch }) {
  const metricKeys = ["fragMargin", "dmgDiff", "sg.accuracy"];
  return (
    <div data-dragonbot-batch={batch.batchId} style={{ ...panelStyle, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <Badge tone={batch.role === "control" ? "neutral" : "komodo"}>{batch.role}</Badge>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h3)", color: "var(--text-strong)" }}>
          {batch.title}
        </span>
        <span style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
          {batch.date} · {batch.kind} · {fmtMatchCount(batch.validMatches)} valid
          {batch.analyzerSchemaVersion != null ? ` · schema v${batch.analyzerSchemaVersion}` : " · schema —"}
        </span>
      </div>

      <div style={{ display: "flex", gap: "var(--sp-8)", flexWrap: "wrap" }}>
        {metricKeys.map((key) => (
          <div key={key} style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 120 }}>
            <span style={labelStyle}>{key}</span>
            <MetricCell metric={batch.metrics[key] ?? null} />
          </div>
        ))}
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 140 }}>
          <span style={labelStyle}>ABBA decision</span>
          <DecisionBadge batch={batch} />
        </div>
      </div>

      {batch.notes && batch.notes.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {batch.notes.map((n, i) => (
            <p key={i} style={{ margin: 0, color: "var(--text-muted)", fontSize: "var(--t-2xs)", lineHeight: 1.5 }}>
              {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricsTimeline({ batches }: { batches: DragonbotBatch[] }) {
  const ordered = [...batches].sort((a, b) => (b.date || "").localeCompare(a.date || "") || (b.batchId || "").localeCompare(a.batchId || ""));
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h2 style={sectionTitleStyle}>Metrics Timeline</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {ordered.map((b) => (
          <BatchRow key={b.batchId} batch={b} />
        ))}
        {ordered.length === 0 && <div style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>no batches in feed</div>}
      </div>
    </section>
  );
}

// --- Eval-loop panel ---

function TacticalTallyChips({ tally }: { tally: DragonbotEval["tacticalTally"] }) {
  return (
    <span style={{ display: "inline-flex", gap: 8 }}>
      <span style={{ ...mono, fontSize: "var(--t-xs)", color: "var(--pos-500)" }}>C {tally.compliant}</span>
      <span style={{ ...mono, fontSize: "var(--t-xs)", color: "var(--neg-500)" }}>D {tally.deviant}</span>
      <span style={{ ...mono, fontSize: "var(--t-xs)", color: "var(--text-muted)" }}>I {tally.inconclusive}</span>
    </span>
  );
}

function EvalBatchCard({ batch }: { batch: DragonbotBatch }) {
  const evalData = batch.eval;
  if (!evalData) return null;
  const lensEntries = Object.entries(evalData.byLens);
  return (
    <div data-dragonbot-eval={batch.batchId} style={{ ...panelStyle, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <Badge tone={evalData.truthVerdict === "CLEAN" ? "komodo" : evalData.truthVerdict === "SUSPECT" ? "neg" : "neutral"}>
          {evalData.truthVerdict}
        </Badge>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h3)", color: "var(--text-strong)" }}>
          {batch.title}
        </span>
        <TacticalTallyChips tally={evalData.tacticalTally} />
      </div>

      {lensEntries.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "var(--t-xs)" }}>
            <thead>
              <tr>
                <th style={{ ...labelStyle, textAlign: "left", padding: "2px 12px 4px 0" }}>lens</th>
                <th style={{ ...labelStyle, textAlign: "right", padding: "2px 12px 4px 0" }}>C</th>
                <th style={{ ...labelStyle, textAlign: "right", padding: "2px 12px 4px 0" }}>D</th>
                <th style={{ ...labelStyle, textAlign: "right", padding: "2px 0 4px 0" }}>I</th>
              </tr>
            </thead>
            <tbody>
              {lensEntries.map(([lens, tally]) => (
                <tr key={lens}>
                  <td style={{ padding: "2px 12px 2px 0", color: "var(--text-body)" }}>{lens}</td>
                  <td style={{ ...mono, padding: "2px 12px 2px 0", textAlign: "right", color: "var(--pos-500)" }}>{tally.COMPLIANT ?? 0}</td>
                  <td style={{ ...mono, padding: "2px 12px 2px 0", textAlign: "right", color: "var(--neg-500)" }}>{tally.DEVIANT ?? 0}</td>
                  <td style={{ ...mono, padding: "2px 0 2px 0", textAlign: "right", color: "var(--text-muted)" }}>{tally.INCONCLUSIVE ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {evalData.reportPaths.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={labelStyle}>eval reports</span>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {evalData.reportPaths.map((p) => (
              <a
                key={p}
                href={dragonbotGithubBlobHref(p)}
                target="_blank"
                rel="noopener"
                style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--accent)", textDecoration: "none" }}
              >
                📄 {p.split("/").pop()}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EvalLoopPanel({ batches }: { batches: DragonbotBatch[] }) {
  const withEval = [...batches]
    .filter((b) => b.eval != null)
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h2 style={sectionTitleStyle}>Eval Loop</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {withEval.map((b) => (
          <EvalBatchCard key={b.batchId} batch={b} />
        ))}
        {withEval.length === 0 && <div style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>no eval-loop data in feed yet</div>}
      </div>
    </section>
  );
}

// --- top-level panel ---

export function DragonbotPanel() {
  const { feed, stale, error } = useDragonbotFeed();
  const buildStale = isSnapshotStale(feed);
  const showStaleBanner = stale || buildStale;

  if (!feed) {
    return (
      <div data-dragonbot-state="loading" style={{ ...panelStyle, ...mono, color: "var(--text-muted)" }}>
        loading dragonbot goals & metrics… (dragonbot-hub-feed.json)
      </div>
    );
  }

  return (
    <div data-dragonbot-panel style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ ...mono, fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
        {feed.goals.length} goal(s) · {feed.batches.length} batch(es) · Xerialen/dragonbot ·
        schema {feed.schema}
      </div>
      {showStaleBanner && <StaleBanner reason={error} />}
      <GoalLadder goals={feed.goals} />
      <MetricsTimeline batches={feed.batches} />
      <EvalLoopPanel batches={feed.batches} />
    </div>
  );
}
