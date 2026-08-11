import React, { useMemo, useState } from 'react';
import { LayoutGrid, ChevronDown } from 'lucide-react';
import { buildPositionalStrength, teamPositionalStrength, LENSES, DEFAULT_LENS } from '../lib/positionalStrength';

// Every number below is WAA (value vs average) — see positionalStrength.js.
const fmt = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(2));
const fmtZ = (v) => (Number.isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(2) : '—');

// Same z-bands for the card and the grid so a colour means one thing.
const zText = (z) => (!Number.isFinite(z) ? 'text-slate-500'
  : z >= 1 ? 'text-emerald-300 font-semibold' : z >= 0.35 ? 'text-emerald-400/80'
  : z > -0.35 ? 'text-slate-300' : z > -1 ? 'text-amber-400/80' : 'text-rose-400/80');
const zCell = (z) => (!Number.isFinite(z) ? ''
  : z >= 1 ? 'bg-emerald-500/25' : z >= 0.35 ? 'bg-emerald-500/10'
  : z > -0.35 ? '' : z > -1 ? 'bg-amber-500/10' : 'bg-rose-500/20');

function LensPicker({ lens, onChange }) {
  return (
    <div className="relative">
      <select value={lens} onChange={(e) => onChange(e.target.value)}
        className="appearance-none bg-slate-800 text-slate-200 text-xs font-semibold rounded-lg pl-2.5 pr-7 py-1.5 border border-slate-700 hover:border-blue-500 focus:outline-none cursor-pointer">
        {Object.values(LENSES).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
      </select>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
    </div>
  );
}

/** Shared hook: build the league board once per (data, league, lens). */
function useStrength(hitters, pitchers, league, knownTeams, lens) {
  return useMemo(
    () => buildPositionalStrength(hitters, pitchers, { league, knownTeams, lens }),
    [hitters, pitchers, league, knownTeams, lens]
  );
}

/**
 * One org against its own league: rank and z at every position, the man who
 * scores the slot, the next man up (shown, never blended into the score), and
 * the league's best / worst club at that position.
 */
export function PositionalStrengthCard({ hitters, pitchers, league, knownTeams = null, team }) {
  const [lens, setLens] = useState(DEFAULT_LENS);
  const build = useStrength(hitters, pitchers, league, knownTeams, lens);
  const rows = useMemo(() => teamPositionalStrength(build, team), [build, team]);
  const n = build.teams.length;
  // The org dropdown also lists affiliates and loan clubs that aren't league
  // members; those have nothing to be ranked against, so say so rather than
  // vanishing.
  if (!rows.length) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl px-4 py-3 text-xs text-slate-500">
        <span className="text-slate-300 font-semibold">Positional Strength</span> — {team || 'this club'} is not one of the {n} {league} clubs, so there is no league to rank it inside.
      </div>
    );
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <LayoutGrid size={15} className="text-blue-400" />
          <span className="text-sm font-black text-white">Positional Strength</span>
          <span className="text-xs text-slate-500">{team} vs the other {n - 1} {league} clubs · {build.lens.note}</span>
        </div>
        <LensPicker lens={lens} onChange={setLens} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-600 border-b border-slate-800/60">
              <th className="px-2 py-1 text-left font-medium">Pos</th>
              <th className="px-2 py-1 text-right font-medium" title="Rank among this league's clubs at this position (1 = best)">Rank</th>
              <th className="px-2 py-1 text-right font-medium" title="Starter's WAA at this slot (SP = top 5 summed, RP = top 8). Empty slots are charged at the league's measured org replacement level.">WAA</th>
              <th className="px-2 py-1 text-right font-medium" title="Standard deviations from this league's mean at this position">z</th>
              <th className="px-2 py-1 text-left font-medium">Scores the slot</th>
              <th className="px-2 py-1 text-left font-medium" title="Next man up — shown for depth, NOT folded into the score (no measurable playing-time weights ship with the data)">Next up</th>
              <th className="px-2 py-1 text-left font-medium">League best</th>
              <th className="px-2 py-1 text-left font-medium">League worst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-slate-800/40 hover:bg-slate-800/30">
                <td className="px-2 py-1 font-semibold text-slate-200 whitespace-nowrap">
                  {r.key}{r.slots > 1 && <span className="text-slate-600 font-normal"> ×{r.slots}</span>}
                </td>
                <td className={`px-2 py-1 text-right tabular-nums ${zText(r.z)}`}>{r.rank}<span className="text-slate-600">/{n}</span></td>
                <td className={`px-2 py-1 text-right tabular-nums ${zText(r.z)}`}>{fmt(r.waa)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-500">{fmtZ(r.z)}</td>
                <td className="px-2 py-1 text-slate-300 whitespace-nowrap">
                  {r.top ? <>{r.top.name} <span className="text-slate-600 tabular-nums">{fmt(r.top.waa)}</span></>
                         : <span className="text-rose-400/80">nobody — charged at replacement</span>}
                  {r.kind === 'arm' && r.count < r.slots && <span className="text-rose-400/70"> · {r.slots - r.count} slot{r.slots - r.count > 1 ? 's' : ''} empty</span>}
                </td>
                <td className="px-2 py-1 text-slate-500 whitespace-nowrap">
                  {r.depth ? <>{r.depth.name} <span className="text-slate-600 tabular-nums">{fmt(r.depth.waa)}</span></> : '—'}
                </td>
                <td className="px-2 py-1 text-slate-500 whitespace-nowrap">{r.league.best.team} <span className="text-emerald-400/60 tabular-nums">{fmt(r.league.best.waa)}</span></td>
                <td className="px-2 py-1 text-slate-500 whitespace-nowrap">{r.league.worst.team} <span className="text-rose-400/60 tabular-nums">{fmt(r.league.worst.waa)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-1.5 text-[10px] text-slate-600 border-t border-slate-800/60">
        WAA = wins vs average. Score = the starter only ({'SP ×5 / RP ×8'} summed) — the shipped rows carry no playing-time
        column, so no starter/backup depth weights can be measured and none are invented. Below-average slots stay negative.
      </div>
    </div>
  );
}

/**
 * The whole league at a glance: one row per club, one column per position,
 * cell = rank (WAA underneath), shaded by z within that position's column.
 */
export function PositionalStrengthGrid({ hitters, pitchers, league, knownTeams = null, teams = null, highlight = null, title = 'Positional Strength' }) {
  const [lens, setLens] = useState(DEFAULT_LENS);
  const build = useStrength(hitters, pitchers, league, knownTeams, lens);
  const shown = useMemo(() => {
    const set = teams ? new Set(teams) : null;
    return build.teams.filter((t) => !set || set.has(t));
  }, [build, teams]);
  if (!shown.length) return null;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-white">{title}</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Rank (of {build.teams.length}) and WAA at each position, ranked within {league} only · {build.lens.note} ·
            starter only for bats, top 5 SP / top 8 RP for the staff
          </p>
        </div>
        <LensPicker lens={lens} onChange={setLens} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500">
              <th className="px-3 py-2 text-left font-semibold">Team</th>
              {build.positions.map((p) => (
                <th key={p.key} className="px-2 py-2 text-center font-semibold" title={p.slots > 1 ? `${p.key} — top ${p.slots} summed` : p.key}>
                  {p.key}{p.slots > 1 && <span className="text-slate-700 normal-case"> ×{p.slots}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t} className={`border-b border-slate-800/50 ${t === highlight ? 'bg-blue-500/10' : 'hover:bg-slate-800/40'}`}>
                <td className={`px-3 py-1.5 whitespace-nowrap ${t === highlight ? 'text-blue-300 font-semibold' : 'text-slate-300'}`}>{t}</td>
                {build.positions.map((p) => {
                  const c = build.cells[t][p.key];
                  return (
                    <td key={p.key} className={`px-2 py-1.5 text-center tabular-nums ${zCell(c.z)}`}
                        title={`${t} ${p.key}: WAA ${fmt(c.waa)}, z ${fmtZ(c.z)}${c.top ? ` — ${c.top.name}` : ' — no eligible player, charged at replacement'}`}>
                      <div className={zText(c.z)}>{c.rank}</div>
                      <div className="text-[9px] text-slate-600">{fmt(c.waa)}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
