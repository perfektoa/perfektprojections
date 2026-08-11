import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { loadRatingTrends } from '../lib/ratingTrends';
import { TrendingUp, TrendingDown, Info, Loader2 } from 'lucide-react';

/**
 * TrendsPage — league-wide scouting-rating movement from the ratings-history
 * DB (backtest/ratings_history.db -> rating_trends.json).
 *
 * INFORMATIONAL ONLY: nothing here feeds a projection. Projections stay
 * ratings-only from the current pull.
 */

function MoverTable({ title, rows, icon, accent }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className={`flex items-center gap-2 px-4 py-2.5 border-b border-slate-800 ${accent}`}>
        {icon}
        <h3 className="text-sm font-bold">{title}</h3>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
            <th className="text-left px-4 py-1.5">Player</th>
            <th className="text-left px-2 py-1.5">Pos</th>
            <th className="text-right px-2 py-1.5">Age</th>
            <th className="text-left px-2 py-1.5">Org</th>
            <th className="text-right px-2 py-1.5">Total Δ</th>
            <th className="text-left px-2 py-1.5">Biggest changes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(x => (
            <tr key={x.id} className="border-b border-slate-800/50 hover:bg-slate-800/40">
              <td className="px-4 py-1.5 text-slate-200 font-medium whitespace-nowrap">{x.n}</td>
              <td className="px-2 py-1.5 text-slate-400">{x.p || '—'}</td>
              <td className="px-2 py-1.5 text-slate-400 text-right">{x.a != null ? Math.round(x.a) : '—'}</td>
              <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap max-w-[160px] overflow-hidden text-ellipsis">{x.o || '—'}</td>
              <td className={`px-2 py-1.5 text-right font-mono font-bold ${x.t > 0 ? 'text-green-400' : 'text-red-400'}`}>
                {x.t > 0 ? '+' : ''}{x.t}
              </td>
              <td className="px-2 py-1.5">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(x.d || {}).slice(0, 4).map(([c, d]) => (
                    <span key={c} className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                      d > 0 ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
                    }`}>
                      {c} {d > 0 ? '+' : ''}{d}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-4 text-slate-500 text-xs">No movers in this window.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function AgeCurveExplorer({ ageCurves }) {
  const cols = useMemo(() => Object.keys(ageCurves?.cols || {}).sort(), [ageCurves]);
  const [col, setCol] = useState('');
  const [minN, setMinN] = useState(50);
  useEffect(() => {
    if (cols.length && !cols.includes(col)) setCol(cols.includes('POW P') ? 'POW P' : cols[0]);
  }, [cols]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = useMemo(() => {
    if (!col || !ageCurves?.cols?.[col]) return [];
    return Object.entries(ageCurves.cols[col])
      .map(([age, [mean, n]]) => ({ age: Number(age), mean, n }))
      .filter(d => d.n >= minN && d.age >= 15 && d.age <= 45)
      .sort((a, b) => a.age - b.age);
  }, [ageCurves, col, minN]);

  if (!cols.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <h3 className="text-sm font-bold text-slate-200">Average Change by Age</h3>
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <label className="flex items-center gap-1.5">
            Rating
            <select
              value={col}
              onChange={e => setCol(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            >
              {cols.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            Min sample
            <input
              type="number" min={1} step={25} value={minN}
              onChange={e => setMinN(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            />
          </label>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={v => v.toFixed(2)} />
          <ReferenceLine y={0} stroke="#64748b" />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0' }}
            formatter={(v, _name, item) => [`${v > 0 ? '+' : ''}${v.toFixed(3)} per pull pair (n=${item?.payload?.n})`, col]}
            labelFormatter={age => `Age ${age}`}
          />
          <Bar dataKey="mean" radius={[3, 3, 0, 0]}>
            {data.map((d, i) => <Cell key={i} fill={d.mean >= 0 ? '#3b82f6' : '#ef4444'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex items-start gap-2 mt-2 text-[11px] text-slate-500">
        <Info size={13} className="shrink-0 mt-0.5" />
        <p>{ageCurves.note}</p>
      </div>
    </div>
  );
}

export default function TrendsPage({ league }) {
  const [trends, setTrends] = useState(undefined);
  useEffect(() => {
    setTrends(undefined);
    let on = true;
    loadRatingTrends(league).then(t => { if (on) setTrends(t); });
    return () => { on = false; };
  }, [league]);

  const windows = useMemo(() => Object.keys(trends?.movers || {}).map(Number).sort((a, b) => a - b), [trends]);
  const [win, setWin] = useState(null);
  useEffect(() => {
    if (windows.length && !windows.includes(win)) setWin(windows.includes(3) ? 3 : windows[windows.length - 1]);
  }, [windows]); // eslint-disable-line react-hooks/exhaustive-deps

  if (trends === undefined) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 size={18} className="animate-spin" /> Loading rating trends…
      </div>
    );
  }
  if (!trends || !trends.pulls || trends.pulls.length < 2) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md text-slate-400 text-sm space-y-2">
          <p className="text-white font-bold">No rating history yet for {league}</p>
          <p>The trends board needs at least two archived ratings pulls. Run:</p>
          <code className="block text-xs text-blue-400 bg-slate-900 rounded p-2">
            python tgs-viz/backtest/ratings_db.py --backfill --export
          </code>
        </div>
      </div>
    );
  }

  const mv = win != null ? trends.movers[String(win)] : null;
  const nPulls = trends.pulls.length;

  return (
    <div className="h-full overflow-auto p-5 space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-black text-white">Rating Trends — {league}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {nPulls} archived ratings vintages ({trends.pulls[0].d} → {trends.pulls[nPulls - 1].d}) ·
            informational only — projections always use the current pull
          </p>
        </div>
        {windows.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-slate-400">
            Mover window
            <select
              value={win ?? ''}
              onChange={e => setWin(Number(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm"
            >
              {windows.map(w => <option key={w} value={w}>last {w} pull{w > 1 ? 's' : ''}</option>)}
            </select>
          </label>
        )}
      </div>

      {mv && (
        <>
          <p className="text-xs text-slate-500">
            {mv.from} → {mv.to}: <span className="text-slate-300 font-semibold">{mv.changed.toLocaleString()}</span> players
            had at least one scouting-rating change. Total Δ = sum of all 20–80 rating-point changes.
          </p>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <MoverTable
              title="Top Risers" rows={mv.risers}
              icon={<TrendingUp size={15} className="text-green-400" />} accent="text-green-400"
            />
            <MoverTable
              title="Top Fallers" rows={mv.fallers}
              icon={<TrendingDown size={15} className="text-red-400" />} accent="text-red-400"
            />
          </div>
        </>
      )}

      <AgeCurveExplorer ageCurves={trends.age_curves} />
    </div>
  );
}
