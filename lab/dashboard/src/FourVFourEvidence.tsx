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

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

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
  "team_damage",
  "rl_drops",
]);

// Per-bot table columns, in wireframe order. AVG/MAX SPD carried per the kit;
// "Team dmg" (self-inflicted on own team, issue #253) is lower-is-better.
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
  { key: "team_damage", label: "Team", sub: "dmg", title: "Damage dealt to own team (lower is better)" },
  { key: "enemy_rl_kills", label: "RL", sub: "kills", title: "Enemies carrying RL killed" },
  { key: "rl_drops", label: "RL", sub: "drop", title: "Rocket launchers dropped" },
  { key: "taken_to_die", label: "TTD", title: "Damage taken per death", precision: 0 },
];

// Team summary card metrics — mirror the per-bot stat columns, team-aggregated
// (issue #253). Frags is shown as the big score, not here; powerups inline.
const TEAM_METRICS: MetricDef[] = [
  { key: "deaths", label: "Deaths", title: "Team deaths" },
  { key: "efficiency", label: "Eff", sub: "%", title: "Team efficiency", kind: "percent" },
  { key: "avg_speed", label: "Avg spd", title: "Team average speed (qu/s)", precision: 0 },
  { key: "max_speed", label: "Max spd", title: "Team peak speed (qu/s)", precision: 0 },
  { key: "damage_done", label: "Dmg given", title: "Team damage done" },
  { key: "damage_taken", label: "Dmg taken", title: "Team damage taken" },
  { key: "health_pickups", label: "Health", title: "Team health pickups" },
  { key: "team_kills", label: "TK", title: "Team kills" },
  { key: "team_damage", label: "Team dmg", title: "Damage dealt to own team (lower is better)" },
  { key: "enemy_rl_kills", label: "RL kills", title: "Enemies carrying RL killed" },
  { key: "rl_drops", label: "RL drop", title: "Rocket launchers dropped" },
  { key: "taken_to_die", label: "TTD", title: "Damage taken per death", precision: 0 },
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

// LEAP = orange, FROG = green (owner override of the kit, issue #253). The
// red/blue side discriminator is kept internally but never surfaced.
const SIDE_LEAP: SideTone = {
  side: "LEAP",
  tag: "RED",
  accent: "var(--leap)",
  bg: "var(--leap-bg)",
  tagTeam: "red",
  squad: "leap",
};
const SIDE_FROG: SideTone = {
  side: "FROG",
  tag: "BLUE",
  accent: "var(--frog)",
  bg: "var(--frog-bg)",
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

type View = "live" | "trends";

function initialView(): View {
  return new URLSearchParams(window.location.search).get("view") === "trends" ? "trends" : "live";
}

// Switch the ?view= param without a reload, so the nav toggle is deep-linkable
// and keeps ?evidence=1 / ?fixture=4v4 intact.
function setViewParam(view: View) {
  const url = new URL(window.location.href);
  if (view === "trends") url.searchParams.set("view", "trends");
  else url.searchParams.delete("view");
  window.history.replaceState(null, "", url.toString());
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

// Δ-vs-previous for a team metric, resolving values through teamMetricValue so
// client-aggregated stats (speed, team damage) get a delta too.
function teamMetricDelta(
  game: ValidationGame,
  prevGame: ValidationGame | null,
  curr: ValidationTeam,
  prev: ValidationTeam | null,
  key: string,
): number | null {
  const c = teamMetricValue(game, curr, key);
  const p = prevGame && prev ? teamMetricValue(prevGame, prev, key) : null;
  return c == null || p == null ? null : c - p;
}

function playerDelta(curr: ValidationPlayer, prev: ValidationPlayer | null, key: string): number | null {
  const c = num(curr.stats[key]);
  const p = prev ? num(prev.stats[key]) : null;
  return c == null || p == null ? null : c - p;
}

// A single ranked list across BOTH teams, sorted by frags desc (issue #253).
// Tie-breaks: efficiency desc -> deaths asc -> slot asc. Players with no frag
// value sink to the bottom. Each row carries its squad tone (the only team
// signal in the table now — no divider, no team grouping).
function teamIdxForName(game: ValidationGame, teamName: string): number {
  const idx = game.teams.findIndex((t) => t.name === teamName);
  return idx < 0 ? 0 : idx;
}

// Bot display name without the redundant "control" role word that the roster
// bakes in (e.g. "frog-control-5" -> "frog-5"); the squad tag already shows the
// role, so the name shouldn't repeat it (issue #253).
function botLabel(raw: string): string {
  return raw.replace(/control/gi, "").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "");
}

function orderedPlayers(game: ValidationGame): Array<{ player: ValidationPlayer; tone: SideTone; teamIdx: number }> {
  return game.players
    .map((player) => {
      const teamName = player.roster.team || player.identity.team;
      const teamIdx = teamIdxForName(game, teamName);
      return { player, tone: toneForTeam(game, teamName, teamIdx), teamIdx };
    })
    .sort((a, b) => {
      const fa = num(a.player.stats.frags);
      const fb = num(b.player.stats.frags);
      // null/missing frags sink to the bottom.
      if (fa == null && fb == null) return a.player.slot - b.player.slot;
      if (fa == null) return 1;
      if (fb == null) return -1;
      if (fb !== fa) return fb - fa;
      const ea = num(a.player.stats.efficiency) ?? -Infinity;
      const eb = num(b.player.stats.efficiency) ?? -Infinity;
      if (eb !== ea) return eb - ea;
      const da = num(a.player.stats.deaths) ?? Infinity;
      const db = num(b.player.stats.deaths) ?? Infinity;
      if (da !== db) return da - db;
      return a.player.slot - b.player.slot;
    });
}

// Client-side team aggregation for stats whose team totals are null in the
// ledger (issue #253): avg_speed (mean of players), max_speed (max of
// players), team_damage (sum of players). A GUI rollup, not a pipeline change.
function teamPlayers(game: ValidationGame, teamName: string): ValidationPlayer[] {
  return game.players.filter((p) => (p.roster.team || p.identity.team) === teamName);
}

function aggregateTeamMetric(game: ValidationGame, teamName: string, key: string): number | null {
  const vals = teamPlayers(game, teamName)
    .map((p) => num(p.stats[key]))
    .filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  if (key === "avg_speed") return vals.reduce((s, v) => s + v, 0) / vals.length;
  if (key === "max_speed") return Math.max(...vals);
  // sum for additive stats (team_damage, etc.)
  return vals.reduce((s, v) => s + v, 0);
}

// Resolve a team-level metric value, preferring the ledger total and falling
// back to a client-side aggregation when the total is null/missing.
function teamMetricValue(game: ValidationGame, team: ValidationTeam, key: string): number | null {
  const total = num(team.totals[key]);
  if (total != null) return total;
  if (CLIENT_AGGREGATED.has(key)) return aggregateTeamMetric(game, team.name, key);
  return null;
}

const CLIENT_AGGREGATED = new Set(["avg_speed", "max_speed", "team_damage"]);

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
// LEAP = orange, FROG = green (owner override, issue #253).
const SQUAD_TAG_COLOR: Record<SideTone["squad"], string> = { leap: "var(--leap)", frog: "var(--frog)" };

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
  suffix = "",
}: {
  value: number | null;
  invert?: boolean;
  magnitude?: "sm" | "md" | "lg";
  suffix?: string;
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
      {suffix}
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
                background: "var(--leap)",
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
                background: "var(--frog)",
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
  game,
  prevGame,
  left,
  right,
  prevLeft,
  prevRight,
}: {
  game: ValidationGame;
  prevGame: ValidationGame | null;
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
            left={teamMetricValue(game, left, row.key)}
            right={teamMetricValue(game, right, row.key)}
            leftDelta={teamMetricDelta(game, prevGame, left, prevLeft, row.key)}
            rightDelta={teamMetricDelta(game, prevGame, right, prevRight, row.key)}
            invert={row.invert}
            format={row.format ?? ((v) => fmt(v, row.metric))}
          />
        ))}
      </div>
    </section>
  );
}

// --- top bar: logo + slogan + tabs + gate/live badges ---

function TopBar({
  game,
  gateGreen,
  view,
  onView,
}: {
  game: ValidationGame;
  gateGreen: boolean | null;
  view: View;
  onView: (v: View) => void;
}) {
  const tabStyle = (on: boolean): CSSProperties => ({
    fontFamily: "var(--font-display)",
    fontWeight: 600,
    fontSize: "var(--t-h3)",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    padding: "6px 4px",
    color: on ? "var(--text-strong)" : "var(--text-muted)",
    borderBottom: `2px solid ${on ? "var(--brand)" : "transparent"}`,
    whiteSpace: "nowrap",
    background: "transparent",
    border: "none",
    borderBottomWidth: 2,
    borderBottomStyle: "solid",
    cursor: "pointer",
  });
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
        <button data-evidence-tab="live" style={tabStyle(view === "live")} onClick={() => onView("live")}>
          Live Stats
        </button>
        <button data-evidence-tab="trends" style={tabStyle(view === "trends")} onClick={() => onView("trends")}>
          Trends
        </button>
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
  game,
  prevGame,
  team,
  prev,
  tone,
  align,
}: {
  game: ValidationGame;
  prevGame: ValidationGame | null;
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
      {/* Squad tag only — match-side RED/BLUE tag dropped (issue #253). */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexDirection: right ? "row-reverse" : "row" }}>
        <TeamTag team={tone.squad} />
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--t-h2)", color: "var(--text-strong)", whiteSpace: "nowrap" }}>
          {team.name}
        </span>
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", color: "var(--text-muted)" }}>
        {team.player_count} bots · {tone.side === "LEAP" ? "trained KomodoBots" : "frogbots"}
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
      {/* Mirror the per-bot stat columns, team-aggregated, with Δ-vs-previous. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "8px 16px", width: "100%", direction: right ? "rtl" : "ltr" }}>
        {TEAM_METRICS.map((m) => (
          <div key={m.key} title={m.title} style={{ direction: "ltr", textAlign: right ? "right" : "left" }}>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
              {m.label}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "baseline", justifyContent: right ? "flex-end" : "flex-start", fontFamily: "var(--font-mono)", fontSize: "var(--t-h3)", color: "var(--text-strong)", fontVariantNumeric: "tabular-nums" }}>
              <span>{fmt(teamMetricValue(game, team, m.key), m)}</span>
              <DeltaValue value={teamMetricDelta(game, prevGame, team, prev, m.key)} invert={HIGHER_IS_BAD.has(m.key)} />
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
            {rows.map(({ player, tone }) => {
              const isLeap = tone.side === "LEAP";
              const prevPlayer = prev?.players.find((p) => p.slot === player.slot) ?? null;
              // Sub-label: controller_version, else a neutral build label —
              // never surface role:"control" (issue #253).
              const subLabel = player.roster.controller_version ?? "build —";
              return (
                <tr
                  key={player.id}
                  data-evidence-bot={player.slot}
                  data-evidence-side={tone.side}
                  style={{ borderBottom: "1px solid var(--border-hair)" }}
                >
                  <td style={{ padding: "9px 0" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ width: 3, alignSelf: "stretch", background: tone.accent, borderRadius: 2 }} />
                      <TeamTag team={tone.squad} size="sm" />
                      <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)", fontWeight: 700, color: "var(--text-strong)" }}>
                          {botLabel(player.roster.name || player.identity.name)}
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)" }}>
                          {subLabel}
                        </span>
                      </span>
                    </span>
                  </td>
                  {BOT_COLUMNS.map((c) => {
                    const speedAccent = (c.key === "avg_speed" || c.key === "max_speed") && isLeap ? tone.accent : "var(--text-strong)";
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

// --- Trends tab (kit ui_kits/trends, ported to TSX) ---------------------------

const BTN_VARIANTS: Record<string, { bg: string; fg: string; bd: string }> = {
  primary: { bg: "var(--brand)", fg: "#0B0F0D", bd: "var(--brand)" },
  amber: { bg: "var(--accent)", fg: "#1B120A", bd: "var(--accent)" },
  secondary: { bg: "var(--surface-raised)", fg: "var(--text-strong)", bd: "var(--border-line)" },
  ghost: { bg: "transparent", fg: "var(--text-body)", bd: "transparent" },
};

function Button({
  variant = "secondary",
  active = false,
  children,
  ...rest
}: {
  variant?: keyof typeof BTN_VARIANTS;
  active?: boolean;
  children: ReactNode;
  [key: string]: unknown;
}) {
  const v = BTN_VARIANTS[variant] ?? BTN_VARIANTS.secondary;
  return (
    <button
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "var(--sp-3)",
        fontFamily: "var(--font-ui)",
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        cursor: "pointer",
        borderRadius: "var(--r-2)",
        fontSize: "var(--t-xs)",
        padding: "5px 10px",
        background: v.bg,
        color: v.fg,
        border: `1px solid ${v.bd}`,
        ...(active ? { boxShadow: "inset 0 0 0 1px var(--brand)" } : null),
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

interface TrendSeries {
  label: string;
  color: string;
  data: number[];
  dashed?: boolean;
}

// Multi-series time graph over a sequence of games (kit charts/TrendChart).
// Auto-scales, faint grid + axis labels, end-dots + latest-value labels.
function TrendChart({
  series = [],
  xLabels = [],
  height = 240,
  yUnit = "",
  area = false,
  endLabels = true,
  gridRows = 4,
}: {
  series?: TrendSeries[];
  xLabels?: string[];
  height?: number;
  yUnit?: string;
  area?: boolean;
  endLabels?: boolean;
  gridRows?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((es) => {
      for (const e of es) setW(e.contentRect.width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const gid = useId().replace(/[:]/g, "");
  const padL = 38;
  const padR = endLabels ? 46 : 14;
  const padT = 12;
  const padB = 24;
  const h = height;
  const all = series.flatMap((s) => s.data);
  let lo = all.length ? Math.min(...all) : 0;
  let hi = all.length ? Math.max(...all) : 1;
  if (lo === hi) hi = lo + 1;
  const range = hi - lo;
  const n = Math.max(...series.map((s) => s.data.length), xLabels.length, 1);
  const X = (i: number) => (n === 1 ? padL : padL + (i / (n - 1)) * (w - padL - padR));
  const Y = (v: number) => padT + (1 - (v - lo) / range) * (h - padT - padB);
  const ticks = Array.from({ length: gridRows + 1 }, (_, r) => lo + (range * r) / gridRows);

  return (
    <div ref={ref} style={{ width: "100%" }}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", overflow: "visible" }}>
        <defs>
          {series.map((s, si) => (
            <linearGradient key={si} id={`tc-${gid}-${si}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} y1={Y(t)} x2={w - padR} y2={Y(t)} stroke="var(--border-hair)" strokeWidth="1" />
            <text x={padL - 8} y={Y(t) + 3} textAnchor="end" fontFamily="var(--font-mono)" fontSize="10" fill="var(--text-faint)">
              {Math.round(t)}
            </text>
          </g>
        ))}
        {xLabels.map((lab, i) => (
          <text key={i} x={X(i)} y={h - 8} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="10" fill="var(--text-muted)">
            {lab}
          </text>
        ))}
        {series.map((s, si) => {
          const pts = s.data.map((v, i) => [X(i), Y(v)] as [number, number]);
          if (pts.length === 0) return null;
          const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
          const areaPath = `${line} L${pts[pts.length - 1][0].toFixed(1)} ${Y(lo)} L${pts[0][0].toFixed(1)} ${Y(lo)} Z`;
          const last = pts[pts.length - 1];
          return (
            <g key={si}>
              {area && <path d={areaPath} fill={`url(#tc-${gid}-${si})`} />}
              <path
                d={line}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? "4 4" : "none"}
              />
              {pts.map((p, i) => (
                <circle
                  key={i}
                  cx={p[0]}
                  cy={p[1]}
                  r={i === pts.length - 1 ? 3.5 : 2.2}
                  fill={i === pts.length - 1 ? s.color : "var(--bg-app)"}
                  stroke={s.color}
                  strokeWidth="1.5"
                />
              ))}
              {endLabels && (
                <text x={last[0] + 8} y={last[1] + 3} fontFamily="var(--font-mono)" fontSize="11" fontWeight="700" fill={s.color}>
                  {Math.round(s.data[s.data.length - 1])}
                  {yUnit}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// Trend metrics. Keys map to ledger team-totals / player-stats keys; `kind`
// percent renders values as integer % on the chart.
interface TrendMetric {
  key: string;
  label: string;
  unit: string;
  invert: boolean;
  kind?: MetricKind;
}

const TREND_METRICS: Record<string, TrendMetric> = {
  frags: { key: "frags", label: "Frags", unit: "", invert: false },
  efficiency: { key: "efficiency", label: "Efficiency", unit: "%", invert: false, kind: "percent" },
  avg_speed: { key: "avg_speed", label: "Avg Speed", unit: "ups", invert: false },
  damage_done: { key: "damage_done", label: "Damage Given", unit: "", invert: false },
  damage_taken: { key: "damage_taken", label: "Damage Taken", unit: "", invert: true },
  deaths: { key: "deaths", label: "Deaths", unit: "", invert: true },
};
const TREND_FOUR = ["frags", "efficiency", "avg_speed", "damage_taken"];
const TREND_METRIC_KEYS = Object.keys(TREND_METRICS);

interface TrendSubject {
  id: string;
  kind: "team" | "player";
  label: string;
  tag: SideTone["squad"];
  color: string;
  // history per metric key, oldest -> newest, one point per game.
  hist: Record<string, number[]>;
}

// Per-metric value scaled for charting (percent -> 0..100).
function trendScale(value: number | null, mk: string): number {
  if (value == null) return 0;
  return TREND_METRICS[mk].kind === "percent" ? Math.round(value * 100) : value;
}

// Build the full per-subject history client-side by mapping over every game in
// the ledger (issue #253). Team scope uses team.totals (with the same null
// fallback aggregation as the live view); player scope keys on slot.
function buildTrendSubjects(ledger: ValidationLedger): { teams: TrendSubject[]; players: TrendSubject[] } {
  const games = ledger.games;
  const latest = games.length ? games[games.length - 1] : null;

  const teamSubjects: TrendSubject[] = [];
  if (latest) {
    const ordered = [...latest.teams]
      .map((team, idx) => ({ team, tone: toneForTeam(latest, team.name, idx) }))
      .sort((a, b) => (a.tone.side === b.tone.side ? 0 : a.tone.side === "LEAP" ? -1 : 1));
    ordered.forEach(({ team, tone }) => {
      const hist: Record<string, number[]> = {};
      TREND_METRIC_KEYS.forEach((mk) => {
        hist[mk] = games.map((g) => {
          const t = g.teams.find((x) => x.name === team.name);
          return t ? trendScale(teamMetricValue(g, t, mk), mk) : 0;
        });
      });
      teamSubjects.push({
        id: tone.squad,
        kind: "team",
        label: tone.side === "LEAP" ? "Team Leap" : "Team Frog",
        tag: tone.squad,
        color: tone.side === "LEAP" ? "var(--leap)" : "var(--frog)",
        hist,
        // LEAP first, FROG dashed handled at render.
      });
    });
  }

  // Player palette: leap shades (orange), frog shades (green).
  const leapColors = ["#F6C77A", "#E8913C", "#C9701F", "#A65A18"];
  const frogColors = ["#B7CE6E", "#8FB23A", "#5E8F2E", "#3F6B1E"];
  const playerSubjects: TrendSubject[] = [];
  if (latest) {
    const rows = orderedPlayers(latest);
    // Stable per-side index for color assignment.
    const sideCount: Record<string, number> = { LEAP: 0, FROG: 0 };
    rows.forEach(({ player, tone }) => {
      const ci = sideCount[tone.side]++;
      const palette = tone.side === "LEAP" ? leapColors : frogColors;
      const hist: Record<string, number[]> = {};
      TREND_METRIC_KEYS.forEach((mk) => {
        hist[mk] = games.map((g) => {
          const p = g.players.find((x) => x.slot === player.slot);
          return p ? trendScale(num(p.stats[mk]), mk) : 0;
        });
      });
      playerSubjects.push({
        id: `slot-${player.slot}`,
        kind: "player",
        label: botLabel(player.roster.name || player.identity.name),
        tag: tone.squad,
        color: palette[ci % palette.length],
        hist,
      });
    });
  }

  return { teams: teamSubjects, players: playerSubjects };
}

function TrendCtl({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
        {label}
      </span>
      <div style={{ display: "flex", gap: 4 }}>{children}</div>
    </div>
  );
}

function TrendSep() {
  return <div style={{ width: 1, height: 22, background: "var(--border-line)" }} />;
}

function TrendsView({ ledger }: { ledger: ValidationLedger }) {
  const { teams, players } = useMemo(() => buildTrendSubjects(ledger), [ledger]);
  const gameLabels = useMemo(() => ledger.games.map((_, i) => `G${i + 1}`), [ledger]);

  const [scope, setScope] = useState<"team" | "player">("team");
  const [mode, setMode] = useState<"single" | "four">("single");
  const [metric, setMetric] = useState<string>("efficiency");
  const [picked, setPicked] = useState<string[]>(teams.map((t) => t.id));

  const pool = scope === "team" ? teams : players;
  // Reset the selection to defaults ONLY when the scope actually changes. The
  // 15s ledger refresh produces fresh teams/players array identities for the
  // same logical subjects; on those we reconcile the existing picks against the
  // new pool (keep picks that still exist, drop those that vanished) instead of
  // wiping the user's custom selection mid-use (issue #258 Codex P2).
  const prevScopeRef = useRef(scope);
  useEffect(() => {
    if (prevScopeRef.current !== scope) {
      prevScopeRef.current = scope;
      setPicked(scope === "team" ? teams.map((t) => t.id) : players.slice(0, 2).map((p) => p.id));
      return;
    }
    setPicked((prev) => {
      const ids = new Set(pool.map((s) => s.id));
      const kept = prev.filter((id) => ids.has(id));
      if (kept.length === prev.length) return prev;
      if (kept.length > 0) return kept;
      // Every prior pick vanished — fall back to the scope's defaults.
      return scope === "team" ? teams.map((t) => t.id) : players.slice(0, 2).map((p) => p.id);
    });
  }, [scope, teams, players, pool]);

  const chosen = pool.filter((s) => picked.includes(s.id));
  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? (p.length > 1 ? p.filter((x) => x !== id) : p) : [...p, id].slice(-4)));

  const seriesFor = (mk: string): TrendSeries[] =>
    chosen.map((s) => ({
      label: s.label,
      color: s.color,
      data: s.hist[mk] ?? [],
      dashed: scope === "team" && s.id === "frog",
    }));
  const net = (s: TrendSubject, mk: string): number => {
    const arr = s.hist[mk] ?? [];
    return arr.length >= 2 ? arr[arr.length - 1] - arr[0] : 0;
  };

  const Legend = ({ mk }: { mk: string }) => (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
      {chosen.map((s) => (
        <span key={s.id} style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 12, height: 3, background: s.color, borderRadius: 2 }} />
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", color: "var(--text-body)" }}>{s.label}</span>
          <DeltaValue value={net(s, mk)} invert={TREND_METRICS[mk].invert} magnitude="sm" suffix={TREND_METRICS[mk].unit === "%" ? "%" : ""} />
        </span>
      ))}
    </div>
  );

  const ChartPanel = ({ mk, height }: { mk: string; height: number }) => (
    <div style={{ minWidth: 0, background: "var(--surface-card)", border: "1px solid var(--border-hair)", borderRadius: "var(--r-3)", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: "var(--t-h3)", letterSpacing: "0.03em", textTransform: "uppercase", color: "var(--text-strong)" }}>
          {TREND_METRICS[mk].label}
        </span>
        <Badge tone={TREND_METRICS[mk].invert ? "neg" : "komodo"}>{TREND_METRICS[mk].invert ? "lower better" : "higher better"}</Badge>
      </div>
      <Legend mk={mk} />
      <TrendChart height={height} yUnit={TREND_METRICS[mk].unit === "%" ? "%" : ""} xLabels={gameLabels} series={seriesFor(mk)} area={chosen.length <= 2 && mode === "single"} />
    </div>
  );

  return (
    <div data-evidence-trends style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Controls */}
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", background: "var(--surface-raised)", border: "1px solid var(--border-hair)", borderRadius: "var(--r-3)", padding: "12px 16px" }}>
        <TrendCtl label="Scope">
          <Button variant={scope === "team" ? "primary" : "ghost"} active={scope === "team"} onClick={() => setScope("team")}>
            Teams
          </Button>
          <Button variant={scope === "player" ? "primary" : "ghost"} active={scope === "player"} onClick={() => setScope("player")}>
            Players
          </Button>
        </TrendCtl>
        <TrendSep />
        <TrendCtl label="Layout">
          <Button variant={mode === "single" ? "primary" : "ghost"} active={mode === "single"} onClick={() => setMode("single")}>
            One stat
          </Button>
          <Button variant={mode === "four" ? "primary" : "ghost"} active={mode === "four"} onClick={() => setMode("four")}>
            Four stats
          </Button>
        </TrendCtl>
        {mode === "single" && (
          <>
            <TrendSep />
            <TrendCtl label="Metric">
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {TREND_METRIC_KEYS.map((k) => (
                  <Button key={k} variant={metric === k ? "amber" : "ghost"} active={metric === k} onClick={() => setMetric(k)}>
                    {TREND_METRICS[k].label}
                  </Button>
                ))}
              </div>
            </TrendCtl>
          </>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, alignItems: "start" }}>
        {/* Subject rail */}
        <aside style={{ background: "var(--surface-card)", border: "1px solid var(--border-hair)", borderRadius: "var(--r-3)", padding: "12px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 4 }}>
            {scope === "team" ? "Teams" : "Players"} · pick up to 4
          </div>
          {pool.map((s) => {
            const on = picked.includes(s.id);
            return (
              <button
                key={s.id}
                onClick={() => toggle(s.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  cursor: "pointer",
                  background: on ? "var(--surface-hover)" : "transparent",
                  border: `1px solid ${on ? "var(--border-line)" : "transparent"}`,
                  borderRadius: "var(--r-2)",
                  textAlign: "left",
                }}
              >
                <span style={{ width: 10, height: 10, borderRadius: 2, background: on ? s.color : "var(--surface-inset)", border: on ? "none" : "1px solid var(--border-line)", flex: "none" }} />
                <TeamTag team={s.tag} size="sm" />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)", color: on ? "var(--text-strong)" : "var(--text-muted)" }}>{s.label}</span>
              </button>
            );
          })}
        </aside>

        {/* Charts */}
        {mode === "single" ? (
          <ChartPanel mk={metric} height={320} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, minWidth: 0 }}>
            {TREND_FOUR.map((mk) => (
              <ChartPanel key={mk} mk={mk} height={170} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function FourVFourEvidence() {
  const [ledger, setLedger] = useState<ValidationLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [view, setView] = useState<View>(initialView);
  const url = useMemo(dataUrl, []);

  const onView = (v: View) => {
    setView(v);
    setViewParam(v);
  };

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

  const isTrends = view === "trends";

  return (
    <main data-evidence-scoreboard style={pageStyle}>
      <TopBar game={game} gateGreen={gateGreen} view={view} onView={onView} />
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
            {isTrends ? "4v4 KTX · Trends" : "4v4 KTX · Live Stats Evidence"}
          </h1>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-muted)", letterSpacing: "0.06em" }}>
            {isTrends
              ? `${ledger.games.length} game(s) · oldest → newest`
              : `RUN ${game.run_id} · Δ vs ${game.previous_valid_run_id ?? "baseline"}`}
          </span>
        </div>

        {isTrends ? (
          <TrendsView ledger={ledger} />
        ) : (
          <LiveStats game={game} prev={prev} bench={bench} orderedTeams={orderedTeams} ledger={ledger} url={url} />
        )}
      </div>
    </main>
  );
}

// The live-stats body (banner + team heads + bench + compare + scoreboard +
// footer), factored out so the Trends view can replace it cleanly.
function LiveStats({
  game,
  prev,
  bench,
  orderedTeams,
  ledger,
  url,
}: {
  game: ValidationGame;
  prev: ValidationGame | null;
  bench: BenchAggregate | undefined;
  orderedTeams: Array<{ team: ValidationTeam; tone: SideTone }>;
  ledger: ValidationLedger;
  url: string;
}) {
  return (
    <>
        <MatchBanner game={game} bench={bench} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {orderedTeams.map(({ team, tone }, pos) => (
            <TeamHead
              key={team.name}
              game={game}
              prevGame={prev}
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
            game={game}
            prevGame={prev}
            left={orderedTeams[0].team}
            right={orderedTeams[1].team}
            prevLeft={prev?.teams.find((t) => t.name === orderedTeams[0].team.name) ?? null}
            prevRight={prev?.teams.find((t) => t.name === orderedTeams[1].team.name) ?? null}
          />
        )}

        <Scoreboard game={game} prev={prev} />

        <footer style={{ borderTop: "1px solid var(--border-hair)", paddingTop: 12, fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)", lineHeight: 1.6 }}>
          <div>
            <span style={{ color: "var(--leap)" }}>LEAP (orange) = trained KomodoBots</span> ·{" "}
            <span style={{ color: "var(--frog)" }}>FROG (green) = frogbots</span> · Avg/Max spd in qu/s ·
            TK = team kills · Team dmg = damage dealt to own team (lower is better) · TTD = damage taken per death ·
            RL kills = enemies carrying RL killed · RL drop = rocket launchers dropped · Q/P/R = quad / pent / ring
            pickups ·{" "}
            <span style={{ color: "var(--pos-500)" }}>▲ green improved</span> /{" "}
            <span style={{ color: "var(--neg-500)" }}>▼ red regressed</span> vs previous valid game.
          </div>
          <div style={{ marginTop: 4 }}>
            Source: {ledger.schema} · {url}
            {ledger.invalid_games?.length ? ` · ${ledger.invalid_games.length} invalid game(s) hidden` : ""}
          </div>
        </footer>
    </>
  );
}
