// 3D heatmap view for the 4v4 dashboard (issue: dashboard-3d-heatmap).
//
// Shows, over the textured dm3 map in 3D, a density heatmap of where the bots
// have been (binned XY columns) plus where they died (markers), filterable by
// team (LEAP vs FROG) and by individual player. Reuses the existing
// createMapScene() rig (mapScene.ts) and the BotLab3D add/dispose discipline so
// there are no GPU leaks. Filtering is a client-side sum over the selected
// players' bins (HeatmapScene.addHeatmapLayer).
//
// Subject rail mirrors TrendsView: a Scope toggle (Team / Player) and a
// multi-select rail, with the same TeamTag tags and --leap/--frog tones.

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createMapScene, normalizeMapName } from "./mapScene.ts";
import { addHeatmapLayer } from "./HeatmapScene.ts";
import type { HeatmapData, HeatmapPlayer } from "./HeatmapScene.ts";
import {
  Button,
  TeamTag,
  toneForTeam,
  botLabel,
  SQUAD_TAG_COLOR,
} from "./FourVFourEvidence.tsx";
import type { ValidationGame, SideTone } from "./FourVFourEvidence.tsx";

type Scope = "team" | "player";

interface Subject {
  id: string;
  kind: Scope;
  label: string;
  tag: SideTone["squad"];
  // the heatmap player rows this subject contributes (team = all of a side,
  // player = exactly one slot).
  players: HeatmapPlayer[];
}

// Resolve the squad tone (LEAP/FROG) for a heatmap row by its team string,
// using the same per-game bench resolution the rest of the page uses.
function squadForTeam(game: ValidationGame, team: string): SideTone {
  const idx = game.teams.findIndex((t) => t.name === team);
  return toneForTeam(game, team, idx < 0 ? 0 : idx);
}

// Build the Team and Player subject lists from a game's heatmap block.
function buildSubjects(game: ValidationGame): { teams: Subject[]; players: Subject[] } {
  const rows = game.heatmap?.players ?? [];
  // Group rows by squad (LEAP / FROG).
  const bySquad: Record<SideTone["squad"], HeatmapPlayer[]> = { leap: [], frog: [] };
  const playerSubjects: Subject[] = [];
  for (const row of rows) {
    const tone = squadForTeam(game, row.team);
    bySquad[tone.squad].push(row);
    playerSubjects.push({
      id: `slot-${row.slot}`,
      kind: "player",
      label: botLabel(row.name || `slot ${row.slot}`),
      tag: tone.squad,
      players: [row],
    });
  }
  // Stable player order: leap first, then frog, then by slot.
  playerSubjects.sort((a, b) => {
    if (a.tag !== b.tag) return a.tag === "leap" ? -1 : 1;
    return a.players[0].slot - b.players[0].slot;
  });
  const teamSubjects: Subject[] = [];
  if (bySquad.leap.length > 0) {
    teamSubjects.push({ id: "leap", kind: "team", label: "Team Leap", tag: "leap", players: bySquad.leap });
  }
  if (bySquad.frog.length > 0) {
    teamSubjects.push({ id: "frog", kind: "team", label: "Team Frog", tag: "frog", players: bySquad.frog });
  }
  return { teams: teamSubjects, players: playerSubjects };
}

// The Three.js canvas + heatmap layer. Remounts (via React key) when the game
// changes; the selected players are passed in and re-applied without a full
// remount when only the filter changes.
function HeatmapCanvas({
  data,
  selectedPlayers,
  mapName,
}: {
  data: HeatmapData;
  selectedPlayers: HeatmapPlayer[];
  mapName: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapSceneRef = useRef<ReturnType<typeof createMapScene> | null>(null);
  const layerRef = useRef<ReturnType<typeof addHeatmapLayer> | null>(null);
  const selectedRef = useRef<HeatmapPlayer[]>(selectedPlayers);
  selectedRef.current = selectedPlayers;

  // Scene setup: mirror BotLab3D — createMapScene owns the rig; we add the
  // heatmap layer on top and run a damped render loop. Dispose order: cancel
  // the loop, dispose our layer, then mapScene.dispose().
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const mapScene = createMapScene(container, mapName);
    mapSceneRef.current = mapScene;
    // Keep the map see-through under the heatmap (shared opacity control).
    mapScene.setOpacity(0.22);
    const { renderer, scene, camera, controls } = mapScene;

    // Initial layer for the current selection.
    layerRef.current = addHeatmapLayer(mapScene, data, selectedRef.current);

    let disposed = false;
    let animId = 0;
    function animate() {
      if (disposed) return;
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(animId);
      layerRef.current?.dispose();
      layerRef.current = null;
      mapSceneRef.current = null;
      mapScene.dispose();
    };
    // mapName/data identity drives a full rebuild; selection is handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, mapName]);

  // Filter change: rebuild only the heatmap layer, not the whole scene, so the
  // camera/controls stay put (mirrors the live view's per-prop effects).
  useEffect(() => {
    const mapScene = mapSceneRef.current;
    if (!mapScene) return;
    layerRef.current?.dispose();
    layerRef.current = addHeatmapLayer(mapScene, data, selectedPlayers);
  }, [data, selectedPlayers]);

  return <div ref={containerRef} data-heatmap-canvas style={{ width: "100%", height: "100%", minHeight: 480 }} />;
}

export function HeatmapView({ game }: { game: ValidationGame }) {
  const heatmap = game.heatmap ?? null;
  // Content signature for the memos below. The HeatmapCanvas setup effect keys
  // on `data`, so a fresh object every render/poll would tear down + rebuild the
  // WebGL context ("too many active WebGL contexts"). The 15s poll replaces
  // `game`/`heatmap` with a NEW object each time, so we key on a CONTENT string:
  // identical content for the same run yields an equal `sig` (scene stays put,
  // no churn), but a same-run update (regenerated movement artifacts) changes
  // `sig` so the view refreshes instead of going stale. Recomputed only when
  // `game` identity changes (≈once per poll); the heatmap payload is small/binned.
  const sig = useMemo(
    () =>
      JSON.stringify({
        run: game.run_id,
        heatmap: game.heatmap ?? null,
        roster: (game.players ?? []).map((p) => [p.slot, p.roster?.team ?? null]),
      }),
    [game],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { teams, players } = useMemo(() => buildSubjects(game), [sig]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const data: HeatmapData | null = useMemo(
    () => (heatmap ? { grid: heatmap.grid, players: heatmap.players } : null),
    [sig],
  );

  const [scope, setScope] = useState<Scope>("team");
  const [picked, setPicked] = useState<string[]>(teams.map((t) => t.id));

  const pool = scope === "team" ? teams : players;
  // Reconcile picks across game/scope changes, same as TrendsView: reset to the
  // scope default when scope flips; otherwise keep picks that still exist.
  const prevScopeRef = useRef(scope);
  const prevRunRef = useRef(game.run_id);
  useEffect(() => {
    const scopeChanged = prevScopeRef.current !== scope;
    const gameChanged = prevRunRef.current !== game.run_id;
    prevScopeRef.current = scope;
    prevRunRef.current = game.run_id;
    if (scopeChanged || gameChanged) {
      setPicked(scope === "team" ? teams.map((t) => t.id) : players.map((p) => p.id));
      return;
    }
    setPicked((prev) => {
      const ids = new Set(pool.map((s) => s.id));
      const kept = prev.filter((id) => ids.has(id));
      if (kept.length > 0) return kept.length === prev.length ? prev : kept;
      // No prior picks survived. This includes the case where `prev` was empty
      // because the pool was empty on first render and only populated on a later
      // live same-run poll (no heatmap rows -> rows): default to all current
      // subjects so the newly arrived heatmap renders instead of staying blank.
      return pool.length ? pool.map((s) => s.id) : prev;
    });
  }, [scope, teams, players, pool, game.run_id]);

  const chosen = pool.filter((s) => picked.includes(s.id));
  // Selected players = union of the chosen subjects' rows, de-duplicated by slot
  // (a player can be in both a team subject and itself, though only one scope is
  // active at a time).
  const selectedPlayers = useMemo(() => {
    const bySlot = new Map<number, HeatmapPlayer>();
    for (const s of chosen) for (const p of s.players) bySlot.set(p.slot, p);
    return [...bySlot.values()];
  }, [chosen]);

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? (p.length > 1 ? p.filter((x) => x !== id) : p) : [...p, id]));

  if (!data || data.players.length === 0) {
    return (
      <div
        data-heatmap-empty
        style={{
          background: "var(--surface-card)",
          border: "1px solid var(--border-hair)",
          borderRadius: "var(--r-3)",
          padding: "40px 18px",
          textAlign: "center",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--t-sm)",
          color: "var(--text-muted)",
        }}
      >
        No position heatmap for this game — the run has no recorded movement
        samples yet.
      </div>
    );
  }

  // dm3 GLB resolves; other maps fall back to an empty (non-crashing) scene.
  const mapName = normalizeMapName(game.match.map) ? game.match.map : "dm3";

  const railBtn = (s: Subject): CSSProperties => {
    const on = picked.includes(s.id);
    return {
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "8px 10px",
      cursor: "pointer",
      background: on ? "var(--surface-hover)" : "transparent",
      border: `1px solid ${on ? "var(--border-line)" : "transparent"}`,
      borderRadius: "var(--r-2)",
      textAlign: "left",
    };
  };

  return (
    <div data-evidence-heatmap style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Controls */}
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "center",
          flexWrap: "wrap",
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hair)",
          borderRadius: "var(--r-3)",
          padding: "12px 16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>
            Filter
          </span>
          <div style={{ display: "flex", gap: 4 }}>
            <Button variant={scope === "team" ? "primary" : "ghost"} active={scope === "team"} onClick={() => setScope("team")}>
              Team
            </Button>
            <Button variant={scope === "player" ? "primary" : "ghost"} active={scope === "player"} onClick={() => setScope("player")}>
              Player
            </Button>
          </div>
        </div>
        <div style={{ width: 1, height: 22, background: "var(--border-line)" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontFamily: "var(--font-mono)", fontSize: "var(--t-2xs)", color: "var(--text-faint)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: "linear-gradient(90deg,#2a4a8a,#ff5a2a)" }} />
            density (taller / hotter = more time spent)
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#ffe14d" }} />
            death
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, alignItems: "stretch" }}>
        {/* Subject rail */}
        <aside style={{ background: "var(--surface-card)", border: "1px solid var(--border-hair)", borderRadius: "var(--r-3)", padding: "12px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--t-2xs)", fontWeight: 600, letterSpacing: "var(--ls-label)", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 4 }}>
            {scope === "team" ? "Teams" : "Players"}
          </div>
          {pool.map((s) => {
            const on = picked.includes(s.id);
            return (
              <button key={s.id} data-heatmap-subject={s.id} aria-pressed={on} onClick={() => toggle(s.id)} style={railBtn(s)}>
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    background: on ? SQUAD_TAG_COLOR[s.tag] : "var(--surface-inset)",
                    border: on ? "none" : "1px solid var(--border-line)",
                    flex: "none",
                  }}
                />
                <TeamTag team={s.tag} size="sm" />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)", color: on ? "var(--text-strong)" : "var(--text-muted)" }}>
                  {s.label}
                </span>
              </button>
            );
          })}
        </aside>

        {/* 3D heatmap */}
        <div
          style={{
            background: "var(--surface-card)",
            border: "1px solid var(--border-hair)",
            borderRadius: "var(--r-3)",
            overflow: "hidden",
            minHeight: 480,
          }}
        >
          {/* key by run_id so a game switch rebuilds the scene from scratch. */}
          <HeatmapCanvas key={game.run_id} data={data} selectedPlayers={selectedPlayers} mapName={mapName} />
        </div>
      </div>
    </div>
  );
}
