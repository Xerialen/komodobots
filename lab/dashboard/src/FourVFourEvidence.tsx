// LD-H3 (#200): full-page "4v4 KTX Live Stats Evidence" report.
//
// Restores the wide-table evidence layout — the canonical wireframe in issue
// #200 — on top of the existing komodobots.4v4_validation.v1 ledger. This is a
// standalone, OBS/report-friendly surface, separate from the BotLab control
// shell, reached at /botlab/?evidence=1.
//   ?fixture=4v4        -> committed example ledger (public/data)
//   ?validation=<url>   -> explicit ledger source
//
// Styling: the "KomodoBots Design System" handoff bundle (issue #253) — a dark
// "match telemetry console". Team Leap (KomodoBots, RED/trained) vs Team Frog
// (frogbots, BLUE/controls); the brand emblem + "Leapfrog to dragon" slogan
// live in the header/banner per the owner's design direction. Tokens are
// vendored in komodo-design.css; this component composes them with inline
// styles (the kit's own technique) so it does not depend on the Tailwind theme.
//
// Deltas are computed here against the previous valid game
// (previous_valid_run_id), so both the team summary cards and the per-bot table
// show change-vs-previous exactly like the wireframe. The page polls every 15s
// so it tracks a live run as new valid games land in the ledger.

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

interface ValidationTeam {
  name: string;
  score: number;
  player_count: number;
  totals: Record<string, number | null>;
}

interface ValidationPlayer {
  slot: number;
  id: string;
  identity: { name: string; team: string };
  roster: {
    name: string;
    team: string;
    role: string;
    controller_version: string | null;
    tracked: boolean;
  };
  stats: Record<string, number | boolean | null>;
}

// docs/18 T0.1 per-game leap-vs-frog resolution (which team is the trained side).
interface GameBench {
  leap_team: string | null;
  frog_team: string | null;
}

interface ValidationGame {
  run_id: string;
  previous_valid_run_id: string | null;
  demo?: { name: string | null; url: string | null };
  match: { map: string; mode: string; duration: number; demo?: string | null };
  teams: ValidationTeam[];
  players: ValidationPlayer[];
  bench?: GameBench;
}

// docs/18 T0.1 best-of-N leap-vs-frog bench, schema komodobots.bench_frag_margin.v1.
interface BenchPerGame {
  run_id: string;
  leap_frags: number;
  frog_frags: number;
  frag_margin: number;
  damage_matrix_gate_pass: boolean | null;
}

interface BenchAggregate {
  schema: string;
  games_scored: number;
  leap_frag_margin_total: number | null;
  leap_frag_margin_mean: number | null;
  leap_wins: number;
  frog_wins: number;
  per_game: BenchPerGame[];
  damage_matrix_gate_pass: boolean;
}

interface ValidationLedger {
  schema: string;
  bench?: BenchAggregate;
  games: ValidationGame[];
  invalid_games?: Array<{ run_id: string; reasons: string[] }>;
}

type MetricKind = "percent" | "number";

interface MetricDef {
  key: string;
  label: string;
  sub?: string;
  title: string;
  kind?: MetricKind;
  precision?: number;
}

const PRIMARY_URL = "/demos/records/4v4-validation.json";
const FIXTURE_URL = "/botlab/data/4v4-validation.example.json";
const REFRESH_MS = 15000;
const SLOGAN = "Leapfrog to dragon"; // owner design direction, issue #253

// Lower-is-better metrics: a negative change-vs-previous is an improvement.
const HIGHER_IS_BAD = new Set([
  "deaths",
  "team_kills",
  "damage_taken",
  "team_weapon_damage",
  "rl_drops",
]);

// Per-bot table columns, in wireframe order. AVG/MAX SPD carried per the kit.
const BOT_COLUMNS: MetricDef[] = [
  { key: "frags", label: "Frags", title: "Frags" },
  { key: "deaths", label: "Deaths", title: "Deaths" },
  { key: "efficiency", label: "Eff", sub: "%", title: "Efficiency", kind: "percent" },
  { key: "avg_speed", label: "Avg", sub: "ups", title: "Average speed (qu/s)", precision: 0 },
  { key: "max_speed", label: "Max", sub: "ups", title: "Peak speed (qu/s)", precision: 0 },
  { key: "damage_done", label: "Dmg", sub: "given", title: "Damage done" },
  { key: "damage_taken", label: "Dmg", sub: "taken", title: "Damage taken" },
  { key: "health_pickups", label: "Health", title: "Health pickups" },
  { key: "team_kills", label: "TK", title: "Team kills" },
  { key: "enemy_rl_kills", label: "RL", sub: "kills", title: "Enemies carrying RL killed" },
  { key: "rl_drops", label: "RL", sub: "drop", title: "Rocket launchers dropped" },
  { key: "taken_to_die", label: "TTD", title: "Damage taken per death", precision: 0 },
];

// Team summary card metrics (score is handled separately, powerups inline).
const TEAM_METRICS: MetricDef[] = [
  { key: "efficiency", label: "Efficiency", title: "Team efficiency", kind: "percent" },
  { key: "damage_done", label: "Damage given", title: "Team damage done" },
  { key: "damage_taken", label: "Damage taken", title: "Team damage taken" },
  { key: "health_pickups", label: "Health pickup", title: "Team health pickups" },
];

const POWERUP_KEYS = ["quad_pickups", "pent_pickups", "ring_pickups"];

// teams[0] renders as side A / LEAP (the trained KomodoBots), teams[1] as side
// B / FROG (frogbot controls) — matching the bench leap_team/frog_team
// convention. Team is the visual differentiator: a whole side is the trained
// bots, so no single row is singled out.
interface SideTone {
  side: "LEAP" | "FROG";
  tag: string; // RED | BLUE
  accent: string; // team color var
  bg: string; // tinted card bg
  tagTeam: "red" | "blue";
  squad: "leap" | "frog";
}

const SIDE_LEAP: SideTone = {
  side: "LEAP",
  tag: "RED",
  accent: "var(--red-team)",
  bg: "var(--red-team-bg)",
  tagTeam: "red",
  squad: "leap",
};
const SIDE_FROG: SideTone = {
  side: "FROG",
  tag: "BLUE",
  accent: "var(--blue-team)",
  bg: "var(--blue-team-bg)",
  tagTeam: "blue",
  squad: "frog",
};

// Resolve which side a team is on, preferring the per-game bench resolution and
// falling back to the wireframe order (teams[0] = leap).
function toneForTeam(game: ValidationGame, teamName: string, teamIdx: number): SideTone {
  const leap = game.bench?.leap_team;
  const frog = game.bench?.frog_team;
  if (leap && teamName === leap) return SIDE_LEAP;
  if (frog && teamName === frog) return SIDE_FROG;
  return teamIdx === 0 ? SIDE_LEAP : SIDE_FROG;
}

function dataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("validation");
  if (explicit) return explicit;
  return params.get("fixture") === "4v4" ? FIXTURE_URL : PRIMARY_URL;
}

function num(value: number | boolean | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function fmt(value: number | null, metric?: MetricDef): string {
  if (value == null) return "—";
  if (metric?.kind === "percent") return `${Math.round(value * 100)}%`;
  if (metric?.precision != null) return value.toFixed(metric.precision);
  if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString();
  if (Math.abs(value) >= 100) return Math.round(value).toString();
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function latestGame(ledger: ValidationLedger): ValidationGame | null {
  return ledger.games.length > 0 ? ledger.games[ledger.games.length - 1] : null;
}

function findPrevGame(ledger: ValidationLedger, game: ValidationGame): ValidationGame | null {
  if (game.previous_valid_run_id) {
    const byId = ledger.games.find((g) => g.run_id === game.previous_valid_run_id);
    if (byId) return byId;
  }
  const idx = ledger.games.indexOf(game);
  return idx > 0 ? ledger.games[idx - 1] : null;
}

function teamDelta(curr: ValidationTeam, prev: ValidationTeam | null, key: string): number | null {
  const c = num(curr.totals[key]);
  const p = prev ? num(prev.totals[key]) : null;
  return c == null || p == null ? null : c - p;
}

function playerDelta(curr: ValidationPlayer, prev: ValidationPlayer | null, key: string): number | null {
  const c = num(curr.stats[key]);
  const p = prev ? num(prev.stats[key]) : null;
  return c == null || p == null ? null : c - p;
}

function orderedPlayers(game: ValidationGame): Array<{ player: ValidationPlayer; tone: SideTone; teamIdx: number }> {
  const out: Array<{ player: ValidationPlayer; tone: SideTone; teamIdx: number }> = [];
  game.teams.forEach((team, teamIdx) => {
    const tone = toneForTeam(game, team.name, teamIdx);
    game.players
      .filter((p) => (p.roster.team || p.identity.team) === team.name)
      .sort((a, b) => a.slot - b.slot)
      .forEach((player) => out.push({ player, tone, teamIdx }));
  });
  return out;
}

// --- design-system primitives (kit components, recreated as inline-style fns) ---

function KomodoMark({ size = 28, color }: { size?: number; color?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      role="img"
      aria-label="KomodoBots"
      style={{ color: color ?? "var(--brand)", display: "block" }}
    >
      <g stroke="currentColor" strokeWidth="3" strokeLinejoin="round">
        <path d="M60 6 L106 32 V88 L60 114 L14 88 V32 Z" fill="currentColor" fillOpacity="0.07" />
        <path d="M60 6 L106 32 L60 50 L14 32 Z" fill="currentColor" fillOpacity="0.14" />
        <path d="M14 88 L60 114 L106 88 L60 70 Z" fill="currentColor" fillOpacity="0.14" />
      </g>
      <path
        d="M30 56 C44 40 76 40 90 56 C76 72 44 72 30 56 Z"
        fill="currentColor"
        fillOpacity="0.16"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
      <path d="M60 41 C56 49 56 63 60 71 C64 63 64 49 60 41 Z" fill="currentColor" />
      <path
        d="M60 72 L60 86 M60 86 L53 96 M60 86 L67 96"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M40 34 L48 30 M80 34 L72 30" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

const TEAM_TAG_FG: Record<SideTone["tagTeam"], string> = { red: "#1A0B0C", blue: "#08111C" };
const SQUAD_TAG_COLOR: Record<SideTone["squad"], string> = { leap: "var(--komodo-500)", frog: "var(--amber-500)" };

function TeamTag({
  team,
  label,
  outline = false,
  size = "md",
}: {
  team: SideTone["tagTeam"] | SideTone["squad"];
  label?: string;
  outline?: boolean;
  size?: "sm" | "md";
}) {
  const isSquad = team === "leap" || team === "frog";
  const color = isSquad
    ? SQUAD_TAG_COLOR[team as SideTone["squad"]]
    : team === "red"
    ? "var(--red-team)"
    : "var(--blue-team)";
  const fg = isSquad ? "#0B0F0D" : TEAM_TAG_FG[team as SideTone["tagTeam"]];
  const dims =
    size === "sm"
      ? { fontSize: "var(--t-2xs)", padding: "2px 6px", minWidth: 34 }
      : { fontSize: "var(--t-xs)", padding: "3px 9px", minWidth: 42 };
  const text = label ?? team.toUpperCase();
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-display)",
        fontWeight: 700,
        letterSpacing: "0.06em",
        borderRadius: "var(--r-1)",
        textTransform: "uppercase",
        lineHeight: 1,
        ...dims,
        ...(outline
          ? { background: "transparent", color, border: `1px solid ${color}` }
          : { background: color, color: fg, border: `1px solid ${color}` }),
      }}
    >
      {text}
    </span>
  );
}

const BADGE_TONES: Record<string, { bg: string; fg: string; bd: string }> = {
  neutral: { bg: "var(--surface-inset)", fg: "var(--text-body)", bd: "var(--border-line)" },
  komodo: { bg: "var(--komodo-900)", fg: "var(--komodo-300)", bd: "var(--komodo-700)" },
  amber: { bg: "var(--amber-900)", fg: "var(--amber-300)", bd: "var(--amber-600)" },
  neg: { bg: "var(--neg-bg)", fg: "var(--neg-500)", bd: "var(--red-team-dim)" },
  live: { bg: "var(--amber-900)", fg: "var(--amber-300)", bd: "var(--amber-600)" },
};

function Badge({
  tone = "neutral",
  dot = false,
  live = false,
  children,
  ...rest
}: {
  tone?: keyof typeof BADGE_TONES;
  dot?: boolean;
  live?: boolean;
  children: React.ReactNode;
  [key: string]: unknown;
}) {
  const t = BADGE_TONES[live ? "live" : tone] ?? BADGE_TONES.neutral;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-mono)",
        fontSize: "var(--t-2xs)",
        fontWeight: 700,
        letterSpacing: "var(--ls-label)",
        textTransform: "uppercase",
        padding: "3px 7px",
        borderRadius: "var(--r-2)",
        whiteSpace: "nowrap",
        background: t.bg,
        color: t.fg,
        border: `1px solid ${t.bd}`,
      }}
      {...rest}
    >
      {(dot || live) && (
        <span
          className={live ? "km-live-dot" : undefined}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "currentColor",
            boxShadow: live ? "0 0 6px currentColor" : "none",
            animation: live ? "km-pulse 1.4s var(--ease-in-out) infinite" : "none",
          }}
        />
      )}
      {children}
    </span>
  );
}

function DeltaValue({
  value,
  invert = false,
  magnitude = "sm",
}: {
  value: number | null;
  invert?: boolean;
  magnitude?: "sm" | "md" | "lg";
}) {
  if (value == null) return null;
  const n = value;
  if (n === 0) {
    return <span style={{ fontFamily: "var(--font-mono)", color: "var(--flat-500)", fontSize: "var(--t-2xs)" }}>±0</span>;
  }
  const good = invert ? n < 0 : n > 0;
  const color = good ? "var(--pos-500)" : "var(--neg-500)";
  const caret = n > 0 ? "▲" : "▼";
  const sizes = { sm: "var(--t-2xs)", md: "var(--t-xs)", lg: "var(--t-sm)" };
  const mag = Math.abs(n);
  const magStr = Number.isInteger(mag) ? mag.toLocaleString() : mag.toFixed(1);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        fontFamily: "var(--font-mono)",
        fontWeight: 700,
        fontVariantNumeric: "tabular-nums",
        fontSize: sizes[magnitude],
        color,
        lineHeight: 1,
      }}
    >
      <span style={{ fontSize: "0.8em", transform: "translateY(-0.5px)" }}>{caret}</span>
      {n > 0 ? "+" : "−"}
      {magStr}
    </span>
  );
}

// Diverging head-to-head bar comparing the two teams on one metric (kit
// charts/CompareBar). Bars grow from a center line; each side scales to the
// larger of the two so the leader fills its half. `invert` flips the win/lose
// emphasis for lower-is-better stats (damage taken, deaths).
function CompareBar({
  label,
  left,
  right,
  leftDelta,
  rightDelta,
  invert = false,
  format = (v: number) => `${v}`,
}: {
  label: string;
  left: number | null;
  right: number | null;
  leftDelta: number | null;
  rightDelta: number | null;
  invert?: boolean;
  format?: (v: number) => string;
}) {
  const l = left ?? 0;
  const r = right ?? 0;
  const max = Math.max(l, r) || 1;
  const lw = (l / max) * 100;
  const rw = (r / max) * 100;
  // For lower-is-better metrics the *smaller* value is the winner.
  const leftWins = invert ? l < r : l > r;
  const rightWins = invert ? r < l : r > l;
  const valStyle: CSSProperties = {
    fontFamily: "var(--font-display)",
    fontWeight: 700,
    fontSize: "var(--t-h3)",
    color: "var(--text-strong)",
    fontVariantNumeric: "tabular-nums",
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div
        style={{
          textAlign: "center",
          fontFamily: "var(--font-ui)",
          fontSize: "var(--t-2xs)",
          fontWeight: 600,
          letterSpacing: "var(--ls-label)",
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        {label}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", alignItems: "center", gap: 2 }}>
        {/* left side (RED / LEAP) */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 }}>
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.1 }}>
            <span style={{ ...valStyle, opacity: leftWins ? 1 : 0.7 }}>{left == null ? "—" : format(l)}</span>
            <DeltaValue value={leftDelta} invert={invert} />
          </span>
          <div
            style={{
              flex: 1,
              maxWidth: 130,
              height: 12,
              background: "var(--surface-inset)",
              borderRadius: "2px 0 0 2px",
              overflow: "hidden",
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <div
              style={{
                width: `${lw}%`,
                height: "100%",
                background: "var(--red-team)",
                opacity: leftWins ? 1 : 0.55,
                transition: "width var(--dur-slow) var(--ease-out)",
              }}
            />
          </div>
        </div>
        {/* right side (BLUE / FROG) */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", gap: 8 }}>
          <div
            style={{
              flex: 1,
              maxWidth: 130,
              height: 12,
              background: "var(--surface-inset)",
              borderRadius: "0 2px 2px 0",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${rw}%`,
                height: "100%",
                background: "var(--blue-team)",
                opacity: rightWins ? 1 : 0.55,
                transition: "width var(--dur-slow) var(--ease-out)",
              }}
            />
          </div>
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.1 }}>
            <span style={{ ...valStyle, opacity: rightWins ? 1 : 0.7 }}>{right == null ? "—" : format(r)}</span>
            <DeltaValue value={rightDelta} invert={invert} />
          </span>
        </div>
      </div>
    </div>
  );
}

// Team-comparison strip — lifts the per-bot stats up to the team level via
// diverging RED-vs-BLUE bars (kit ui_kits/live-stats/TeamCompare). teams[0] is
// LEAP/RED, teams[1] is FROG/BLUE, matching the page order.
interface CompareRow {
  key: string;
  label: string;
  metric?: MetricDef;
  invert?: boolean;
  format?: (v: number) => string;
}

const COMPARE_ROWS: CompareRow[] = [
  { key: "frags", label: "Frags" },
  { key: "efficiency", label: "Efficiency %", metric: { key: "efficiency", label: "Eff", title: "Efficiency", kind: "percent" } },
  { key: "avg_speed", label: "Avg Speed (qu/s)", metric: { key: "avg_speed", label: "Avg", title: "Average speed", precision: 0 } },
  { key: "max_speed", label: "Max Speed (qu/s)", metric: { key: "max_speed", label: "Max", title: "Peak speed", precision: 0 } },
  { key: "damage_done", label: "Damage Given", format: (v) => Math.round(v).toLocaleString() },
  { key: "damage_taken", label: "Damage Taken", invert: true, format: (v) => Math.round(v).toLocaleString() },
  { key: "health_pickups", label: "Health Pickup" },
  { key: "deaths", label: "Deaths", invert: true },
];

function TeamCompare({
  left,
  right,
  prevLeft,
  prevRight,
}: {
  left: ValidationTeam;
  right: ValidationTeam;
  prevLeft: ValidationTeam | null;
  prevRight: ValidationTeam | null;
}) {
  return (
    <section
      data-evidence-compare
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border-hair)",
        borderRadius: "var(--r-3)",
        padding: "14px 18px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, gap: 12 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: "var(--t-h3)", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--text-body)" }}>
          Team comparison · current game
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)" }}>
          Δ vs previous valid game
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 36, rowGap: 16 }}>
        {COMPARE_ROWS.map((row) => (
          <CompareBar
            key={row.key}
            label={row.label}
            left={num(left.totals[row.key])}
            right={num(right.totals[row.key])}
            leftDelta={teamDelta(left, prevLeft, row.key)}
            rightDelta={teamDelta(right, prevRight, row.key)}
            invert={row.invert}
            format={row.format ?? ((v) => fmt(v, row.metric))}
          />
        ))}
      </div>
    </section>
  );
}

// --- top bar: logo + slogan + tabs + gate/live badges ---

function TopBar({ game, gateGreen }: { game: ValidationGame; gateGreen: boolean | null }) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--sp-7)",
        padding: "14px 20px",
        borderBottom: "1px solid var(--border-line)",
        background: "var(--surface-raised)",
      }}
    >
      <div style={{ display: "inline-flex", alignItems: "center", gap: "var(--sp-4)" }}>
        <KomodoMark size={30} />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 22, letterSpacing: "0.02em", color: "var(--text-strong)" }}>
            KOMODO<span style={{ color: "var(--brand)" }}>BOTS</span>
          </span>
          <span
            data-evidence-slogan
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--t-2xs)",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            {SLOGAN}
          </span>
        </div>
      </div>
      <nav style={{ display: "flex", gap: "var(--sp-6)", alignItems: "center", marginLeft: "var(--sp-4)" }}>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 600,
            fontSize: "var(--t-h3)",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            padding: "6px 4px",
            color: "var(--text-strong)",
            borderBottom: "2px solid var(--brand)",
            whiteSpace: "nowrap",
          }}
        >
          Live Stats
        </span>
      </nav>
      <div style={{ flex: 1 }} />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--sp-5)",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--t-2xs)",
          color: "var(--text-muted)",
        }}
      >
        <span>
          map <b style={{ color: "var(--text-body)" }}>{game.match.map}</b>
        </span>
        {(game.demo?.name ?? game.match.demo) && (
          <span>
            demo <b style={{ color: "var(--text-body)" }}>{game.demo?.name ?? game.match.demo}</b>
          </span>
        )}
      </div>
      {gateGreen != null &&
        (gateGreen ? (
          <Badge tone="komodo" dot>
            R-T GATE GREEN
          </Badge>
        ) : (
          <Badge tone="neg" dot>
            R-T GATE RED
          </Badge>
        ))}
      <Badge live>LIVE</Badge>
    </header>
  );
}

// --- branded LEAP vs FROG match banner (gradient staging) ---

function MatchBanner({ game, bench }: { game: ValidationGame; bench: BenchAggregate | undefined }) {
  const margin = bench?.leap_frag_margin_total ?? null;
  const lead =
    margin == null ? "NO SCORED GAMES" : margin > 0 ? "LEAP LEADS" : margin < 0 ? "FROG LEADS" : "EVEN";
  const leadTone: keyof typeof BADGE_TONES = margin == null ? "neutral" : margin >= 0 ? "komodo" : "amber";
  return (
    <div
      data-evidence-banner
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--sp-6)",
        padding: "12px 18px",
        background:
          "linear-gradient(90deg, var(--komodo-900) 0%, var(--surface-card) 38%, var(--surface-card) 62%, var(--amber-900) 100%)",
        border: "1px solid var(--border-hair)",
        borderRadius: "var(--r-3)",
      }}
    >
      <KomodoMark size={34} />
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h2)", color: "var(--text-strong)", letterSpacing: "0.02em" }}>
          LEAP <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>vs</span> FROG
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
          {game.match.mode.toUpperCase()} · MAP {game.match.map.toUpperCase()}
        </span>
      </div>
      <div style={{ flex: 1 }} />
      {margin != null && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
              Frag margin
            </span>
            <span
              data-bench-margin-total
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: 700,
                fontSize: "var(--t-stat-md)",
                color: margin >= 0 ? "var(--komodo-300)" : "var(--amber-300)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {margin > 0 ? "+" : ""}
              {margin}
            </span>
          </div>
          <div style={{ width: 1, height: 34, background: "var(--border-line)" }} />
        </>
      )}
      {bench && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
              Game wins
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h2)", color: "var(--text-strong)" }}>
              <TeamTag team="leap" size="sm" /> {bench.leap_wins} – {bench.frog_wins} <TeamTag team="frog" size="sm" />
            </span>
          </div>
          <div style={{ width: 1, height: 34, background: "var(--border-line)" }} />
        </>
      )}
      <Badge tone={leadTone} dot>
        {lead}
      </Badge>
    </div>
  );
}

// --- two team heads + the R-T gate / bench verdict strip ---

function TeamHead({
  team,
  prev,
  tone,
  align,
}: {
  team: ValidationTeam;
  prev: ValidationTeam | null;
  tone: SideTone;
  align: "left" | "right";
}) {
  const right = align === "right";
  const scoreDelta = prev ? team.score - prev.score : null;
  const powerups = POWERUP_KEYS.map((k) => num(team.totals[k]) ?? 0);
  return (
    <section
      data-evidence-team={team.name}
      data-evidence-side={tone.side}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "14px 16px",
        background: tone.bg,
        border: `1px solid ${tone.accent}`,
        borderTop: `2px solid ${tone.accent}`,
        borderRadius: "var(--r-3)",
        alignItems: right ? "flex-end" : "flex-start",
      }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexDirection: right ? "row-reverse" : "row" }}>
        <TeamTag team={tone.tagTeam} />
        <TeamTag team={tone.squad} outline />
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h2)", color: "var(--text-strong)", whiteSpace: "nowrap" }}>
          {team.name}
        </span>
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", color: "var(--text-muted)" }}>
        {team.player_count} bots · {tone.side === "LEAP" ? "trained KomodoBots" : "frogbot controls"}
      </span>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexDirection: right ? "row-reverse" : "row" }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-stat-xl)", lineHeight: 1, color: "var(--text-strong)", fontVariantNumeric: "tabular-nums" }}>
          {team.score}
        </span>
        <div style={{ display: "flex", flexDirection: "column", alignItems: right ? "flex-end" : "flex-start" }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-xs)", letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
            frags
          </span>
          <DeltaValue value={scoreDelta} magnitude="lg" />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px 18px", width: "100%", direction: right ? "rtl" : "ltr" }}>
        {TEAM_METRICS.map((m) => (
          <div key={m.key} title={m.title} style={{ direction: "ltr", textAlign: right ? "right" : "left" }}>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-xs)", letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
              {m.label}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "baseline", justifyContent: right ? "flex-end" : "flex-start", fontFamily: "var(--font-mono)", fontSize: "var(--t-h3)", color: "var(--text-strong)", fontVariantNumeric: "tabular-nums" }}>
              <span>{fmt(num(team.totals[m.key]), m)}</span>
              <DeltaValue value={teamDelta(team, prev, m.key)} invert={HIGHER_IS_BAD.has(m.key)} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, flexDirection: right ? "row-reverse" : "row" }}>
        <Badge tone="neutral">Q {powerups[0]}</Badge>
        <Badge tone="neutral">P {powerups[1]}</Badge>
        <Badge tone="neutral">R {powerups[2]}</Badge>
      </div>
    </section>
  );
}

function signedMargin(value: number | null): string {
  if (value == null) return "—";
  const v = Number.isInteger(value) ? `${value}` : value.toFixed(1);
  return value > 0 ? `+${v}` : v;
}

// docs/18 T0.7 headline verdict: best-of-N leap-vs-frog frag margin + the R-T
// damage.matrix gate. A negative margin is a valid Phase-0 baseline.
function BenchVerdict({ bench }: { bench: BenchAggregate }) {
  const gate = bench.damage_matrix_gate_pass;
  const total = bench.leap_frag_margin_total;
  return (
    <section
      data-evidence-bench
      data-bench-gate={gate ? "green" : "red"}
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border-hair)",
        borderRadius: "var(--r-3)",
        padding: "14px 18px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 12 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: "var(--t-h3)", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--text-body)" }}>
          Leap vs Frog · bench · best-of-{bench.games_scored}
        </span>
        {gate ? (
          <Badge tone="komodo" dot>
            R-T GATE GREEN
          </Badge>
        ) : (
          <Badge tone="neg" dot>
            R-T GATE RED
          </Badge>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "8px 28px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
            Frag margin
          </span>
          <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span
              data-bench-margin-total
              style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-stat-lg)", lineHeight: 1, color: "var(--text-strong)", fontVariantNumeric: "tabular-nums" }}
            >
              {signedMargin(total)}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-muted)" }}>
              mean {signedMargin(bench.leap_frag_margin_mean)}/game
            </span>
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
            Game wins
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)", color: "var(--text-strong)" }}>
            <TeamTag team="leap" size="sm" /> {bench.leap_wins} – {bench.frog_wins} <TeamTag team="frog" size="sm" />
          </span>
        </div>
        <div data-bench-series style={{ display: "flex", flexWrap: "wrap", gap: 6, alignSelf: "center" }}>
          {bench.per_game.map((g) => (
            <span
              key={g.run_id}
              title={`${g.run_id}: leap ${g.leap_frags} – ${g.frog_frags} frog`}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "var(--t-2xs)",
                fontWeight: 700,
                padding: "3px 7px",
                borderRadius: "var(--r-2)",
                border: "1px solid",
                fontVariantNumeric: "tabular-nums",
                ...(g.frag_margin > 0
                  ? { color: "var(--pos-500)", background: "var(--pos-bg)", borderColor: "var(--komodo-700)" }
                  : g.frag_margin < 0
                  ? { color: "var(--neg-500)", background: "var(--neg-bg)", borderColor: "var(--red-team-dim)" }
                  : { color: "var(--flat-500)", background: "transparent", borderColor: "var(--border-line)" }),
              }}
            >
              {signedMargin(g.frag_margin)}
              {g.damage_matrix_gate_pass === false ? " ⚠" : ""}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

// --- the 8-bot scoreboard ---

function Scoreboard({ game, prev }: { game: ValidationGame; prev: ValidationGame | null }) {
  const rows = orderedPlayers(game);
  const thStyle: CSSProperties = {
    padding: "0 0 8px",
    textAlign: "right",
    fontFamily: "var(--font-ui)",
    fontSize: "var(--t-2xs)",
    fontWeight: 600,
    letterSpacing: "var(--ls-label)",
    textTransform: "uppercase",
    color: "var(--text-muted)",
    whiteSpace: "nowrap",
  };
  const cellStyle: CSSProperties = {
    padding: "9px 8px 9px 0",
    textAlign: "right",
    fontFamily: "var(--font-mono)",
    fontSize: "var(--t-sm)",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  };
  return (
    <section
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border-hair)",
        borderRadius: "var(--r-3)",
        padding: "14px 18px 6px",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6, gap: 12 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: "var(--t-h3)", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--text-body)" }}>
          All eight bots · current stat
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)" }}>
          green = improved · red = regressed · Δ vs previous valid game
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 980 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-line)" }}>
              <th style={{ ...thStyle, textAlign: "left", paddingLeft: 0 }}>Bot / build</th>
              {BOT_COLUMNS.map((c) => (
                <th key={c.key} style={{ ...thStyle, paddingRight: 8 }} title={c.title}>
                  {c.label}
                  {c.sub && <span style={{ display: "block", color: "var(--text-faint)", fontWeight: 400 }}>{c.sub}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ player, tone }, i) => {
              const isLeap = tone.side === "LEAP";
              const firstOfTeam = i === 0 || rows[i - 1].tone.side !== tone.side;
              const prevPlayer = prev?.players.find((p) => p.slot === player.slot) ?? null;
              const nameColor = isLeap ? "var(--komodo-300)" : "var(--text-strong)";
              return (
                <tr
                  key={player.id}
                  data-evidence-bot={player.slot}
                  data-evidence-side={tone.side}
                  style={{
                    borderBottom: "1px solid var(--border-hair)",
                    borderTop: firstOfTeam && i !== 0 ? "2px solid var(--border-line)" : "none",
                    background: isLeap ? "rgba(143,178,58,0.04)" : "transparent",
                  }}
                >
                  <td style={{ padding: "9px 0" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ width: 3, alignSelf: "stretch", background: tone.accent, borderRadius: 2 }} />
                      <TeamTag team={tone.tagTeam} size="sm" />
                      <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)", fontWeight: 700, color: nameColor }}>
                          {player.roster.name || player.identity.name}
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)" }}>
                          {player.roster.controller_version ?? player.roster.role}
                        </span>
                      </span>
                    </span>
                  </td>
                  {BOT_COLUMNS.map((c) => {
                    const speedAccent = (c.key === "avg_speed" || c.key === "max_speed") && isLeap ? "var(--komodo-300)" : "var(--text-strong)";
                    return (
                      <td key={c.key} style={{ ...cellStyle, color: speedAccent }} title={c.title}>
                        <span style={{ display: "inline-flex", alignItems: "baseline", gap: 6, justifyContent: "flex-end" }}>
                          {fmt(num(player.stats[c.key]), c)}
                          <DeltaValue value={playerDelta(player, prevPlayer, c.key)} invert={HIGHER_IS_BAD.has(c.key)} />
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function FourVFourEvidence() {
  const [ledger, setLedger] = useState<ValidationLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const url = useMemo(dataUrl, []);

  useEffect(() => {
    const id = window.setInterval(() => setRefreshKey((k) => k + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`4v4-validation.json ${res.status}`);
        return res.json() as Promise<ValidationLedger>;
      })
      .then((data) => {
        if (cancelled) return;
        setLedger(data);
        setError(null);
        setLoading(false);
      })
      .catch((exc) => {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : "validation ledger unavailable");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url, refreshKey]);

  const game = useMemo(() => (ledger ? latestGame(ledger) : null), [ledger]);
  const prev = useMemo(() => (ledger && game ? findPrevGame(ledger, game) : null), [ledger, game]);

  const pageStyle: CSSProperties = {
    minHeight: "100vh",
    background: "var(--bg-app)",
    color: "var(--text-body)",
    fontFamily: "var(--font-ui)",
  };
  const centerStyle: CSSProperties = {
    ...pageStyle,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  };

  if (loading) {
    return (
      <main data-evidence-state="loading" style={centerStyle}>
        <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>loading 4v4 validation…</span>
      </main>
    );
  }

  if (error || !ledger) {
    return (
      <main data-evidence-state="error" style={centerStyle}>
        <span style={{ color: "var(--neg-500)", fontFamily: "var(--font-mono)" }}>
          4v4 validation unavailable — {error ?? "no ledger"}
        </span>
      </main>
    );
  }

  if (!game) {
    return (
      <main data-evidence-state="empty" style={centerStyle}>
        <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>no valid 4v4 games yet</span>
      </main>
    );
  }

  const bench = ledger.bench && ledger.bench.games_scored > 0 ? ledger.bench : undefined;
  const gateGreen = bench ? bench.damage_matrix_gate_pass : null;
  const orderedTeams = [...game.teams]
    .map((team, idx) => ({ team, tone: toneForTeam(game, team.name, idx) }))
    .sort((a, b) => (a.tone.side === b.tone.side ? 0 : a.tone.side === "LEAP" ? -1 : 1));

  return (
    <main data-evidence-scoreboard style={pageStyle}>
      <TopBar game={game} gateGreen={gateGreen} />
      <div
        style={{
          maxWidth: "var(--view-max)",
          margin: "0 auto",
          padding: "0 20px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, padding: "18px 0 2px", flexWrap: "wrap" }}>
          <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: "var(--t-h1)", color: "var(--text-strong)", letterSpacing: "var(--ls-display)", lineHeight: "var(--lh-tight)", margin: 0, whiteSpace: "nowrap" }}>
            4v4 KTX · Live Stats Evidence
          </h1>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-muted)", letterSpacing: "0.06em" }}>
            RUN {game.run_id} · Δ vs {game.previous_valid_run_id ?? "baseline"}
          </span>
        </div>

        <MatchBanner game={game} bench={bench} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {orderedTeams.map(({ team, tone }, pos) => (
            <TeamHead
              key={team.name}
              team={team}
              prev={prev?.teams.find((t) => t.name === team.name) ?? null}
              tone={tone}
              align={pos === 0 ? "left" : "right"}
            />
          ))}
        </div>

        {bench && <BenchVerdict bench={bench} />}

        {orderedTeams.length === 2 && (
          <TeamCompare
            left={orderedTeams[0].team}
            right={orderedTeams[1].team}
            prevLeft={prev?.teams.find((t) => t.name === orderedTeams[0].team.name) ?? null}
            prevRight={prev?.teams.find((t) => t.name === orderedTeams[1].team.name) ?? null}
          />
        )}

        <Scoreboard game={game} prev={prev} />

        <footer style={{ borderTop: "1px solid var(--border-hair)", paddingTop: 12, fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)", lineHeight: 1.6 }}>
          <div>
            <span style={{ color: "var(--komodo-300)" }}>RED = LEAP (trained KomodoBots)</span> ·{" "}
            <span style={{ color: "var(--blue-team)" }}>BLUE = FROG (frogbot controls)</span> · Avg/Max spd in qu/s ·
            TK = team kills · TTD = damage taken per death · RL kills = enemies carrying RL killed · RL drop = rocket
            launchers dropped · Q/P/R = quad / pent / ring pickups ·{" "}
            <span style={{ color: "var(--pos-500)" }}>▲ green improved</span> /{" "}
            <span style={{ color: "var(--neg-500)" }}>▼ red regressed</span> vs previous valid game.
          </div>
          <div style={{ marginTop: 4 }}>
            Source: {ledger.schema} · {url}
            {ledger.invalid_games?.length ? ` · ${ledger.invalid_games.length} invalid game(s) hidden` : ""}
          </div>
        </footer>
      </div>
    </main>
  );
}
