import React, { useState, useMemo } from 'react';
import { optimizeRoster, getMaxWAA } from '../lib/rosterOptimizer';
import { formatCellValue, getCellColorClass } from '../lib/columns';
import PlayerDetail from '../components/PlayerDetail';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { Trophy, Users, Zap, Shield, Target, ArrowLeftRight } from 'lucide-react';

export default function RosterOptimizerPage({ hitters, pitchers }) {
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [playerType, setPlayerType] = useState(null);
  const [orgFilter, setOrgFilter] = useState('ALL');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const [activeLineup, setActiveLineup] = useState('vR'); // 'vR' or 'vL'

  const organizations = useMemo(() => {
    const orgs = new Set([
      ...hitters.map(h => h.ORG).filter(Boolean),
      ...pitchers.map(p => p.ORG).filter(Boolean),
    ]);
    return ['ALL', ...Array.from(orgs).sort()];
  }, [hitters, pitchers]);

  const levels = useMemo(() => {
    const lvls = new Set([
      ...hitters.map(h => h.Lev).filter(Boolean),
      ...pitchers.map(p => p.Lev).filter(Boolean),
    ]);
    return ['ALL', ...Array.from(lvls).sort()];
  }, [hitters, pitchers]);

  // Run the optimizer (always uses weighted WAA for roster selection)
  const roster = useMemo(() => {
    return optimizeRoster(hitters, pitchers, {
      teamOrg: orgFilter !== 'ALL' ? orgFilter : null,
      levelFilter: levelFilter !== 'ALL' ? levelFilter : null,
    });
  }, [hitters, pitchers, orgFilter, levelFilter]);

  // Active lineup data based on tab
  const activeLineupData = useMemo(() => {
    return activeLineup === 'vR' ? roster.lineupVsRHP : roster.lineupVsLHP;
  }, [roster, activeLineup]);

  // Position WAA chart data (from active split lineup)
  const positionWAAData = useMemo(() => {
    if (!activeLineupData?.battingOrder) return [];
    return activeLineupData.battingOrder.map(entry => ({
      pos: entry.position,
      waa: entry.waa || 0,
      name: entry.player.Name,
    }));
  }, [activeLineupData]);

  // Pitching WAA data
  const pitchingWAAData = useMemo(() => {
    const data = [];
    roster.startingPitchers?.forEach((p, i) => {
      data.push({ name: `SP${i + 1}`, waa: p._spWAA || p._bestWAA || 0, player: p.Name, role: 'SP' });
    });
    roster.reliefPitchers?.forEach((p, i) => {
      data.push({ name: `RP${i + 1}`, waa: p._rpWAA || p._bestWAA || 0, player: p.Name, role: 'RP' });
    });
    return data;
  }, [roster]);

  const splitLabel = activeLineup === 'vR' ? 'vs RHP' : 'vs LHP';
  const splitWAACol = activeLineup === 'vR' ? 'Max WAA vR' : 'Max WAA vL';

  // Helper for bench rows
  const BenchRow = ({ player, role, note }) => {
    if (!player) return (
      <tr><td colSpan={7} className="text-xs text-orange-400/70 italic">No {role} available</td></tr>
    );
    const waa = player._maxWAA || 0;
    return (
      <tr className="cursor-pointer hover:bg-slate-800/50"
        onClick={() => { setSelectedPlayer(player); setPlayerType('hitter'); }}>
        <td className="font-bold text-green-400">{role}</td>
        <td className="font-medium text-white">{player.Name}</td>
        <td className="text-slate-400">{player.POS}</td>
        <td>{Math.round(parseFloat(player.Age) || 0)}</td>
        <td className={getCellColorClass(waa, 'Max WAA wtd')}>{waa.toFixed(1)}</td>
        <td className="text-xs text-slate-500 max-w-[240px] truncate">{note}</td>
        <td className="text-slate-400">{player.ORG}</td>
      </tr>
    );
  };

  return (
    <div className="h-full overflow-auto">
      <div className="p-4">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Trophy className="text-amber-400" size={24} />
          Roster Optimizer
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          26-man roster built on weighted WAA &bull; Split lineups vs RHP & LHP &bull; The Book batting order (wOBA + OBP)
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 px-4 pb-4">
        <select value={orgFilter} onChange={e => setOrgFilter(e.target.value)}
          className="py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {organizations.map(o => <option key={o} value={o}>{o === 'ALL' ? 'All Organizations' : o}</option>)}
        </select>

        <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)}
          className="py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {levels.map(l => <option key={l} value={l}>{l === 'ALL' ? 'All Levels' : l}</option>)}
        </select>
      </div>

      {/* Summary Cards */}
      {roster.totals && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 px-4 pb-4">
          <div className="bg-gradient-to-br from-blue-900/50 to-blue-800/30 rounded-lg p-3 border border-blue-700/30">
            <div className="text-2xl font-black text-blue-400">{roster.totals.estimatedWins}</div>
            <div className="text-xs text-blue-300/70">Projected Wins</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-green-400">{roster.totals.totalRosterWAA}</div>
            <div className="text-xs text-slate-500">Total WAA (Roster)</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-cyan-400">{roster.totals.lineupWAA_vR}</div>
            <div className="text-xs text-slate-500">vs RHP Lineup WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-emerald-400">{roster.totals.lineupWAA_vL}</div>
            <div className="text-xs text-slate-500">vs LHP Lineup WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-amber-400">{roster.totals.totalSPWAA}</div>
            <div className="text-xs text-slate-500">SP WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-purple-400">{roster.totals.totalRPWAA}</div>
            <div className="text-xs text-slate-500">RP WAA</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-4">
        {/* Batting Order with Split Tabs */}
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Target className="text-blue-400" size={16} />
            <h2 className="text-sm font-bold text-white">Batting Order</h2>
            <span className="text-xs text-slate-500">(The Book &bull; wOBA + OBP)</span>
            <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5 ml-auto">
              <button onClick={() => setActiveLineup('vR')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  activeLineup === 'vR' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}>
                vs RHP
              </button>
              <button onClick={() => setActiveLineup('vL')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  activeLineup === 'vL' ? 'bg-green-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}>
                vs LHP
              </button>
            </div>
          </div>
          <div className="text-xs text-slate-500 px-3 pt-1">
            Lineup WAA ({splitLabel}): <span className={activeLineup === 'vR' ? 'text-cyan-400 font-semibold' : 'text-emerald-400 font-semibold'}>
              {activeLineupData?.totalLineupWAA || 0}
            </span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>POS</th>
                <th>Name</th>
                <th>Role</th>
                <th>Age</th>
                <th>wOBA</th>
                <th>WAA</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {activeLineupData?.battingOrder?.map((entry, idx) => {
                if (!entry) return null;
                return (
                  <tr key={idx} className="cursor-pointer hover:bg-slate-800/50"
                    onClick={() => { setSelectedPlayer(entry.player); setPlayerType('hitter'); }}>
                    <td className="font-bold text-blue-400">{entry.slot}</td>
                    <td className="font-bold text-amber-400">{entry.position}</td>
                    <td className="font-medium text-white">{entry.player.Name}</td>
                    <td className="text-xs text-slate-500">{entry.role}</td>
                    <td>{Math.round(parseFloat(entry.player.Age) || 0)}</td>
                    <td className={getCellColorClass(entry.woba, 'wOBA wtd')}>
                      {entry.woba ? entry.woba.toFixed(3) : '-'}
                    </td>
                    <td className={getCellColorClass(entry.waa, splitWAACol)}>
                      {entry.waa.toFixed(1)}
                    </td>
                    <td className="text-slate-400">{entry.player.ORG}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Bench */}
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Users className="text-green-400" size={16} />
            <h2 className="text-sm font-bold text-white">Bench & Reserves</h2>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Name</th>
                <th>POS</th>
                <th>Age</th>
                <th>WAA</th>
                <th>Note</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              <BenchRow
                player={roster.bench?.backupC}
                role="Backup C"
                note="Second catcher"
              />
              <BenchRow
                player={roster.bench?.utilityIF}
                role="Util IF"
                note={roster.bench?.utilityIF?._canPlayAllIF ? 'SS/2B/3B eligible' : 'SS + IF eligible'}
              />
              <BenchRow
                player={roster.bench?.utilityOF}
                role="Util OF"
                note={roster.bench?.utilityOF?._canPlayCFAndCornerOF ? 'CF + corner OF' : 'CF + OF eligible'}
              />
              {roster.bench?.platoonBat ? (
                <BenchRow
                  player={roster.bench.platoonBat.player}
                  role="Platoon"
                  note={`+${roster.bench.platoonBat.waaAdvantage} WAA at ${roster.bench.platoonBat.platoonPosition} ${roster.bench.platoonBat.platoonSplit === 'vR' ? 'vs RHP' : 'vs LHP'} (over ${roster.bench.platoonBat.replacesStarter})`}
                />
              ) : (
                <tr><td colSpan={7} className="text-xs text-slate-500 italic">No platoon advantage found</td></tr>
              )}
              {roster.bench?.extraBench?.map((p, i) => (
                <BenchRow key={i} player={p} role="Bench" note="Best available" />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pitching Staff */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-4">
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Zap className="text-amber-400" size={16} />
            <h2 className="text-sm font-bold text-white">Starting Rotation (5 SP)</h2>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Age</th>
                <th>SP WAA</th>
                <th>RA/9</th>
                <th>STM</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {roster.startingPitchers?.map((p, i) => (
                <tr key={i} className="cursor-pointer hover:bg-slate-800/50"
                  onClick={() => { setSelectedPlayer(p); setPlayerType('pitcher'); }}>
                  <td className="font-bold text-amber-400">SP{i + 1}</td>
                  <td className="font-medium text-white">{p.Name}</td>
                  <td>{Math.round(parseFloat(p.Age) || 0)}</td>
                  <td className={getCellColorClass(p._spWAA, 'WAA wtd')}>{(p._spWAA || 0).toFixed(1)}</td>
                  <td className={getCellColorClass(p['RA/9 wtd'], 'RA/9 wtd')}>
                    {formatCellValue(p['RA/9 wtd'], 'RA/9 wtd')}
                  </td>
                  <td>{p.STM}</td>
                  <td className="text-slate-400">{p.ORG}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Shield className="text-purple-400" size={16} />
            <h2 className="text-sm font-bold text-white">Bullpen (8 RP)</h2>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Age</th>
                <th>RP WAA</th>
                <th>RA/9</th>
                <th>HLD</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {roster.reliefPitchers?.map((p, i) => (
                <tr key={i} className="cursor-pointer hover:bg-slate-800/50"
                  onClick={() => { setSelectedPlayer(p); setPlayerType('pitcher'); }}>
                  <td className="font-bold text-purple-400">RP{i + 1}</td>
                  <td className="font-medium text-white">{p.Name}</td>
                  <td>{Math.round(parseFloat(p.Age) || 0)}</td>
                  <td className={getCellColorClass(p._rpWAA, 'WAA wtd RP')}>{(p._rpWAA || 0).toFixed(1)}</td>
                  <td className={getCellColorClass(p['RA/9 wtd RP'], 'RA/9 wtd RP')}>
                    {formatCellValue(p['RA/9 wtd RP'], 'RA/9 wtd RP')}
                  </td>
                  <td>{p.HLD}</td>
                  <td className="text-slate-400">{p.ORG}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 px-4 pb-6">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
            Position Player WAA ({splitLabel})
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={positionWAAData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="pos" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                formatter={(val, name, props) => [`${val.toFixed(1)} WAA - ${props.payload.name}`, 'WAA']}
              />
              <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                {positionWAAData.map((entry, i) => (
                  <Cell key={i} fill={entry.waa >= 2 ? '#3b82f6' : entry.waa >= 0 ? '#60a5fa' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Pitching Staff WAA</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pitchingWAAData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                formatter={(val, name, props) => [`${val.toFixed(1)} WAA - ${props.payload.player}`, 'WAA']}
              />
              <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                {pitchingWAAData.map((entry, i) => (
                  <Cell key={i} fill={entry.role === 'SP' ? '#f59e0b' : '#8b5cf6'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={() => setSelectedPlayer(null)}
          type={playerType}
        />
      )}
    </div>
  );
}
