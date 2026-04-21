import React, { useState, useMemo } from 'react';
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend, BarChart, Bar, Cell } from 'recharts';
import { analyzeMarket, calculatePlayerValue, getBestWAA, formatMoney } from '../lib/marketValue';
import { usePlayersWithFV } from '../hooks/usePlayerData';
import { Search, ChevronDown, ChevronUp, DollarSign, TrendingUp, Info } from 'lucide-react';

/**
 * Market Value Page — $/WAA analysis and IFA valuation tool.
 * Helps answer: "How much should I offer this international free agent?"
 */
export default function MarketValuePage({ hitters, pitchers }) {
  // Compute FV for all players (needed for year-by-year projections)
  const hittersWithFV = usePlayersWithFV(hitters);
  const pitchersWithFV = usePlayersWithFV(pitchers);

  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('ALL'); // ALL, IFA, MLB, PROSPECT
  const [sortKey, setSortKey] = useState('_marketValue');
  const [sortDir, setSortDir] = useState('desc');
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [marketRateOverride, setMarketRateOverride] = useState('');

  // Run market analysis
  const market = useMemo(() => analyzeMarket(hittersWithFV, pitchersWithFV), [hittersWithFV, pitchersWithFV]);

  // Active market rate (user can override)
  const activeMarketRate = marketRateOverride
    ? parseInt(marketRateOverride, 10)
    : market.avgPerWAA;

  // Enrich all players with market value calculations
  const allPlayers = useMemo(() => {
    const combined = [
      ...hittersWithFV.map(p => ({ ...p, _playerType: 'Hitter' })),
      ...pitchersWithFV.map(p => ({ ...p, _playerType: 'Pitcher' })),
    ];

    return combined.map(p => {
      const waa = getBestWAA(p);
      const val = calculatePlayerValue(p, activeMarketRate);
      return {
        ...p,
        _bestWAA: waa,
        _marketValue: val.adjustedValue,
        _totalProjectedValue: val.totalValue,
        _offerFloor: val.offerFloor,
        _offerMid: val.offerMid,
        _offerCeiling: val.offerCeiling,
        _annualValue: val.annualValue,
        _surplus: val.surplus,
        _prospectDiscount: val.prospectDiscount,
        _productiveYears: val.productiveYears,
        _isProspect: val.isProspect,
        _perWAA: p.Price > 0 && waa > 0 ? Math.round(p.Price / waa) : null,
        _valuation: val,
      };
    });
  }, [hittersWithFV, pitchersWithFV, activeMarketRate]);

  // Filter and sort
  const filteredPlayers = useMemo(() => {
    let result = allPlayers;

    // Type filter
    if (filterType === 'IFA') {
      result = result.filter(p => p.Lev === 'INT');
    } else if (filterType === 'MLB') {
      result = result.filter(p => p.Lev === 'MLB');
    } else if (filterType === 'PROSPECT') {
      result = result.filter(p => p._isProspect);
    } else if (filterType === 'FREE_AGENT') {
      result = result.filter(p => !p.ORG || p.ORG === '' || p.ORG === '-');
    }

    // Search
    if (search) {
      const s = search.toLowerCase();
      result = result.filter(p =>
        (p.Name || '').toLowerCase().includes(s) ||
        (p.ORG || '').toLowerCase().includes(s)
      );
    }

    // Sort
    result = [...result].sort((a, b) => {
      const aVal = parseFloat(a[sortKey]) || 0;
      const bVal = parseFloat(b[sortKey]) || 0;
      return sortDir === 'desc' ? bVal - aVal : aVal - bVal;
    });

    return result;
  }, [allPlayers, filterType, search, sortKey, sortDir]);

  // Scatter chart data (MLB players with positive WAA and salary)
  const scatterData = useMemo(() => {
    return allPlayers
      .filter(p => p.Lev === 'MLB' && p.Price > 0 && p._bestWAA > 0)
      .map(p => ({
        waa: Math.round(p._bestWAA * 100) / 100,
        price: p.Price,
        name: p.Name,
        pos: p.POS,
        age: p.Age,
        isPreArb: p.Price < 1_000_000,
      }));
  }, [allPlayers]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const SortIcon = ({ col }) => {
    if (sortKey !== col) return <ChevronDown size={12} className="text-slate-600" />;
    return sortDir === 'desc'
      ? <ChevronDown size={12} className="text-blue-400" />
      : <ChevronUp size={12} className="text-blue-400" />;
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <DollarSign size={24} className="text-green-400" />
            Market Value &amp; $/WAA
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Analyze salary market rates and estimate fair offer values for free agent signings
          </p>
        </div>

        {/* Market Summary Cards */}
        <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard
            label="Hitter $/WAA"
            value={formatMoney(market.hitter?.avg)}
            sub={`${market.hitter?.freeMarketCount || 0} free market`}
            color="text-green-400"
          />
          <StatCard
            label="SP $/WAA"
            value={formatMoney(market.sp?.avg)}
            sub={`${market.sp?.freeMarketCount || 0} starters`}
            color="text-blue-400"
          />
          <StatCard
            label="RP $/WAA"
            value={formatMoney(market.rp?.avg)}
            sub={`${market.rp?.freeMarketCount || 0} relievers`}
            color="text-yellow-300"
          />
          <StatCard
            label="Combined $/WAA"
            value={formatMoney(market.avgPerWAA)}
            sub="All positions"
            color="text-slate-300"
          />
          <StatCard
            label="Market Sample"
            value={market.marketPlayers}
            sub={`${market.preArbPlayers} pre-arb excluded`}
            color="text-cyan-400"
          />
          <StatCard
            label="Total MLB w/ +WAA"
            value={market.totalMLBPositiveWAA}
            sub="Hitters + Pitchers"
            color="text-purple-400"
          />
        </div>

        {/* Market Rate Override */}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-400">Active $/WAA Rate:</span>
              <input
                type="number"
                value={marketRateOverride}
                onChange={(e) => setMarketRateOverride(e.target.value)}
                placeholder={market.avgPerWAA.toLocaleString()}
                className="w-40 bg-slate-800 text-white text-sm rounded px-3 py-1.5 border border-slate-700 focus:border-blue-500 focus:outline-none placeholder-slate-500"
              />
              {marketRateOverride && (
                <button
                  onClick={() => setMarketRateOverride('')}
                  className="text-xs text-slate-500 hover:text-slate-300"
                >
                  Reset
                </button>
              )}
            </div>
            <div className="text-xs text-slate-500 flex items-center gap-1">
              <Info size={12} />
              Override the market rate to model different scenarios. Leave blank to use league average.
            </div>
          </div>
        </div>

        {/* Two-column layout: Chart + Buckets */}
        <div className="grid grid-cols-2 gap-4">
          {/* Scatter: Salary vs WAA */}
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h2 className="text-sm font-semibold text-white mb-3">Salary vs WAA (MLB Players)</h2>
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="waa"
                  name="WAA"
                  type="number"
                  domain={[0, 'auto']}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: 'WAA', position: 'insideBottom', offset: -10, fill: '#64748b', fontSize: 11 }}
                />
                <YAxis
                  dataKey="price"
                  name="Salary"
                  type="number"
                  tickFormatter={(v) => formatMoney(v)}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: 'Salary', angle: -90, position: 'insideLeft', offset: 10, fill: '#64748b', fontSize: 11 }}
                />
                <Tooltip content={<ScatterTooltip />} />
                <ReferenceLine
                  stroke="#22c55e"
                  strokeDasharray="5 5"
                  strokeWidth={1.5}
                  segment={[
                    { x: 0, y: 0 },
                    { x: Math.max(...scatterData.map(d => d.waa), 1), y: activeMarketRate * Math.max(...scatterData.map(d => d.waa), 1) },
                  ]}
                />
                <Scatter data={scatterData.filter(d => !d.isPreArb)} fill="#3b82f6" fillOpacity={0.7} r={4} name="Free Market" />
                <Scatter data={scatterData.filter(d => d.isPreArb)} fill="#f59e0b" fillOpacity={0.5} r={3} name="Pre-Arb" />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </ScatterChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-500 mt-2">
              Green line = {formatMoney(activeMarketRate)}/WAA market rate. Points above the line are overpaid, below are underpaid.
            </p>
          </div>

          {/* WAA Bucket Analysis */}
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h2 className="text-sm font-semibold text-white mb-3">$/WAA by Performance Tier</h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={market.buckets} margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis
                  tickFormatter={(v) => formatMoney(v)}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: '$/WAA', angle: -90, position: 'insideLeft', offset: 10, fill: '#64748b', fontSize: 11 }}
                />
                <Tooltip content={<BucketTooltip />} />
                <Bar dataKey="avgPerWAA" radius={[4, 4, 0, 0]}>
                  {market.buckets.map((entry, i) => (
                    <Cell key={i} fill={BUCKET_COLORS[i] || '#3b82f6'} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-500 mt-2">
              Higher WAA tiers command a premium. Superstars cost significantly more per win.
            </p>

            {/* Tier breakdown table */}
            <div className="mt-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-800">
                    <th className="text-left py-1">Tier</th>
                    <th className="text-right py-1">Players</th>
                    <th className="text-right py-1">WAA Range</th>
                    <th className="text-right py-1">Avg Salary</th>
                    <th className="text-right py-1">$/WAA</th>
                  </tr>
                </thead>
                <tbody>
                  {market.tiers.map((tier, i) => (
                    <tr key={i} className="border-b border-slate-800/50 text-slate-300">
                      <td className="py-1.5 font-medium">{tier.label}</td>
                      <td className="text-right">{tier.count}</td>
                      <td className="text-right">{tier.minWAA.toFixed(1)} - {tier.maxWAA.toFixed(1)}</td>
                      <td className="text-right text-green-400">{formatMoney(tier.avgPrice)}</td>
                      <td className="text-right text-blue-400 font-semibold">{formatMoney(tier.avgPerWAA)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Player Valuation Table */}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <TrendingUp size={16} className="text-green-400" />
              Player Valuations
            </h2>
            <div className="flex items-center gap-2">
              {/* Filter */}
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
                className="bg-slate-800 text-white text-xs rounded px-2 py-1.5 border border-slate-700 focus:border-blue-500 focus:outline-none"
              >
                <option value="ALL">All Players</option>
                <option value="IFA">International FA</option>
                <option value="FREE_AGENT">Unsigned FA</option>
                <option value="MLB">MLB Only</option>
                <option value="PROSPECT">Prospects Only</option>
              </select>

              {/* Search */}
              <div className="relative">
                <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search name or org..."
                  className="bg-slate-800 text-white text-xs rounded pl-7 pr-3 py-1.5 w-48 border border-slate-700 focus:border-blue-500 focus:outline-none placeholder-slate-500"
                />
              </div>
            </div>
          </div>

          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-900 z-10">
                <tr className="text-slate-500 border-b border-slate-700">
                  <Th col="Name" label="Name" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_playerType" label="Type" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="POS" label="Pos" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="ORG" label="Org" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Lev" label="Lev" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Age" label="Age" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_bestWAA" label="WAA" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_fvScale" label="FV" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Price" label="Current $" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_perWAA" label="$/WAA" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_marketValue" label="Proj Value" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerFloor" label="Offer Low" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerMid" label="Offer Mid" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerCeiling" label="Offer High" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_annualValue" label="AAV" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_surplus" label="Surplus" current={sortKey} dir={sortDir} onClick={handleSort} />
                </tr>
              </thead>
              <tbody>
                {filteredPlayers.slice(0, 500).map((p, i) => (
                  <tr
                    key={p.ID || i}
                    onClick={() => setSelectedPlayer(selectedPlayer?.ID === p.ID ? null : p)}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/50 cursor-pointer transition-colors ${
                      selectedPlayer?.ID === p.ID ? 'bg-blue-900/20' : ''
                    }`}
                  >
                    <td className="py-1.5 px-2 font-medium text-white whitespace-nowrap">{p.Name}</td>
                    <td className="py-1.5 px-2 text-slate-400">{p._playerType}</td>
                    <td className="py-1.5 px-2 text-slate-300">{p.POS}</td>
                    <td className="py-1.5 px-2 text-slate-400 whitespace-nowrap max-w-[120px] truncate">{p.ORG || '-'}</td>
                    <td className={`py-1.5 px-2 ${p.Lev === 'INT' ? 'text-yellow-400 font-semibold' : 'text-slate-400'}`}>{p.Lev || '-'}</td>
                    <td className="py-1.5 px-2 text-slate-300">{p.Age}</td>
                    <td className={`py-1.5 px-2 font-mono ${waaColor(p._bestWAA)}`}>{p._bestWAA.toFixed(1)}</td>
                    <td className={`py-1.5 px-2 font-mono ${fvColor(p._fvScale)}`}>{p._fvScale || '-'}</td>
                    <td className="py-1.5 px-2 text-green-400 font-mono">{p.Price > 0 ? formatMoney(p.Price) : '-'}</td>
                    <td className="py-1.5 px-2 text-blue-400 font-mono">{p._perWAA ? formatMoney(p._perWAA) : '-'}</td>
                    <td className="py-1.5 px-2 text-cyan-400 font-mono font-semibold">{formatMoney(p._marketValue)}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono">{formatMoney(p._offerFloor)}</td>
                    <td className="py-1.5 px-2 text-green-400 font-mono">{formatMoney(p._offerMid)}</td>
                    <td className="py-1.5 px-2 text-yellow-300 font-mono">{formatMoney(p._offerCeiling)}</td>
                    <td className="py-1.5 px-2 text-slate-300 font-mono">{formatMoney(p._annualValue)}</td>
                    <td className={`py-1.5 px-2 font-mono ${p._surplus > 0 ? 'text-green-400' : p._surplus < 0 ? 'text-red-400' : 'text-slate-500'}`}>
                      {formatMoney(p._surplus)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-slate-500 mt-2">
            Showing {Math.min(filteredPlayers.length, 500)} of {filteredPlayers.length} players |
            Surplus = Projected Value - Current Salary | Negative surplus = overpaid
          </p>
        </div>

        {/* Selected Player Detail */}
        {selectedPlayer && selectedPlayer._valuation && (
          <PlayerValuationDetail player={selectedPlayer} marketRate={activeMarketRate} />
        )}
      </div>
    </div>
  );
}

// ============================================================
// SUB-COMPONENTS
// ============================================================

function StatCard({ label, value, sub, color }) {
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-3">
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
      <p className="text-xs text-slate-600 mt-0.5">{sub}</p>
    </div>
  );
}

function Th({ col, label, current, dir, onClick }) {
  return (
    <th
      className="py-2 px-2 text-right cursor-pointer hover:text-slate-300 select-none whitespace-nowrap"
      onClick={() => onClick(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {current === col && (
          dir === 'desc' ? <ChevronDown size={10} /> : <ChevronUp size={10} />
        )}
      </span>
    </th>
  );
}

function ScatterTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs shadow-lg">
      <p className="font-semibold text-white">{d.name}</p>
      <p className="text-slate-400">{d.pos} | Age {d.age}</p>
      <p className="text-green-400">Salary: {formatMoney(d.price)}</p>
      <p className="text-blue-400">WAA: {d.waa.toFixed(1)}</p>
      <p className="text-cyan-400">$/WAA: {formatMoney(Math.round(d.price / d.waa))}</p>
      {d.isPreArb && <p className="text-yellow-400 mt-1">Pre-Arb (below market)</p>}
    </div>
  );
}

function BucketTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs shadow-lg">
      <p className="font-semibold text-white">{d.label} WAA</p>
      <p className="text-slate-400">{d.freeMarketCount} free market players ({d.count} total)</p>
      <p className="text-green-400">Avg Salary: {formatMoney(d.avgPrice)}</p>
      <p className="text-blue-400">$/WAA: {formatMoney(d.avgPerWAA)}</p>
    </div>
  );
}

function PlayerValuationDetail({ player, marketRate }) {
  const val = player._valuation;
  const fv = player._fvBreakdown;

  return (
    <div className="bg-slate-900 rounded-lg border border-blue-800/50 p-4">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg font-bold text-white">{player.Name}</h3>
          <p className="text-sm text-slate-400">
            {player.POS} | {player.ORG || 'Free Agent'} | {player.Lev} | Age {player.Age} | {player._playerType}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">FV Scale</p>
          <p className={`text-2xl font-bold ${fvColor(player._fvScale)}`}>{player._fvScale}</p>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-3 mb-4">
        <MiniStat label="Current WAA" value={player._bestWAA.toFixed(1)} color={waaColor(player._bestWAA)} />
        <MiniStat label="Current Salary" value={formatMoney(player.Price)} color="text-green-400" />
        <MiniStat label="Projected Value" value={formatMoney(val.adjustedValue)} color="text-cyan-400" />
        <MiniStat label="Prospect Discount" value={`${val.prospectDiscount}%`} color={val.isProspect ? 'text-yellow-300' : 'text-slate-400'} />
        <MiniStat label="Surplus" value={formatMoney(val.surplus)} color={val.surplus > 0 ? 'text-green-400' : 'text-red-400'} />
      </div>

      {/* Offer Range */}
      <div className="bg-slate-800 rounded-lg p-3 mb-4">
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Suggested Offer Range</p>
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>Conservative</span>
              <span>Fair Value</span>
              <span>Aggressive</span>
            </div>
            <div className="relative h-6 bg-slate-700 rounded-full overflow-hidden">
              <div className="absolute inset-y-0 left-0 bg-gradient-to-r from-slate-600 via-green-600 to-yellow-600 rounded-full" style={{ width: '100%' }} />
              {/* Current price marker */}
              {player.Price > 0 && val.offerCeiling > 0 && (
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-red-400 z-10"
                  style={{ left: `${Math.min(100, (player.Price / val.offerCeiling) * 100)}%` }}
                  title={`Current: ${formatMoney(player.Price)}`}
                />
              )}
            </div>
            <div className="flex justify-between text-sm font-mono mt-1">
              <span className="text-slate-400">{formatMoney(val.offerFloor)}</span>
              <span className="text-green-400 font-semibold">{formatMoney(val.offerMid)}</span>
              <span className="text-yellow-300">{formatMoney(val.offerCeiling)}</span>
            </div>
          </div>
          <div className="text-center px-4 border-l border-slate-700">
            <p className="text-xs text-slate-500">AAV</p>
            <p className="text-lg font-bold text-white">{formatMoney(val.annualValue)}</p>
            <p className="text-xs text-slate-500">{val.productiveYears} productive yrs</p>
          </div>
        </div>
        {player.Price > 0 && (
          <p className="text-xs text-slate-500 mt-2">
            Red line = current salary ({formatMoney(player.Price)})
          </p>
        )}
      </div>

      {/* Year-by-year projection */}
      {val.yearlyValues && val.yearlyValues.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Year-by-Year Projected Value (at {formatMoney(marketRate)}/WAA)</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1 px-2">Age</th>
                  <th className="text-right py-1 px-2">Raw WAA</th>
                  <th className="text-right py-1 px-2">Discounted WAA</th>
                  <th className="text-right py-1 px-2">Year Value</th>
                </tr>
              </thead>
              <tbody>
                {val.yearlyValues.map((yr, i) => (
                  <tr key={i} className={`border-b border-slate-800/30 ${yr.rawWAA > 0 ? '' : 'opacity-40'}`}>
                    <td className="py-1 px-2 text-slate-300">{yr.age}</td>
                    <td className={`py-1 px-2 text-right font-mono ${waaColor(yr.rawWAA)}`}>{yr.rawWAA.toFixed(1)}</td>
                    <td className="py-1 px-2 text-right font-mono text-slate-400">{yr.discountedWAA.toFixed(1)}</td>
                    <td className="py-1 px-2 text-right font-mono text-green-400">{formatMoney(yr.yearValue)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-700 font-semibold">
                  <td className="py-1.5 px-2 text-slate-300">Total</td>
                  <td className="py-1.5 px-2 text-right font-mono text-slate-400">
                    {val.yearlyValues.reduce((s, y) => s + y.rawWAA, 0).toFixed(1)}
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-slate-400">
                    {val.yearlyValues.reduce((s, y) => s + y.discountedWAA, 0).toFixed(1)}
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-cyan-400">
                    {formatMoney(val.totalValue)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniStat({ label, value, color }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ============================================================
// HELPERS
// ============================================================

function waaColor(waa) {
  if (waa >= 3) return 'text-purple-400';
  if (waa >= 1.5) return 'text-cyan-400';
  if (waa >= 0) return 'text-green-400';
  if (waa >= -1) return 'text-orange-400';
  return 'text-red-400';
}

function fvColor(fv) {
  if (fv >= 70) return 'text-purple-400';
  if (fv >= 60) return 'text-cyan-400';
  if (fv >= 50) return 'text-green-400';
  if (fv >= 40) return 'text-yellow-300';
  return 'text-red-400';
}

const BUCKET_COLORS = ['#64748b', '#3b82f6', '#06b6d4', '#22c55e', '#f59e0b', '#a855f7'];
