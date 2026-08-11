import React, { useMemo, useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from 'recharts';
import { calculateFutureValue } from '../lib/futureValue';
import { formatCellValue, getCellColorClass } from '../lib/columns';
import { loadRatingTrends, playerHistory } from '../lib/ratingTrends';
import { X } from 'lucide-react';

/** Tiny inline sparkline for a rating series (nulls = missing pulls, skipped). */
function Sparkline({ values, delta }) {
  const pts = values
    .map((v, i) => (v === null || v === undefined ? null : [i, v]))
    .filter(Boolean);
  if (pts.length < 2) return <span className="w-[72px] inline-block" />;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 72, H = 18, PAD = 2;
  const sx = x => PAD + (maxX === minX ? 0.5 : (x - minX) / (maxX - minX)) * (W - 2 * PAD);
  const sy = y => H - PAD - (maxY === minY ? 0.5 : (y - minY) / (maxY - minY)) * (H - 2 * PAD);
  const color = delta > 0 ? '#4ade80' : delta < 0 ? '#f87171' : '#64748b';
  return (
    <svg width={W} height={H} className="shrink-0">
      <polyline
        points={pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ')}
        fill="none" stroke={color} strokeWidth="1.5"
      />
      {pts.map(([x, y], i) => (
        <circle key={i} cx={sx(x)} cy={sy(y)} r="1.6" fill={color} />
      ))}
    </svg>
  );
}

/**
 * Compact per-rating scouting history (informational — from the ratings-history
 * DB export; never feeds projections). Shows only ratings that CHANGED across
 * the archived pulls in the window.
 */
function RatingHistory({ player }) {
  const [trends, setTrends] = useState(undefined); // undefined=loading, null=unavailable
  useEffect(() => {
    let on = true;
    loadRatingTrends(player._appLeague).then(t => { if (on) setTrends(t); });
    return () => { on = false; };
  }, [player._appLeague]);

  if (trends === undefined) return null;           // still loading — stay quiet
  if (trends === null) return null;                // no trends file — feature hidden
  const hist = playerHistory(trends, player.ID);
  if (!hist) return null;
  const { dates, rows, vintages } = hist;
  const shown = rows.slice(0, 12);
  const range = dates.length ? `${dates[0]} → ${dates[dates.length - 1]}` : '';

  return (
    <div className="bg-slate-800/50 rounded-lg p-3">
      <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1">Rating History</h3>
      <div className="text-[10px] text-slate-500 mb-2">
        {range} · {vintages} archived pulls · informational only (projections use current ratings)
      </div>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">No scouting-rating changes across the last {dates.length} pulls.</div>
      ) : (
        <>
          {shown.map(r => (
            <div key={r.col} className="flex items-center justify-between gap-2 py-0.5">
              <span className="text-slate-500 text-xs w-16 shrink-0">{r.col}</span>
              <Sparkline values={r.values} delta={r.delta} />
              <span className="text-xs font-mono text-slate-300 w-16 text-right">
                {r.first} → {r.last}
              </span>
              <span className={`text-xs font-mono w-9 text-right ${
                r.delta > 0 ? 'text-green-400' : r.delta < 0 ? 'text-red-400' : 'text-slate-500'
              }`}>
                {r.delta > 0 ? '+' : ''}{Math.round(r.delta * 10) / 10}
              </span>
            </div>
          ))}
          {rows.length > shown.length && (
            <div className="text-[10px] text-slate-600 mt-1">
              +{rows.length - shown.length} more changed ratings
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function PlayerDetail({ player, onClose, type = 'hitter' }) {
  if (!player) return null;

  const fv = useMemo(() => calculateFutureValue(player), [player]);

  // Development curve data
  const devCurve = fv.yearByYear.map(y => ({
    age: y.age,
    WAA: y.rawWAA,
  }));

  // Radar chart data for hitters
  const radarData = type === 'hitter' ? [
    { stat: 'Contact', value: parseFloat(player['BA vR']) || 0, potential: parseFloat(player['HT P']) || 0 },
    { stat: 'Power', value: parseFloat(player['POW vR']) || 0, potential: parseFloat(player['POW P']) || 0 },
    { stat: 'Eye', value: parseFloat(player['EYE vR']) || 0, potential: parseFloat(player['EYE P']) || 0 },
    { stat: 'Gap', value: parseFloat(player['GAP vR']) || 0, potential: parseFloat(player['GAP P']) || 0 },
    { stat: 'Speed', value: parseFloat(player['SPE']) || 0, potential: parseFloat(player['SPE']) || 0 },
    { stat: 'Avoid K', value: parseFloat(player['K vR']) || 0, potential: parseFloat(player['K P']) || 0 },
  ] : [
    { stat: 'Stuff', value: parseFloat(player['STU vR']) || 0, potential: parseFloat(player['STU P']) || 0 },
    { stat: 'Control', value: parseFloat(player['CON vR']) || 0, potential: parseFloat(player['CON P']) || 0 },
    { stat: 'HR Rate', value: parseFloat(player['HRR vR']) || 0, potential: parseFloat(player['HRR P']) || 0 },
    { stat: 'BABIP', value: parseFloat(player['PBABIP vR']) || 0, potential: parseFloat(player['PBABIP P']) || 0 },
    { stat: 'Stamina', value: parseFloat(player['STM']) || 0, potential: parseFloat(player['STM']) || 0 },
    { stat: 'Hold', value: parseFloat(player['HLD']) || 0, potential: parseFloat(player['HLD']) || 0 },
  ];

  // Position WAA bar chart (hitters only)
  const posWAAData = type === 'hitter' ? [
    { pos: 'C', waa: parseFloat(player['C WAA wtd']) || 0 },
    { pos: '1B', waa: parseFloat(player['1B WAA wtd']) || 0 },
    { pos: '2B', waa: parseFloat(player['2B WAA wtd']) || 0 },
    { pos: '3B', waa: parseFloat(player['3B WAA wtd']) || 0 },
    { pos: 'SS', waa: parseFloat(player['SS WAA wtd']) || 0 },
    { pos: 'LF', waa: parseFloat(player['LF WAA wtd']) || 0 },
    { pos: 'CF', waa: parseFloat(player['CF WAA wtd']) || 0 },
    { pos: 'RF', waa: parseFloat(player['RF WAA wtd']) || 0 },
    { pos: 'DH', waa: parseFloat(player['DH WAA wtd']) || 0 },
  ].filter(d => d.waa !== 0) : [];

  const statLine = (label, value, colorCol) => {
    const display = formatCellValue(value, colorCol || label);
    const colorClass = getCellColorClass(value, colorCol || label);
    return (
      <div className="flex justify-between items-center py-0.5">
        <span className="text-slate-500 text-xs">{label}</span>
        <span className={`text-sm font-mono ${colorClass}`}>{display}</span>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-5xl w-full max-h-[90vh] overflow-auto shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700 sticky top-0 bg-slate-900 z-10">
          <div>
            <h2 className="text-xl font-bold text-white">{player.Name}</h2>
            <div className="flex gap-3 mt-1 text-sm text-slate-400">
              <span>{player.POS}</span>
              <span>{player.ORG}</span>
              <span>Age {Math.round(parseFloat(player.Age) || 0)}</span>
              <span>{player.B}/{player.T}</span>
              <span>Lvl: {player.Lev}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {player._draftFV !== undefined && (
              <div className="text-center">
                <div className="text-3xl font-black text-green-400">{player._draftFV}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wide">Draft FV</div>
              </div>
            )}
            <div className="text-center">
              <div className="text-3xl font-black text-blue-400">{fv.fvScale}</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Future Value</div>
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
          {/* Column 1: Key Stats */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Value Summary</h3>
              {type === 'hitter' ? (
                <>
                  {statLine('Max WAA (wtd)', player['Max WAA wtd'], 'Max WAA wtd')}
                  {statLine('Max WAA (vR)', player['Max WAA vR'], 'Max WAA vR')}
                  {statLine('Max WAA (vL)', player['Max WAA vL'], 'Max WAA vL')}
                  {statLine('wOBA (wtd)', player['wOBA wtd'], 'wOBA wtd')}
                  {statLine('OBP (wtd)', player['OBP wtd'], 'OBP wtd')}
                  {statLine('BatR (wtd)', player['BatR wtd'], 'BatR wtd')}
                  {statLine('BSR (wtd)', player['BSR wtd'], 'BSR wtd')}
                </>
              ) : (
                <>
                  {statLine('SP WAA (wtd)', player['WAA wtd'], 'WAA wtd')}
                  {statLine('SP WAR', player['WAR wtd'], 'WAR wtd')}
                  {statLine('RP WAA (wtd)', player['WAA wtd RP'], 'WAA wtd RP')}
                  {statLine('RA/9 (wtd)', player['RA/9 wtd'], 'RA/9 wtd')}
                  {statLine('RA/9 RP', player['RA/9 wtd RP'], 'RA/9 wtd RP')}
                  {statLine('wOBA (wtd)', player['wOBA wtd'], 'wOBA wtd')}
                </>
              )}
            </div>

            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Future Value Breakdown</h3>
              {statLine('FV (20-80)', fv.fvScale, '_fvScale')}
              {statLine('Total Future$', fv.futureValue, '_futureValue')}
              {/* WAA (vs average) — same basis as the boards. fv.currentWAA /
                  expectedPeakWAA / potentialWAA are the internal WAR values and must
                  NOT be shown under a WAA label; fv.displayWAA is the converted track. */}
              {statLine('Current WAA', fv.displayWAA?.current, '_currentWAA')}
              {statLine('Proj Peak (WAA)', fv.displayWAA?.expectedPeak, '_potentialWAA')}
              {statLine('Raw Ceiling (WAA)', fv.displayWAA?.potential, '_potentialWAA')}
              {statLine('Peak WAA', fv.displayWAA?.peakProjected, '_peakWAA')}
              {/* The internal WAR basis, shown raw so the WAA numbers above are auditable.
                  Plain divs, not statLine — statLine runs values through formatCellValue,
                  which parseFloat()s a composite string down to its first number. */}
              <div className="flex justify-between items-center py-0.5 border-t border-slate-700/50 mt-1 pt-1">
                <span className="text-slate-500 text-xs">Internal WAR (cur / peak)</span>
                <span className="text-sm font-mono text-slate-400">{fv.currentWAA} / {fv.expectedPeakWAA}</span>
              </div>
              <div className="flex justify-between items-center py-0.5">
                <span className="text-slate-500 text-xs">Role (cur / peak)</span>
                <span className="text-sm font-mono text-slate-400">
                  {fv.currentRole ?? '?'} / {fv.potentialRole ?? '?'}
                  {fv.currentRole !== fv.potentialRole && (
                    <span className="ml-1 text-amber-400" title="Current and peak roles differ — the two ends carry different replacement offsets.">*</span>
                  )}
                </span>
              </div>
              {statLine('% to Peak', `${fv.pctToPeak}%`)}
              {statLine('ETA to Peak', fv.yearsTilPeak > 0 ? `${fv.yearsTilPeak} yrs` : 'At peak')}
            </div>

            {player._draftFV !== undefined && (
              <div className="bg-slate-800/50 rounded-lg p-3 border border-blue-900/30">
                <h3 className="text-xs font-semibold text-blue-400 uppercase mb-2">Draft FV Breakdown</h3>
                {statLine('Draft FV (20-80)', player._draftFV, '_draftFV')}
                {statLine('Draft Raw Score', player._draftRawFV, '_draftRawFV')}
                {statLine('Age Percentile', player._agePercentile, '_agePercentile')}
                {statLine('Ceiling (WAA)', player._draftCeilingWAA, '_draftCeilingWAA')}
                {statLine('Ceiling (WAR, scored)', player._draftCeiling, '_draftCeiling')}
                {player._ceilingRole && statLine('Ceiling role', player._ceilingRole)}
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">Durability</span>
                  <span className={`text-sm font-mono ${getCellColorClass(player._durability, '_durability')}`}>
                    {player._durability}
                  </span>
                </div>
                {statLine('WE Boost', player._weBoost ? '+2%' : 'None')}
                {player._toolPenalty !== undefined && player._toolPenalty < 1.0 && (
                  <div className="flex justify-between items-center py-0.5">
                    <span className="text-slate-500 text-xs">Tool Penalty</span>
                    <span className="text-sm font-mono text-red-400">
                      -{Math.round((1 - player._toolPenalty) * 100)}% (age pctl)
                    </span>
                  </div>
                )}
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">High INT</span>
                  <span className={`text-sm font-mono ${player._highINT ? 'text-green-400' : 'text-slate-600'}`}>
                    {player._highINT ? 'Yes (TCR lottery)' : 'No'}
                  </span>
                </div>
                {player._wrecked && (
                  <div className="mt-2 text-center text-red-400 font-bold text-xs uppercase bg-red-900/20 rounded py-1">
                    Undraftable (Wrecked)
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Column 2: Charts */}
          <div className="space-y-4">
            {/* Radar Chart - Ratings vs Potential */}
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
                {type === 'hitter' ? 'Hitting Profile' : 'Pitching Profile'}
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#334155" />
                  <PolarAngleAxis dataKey="stat" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <PolarRadiusAxis domain={[0, 80]} tick={false} />
                  <Radar name="Current" dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.3} />
                  <Radar name="Potential" dataKey="potential" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.15} strokeDasharray="4 4" />
                </RadarChart>
              </ResponsiveContainer>
              <div className="flex justify-center gap-6 text-xs">
                <span className="text-blue-400">--- Current</span>
                <span className="text-purple-400">- - Potential</span>
              </div>
            </div>

            {/* Position WAA Bar Chart (hitters only) */}
            {type === 'hitter' && posWAAData.length > 0 && (
              <div className="bg-slate-800/50 rounded-lg p-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">WAA by Position</h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={posWAAData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="pos" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                      {posWAAData.map((entry, i) => (
                        <Cell key={i} fill={entry.waa >= 0 ? '#3b82f6' : '#ef4444'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Column 3: Development Curve */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Projected Development Curve</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={devCurve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                    labelStyle={{ color: '#e2e8f0' }}
                  />
                  <Line type="monotone" dataKey="WAA" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
              <div className="text-center text-xs text-slate-500 mt-1">
                Projected WAA by Age (dev to 25, decline starts immediately after)
              </div>
            </div>

            {type === 'hitter' && (
              <div className="bg-slate-800/50 rounded-lg p-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Fielding Skills</h3>
                <div className="grid grid-cols-2 gap-x-4">
                  {statLine('IF Range', player['IF RNG'], 'IF RNG')}
                  {statLine('IF Error', player['IF ERR'], 'IF ERR')}
                  {statLine('IF Arm', player['IF ARM'], 'IF ARM')}
                  {statLine('Turn DP', player['TDP'], 'TDP')}
                  {statLine('OF Range', player['OF RNG'], 'OF RNG')}
                  {statLine('OF Error', player['OF ERR'], 'OF ERR')}
                  {statLine('OF Arm', player['OF ARM'], 'OF ARM')}
                  {statLine('C Ability', player['C ABI'], 'C ABI')}
                  {statLine('C Frame', player['C FRM'], 'C FRM')}
                  {statLine('C Arm', player['C ARM'], 'C ARM')}
                </div>
              </div>
            )}

            <RatingHistory player={player} />
          </div>
        </div>
      </div>
    </div>
  );
}
