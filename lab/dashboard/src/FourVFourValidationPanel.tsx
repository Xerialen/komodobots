// LD-H3.4 (#180): fixed-roster 4v4 validation dashboard panel.
//
// Fetches the BotLab validation ledger from /demos/records/4v4-validation.json.
// For local/browser QA, ?fixture=4v4 switches to the committed static fixture
// under public/data/4v4-validation.example.json; production does not silently
// fall back to fixture data.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useShellActions } from "./App.tsx";

type DeltaScope = "no_previous" | "same-version" | "cross-version" | string;
type MetricKind = "percent" | "number";
type TabId = "latest" | "trends";

interface DeltaEntry {
  current: number | null;
  previous: number | null;
  value: number | null;
  scope: DeltaScope;
}

interface ValidationPlayer {
  slot: number;
  id: string;
  identity: {
    name: string;
    team: string;
  };
  roster: {
    id: string;
    name: string;
    team: string;
    role: string;
    bot_kind: string | null;
    bot_skill: number | null;
    controller_version: string | null;
    tracked: boolean;
  };
  stats: Record<string, number | boolean | null>;
  deltas: Record<string, DeltaEntry>;
}

interface ValidationTeam {
  name: string;
  score: number;
  player_count: number;
  totals: Record<string, number | null>;
}

interface ValidationGame {
  run_id: string;
  previous_valid_run_id: string | null;
  demo?: {
    name: string | null;
    url: string | null;
  };
  match: {
    map: string;
    mode: string;
    duration: number;
    demo?: string | null;
  };
  teams: ValidationTeam[];
  players: ValidationPlayer[];
}

interface ValidationLedger {
  schema: string;
  metrics?: string[];
  games: ValidationGame[];
  invalid_games: Array<{ run_id: string; reasons: string[] }>;
  provenance: {
    valid_games: number;
    runs_scanned: number;
    skipped: Record<string, number>;
  };
}

interface MetricDef {
  key: string;
  label: string;
  title: string;
  kind?: MetricKind;
  precision?: number;
}

const PRIMARY_URL = "/demos/records/4v4-validation.json";
const FIXTURE_URL = "/botlab/data/4v4-validation.example.json";

const HIGHER_IS_BAD = new Set(["deaths", "team_kills", "damage_taken", "team_weapon_damage", "rl_drops"]);

const STAT_COLUMNS: MetricDef[] = [
  { key: "frags", label: "Frg", title: "Frags" },
  { key: "deaths", label: "Dth", title: "Deaths" },
  { key: "efficiency", label: "Eff", title: "Efficiency", kind: "percent" },
  { key: "team_kills", label: "TK", title: "Team kills" },
  { key: "taken_to_die", label: "to-die", title: "Damage taken per death", precision: 0 },
  { key: "damage_done", label: "Dmg+", title: "Damage done" },
  { key: "damage_taken", label: "Dmg-", title: "Damage taken" },
  { key: "enemy_rl_kills", label: "RL EK", title: "Enemies carrying RL killed" },
  { key: "avg_speed", label: "AvgSpd", title: "Average horizontal speed", precision: 0 },
  { key: "max_speed", label: "MaxSpd", title: "Max horizontal speed", precision: 0 },
];

const PICKUP_COLUMNS: MetricDef[] = [
  { key: "pill_pickups", label: "Pills", title: "Health 15 pickups" },
  { key: "brick_pickups", label: "Bricks", title: "Health 25 pickups" },
  { key: "mega_pickups", label: "Mega", title: "Mega health pickups" },
  { key: "ya_pickups", label: "YA", title: "Yellow armor pickups" },
  { key: "ra_pickups", label: "RA", title: "Red armor pickups" },
  { key: "lg_pickups", label: "LG", title: "Lightning gun pickups" },
  { key: "rl_pickups", label: "RL", title: "Rocket launcher pickups" },
  { key: "quad_pickups", label: "Q", title: "Quad pickups" },
  { key: "pent_pickups", label: "P", title: "Pentagram pickups" },
  { key: "ring_pickups", label: "R", title: "Ring pickups" },
  { key: "rl_drops", label: "RL drop", title: "Rocket launcher drops" },
];

const TREND_COLUMNS: MetricDef[] = [
  ...STAT_COLUMNS,
  ...PICKUP_COLUMNS.filter((metric) => !["quad_pickups", "pent_pickups", "ring_pickups", "rl_drops"].includes(metric.key)),
];

const METRIC_BY_KEY = new Map(TREND_COLUMNS.map((metric) => [metric.key, metric]));
const DEFAULT_TREND_KEYS = ["frags", "damage_done", "enemy_rl_kills", "avg_speed"];
const TREND_COLORS = ["#38bdf8", "#f59e0b", "#34d399", "#f472b6"];

function dataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("validation");
  if (explicit) return explicit;
  return params.get("fixture") === "4v4" ? FIXTURE_URL : PRIMARY_URL;
}

function initialTab(): TabId {
  const params = new URLSearchParams(window.location.search);
  return params.get("validationView") === "trends" ? "trends" : "latest";
}

function latestGame(ledger: ValidationLedger): ValidationGame | null {
  return ledger.games.length > 0 ? ledger.games[ledger.games.length - 1] : null;
}

function playersForTeam(game: ValidationGame, teamName: string): ValidationPlayer[] {
  return game.players
    .filter((player) => (player.roster.team || player.identity.team) === teamName)
    .sort((a, b) => a.slot - b.slot);
}

function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function playerMetricValue(player: ValidationPlayer, key: string): number | null {
  return numeric(player.stats[key]);
}

function teamMetricValue(team: ValidationTeam, key: string): number | null {
  if (key === "frags") return numeric(team.score);
  return numeric(team.totals[key]);
}

function displayName(player: ValidationPlayer): string {
  if (player.roster.tracked || player.roster.role === "komodobot") return "komodo";
  return player.roster.name || player.identity.name || `slot ${player.slot}`;
}

function fmtValue(value: number | null, metric: MetricDef): string {
  if (value == null) return "n/a";
  if (metric.kind === "percent") return `${Math.round(value * 100)}%`;
  if (metric.precision != null) return value.toFixed(metric.precision);
  if (Math.abs(value) >= 100) return Math.round(value).toString();
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function deltaTone(metric: string, value: number | null): "good" | "bad" | "neutral" | "none" {
  if (value == null) return "none";
  if (value === 0) return "neutral";
  const better = HIGHER_IS_BAD.has(metric) ? value < 0 : value > 0;
  return better ? "good" : "bad";
}

function deltaLabel(delta: DeltaEntry | undefined, metric: MetricDef): string {
  if (!delta || delta.value == null || delta.scope === "no_previous") return "";
  const value = delta.value;
  const sign = value > 0 ? "+" : "";
  if (metric.kind === "percent") return `${sign}${Math.round(value * 100)}%`;
  if (metric.precision != null) return `${sign}${value.toFixed(metric.precision)}`;
  return Number.isInteger(value) ? `${sign}${value}` : `${sign}${value.toFixed(1)}`;
}

function deltaClass(metric: string, delta: DeltaEntry | undefined): string {
  const tone = deltaTone(metric, delta?.value ?? null);
  switch (tone) {
    case "good": return "text-green-300";
    case "bad": return "text-red-300";
    case "neutral": return "text-gray-500";
    case "none": return "text-gray-700";
  }
}

function scopeLabel(scope: DeltaScope | undefined): string {
  if (scope === "same-version") return "same version";
  if (scope === "cross-version") return "cross version";
  return "baseline";
}

function MetricTile({
  label,
  value,
  delta,
  metric,
}: {
  label: string;
  value: number | null;
  delta?: DeltaEntry;
  metric: MetricDef;
}) {
  const deltaText = deltaLabel(delta, metric);
  return (
    <div className="min-w-0 border border-slate-800 bg-slate-950/80 px-1 py-1 font-mono" title={metric.title}>
      <div className="truncate text-[8px] uppercase leading-tight text-gray-500">{label}</div>
      <div className="truncate text-[10px] leading-tight text-gray-200">{fmtValue(value, metric)}</div>
      <div className={`truncate text-[9px] leading-tight ${deltaClass(metric.key, delta)}`} title={scopeLabel(delta?.scope)}>
        {delta ? (deltaText || "base") : ""}
      </div>
    </div>
  );
}

function PlayerMetricGrid({ player, metrics }: { player: ValidationPlayer; metrics: MetricDef[] }) {
  return (
    <div className="grid grid-cols-4 gap-1">
      {metrics.map((metric) => (
        <MetricTile
          key={metric.key}
          label={metric.label}
          value={playerMetricValue(player, metric.key)}
          delta={player.deltas[metric.key]}
          metric={metric}
        />
      ))}
    </div>
  );
}

function TeamMetricGrid({ team, metrics }: { team: ValidationTeam; metrics: MetricDef[] }) {
  return (
    <div className="grid grid-cols-4 gap-1">
      {metrics.map((metric) => (
        <MetricTile
          key={metric.key}
          label={metric.label}
          value={teamMetricValue(team, metric.key)}
          metric={metric}
        />
      ))}
    </div>
  );
}

function MetricTable({
  title,
  team,
  players,
  metrics,
}: {
  title: string;
  team: ValidationTeam;
  players: ValidationPlayer[];
  metrics: MetricDef[];
}) {
  return (
    <div className="border border-slate-800 bg-slate-950/30" data-validation-table={title}>
      <div className="border-b border-slate-800 bg-slate-900/70 px-2 py-1 text-[9px] font-semibold uppercase text-gray-500">
        {title}
      </div>
      <div className="flex flex-col gap-y-1 p-1">
        <div className="border-b border-slate-800/80 bg-slate-900/40 px-1 pb-1">
          <div className="mb-1 text-[10px] font-semibold text-slate-300">team total</div>
          <TeamMetricGrid team={team} metrics={metrics} />
        </div>
        {players.map((player) => {
          const tracked = player.roster.tracked || player.roster.role === "komodobot";
          return (
            <div
              key={`${title}-${player.id}`}
              data-validation-bot={player.slot}
              data-validation-tracked={tracked ? "true" : "false"}
              className={`px-1 py-1 ${tracked ? "bg-amber-950/30" : "bg-slate-950/30"}`}
            >
              <div className={`mb-1 truncate text-[10px] font-semibold ${tracked ? "text-amber-200" : "text-gray-300"}`}>
                <span className="mr-1 font-mono text-gray-500">#{player.slot}</span>
                <span title={player.roster.name || player.identity.name}>{displayName(player)}</span>
              </div>
              <PlayerMetricGrid player={player} metrics={metrics} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TeamSection({ game, team }: { game: ValidationGame; team: ValidationTeam }) {
  const players = playersForTeam(game, team.name);
  return (
    <section data-validation-team={team.name} className="flex flex-col gap-y-1.5">
      <div className="flex items-center gap-x-2 px-1 text-[10px] font-mono text-gray-500">
        <span className="text-xs font-semibold text-gray-200">{team.name}</span>
        <span>score {team.score}</span>
        <span>{team.player_count} players</span>
      </div>
      <MetricTable title="stats" team={team} players={players} metrics={STAT_COLUMNS} />
      <MetricTable title="pickups" team={team} players={players} metrics={PICKUP_COLUMNS} />
    </section>
  );
}

function trendSlot(game: ValidationGame): number | null {
  const tracked = game.players.find((player) => player.roster.tracked || player.roster.role === "komodobot");
  return tracked?.slot ?? game.players[0]?.slot ?? null;
}

function trendRows(ledger: ValidationLedger, slot: number, metricKeys: string[]) {
  return ledger.games.map((game, index) => {
    const player = game.players.find((candidate) => candidate.slot === slot);
    const values: Record<string, number | null> = {};
    for (const key of metricKeys) values[key] = player ? playerMetricValue(player, key) : null;
    return {
      index,
      run_id: game.run_id,
      label: game.run_id.replace(/^.*?(\d{8}T\d{4}).*$/, "$1"),
      values,
    };
  });
}

function linePoints(rows: ReturnType<typeof trendRows>, key: string, width: number, height: number): string {
  const values = rows.map((row) => row.values[key]).filter((value): value is number => value != null);
  if (rows.length === 0 || values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min;
  return rows.map((row, index) => {
    const value = row.values[key];
    const x = rows.length === 1 ? width / 2 : (index / (rows.length - 1)) * width;
    const normalized = value == null ? 0.5 : spread === 0 ? 0.5 : (value - min) / spread;
    const y = height - normalized * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function TrendView({ ledger, game }: { ledger: ValidationLedger; game: ValidationGame }) {
  const slot = trendSlot(game);
  const [selected, setSelected] = useState<string[]>(DEFAULT_TREND_KEYS);
  const activeMetrics = selected
    .map((key) => METRIC_BY_KEY.get(key))
    .filter((metric): metric is MetricDef => Boolean(metric));
  const rows = slot == null ? [] : trendRows(ledger, slot, selected);
  const width = 320;
  const height = 120;
  const toggleMetric = (key: string) => {
    setSelected((current) => {
      if (current.includes(key)) return current.length === 1 ? current : current.filter((item) => item !== key);
      if (current.length >= 4) return current;
      return [...current, key];
    });
  };

  return (
    <div className="flex flex-col gap-y-2 px-2 pb-2" data-validation-view="trends">
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
        {TREND_COLUMNS.map((metric) => {
          const active = selected.includes(metric.key);
          const disabled = !active && selected.length >= 4;
          return (
            <button
              key={metric.key}
              type="button"
              onClick={() => toggleMetric(metric.key)}
              disabled={disabled}
              className={`px-2 py-1 text-left text-[10px] border ${
                active
                  ? "border-sky-600 bg-sky-950/50 text-sky-200"
                  : "border-slate-800 bg-slate-950 text-gray-500 disabled:text-gray-800"
              }`}
              title={metric.title}
            >
              {metric.label}
            </button>
          );
        })}
      </div>

      <div className="border border-slate-800 bg-slate-950/50 px-2 py-2">
        <div className="mb-1 flex items-center justify-between gap-x-2 text-[10px] text-gray-500">
          <span>slot {slot ?? "n/a"} trend</span>
          <span>{ledger.games.length} valid games</span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Selected 4v4 stat trends" className="h-32 w-full overflow-visible">
          <line x1="0" y1={height} x2={width} y2={height} stroke="#334155" strokeWidth="1" />
          <line x1="0" y1="0" x2="0" y2={height} stroke="#334155" strokeWidth="1" />
          {activeMetrics.map((metric, index) => {
            const points = linePoints(rows, metric.key, width, height);
            return points ? (
              <polyline
                key={metric.key}
                points={points}
                fill="none"
                stroke={TREND_COLORS[index % TREND_COLORS.length]}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null;
          })}
        </svg>
        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1">
          {activeMetrics.map((metric, index) => (
            <span key={metric.key} className="text-[10px] font-mono" style={{ color: TREND_COLORS[index % TREND_COLORS.length] }}>
              {metric.label}
            </span>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto border border-slate-800">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/70 text-[9px] uppercase text-gray-500">
              <th className="px-2 py-1 text-left">run</th>
              {activeMetrics.map((metric) => (
                <th key={metric.key} className="px-2 py-1 text-right">{metric.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(-8).map((row) => (
              <tr key={row.run_id} className="border-b border-slate-900 last:border-b-0">
                <td className="px-2 py-1 text-left font-mono text-gray-500" title={row.run_id}>{row.label}</td>
                {activeMetrics.map((metric) => (
                  <td key={metric.key} className="px-2 py-1 text-right font-mono text-gray-300">
                    {fmtValue(row.values[metric.key], metric)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function FourVFourValidationPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const shell = useShellActions();
  const [ledger, setLedger] = useState<ValidationLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>(() => initialTab());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(dataUrl())
      .then((res) => {
        if (!res.ok) throw new Error(`4v4-validation.json ${res.status}`);
        return res.json() as Promise<ValidationLedger>;
      })
      .then((data) => {
        if (cancelled) return;
        setLedger(data);
        setLoading(false);
      })
      .catch((exc) => {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : "validation ledger unavailable");
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const game = useMemo(() => (ledger ? latestGame(ledger) : null), [ledger]);
  const openDemo = useCallback(() => {
    if (!shell || !game?.demo?.url) return;
    shell.openDemo({
      demo_url: game.demo.url,
      map: game.match.map,
      t: null,
      route: null,
      name: `4v4-${game.run_id}`,
    });
  }, [game, shell]);

  if (loading) {
    return (
      <div data-section="4v4-validation" className="px-2 py-2 text-[10px] text-gray-600 animate-pulse">
        loading 4v4 validation...
      </div>
    );
  }

  if (error || !ledger) {
    return (
      <div data-section="4v4-validation" data-validation-state="error" className="px-2 py-2 text-[10px] text-amber-700">
        4v4 validation unavailable
      </div>
    );
  }

  if (!game) {
    return (
      <div data-section="4v4-validation" data-validation-state="empty" className="px-2 py-2 text-[10px] text-gray-600">
        no valid 4v4 games yet
      </div>
    );
  }

  return (
    <div data-section="4v4-validation" className="flex flex-col gap-y-2">
      <div className="flex items-center gap-x-2 px-2 py-1 border-b border-slate-800">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase text-gray-500">4v4 Validation</div>
          <div className="text-[10px] font-mono text-gray-400 truncate" title={game.run_id}>
            {game.match.map} / {game.match.duration}s / {game.run_id}
          </div>
        </div>
        <div className="flex shrink-0 overflow-hidden border border-slate-800">
          {(["latest", "trends"] as TabId[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setTab(item)}
              className={`px-2 py-1 text-[10px] uppercase ${tab === item ? "bg-sky-950 text-sky-200" : "bg-slate-950 text-gray-500"}`}
            >
              {item}
            </button>
          ))}
        </div>
        {game.demo?.url && (
          <button
            type="button"
            onClick={openDemo}
            className="text-[10px] px-1.5 py-1 border border-slate-700 text-gray-400 hover:text-gray-200"
            title={game.demo.name ?? "open demo"}
          >
            demo
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-2 text-[9px] text-gray-600">
        <span className="text-green-300">green improved</span>
        <span className="text-red-300">red regressed</span>
        <span>delta vs {game.previous_valid_run_id ?? "baseline"}</span>
        <span>{ledger.invalid_games.length} invalid hidden</span>
      </div>

      {tab === "latest" ? (
        <div className="flex flex-col gap-y-2 px-2 pb-2" data-validation-view="latest">
          {game.teams.map((team) => (
            <TeamSection key={team.name} game={game} team={team} />
          ))}
        </div>
      ) : (
        <TrendView ledger={ledger} game={game} />
      )}
    </div>
  );
}
