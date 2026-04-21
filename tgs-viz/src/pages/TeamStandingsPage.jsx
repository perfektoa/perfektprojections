import React, { useMemo, useState } from 'react';
import { optimizeRoster } from '../lib/rosterOptimizer';
import { Download, ArrowUpDown, Loader2 } from 'lucide-react';

// ─── League assignments (TGS OOTP 26) ───────────────────────────
const AL_TEAMS = new Set([
  'New York Yankees', 'Boston Red Sox', 'Baltimore Orioles',
  'Kansas City Royals', 'Chicago White Sox', 'Minnesota Twins',
  'Detroit Tigers', 'Oakland Athletics', 'Texas Rangers',
  'Tampa Bay Devil Rays', 'Toronto Blue Jays', 'Cleveland Guardians',
  'Anaheim Angels', 'Seattle Mariners', 'Milwaukee Brewers',
  'Houston Astros',
]);

const NL_TEAMS = new Set([
  'Atlanta Hammers', 'Cincinnati Reds', 'Chicago Cubs',
  'Arizona Diamondbacks', 'Kansas City Monarchs', 'Philadelphia Phillies',
  'Florida Marlins', 'New York Mets', 'Colorado Rockies',
  'Los Angeles Dodgers', 'Pittsburgh Pirates', 'San Diego Padres',
  'San Francisco Giants', 'Washington Nationals', 'St. Louis Cardinals',
  'Montreal Expos',
]);

const ALL_KNOWN_TEAMS = new Set([...AL_TEAMS, ...NL_TEAMS]);

// ─── Build team projections using the roster optimizer ───────────
// Step 1: Run optimizer per team to get raw WAA
// Step 2: Normalize so total league wins = total league losses
//         (optimizer cherry-picks best 26, leaving negative-WAA guys
//          off rosters, inflating the sum — normalization fixes this)
function buildTeamProjections(hitters, pitchers) {
  // Get unique orgs that are in AL or NL
  const orgs = new Set();
  for (const p of hitters) {
    if (p.ORG && p.ORG !== '-' && ALL_KNOWN_TEAMS.has(p.ORG)) orgs.add(p.ORG);
  }
  for (const p of pitchers) {
    if (p.ORG && p.ORG !== '-' && ALL_KNOWN_TEAMS.has(p.ORG)) orgs.add(p.ORG);
  }

  // ── Pass 1: raw optimizer results ──
  const raw = [];
  for (const org of orgs) {
    const roster = optimizeRoster(hitters, pitchers, { teamOrg: org });
    const t = roster.totals;
    raw.push({
      team: org,
      rawWAAwtd: t.totalRosterWAA,
      rawWAAvR: t.lineupWAA_vR,
      rawWAAvL: t.lineupWAA_vL,
      rawSPWAA: t.totalSPWAA,
      rawRPWAA: t.totalRPWAA,
      rawHitterWAA: t.totalHitterWAA,
    });
  }

  const numTeams = raw.length;
  if (numTeams === 0) return [];

  // ── Pass 2: normalize ──
  // WAA should be zero-sum: total wins across league = numTeams × 81
  // Raw sum is inflated → compute per-team offset to bring average WAA to 0
  const rawTotalWAA = raw.reduce((s, t) => s + t.rawWAAwtd, 0);
  const waaOffset = rawTotalWAA / numTeams; // subtract this from each team

  // Also normalize the split WAAs (vR / vL) and component WAAs proportionally
  const rawTotalvR = raw.reduce((s, t) => s + t.rawWAAvR, 0);
  const rawTotalvL = raw.reduce((s, t) => s + t.rawWAAvL, 0);
  const vROffset = rawTotalvR / numTeams;
  const vLOffset = rawTotalvL / numTeams;

  // For SP/RP WAA: normalize proportionally based on their share of total WAA
  // so that the component columns still add up correctly
  const rawTotalSP = raw.reduce((s, t) => s + t.rawSPWAA, 0);
  const rawTotalRP = raw.reduce((s, t) => s + t.rawRPWAA, 0);
  const rawTotalHitter = raw.reduce((s, t) => s + t.rawHitterWAA, 0);
  const rawComponentTotal = rawTotalSP + rawTotalRP + rawTotalHitter;

  // Each component gets its proportional share of the offset
  const spShare = rawComponentTotal !== 0 ? rawTotalSP / rawComponentTotal : 1 / 3;
  const rpShare = rawComponentTotal !== 0 ? rawTotalRP / rawComponentTotal : 1 / 3;

  const spOffset = waaOffset * spShare;
  const rpOffset = waaOffset * rpShare;

  return raw.map(t => {
    const adjWAA = t.rawWAAwtd - waaOffset;
    const adjSP = t.rawSPWAA - spOffset;
    const adjRP = t.rawRPWAA - rpOffset;
    const adjvR = t.rawWAAvR - vROffset;
    const adjvL = t.rawWAAvL - vLOffset;
    const projW = Math.round(81 + adjWAA);

    return {
      team: t.team,
      projW,
      projL: 162 - projW,
      totalWAAvR: Math.round(adjvR * 100) / 100,
      totalWAAvL: Math.round(adjvL * 100) / 100,
      spWAA: Math.round(adjSP * 100) / 100,
      rpWAA: Math.round(adjRP * 100) / 100,
      totalWAAwtd: Math.round(adjWAA * 100) / 100,
    };
  });
}

// ─── CSV export ──────────────────────────────────────────────────
function toCSV(rows, columns) {
  const header = columns.map(c => c.label).join(',');
  const body = rows.map(r =>
    columns.map(c => {
      const v = c.accessor(r);
      if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
      return v;
    }).join(',')
  );
  return [header, ...body].join('\n');
}

function downloadCSV(filename, csvText) {
  const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Column definitions ──────────────────────────────────────────
const COLUMNS = [
  { key: 'team',       label: 'Team',       accessor: r => r.team,         fmt: v => v,            align: 'left' },
  { key: 'projW',      label: 'Proj W',     accessor: r => r.projW,        fmt: v => v,            align: 'right' },
  { key: 'projL',      label: 'Proj L',     accessor: r => r.projL,        fmt: v => v,            align: 'right' },
  { key: 'totalWAAvR', label: 'WAA vR',     accessor: r => r.totalWAAvR,   fmt: v => v.toFixed(1), align: 'right' },
  { key: 'totalWAAvL', label: 'WAA vL',     accessor: r => r.totalWAAvL,   fmt: v => v.toFixed(1), align: 'right' },
  { key: 'spWAA',      label: 'SP WAA',     accessor: r => r.spWAA,        fmt: v => v.toFixed(1), align: 'right' },
  { key: 'rpWAA',      label: 'RP WAA',     accessor: r => r.rpWAA,        fmt: v => v.toFixed(1), align: 'right' },
  { key: 'totalWAAwtd',label: 'wtd WAA',    accessor: r => r.totalWAAwtd,  fmt: v => v.toFixed(1), align: 'right' },
];

// ─── Sortable table component ────────────────────────────────────
function StandingsTable({ title, rows, onExport }) {
  const [sortKey, setSortKey] = useState('projW');
  const [sortDir, setSortDir] = useState('desc');

  const sorted = useMemo(() => {
    const col = COLUMNS.find(c => c.key === sortKey);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const av = col.accessor(a);
      const bv = col.accessor(b);
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av;
      }
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [rows, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-lg font-bold text-white">{title}</h2>
        <button
          onClick={onExport}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
        >
          <Download size={14} /> Export CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`px-4 py-2.5 font-semibold text-slate-400 cursor-pointer hover:text-white transition-colors select-none whitespace-nowrap ${
                    col.align === 'left' ? 'text-left' : 'text-right'
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <ArrowUpDown size={12} className="text-blue-400" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={row.team}
                className={`border-b border-slate-800/50 hover:bg-slate-800/40 transition-colors ${
                  i % 2 === 0 ? '' : 'bg-slate-900/50'
                }`}
              >
                {COLUMNS.map(col => {
                  const raw = col.accessor(row);
                  const display = col.fmt(raw);
                  let colorClass = 'text-slate-300';

                  if (col.key === 'projW') {
                    // Scale: 81 = neutral, 95+ = bright green, 67- = bright red
                    const diff = raw - 81;
                    if (diff >= 14) colorClass = 'text-green-400 font-semibold';
                    else if (diff >= 9) colorClass = 'text-green-400';
                    else if (diff >= 4) colorClass = 'text-green-400/70';
                    else if (diff > 0) colorClass = 'text-green-400/50';
                    else if (diff === 0) colorClass = 'text-slate-400';
                    else if (diff > -4) colorClass = 'text-red-400/50';
                    else if (diff > -9) colorClass = 'text-red-400/70';
                    else if (diff > -14) colorClass = 'text-red-400';
                    else colorClass = 'text-red-400 font-semibold';
                  } else if (col.key === 'projL') {
                    // Inverse: high losses = red, low losses = green
                    const diff = raw - 81;
                    if (diff >= 14) colorClass = 'text-red-400 font-semibold';
                    else if (diff >= 9) colorClass = 'text-red-400';
                    else if (diff >= 4) colorClass = 'text-red-400/70';
                    else if (diff > 0) colorClass = 'text-red-400/50';
                    else if (diff === 0) colorClass = 'text-slate-400';
                    else if (diff > -4) colorClass = 'text-green-400/50';
                    else if (diff > -9) colorClass = 'text-green-400/70';
                    else if (diff > -14) colorClass = 'text-green-400';
                    else colorClass = 'text-green-400 font-semibold';
                  } else if (col.key !== 'team' && typeof raw === 'number') {
                    if (raw > 5) colorClass = 'text-green-400';
                    else if (raw > 0) colorClass = 'text-green-400/70';
                    else if (raw < -5) colorClass = 'text-red-400';
                    else if (raw < 0) colorClass = 'text-red-400/70';
                  }

                  return (
                    <td
                      key={col.key}
                      className={`px-4 py-2 whitespace-nowrap ${col.align === 'left' ? 'text-left' : 'text-right'} ${colorClass}`}
                    >
                      {display}
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

// ─── Main page ───────────────────────────────────────────────────
export default function TeamStandingsPage({ hitters, pitchers }) {
  const allTeams = useMemo(
    () => buildTeamProjections(hitters, pitchers),
    [hitters, pitchers]
  );

  const alTeams = useMemo(() => allTeams.filter(t => AL_TEAMS.has(t.team)), [allTeams]);
  const nlTeams = useMemo(() => allTeams.filter(t => NL_TEAMS.has(t.team)), [allTeams]);

  const exportLeague = (teams, filename) => {
    const csv = toCSV(teams, COLUMNS);
    downloadCSV(filename, csv);
  };

  const exportAll = () => {
    const allCols = [
      { label: 'League', accessor: r => AL_TEAMS.has(r.team) ? 'AL' : 'NL' },
      ...COLUMNS,
    ];
    const csv = toCSV([...alTeams, ...nlTeams], allCols);
    downloadCSV('team_projections.csv', csv);
  };

  if (allTeams.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <Loader2 size={36} className="animate-spin text-blue-500 mx-auto" />
          <p className="text-slate-400 text-sm">Building optimal rosters for all teams...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Team Projections</h1>
            <p className="text-sm text-slate-400 mt-1">
              Optimized 26-man rosters | Normalized so league W = L (zero-sum WAA)
            </p>
          </div>
          <button
            onClick={exportAll}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
          >
            <Download size={16} /> Export All Teams
          </button>
        </div>
      </div>

      <div className="p-4 space-y-6">
        <StandingsTable
          title="American League"
          rows={alTeams}
          onExport={() => exportLeague(alTeams, 'al_projections.csv')}
        />
        <StandingsTable
          title="National League"
          rows={nlTeams}
          onExport={() => exportLeague(nlTeams, 'nl_projections.csv')}
        />
      </div>
    </div>
  );
}
