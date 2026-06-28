// T3.3 (#424): attempt recording & komodolab gallery.
//
// A standalone, read-only gallery of every live bot attempt — reached at
// /botlab/?attempts=1 (the same standalone-page pattern as ?casting=1 and
// ?evidence=1). It consumes the komodobots.bot_attempts.v1 ledger that
// scripts/prewar_movecheck.py emits and the /bot-live-watch publish path scp's
// to prod; cloud_hub serves it at /demos/records/bot-attempts.json with a
// fall-back to the committed bot-attempts.example.json so this page renders
// before the first real run.
//
// The accountability rule (docs/28): no success claim without a linked, viewable
// recording. Each GREEN row links its served MVD watch URL; a RED row with no
// demo shows that absence rather than hiding it.
//
// See tests/test_bot_attempts_panel.py for the pure-logic contract tests over
// the example ledger this page reads.

import { useEffect, useMemo, useState } from "react";
import { logError } from "./logger.ts";

interface AttemptDemo {
  name: string;
  url: string;
}

interface AttemptFreshness {
  ok: boolean;
  live_fraction: number | null;
  min_fraction: number | null;
}

interface BotAttempt {
  run_id: string;
  ts_utc: string;
  map: string;
  n_bots: number;
  mode: string;
  demo: AttemptDemo | null;
  freshness: AttemptFreshness;
  verdict: string;
  artifact_dir: string;
  contact_sheet?: { name: string; url: string } | null;
}

interface AttemptsLedger {
  schema: string;
  map: string;
  attempts: BotAttempt[];
}

const PRIMARY_URL = "/demos/records/bot-attempts.json";
const FIXTURE_URL = "/botlab/data/bot-attempts.example.json";

function attemptsUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const explicit = params.get("attempts_src");
  if (explicit) return explicit;
  return params.get("fixture") === "attempts" ? FIXTURE_URL : PRIMARY_URL;
}

// In-dashboard watch link: the FTE demo pane is served at /botlab/panes/demo.html
// and the gallery is itself under /botlab/, so a relative href resolves there.
function watchHref(demo: AttemptDemo, map: string): string {
  return `panes/demo.html?demo=${encodeURIComponent(demo.url)}&map=${encodeURIComponent(map)}`;
}

function fmtFraction(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function fmtTs(ts: string): string {
  // The ledger carries an ISO-8601 UTC timestamp; show it verbatim minus the
  // microseconds/offset noise. Never throw on a malformed value.
  return ts.replace("T", " ").replace(/(\+00:00|Z)$/, " UTC").slice(0, 23);
}

export function BotAttemptsGallery() {
  const url = useMemo(attemptsUrl, []);
  const [ledger, setLedger] = useState<AttemptsLedger | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`bot-attempts.json ${res.status}`);
        return res.json() as Promise<AttemptsLedger>;
      })
      .then((data) => {
        if (cancelled) return;
        setLedger(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        logError("bot-attempts gallery fetch failed", err, { url });
        setError(true);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [url]);

  if (loading) {
    return <div className="p-4 text-sm text-gray-500 animate-pulse">loading attempts…</div>;
  }
  if (error || !ledger) {
    return <div className="p-4 text-sm text-amber-700">attempts ledger unavailable</div>;
  }

  const attempts = ledger.attempts ?? [];

  return (
    <div className="min-h-screen bg-slate-950 text-gray-200 p-4">
      <header className="mb-3">
        <h1 className="text-lg font-semibold">Bot attempts — {ledger.map}</h1>
        <p className="text-xs text-gray-500">
          {attempts.length} attempt{attempts.length === 1 ? "" : "s"} · newest first ·
          no success claim without a linked, viewable recording
        </p>
      </header>

      {attempts.length === 0 ? (
        <div data-attempts-state="empty" className="text-sm text-gray-600">no attempts yet</div>
      ) : (
        <table className="w-full text-xs border-collapse">
          <thead className="text-gray-500 uppercase tracking-wide text-[10px]">
            <tr className="border-b border-slate-800 text-left">
              <th className="py-1 pr-3">When (UTC)</th>
              <th className="py-1 pr-3">Run</th>
              <th className="py-1 pr-3">Bots</th>
              <th className="py-1 pr-3">Verdict</th>
              <th className="py-1 pr-3">Live</th>
              <th className="py-1 pr-3">Recording</th>
            </tr>
          </thead>
          <tbody>
            {attempts.map((a) => {
              const green = a.verdict === "GREEN";
              return (
                <tr key={a.run_id} data-run-id={a.run_id} className="border-b border-slate-900">
                  <td className="py-1 pr-3 font-mono text-gray-400">{fmtTs(a.ts_utc)}</td>
                  <td className="py-1 pr-3 font-mono text-gray-500">{a.run_id}</td>
                  <td className="py-1 pr-3 font-mono">{a.n_bots}</td>
                  <td className={`py-1 pr-3 font-mono font-semibold ${green ? "text-green-400" : "text-red-400"}`}>
                    {a.verdict}
                  </td>
                  <td className="py-1 pr-3 font-mono text-gray-400" title={`freshness ok=${a.freshness.ok}`}>
                    {fmtFraction(a.freshness.live_fraction)}
                  </td>
                  <td className="py-1 pr-3">
                    {a.demo ? (
                      <a
                        className="text-sky-400 hover:underline"
                        href={watchHref(a.demo, a.map)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        watch demo
                      </a>
                    ) : (
                      <span className="text-gray-600">no recording</span>
                    )}
                    {a.contact_sheet && (
                      <>
                        {" · "}
                        <a
                          className="text-sky-400 hover:underline"
                          href={a.contact_sheet.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          contact sheet
                        </a>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
