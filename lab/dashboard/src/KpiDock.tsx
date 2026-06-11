// LD-E1 (#100): KPI dock — collapsible thin left dock with context store.
//
// Renders as a flex/grid column member (never an overlay) so the Demo pane
// (leftmost) is never obscured.  Two modes:
//   expanded  — ~300 px, semi-opaque, full context line + section slots
//   rail      — ~28 px, slim vertical "KPI" label only
//
// The collapse/expand button is also wired from the top-bar stub in App.tsx
// (the button existed as a placeholder since LD-B1).
//
// Section slots for LD-E2 (scoreboard), LD-E3 (live metrics), LD-E4 (records)
// are rendered as named skeleton placeholders.  Each slot has a data-section
// attribute so Playwright tests can assert presence.
//
// Context line format: "<map> · <route> · <source>" or "<map> · (no route) · <source>"

import type { KpiContext } from "./contextStore.ts";

// ---- Props ------------------------------------------------------------------

type KpiDockProps = {
  context: KpiContext;
  collapsed: boolean;
  onToggle: () => void;
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

export function KpiDock({ context, collapsed, onToggle }: KpiDockProps) {
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
        {/* Vertical label */}
        <span
          className="text-[10px] text-gray-600 [writing-mode:vertical-rl] mt-2 select-none"
          aria-hidden="true"
        >
          KPI
        </span>
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

      {/* Section slots: populated by future LD stages */}
      <div className="flex flex-col gap-y-2 p-3 overflow-y-auto grow">
        <SectionSlot
          section="scoreboard"
          label="Scoreboard — LD-E2 (#101)"
        />
        <SectionSlot
          section="live-metrics"
          label="Live metrics — LD-E3 (#102)"
        />
        <SectionSlot
          section="records"
          label="Records — LD-E4 (#104)"
        />
      </div>
    </aside>
  );
}
