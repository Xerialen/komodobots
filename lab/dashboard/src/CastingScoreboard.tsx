// LD-H3.8 (#184): read-only casting scoreboard / OBS browser-source view.
//
// This surface is separate from BotLab controls. It consumes the canonical
// KTX match schema produced by ktx_match_stats / ktx_casting_ingest and renders
// final post-game stats first. Live observer data can later feed the same view
// as provisional rows, but no value is fabricated here.

import { useEffect, useMemo, useState } from "react";

interface CastingPlayer {
  slot: number;
  id: string;
  identity: {
    name: string;
    team: string;
    is_bot: boolean;
  };
  stats: Record<string, number | boolean | null>;
}

interface CastingTeam {
  name: string;
  score: number;
  player_count: number;
  totals: Record<string, number | null>;
}

interface CastingMatchStats {
  schema: string;
  source: {
    kind: string;
    provisional?: boolean;
    final?: boolean;
    casting_read_only?: boolean;
  };
  match: {
    map: string;
    hostname: string;
    mode: string;
    duration: number;
    demo: string | null;
  };
  teams: CastingTeam[];
  players: CastingPlayer[];
  warnings: string[];
}

const DEFAULT_STATS_URL = "/demos/records/latest-ktx-match.json";
const FIXTURE_STATS_URL = "/botlab/data/casting-match.example.json";

function statsUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("stats");
  if (explicit) return explicit;
  return params.get("fixture") === "casting" ? FIXTURE_STATS_URL : DEFAULT_STATS_URL;
}

function playersForTeam(data: CastingMatchStats, teamName: string): CastingPlayer[] {
  return data.players
    .filter((player) => player.identity.team === teamName)
    .sort((a, b) => Number(b.stats.frags ?? 0) - Number(a.stats.frags ?? 0));
}

function numberStat(player: CastingPlayer, key: string): number | null {
  const value = player.stats[key];
  return typeof value === "number" ? value : null;
}

function fmtInt(value: number | null): string {
  return value == null ? "—" : Math.round(value).toString();
}

function fmtPercent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function durationLabel(seconds: number | null | undefined): string {
  if (typeof seconds !== "number") return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function statusLabel(data: CastingMatchStats): string {
  if (data.source.provisional) return "live provisional";
  return "final KTX";
}

function TeamTable({ data, team }: { data: CastingMatchStats; team: CastingTeam }) {
  const players = playersForTeam(data, team.name);
  return (
    <section data-casting-team={team.name} className="min-w-0">
      <div className="flex items-end gap-x-2 border-b border-white/15 pb-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm uppercase tracking-wide text-white/50">Team</div>
          <div className="truncate text-2xl font-semibold text-white" title={team.name}>
            {team.name}
          </div>
        </div>
        <div className="text-5xl leading-none font-mono font-bold text-sky-200">
          {team.score}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-[minmax(72px,1fr)_32px_30px_38px_44px_44px_30px_46px] gap-x-1 text-[10px] uppercase text-white/45">
        <span>Player</span>
        <span className="text-right">Frg</span>
        <span className="text-right">Dth</span>
        <span className="text-right">Eff</span>
        <span className="text-right">Dmg+</span>
        <span className="text-right">Dmg-</span>
        <span className="text-right">RL</span>
        <span className="text-right">Q/P/R</span>
      </div>

      <div className="mt-1 flex flex-col gap-y-1">
        {players.map((player) => (
          <div
            key={player.id}
            data-casting-player={player.identity.name}
            className="grid grid-cols-[minmax(72px,1fr)_32px_30px_38px_44px_44px_30px_46px] gap-x-1 items-center rounded border border-white/10 bg-white/[0.035] px-1.5 py-2"
          >
            <div className="min-w-0">
              <div className="truncate text-sm text-white" title={player.identity.name}>
                {player.identity.name}
              </div>
              <div className="text-[10px] text-white/35">
                hp {fmtInt(numberStat(player, "health_pickups"))}
              </div>
            </div>
            <span className="text-right text-xl font-mono font-semibold text-sky-200">
              {fmtInt(numberStat(player, "frags"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtInt(numberStat(player, "deaths"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtPercent(numberStat(player, "efficiency"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtInt(numberStat(player, "damage_done"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtInt(numberStat(player, "damage_taken"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtInt(numberStat(player, "rl_pickups"))}
            </span>
            <span className="text-right font-mono text-white/75">
              {fmtInt(numberStat(player, "quad_pickups"))}/
              {fmtInt(numberStat(player, "pent_pickups"))}/
              {fmtInt(numberStat(player, "ring_pickups"))}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CastingScoreboard() {
  const [data, setData] = useState<CastingMatchStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const url = useMemo(statsUrl, []);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`casting stats ${res.status}`);
        return res.json() as Promise<CastingMatchStats>;
      })
      .then((json) => {
        if (cancelled) return;
        setData(json);
        setLoading(false);
      })
      .catch((exc) => {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : "casting stats unavailable");
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [url]);

  if (loading) {
    return (
      <main data-casting-state="loading" className="h-screen bg-black text-white flex items-center justify-center">
        <span className="text-white/50">loading casting stats</span>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main data-casting-state="error" className="h-screen bg-black text-white flex items-center justify-center">
        <span className="text-red-300">{error ?? "casting stats unavailable"}</span>
      </main>
    );
  }

  return (
    <main
      data-casting-scoreboard
      className="h-screen min-h-[480px] overflow-hidden bg-neutral-950 text-white px-4 py-4"
    >
      <header className="flex items-center gap-x-4 border-b border-white/15 pb-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm uppercase tracking-wide text-white/45">
            QuakeWorld 4v4
          </div>
          <h1 className="text-3xl font-semibold truncate">
            {data.match.map} · {data.match.hostname}
          </h1>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase text-white/45">{statusLabel(data)}</div>
          <div className="font-mono text-xl text-white/80">{durationLabel(data.match.duration)}</div>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-x-4 pt-4">
        {data.teams.map((team) => (
          <TeamTable key={team.name} data={data} team={team} />
        ))}
      </div>

      <footer className="absolute bottom-3 left-4 right-4 flex items-center gap-x-4 text-xs text-white/35">
        <span>{data.source.kind}</span>
        <span>{data.match.demo ?? "no demo"}</span>
        {data.warnings.length > 0 && <span>{data.warnings.length} source warning(s)</span>}
      </footer>
    </main>
  );
}
