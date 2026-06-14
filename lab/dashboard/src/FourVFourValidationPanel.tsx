// LD-H3.4 (#180): fixed-roster 4v4 validation dashboard panel.
//
// Fetches the BotLab validation ledger from /demos/records/4v4-validation.json.
// For local/browser QA, ?fixture=4v4 switches to the committed static fixture
// under public/data/4v4-validation.example.json; production does not silently
// fall back to fixture data.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useShellActions } from "./App.tsx";

type DeltaScope = "no_previous" | "same-version" | "cross-version" | string;

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
  games: ValidationGame[];
  invalid_games: Array<{ run_id: string; reasons: string[] }>;
  provenance: {
    valid_games: number;
    runs_scanned: number;
    skipped: Record<string, number>;
  };
}

const PRIMARY_URL = "/demos/records/4v4-validation.json";
const FIXTURE_URL = "/botlab/data/4v4-validation.example.json";
const HIGHER_IS_BAD = new Set(["deaths", "team_kills", "damage_taken", "team_weapon_damage"]);

const METRICS: Array<{ key: string; label: string; kind?: "percent" | "number" }> = [
  { key: "deaths", label: "Deaths" },
  { key: "efficiency", label: "Eff", kind: "percent" },
  { key: "team_kills", label: "TK" },
  { key: "health_pickups", label: "HP" },
  { key: "quad_pickups", label: "Q" },
  { key: "pent_pickups", label: "P" },
  { key: "ring_pickups", label: "R" },
  { key: "taken_to_die", label: "TTD" },
  { key: "damage_done", label: "Dmg+" },
  { key: "damage_taken", label: "Dmg-" },
];

function dataUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("validation");
  if (explicit) return explicit;
  return params.get("fixture") === "4v4" ? FIXTURE_URL : PRIMARY_URL;
}

function latestGame(ledger: ValidationLedger): ValidationGame | null {
  return ledger.games.length > 0 ? ledger.games[ledger.games.length - 1] : null;
}

function playersForTeam(game: ValidationGame, teamName: string): ValidationPlayer[] {
  return game.players
    .filter((player) => (player.roster.team || player.identity.team) === teamName)
    .sort((a, b) => a.slot - b.slot);
}

function metricValue(player: ValidationPlayer, key: string): number | null {
  const value = player.stats[key];
  return typeof value === "number" ? value : null;
}

function fmtValue(value: number | null, kind: "percent" | "number" = "number"): string {
  if (value == null) return "unavailable";
  if (kind === "percent") return `${Math.round(value * 100)}%`;
  if (Math.abs(value) >= 100) return Math.round(value).toString();
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function deltaTone(metric: string, value: number | null): "good" | "bad" | "neutral" | "none" {
  if (value == null) return "none";
  if (value === 0) return "neutral";
  const better = HIGHER_IS_BAD.has(metric) ? value < 0 : value > 0;
  return better ? "good" : "bad";
}

function deltaLabel(delta: DeltaEntry | undefined, kind: "percent" | "number" = "number"): string {
  if (!delta || delta.value == null || delta.scope === "no_previous") return "";
  const value = delta.value;
  const sign = value > 0 ? "+" : "";
  if (kind === "percent") return `${sign}${Math.round(value * 100)}%`;
  return Number.isInteger(value) ? `${sign}${value}` : `${sign}${value.toFixed(1)}`;
}

function deltaClass(metric: string, delta: DeltaEntry | undefined): string {
  const tone = deltaTone(metric, delta?.value ?? null);
  switch (tone) {
    case "good": return "text-green-300 bg-green-950/50 border-green-800";
    case "bad": return "text-red-300 bg-red-950/50 border-red-800";
    case "neutral": return "text-gray-500 bg-slate-900 border-slate-700";
    case "none": return "text-gray-700 bg-slate-950 border-slate-800";
  }
}

function scopeLabel(scope: DeltaScope | undefined): string {
  if (scope === "same-version") return "same";
  if (scope === "cross-version") return "cross";
  return "base";
}

function DeltaPill({
  metric,
  delta,
  kind = "number",
}: {
  metric: string;
  delta: DeltaEntry | undefined;
  kind?: "percent" | "number";
}) {
  const label = deltaLabel(delta, kind);
  if (!label) {
    return (
      <span className="text-[9px] px-1 py-0.5 rounded border border-slate-800 text-gray-700">
        base
      </span>
    );
  }
  const rawDelta = delta?.value ?? 0;
  const arrow = rawDelta > 0 ? "↑" : rawDelta < 0 ? "↓" : "•";
  return (
    <span
      className={`text-[9px] px-1 py-0.5 rounded border font-mono ${deltaClass(metric, delta)}`}
      title={`${scopeLabel(delta?.scope)} version delta`}
    >
      {arrow} {label}
    </span>
  );
}

function StatCell({
  player,
  metric,
  label,
  kind = "number",
}: {
  player: ValidationPlayer;
  metric: string;
  label: string;
  kind?: "percent" | "number";
}) {
  const value = metricValue(player, metric);
  const unavailable = value == null;
  return (
    <div
      className="min-w-0"
      title={unavailable ? `${label} unavailable from KTX source` : `${label}: ${fmtValue(value, kind)}`}
    >
      <div className="flex items-center gap-x-1">
        <span className="text-[9px] text-gray-600 uppercase w-8 shrink-0">{label}</span>
        <span className={unavailable ? "text-[10px] text-gray-700 truncate" : "text-[10px] font-mono text-gray-300"}>
          {fmtValue(value, kind)}
        </span>
        <span className="ml-auto">
          <DeltaPill metric={metric} delta={player.deltas[metric]} kind={kind} />
        </span>
      </div>
    </div>
  );
}

function BotRow({ player }: { player: ValidationPlayer }) {
  const tracked = player.roster.role === "komodobot";
  const frags = metricValue(player, "frags");
  return (
    <div
      data-validation-bot={player.slot}
      data-validation-role={player.roster.role}
      className={`rounded border px-2 py-1.5 ${
        tracked
          ? "border-amber-600/70 bg-amber-950/20"
          : "border-slate-800 bg-slate-950/30"
      }`}
    >
      <div className="flex items-center gap-x-2">
        <span className="text-[10px] text-gray-500 font-mono w-5">#{player.slot}</span>
        <span className="text-xs text-gray-300 truncate flex-1" title={player.roster.name}>
          {player.roster.name}
        </span>
        {tracked && (
          <span className="text-[9px] uppercase text-amber-300 border border-amber-700 rounded px-1">
            dev
          </span>
        )}
      </div>
      <div className="flex items-center gap-x-2 mt-1">
        <div className="shrink-0">
          <div className="text-[9px] uppercase text-gray-600">Frags</div>
          <div className="text-lg leading-none font-mono font-semibold text-sky-200">
            {frags == null ? "—" : frags}
          </div>
        </div>
        <div className="flex-1">
          <DeltaPill metric="frags" delta={player.deltas.frags} />
        </div>
        <div className="text-[9px] text-gray-600 font-mono truncate max-w-[80px]" title={player.roster.controller_version ?? ""}>
          {player.roster.controller_version ?? "unknown"}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-y-0.5 mt-1">
        {METRICS.map((metric) => (
          <StatCell
            key={metric.key}
            player={player}
            metric={metric.key}
            label={metric.label}
            kind={metric.kind}
          />
        ))}
      </div>
    </div>
  );
}

function TeamSection({ game, team }: { game: ValidationGame; team: ValidationTeam }) {
  const players = playersForTeam(game, team.name);
  return (
    <section data-validation-team={team.name} className="flex flex-col gap-y-1">
      <div className="flex items-center gap-x-2 px-1 text-[10px] font-mono text-gray-500">
        <span className="text-gray-300">{team.name}</span>
        <span>score {team.score}</span>
        <span>dmg {team.totals.damage_done ?? "—"}</span>
      </div>
      {players.map((player) => (
        <BotRow key={player.id} player={player} />
      ))}
    </section>
  );
}

export function FourVFourValidationPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const shell = useShellActions();
  const [ledger, setLedger] = useState<ValidationLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      name: `4v4·${game.run_id}`,
    });
  }, [game, shell]);

  if (loading) {
    return (
      <div data-section="4v4-validation" className="px-2 py-2 text-[10px] text-gray-600 animate-pulse">
        loading 4v4 validation…
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
            {game.match.map} · {game.match.duration}s · {game.run_id}
          </div>
        </div>
        {game.demo?.url && (
          <button
            type="button"
            onClick={openDemo}
            className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-gray-400 hover:text-gray-200"
            title={game.demo.name ?? "open demo"}
          >
            demo
          </button>
        )}
      </div>

      <div className="flex items-center gap-x-2 px-2 text-[9px] text-gray-600">
        <span className="text-green-300">green improved</span>
        <span className="text-red-300">red regressed</span>
        <span>{ledger.invalid_games.length} invalid hidden</span>
      </div>

      {game.teams.map((team) => (
        <TeamSection key={team.name} game={game} team={team} />
      ))}
    </div>
  );
}
