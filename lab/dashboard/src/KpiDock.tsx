// LD-E1 (#100): KPI dock — collapsible thin left dock with context store.
// LD-E2 (#101): Brutal scoreboard — four metric rows (Race / Jump Count /
//               Speedometer / Eye Test) wired into the scoreboard section slot.
//
// Renders as a flex/grid column member (never an overlay) so the Demo pane
// (leftmost) is never obscured.  Two modes:
//   expanded  — ~300 px, semi-opaque, context line + scoreboard + section slots
//   rail      — ~28 px, slim vertical strip with four micro scoreboard glyphs
//
// The collapse/expand button is also wired from the top-bar stub in App.tsx
// (the button existed as a placeholder since LD-B1).
//
// Section slots for LD-E3 (live metrics) and LD-E4 (records) are still rendered
// as named skeleton placeholders.  The scoreboard slot is now the real component.
//
// Context line format: "<map> · <route> · <source>" or "<map> · (no route) · <source>"

import type { KpiContext } from "./contextStore.ts";
import { BrutalScoreboard, RailScoreboard } from "./BrutalScoreboard.tsx";

// ---- Props ------------------------------------------------------------------

type KpiDockProps = {
  context: KpiContext;
  collapsed: boolean;
  onToggle: () => void;
  /**
   * Incremented by the parent (App.tsx) when an attempt ends so the scoreboard
   * refetches records.  Passed through to BrutalScoreboard / RailScoreboard.
   * LD-E2 (#101).
   */
  refreshKey?: number;
};

// ---- Helpers ----------------------------------------------------------------

function sourceBadgeClass(source: KpiContext["source"]): string {
  switch (source) {
    case "live":   return "bg-green-900/60 text-green-300 border border-green-700";
    case "mockup": return "bg-sky-900/60 text-sky-300 border border-sky-700";
    case "demo":   return "bg-purple-900/60 text-purple-300 border border-purple-700";
    case "none":   return "bg-slate-800 text-gray-500 border border-slate-700";
  }
}

// ---- Sections ---------------------------------------------------------------

function SectionSlot({ label, section }: { label: string; section: string }) {
  return (
    <div
      data-section={section}
      className="rounded border border-dashed border-slate-700 px-2 py-3 text-center"
    >
      <span className="text-xs text-gray-600">{label}</span>
    </div>
  );
}

// ---- Component --------------------------------------------------------------

export function KpiDock({ context, collapsed, onToggle, refreshKey = 0 }: KpiDockProps) {
  if (collapsed) {
    return (
      <aside
        data-dock="rail"
        className="shrink-0 w-7 flex flex-col items-center gap-y-1 pt-2 border-r border-slate-800 bg-slate-950/60"
      >
        {/* Expand button */}
        <button
          type="button"
          title="Expand KPI dock"
          onClick={onToggle}
          className="text-[10px] text-gray-500 hover:text-gray-300 leading-none"
          aria-label="expand KPI dock"
        >
          ▸
        </button>
        {/* LD-E2 (#101): four micro scoreboard glyphs in rail mode. */}
        <div className="flex flex-col items-center gap-y-1 mt-1">
          <RailScoreboard context={context} refreshKey={refreshKey} />
        </div>
        {/* Source badge in rail: just a colored 4 px dot */}
        <span
          data-source={context.source}
          aria-label={`context source: ${context.source}`}
          className={`mt-auto mb-2 w-1.5 h-1.5 rounded-full ${
            context.source === "live"
              ? "bg-green-400"
              : context.source === "mockup"
                ? "bg-sky-400"
                : context.source === "demo"
                  ? "bg-purple-400"
                  : "bg-slate-600"
          }`}
        />
      </aside>
    );
  }

  return (
    <aside
      data-dock="expanded"
      className="shrink-0 w-72 flex flex-col border-r border-slate-800 bg-slate-950/80 overflow-hidden"
    >
      {/* Dock header: collapse button + context line */}
      <div className="flex items-center gap-x-2 px-3 py-2 border-b border-slate-800 bg-slate-900/60 text-xs">
        <button
          type="button"
          title="Collapse KPI dock"
          onClick={onToggle}
          className="text-gray-500 hover:text-gray-300"
          aria-label="collapse KPI dock"
        >
          ◂
        </button>
        <span className="font-semibold text-gray-300 uppercase tracking-wide">KPI</span>

        {/* Source badge */}
        <span
          data-source={context.source}
          className={`ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono ${sourceBadgeClass(context.source)}`}
        >
          {context.source}
        </span>
      </div>

      {/* Context line: map · route */}
      <div
        data-context-line
        className="px-3 py-1.5 text-xs font-mono text-gray-400 border-b border-slate-800 truncate"
        title={`${context.map} · ${context.route ?? "(no route)"} · ${context.source}`}
      >
        <span className="text-gray-300">{context.map}</span>
        {" · "}
        <span className={context.route ? "text-sky-300" : "text-gray-600"}>
          {context.route ?? "(no route)"}
        </span>
      </div>

      {/* Sections */}
      <div className="flex flex-col overflow-y-auto grow">
        {/* LD-E2 (#101): Brutal scoreboard — four KPI rows. */}
        <div className="px-3 pt-2 pb-1">
          <BrutalScoreboard context={context} refreshKey={refreshKey} />
        </div>

        {/* LD-E3 (#102): Live metrics — skeleton placeholder. */}
        <div className="px-3 py-2 border-t border-slate-800">
          <SectionSlot
            section="live-metrics"
            label="Live metrics — LD-E3 (#102)"
          />
        </div>

        {/* LD-E4 (#104): Records — skeleton placeholder. */}
        <div className="px-3 py-2 border-t border-slate-800">
          <SectionSlot
            section="records"
            label="Records — LD-E4 (#104)"
          />
        </div>
      </div>
    </aside>
  );
}
