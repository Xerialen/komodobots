// LD-H3 (#200): full-page "4v4 KTX Live Stats Evidence" report.
//
// Restores the wide-table evidence layout — the canonical wireframe in issue
// #200 — on top of the existing komodobots.4v4_validation.v1 ledger. This is a
// standalone, OBS/report-friendly surface (light "evidence sheet" theme),
// separate from the BotLab control shell, reached at /botlab/?evidence=1.
//   ?fixture=4v4        -> committed example ledger (public/data)
//   ?validation=<url>   -> explicit ledger source
// Deltas are computed here against the previous valid game
// (previous_valid_run_id), so both the team summary cards and the per-bot table
// show change-vs-previous exactly like the wireframe. The page polls every 15s
// so it tracks a live run as new valid games land in the ledger.

import { useEffect, useMemo, useState } from "react";

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
  title: string;
  kind?: MetricKind;
  precision?: number;
}

interface TeamTone {
  tag: string;
  side: string;
  text: string;
  chip: string;
  soft: string;
  ring: string;
}

const PRIMARY_URL = "/demos/records/4v4-validation.json";
const FIXTURE_URL = "/botlab/data/4v4-validation.example.json";
const REFRESH_MS = 15000;

// Lower-is-better metrics: a negative change-vs-previous is an improvement.
const HIGHER_IS_BAD = new Set([
  "deaths",
  "team_kills",
  "damage_taken",
  "team_weapon_damage",
  "rl_drops",
]);

// Per-bot table columns, in wireframe order.
const BOT_COLUMNS: MetricDef[] = [
  { key: "frags", label: "Frags", title: "Frags" },
  { key: "deaths", label: "Deaths", title: "Deaths" },
  { key: "efficiency", label: "Eff", title: "Efficiency", kind: "percent" },
  { key: "team_kills", label: "TK", title: "Team kills" },
  { key: "health_pickups", label: "Health", title: "Health pickups" },
  { key: "quad_pickups", label: "Quad", title: "Quad pickups" },
  { key: "pent_pickups", label: "Pent", title: "Pentagram pickups" },
  { key: "ring_pickups", label: "Ring", title: "Ring (eyes) pickups" },
  { key: "enemy_rl_kills", label: "RL kills", title: "Enemies carrying RL killed" },
  { key: "rl_drops", label: "RL drop", title: "Rocket launchers dropped" },
  { key: "taken_to_die", label: "TTD", title: "Damage taken per death", precision: 0 },
  { key: "damage_done", label: "Dmg done", title: "Damage done" },
  { key: "damage_taken", label: "Dmg taken", title: "Damage taken" },
  { key: "avg_speed", label: "Avg spd", title: "Average speed (qu/s)", precision: 0 },
  { key: "max_speed", label: "Max spd", title: "Peak speed (qu/s)", precision: 0 },
];

// Team summary card metrics (score is handled separately, powerups inline).
const TEAM_METRICS: MetricDef[] = [
  { key: "efficiency", label: "Efficiency", title: "Team efficiency", kind: "percent" },
  { key: "damage_done", label: "Damage given", title: "Team damage done" },
  { key: "damage_taken", label: "Damage taken", title: "Team damage taken" },
  { key: "health_pickups", label: "Health pickup", title: "Team health pickups" },
];

const POWERUP_KEYS = ["quad_pickups", "pent_pickups", "ring_pickups"];

// teams[0] renders RED (the LEAP / trained side), teams[1] BLUE (FROG controls) —
// matching the wireframe and the bench leap_team/frog_team convention. Team is the
// visual differentiator: a whole side is the trained bots, so no single row is
// singled out anymore.
const TEAM_TONES: TeamTone[] = [
  { tag: "RED", side: "LEAP", text: "text-red-700", chip: "bg-red-600", soft: "bg-red-50", ring: "border-red-200" },
  { tag: "BLUE", side: "FROG", text: "text-blue-700", chip: "bg-blue-600", soft: "bg-blue-50", ring: "border-blue-200" },
];

// Resolve the LEAP/FROG side per team name, preferring the per-game bench
// resolution and falling back to the wireframe order (teams[0] = leap).
function sideForTeam(game: ValidationGame, teamName: string, teamIdx: number): string {
  const leap = game.bench?.leap_team;
  const frog = game.bench?.frog_team;
  if (leap && teamName === leap) return "LEAP";
  if (frog && teamName === frog) return "FROG";
  return teamIdx === 0 ? "LEAP" : "FROG";
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
  if (Math.abs(value) >= 100) return Math.round(value).toString();
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function deltaText(delta: number | null, metric?: MetricDef): string {
  if (delta == null || delta === 0) return "";
  const sign = delta > 0 ? "+" : "";
  if (metric?.kind === "percent") return `${sign}${Math.round(delta * 100)}%`;
  if (metric?.precision != null) return `${sign}${delta.toFixed(metric.precision)}`;
  return Number.isInteger(delta) ? `${sign}${delta}` : `${sign}${delta.toFixed(1)}`;
}

function deltaToneClass(metricKey: string, delta: number | null): string {
  if (delta == null || delta === 0) return "text-neutral-400";
  const better = HIGHER_IS_BAD.has(metricKey) ? delta < 0 : delta > 0;
  return better ? "text-green-600" : "text-red-600";
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

function orderedPlayers(game: ValidationGame): Array<{ player: ValidationPlayer; teamIdx: number }> {
  const out: Array<{ player: ValidationPlayer; teamIdx: number }> = [];
  game.teams.forEach((team, teamIdx) => {
    game.players
      .filter((p) => (p.roster.team || p.identity.team) === team.name)
      .sort((a, b) => a.slot - b.slot)
      .forEach((player) => out.push({ player, teamIdx }));
  });
  return out;
}

function DeltaSpan({ metricKey, delta, metric }: { metricKey: string; delta: number | null; metric?: MetricDef }) {
  const text = deltaText(delta, metric);
  if (!text) return null;
  return <span className={`ml-1 text-[11px] font-mono ${deltaToneClass(metricKey, delta)}`}>{text}</span>;
}

function TeamCard({ team, prev, tone, side }: { team: ValidationTeam; prev: ValidationTeam | null; tone: TeamTone; side: string }) {
  const scoreDelta = prev ? team.score - prev.score : null;
  const powerups = POWERUP_KEYS.map((k) => num(team.totals[k]) ?? 0);
  return (
    <section
      className={`rounded-md border ${tone.ring} ${tone.soft} px-4 py-3`}
      data-evidence-team={team.name}
      data-evidence-side={side}
    >
      <div className="flex items-center justify-between gap-x-3">
        <div className="min-w-0">
          <span className={`text-sm font-bold uppercase tracking-wide ${tone.text}`}>{tone.tag} team</span>
          <span className={`ml-2 text-[10px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 text-white ${tone.chip}`}>
            {side}
          </span>
          <span className="ml-2 text-xs text-neutral-500">
            {team.name} · {team.player_count} players
          </span>
        </div>
        <div className="flex items-baseline whitespace-nowrap">
          <span className="text-xs uppercase text-neutral-400 mr-1">Score</span>
          <span className="text-3xl font-bold font-mono text-neutral-900">{team.score}</span>
          <DeltaSpan metricKey="frags" delta={scoreDelta} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-5">
        {TEAM_METRICS.map((m) => (
          <div key={m.key} title={m.title}>
            <div className="text-[10px] uppercase tracking-wide text-neutral-500">{m.label}</div>
            <div className="font-mono text-sm text-neutral-900">
              {fmt(num(team.totals[m.key]), m)}
              <DeltaSpan metricKey={m.key} delta={teamDelta(team, prev, m.key)} metric={m} />
            </div>
          </div>
        ))}
        <div title="Quad / Pentagram / Ring pickups">
          <div className="text-[10px] uppercase tracking-wide text-neutral-500">Powerup Q/P/R</div>
          <div className="font-mono text-sm text-neutral-900">{powerups.join(" / ")}</div>
        </div>
      </div>
    </section>
  );
}

function BotTable({ game, prev }: { game: ValidationGame; prev: ValidationGame | null }) {
  const rows = orderedPlayers(game);
  const headCell = "px-2 py-2 text-right font-semibold text-neutral-500";
  return (
    <div className="mt-5 overflow-x-auto rounded-md border border-neutral-200">
      <table className="w-full border-collapse text-xs">
        <caption className="px-2 pt-2 pb-1 text-left text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
          All eight bots — current stat with delta vs previous game
        </caption>
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-[10px] uppercase">
            <th className="px-2 py-2 text-left font-semibold text-neutral-500">Team</th>
            <th className="px-2 py-2 text-right font-semibold text-neutral-500">Slot</th>
            <th className="px-2 py-2 text-left font-semibold text-neutral-500">Bot / build</th>
            <th className="px-2 py-2 text-left font-semibold text-neutral-500">KTX name</th>
            <th className="px-2 py-2 text-left font-semibold text-neutral-500">Role</th>
            {BOT_COLUMNS.map((c) => (
              <th key={c.key} className={headCell} title={c.title}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ player, teamIdx }) => {
            const tone = TEAM_TONES[teamIdx] ?? TEAM_TONES[0];
            const teamName = player.roster.team || player.identity.team;
            const side = sideForTeam(game, teamName, teamIdx);
            const prevPlayer = prev?.players.find((p) => p.slot === player.slot) ?? null;
            return (
              <tr
                key={player.id}
                data-evidence-bot={player.slot}
                data-evidence-side={side}
                className="border-b border-neutral-100 last:border-b-0"
              >
                <td className="px-2 py-1.5 whitespace-nowrap">
                  <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white ${tone.chip}`}>
                    {tone.tag}
                  </span>
                  <span className={`ml-1 text-[10px] font-semibold uppercase ${tone.text}`}>{side}</span>
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-neutral-500">{player.slot}</td>
                <td className="px-2 py-1.5">
                  <div className="font-semibold text-neutral-800">
                    {player.roster.name || player.identity.name}
                  </div>
                  {player.roster.controller_version && (
                    <div className="text-[10px] text-neutral-400">{player.roster.controller_version}</div>
                  )}
                </td>
                <td className="px-2 py-1.5 font-mono text-neutral-600">{player.identity.name}</td>
                <td className="px-2 py-1.5 text-neutral-600">{player.roster.role}</td>
                {BOT_COLUMNS.map((c) => (
                  <td key={c.key} className="px-2 py-1.5 text-right font-mono text-neutral-800 whitespace-nowrap" title={c.title}>
                    {fmt(num(player.stats[c.key]), c)}
                    <DeltaSpan metricKey={c.key} delta={playerDelta(player, prevPlayer, c.key)} metric={c} />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function signedMargin(value: number | null): string {
  if (value == null) return "—";
  const v = Number.isInteger(value) ? `${value}` : value.toFixed(1);
  return value > 0 ? `+${v}` : v;
}

// docs/18 T0.7 headline verdict banner: best-of-N leap-vs-frog frag margin + the
// R-T damage.matrix gate. A negative margin is a valid Phase-0 baseline.
function BenchVerdictBanner({ bench }: { bench: BenchAggregate }) {
  const gate = bench.damage_matrix_gate_pass;
  const total = bench.leap_frag_margin_total;
  const lead = total == null ? "no scored games" : total > 0 ? "leap ahead" : total < 0 ? "leap behind" : "even";
  return (
    <section
      data-evidence-bench
      data-bench-gate={gate ? "green" : "red"}
      className="mt-4 rounded-md border border-neutral-200 bg-neutral-50 px-4 py-3"
    >
      <div className="flex items-center justify-between gap-x-3">
        <div className="min-w-0">
          <span className="text-sm font-bold uppercase tracking-wide text-neutral-700">
            Leap vs Frog — bench (best-of-{bench.games_scored})
          </span>
          <span className="ml-2 text-xs text-neutral-500">win = total frags · {lead}</span>
        </div>
        <span
          className={`text-[11px] font-bold uppercase rounded px-2 py-0.5 ${
            gate ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
          }`}
          title="R-T damage.matrix gate: bots damage the enemy, not their own team"
        >
          R-T gate {gate ? "green" : "RED"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <span className="text-[10px] uppercase tracking-wide text-neutral-500">Frag margin</span>
          <span data-bench-margin-total className="ml-2 text-2xl font-bold font-mono text-neutral-900">
            {signedMargin(total)}
          </span>
          <span className="ml-1 text-xs text-neutral-500">mean {signedMargin(bench.leap_frag_margin_mean)}/game</span>
        </div>
        <div>
          <span className="text-[10px] uppercase tracking-wide text-neutral-500">Game wins</span>
          <span className="ml-2 font-mono text-sm text-neutral-900">leap {bench.leap_wins} – {bench.frog_wins} frog</span>
        </div>
        <div data-bench-series className="flex flex-wrap gap-1">
          {bench.per_game.map((g) => (
            <span
              key={g.run_id}
              title={`${g.run_id}: leap ${g.leap_frags} – ${g.frog_frags} frog`}
              className={`text-[11px] font-mono rounded px-1.5 py-0.5 border ${
                g.frag_margin > 0
                  ? "border-green-200 bg-green-50 text-green-700"
                  : g.frag_margin < 0
                  ? "border-red-200 bg-red-50 text-red-700"
                  : "border-neutral-200 text-neutral-500"
              }`}
            >
              {signedMargin(g.frag_margin)}{g.damage_matrix_gate_pass === false ? " ⚠" : ""}
            </span>
          ))}
        </div>
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

  if (loading) {
    return (
      <main data-evidence-state="loading" className="min-h-screen bg-white text-neutral-900 flex items-center justify-center">
        <span className="text-neutral-400">loading 4v4 validation…</span>
      </main>
    );
  }

  if (error || !ledger) {
    return (
      <main data-evidence-state="error" className="min-h-screen bg-white text-neutral-900 flex items-center justify-center">
        <span className="text-red-600">4v4 validation unavailable — {error ?? "no ledger"}</span>
      </main>
    );
  }

  if (!game) {
    return (
      <main data-evidence-state="empty" className="min-h-screen bg-white text-neutral-900 flex items-center justify-center">
        <span className="text-neutral-400">no valid 4v4 games yet</span>
      </main>
    );
  }

  const demoName = game.demo?.name ?? game.match.demo ?? null;
  return (
    <main data-evidence-scoreboard className="min-h-screen bg-white text-neutral-900 px-6 py-5">
      <header className="border-b border-neutral-200 pb-3">
        <h1 className="text-xl font-bold tracking-tight">4v4 KTX Live Stats Evidence</h1>
        <div className="mt-1 text-xs text-neutral-500 font-mono">
          Run: {game.run_id} · Map: {game.match.map} · {game.match.mode}
          {demoName ? ` · demo ${demoName}` : ""}
        </div>
        <div className="mt-0.5 text-xs text-neutral-500">
          Comparison: current values with change vs previous valid game (
          {game.previous_valid_run_id ?? "none — baseline"})
        </div>
      </header>

      {ledger.bench && ledger.bench.games_scored > 0 && <BenchVerdictBanner bench={ledger.bench} />}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {game.teams.map((team, idx) => (
          <TeamCard
            key={team.name}
            team={team}
            prev={prev?.teams.find((t) => t.name === team.name) ?? null}
            tone={TEAM_TONES[idx] ?? TEAM_TONES[0]}
            side={sideForTeam(game, team.name, idx)}
          />
        ))}
      </div>

      <BotTable game={game} prev={prev} />

      <footer className="mt-5 border-t border-neutral-200 pt-3 text-[11px] text-neutral-400">
        <div>
          Headings: TK = team kills · TTD = damage taken per death · RL kills = enemies carrying RL killed ·
          RL drop = rocket launchers dropped · Q/P/R = quad / pent / ring pickups ·
          Avg/Max spd = average / peak speed in qu/s ·
          <span className="text-red-700"> RED = LEAP (trained)</span> /
          <span className="text-blue-700"> BLUE = FROG (controls)</span> ·
          <span className="text-green-600"> green improved</span> /
          <span className="text-red-600"> red regressed</span> vs previous valid game.
        </div>
        <div className="mt-1">
          Source: {ledger.schema} · {url}
          {ledger.invalid_games?.length ? ` · ${ledger.invalid_games.length} invalid game(s) hidden` : ""}
        </div>
      </footer>
    </main>
  );
}
