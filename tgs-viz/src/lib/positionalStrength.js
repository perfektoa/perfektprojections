/**
 * positionalStrength.js — league-relative depth chart.
 *
 * Answers "my shortstops are 27th in the league and my catchers are 3rd" by
 * scoring every org at every position, then z-scoring and RANKING those scores
 * ACROSS THE TEAMS OF ONE LEAGUE. Nothing here ever looks at a second league:
 * the mean/SD/rank a team is measured against come from that league's own
 * shipped rows and nowhere else.
 *
 * WHAT A POSITION SCORES (and what it deliberately does not)
 *  - Bats: the position's score is its STARTER's position-specific WAA, taken
 *    from the exact lineup assignment the roster optimizer already solves
 *    (optimalPositionAssignment). Reusing that solver is the point: it fills all
 *    nine slots simultaneously, so an org's best shortstop can't be scored at SS
 *    while stranding 2B — the DP decides who plays where.
 *  - NO depth WEIGHTING. A starter/backup/third-stringer weight vector would
 *    have to be measured from the league's own distribution of playing time by
 *    depth slot, and the shipped player rows carry no playing-time column at all
 *    (no PA, no G, no IP — they are projections, not outcomes). So the score is
 *    the starter, full stop. The next man up IS computed and shown beside it as
 *    its own unweighted number (`depth`), because a thin position is worth
 *    seeing — it is simply never folded into the score with an invented weight.
 *  - Arms: SP scores the top 5 starters' summed WAA, RP the top 8 relievers'.
 *    5 and 8 are the roster shape the optimizer already builds to
 *    (numStartingPitchers / numReliefPitchers), i.e. a stated roster
 *    convention, not a fitted weight.
 *
 * EMPTY SLOTS. A slot the org genuinely cannot field is scored at the league's
 * MEASURED **ORG** ("next man up") replacement level — leagueCalib
 * replacementOrg, expressed back in WAA (WAR = WAA + offset, so a replacement
 * body is WAA = −offset). ORG is the right currency here because filling a hole
 * from inside the system is exactly the question this board asks. A starter who
 * is BELOW that level is left where he is: negative, unclamped — a hole is a
 * hole, and clamping it to zero is how a board lies about a weakness.
 *
 * CURRENCY: WAA throughout (value vs average). No WAR is displayed anywhere in
 * this module; the replacement offsets appear only to convert an empty slot into
 * its WAA equivalent.
 *
 * LENSES: 'mlb' scores the current major-league club (Lev === 'MLB') off the
 * weighted columns; 'farm' scores everything below the majors off the engine's
 * POTENTIAL columns ('C WAA P' …, 'WAP', 'WAP RP') — the raw scouting ceiling,
 * with no age or risk haircut applied.
 */

import {
  getEligiblePositions,
  optimalPositionAssignment,
  getPositionWAAForSplit,
  leagueOrgs,
} from './rosterOptimizer.js';
import { replacementOrgOffset } from './leagueCalib.js';

// Lineup slots scored as bats, plus the two staff groups. `slots` is how many
// bodies the group fields — 1 per lineup spot, and the optimizer's own 5 SP /
// 8 RP roster shape.
export const STRENGTH_POSITIONS = [
  { key: 'C',  kind: 'bat', slots: 1 },
  { key: '1B', kind: 'bat', slots: 1 },
  { key: '2B', kind: 'bat', slots: 1 },
  { key: '3B', kind: 'bat', slots: 1 },
  { key: 'SS', kind: 'bat', slots: 1 },
  { key: 'LF', kind: 'bat', slots: 1 },
  { key: 'CF', kind: 'bat', slots: 1 },
  { key: 'RF', kind: 'bat', slots: 1 },
  { key: 'DH', kind: 'bat', slots: 1 },
  { key: 'SP', kind: 'arm', slots: 5 },
  { key: 'RP', kind: 'arm', slots: 8 },
];

const BAT_POSITIONS = STRENGTH_POSITIONS.filter(p => p.kind === 'bat').map(p => p.key);

// Which rows each lens reads, and which shipped columns it scores them on.
// `split` is the suffix optimalPositionAssignment / getPositionWAAForSplit build
// their column names from ('C WAA wtd' vs 'C WAA P').
export const LENSES = {
  mlb: {
    key: 'mlb',
    label: 'Majors',
    split: 'wtd',
    spCol: 'WAA wtd',
    rpCol: 'WAA wtd RP',
    inLens: (p) => (p.Lev || '') === 'MLB',
    note: 'current major-league club, weighted WAA',
  },
  farm: {
    key: 'farm',
    label: 'Farm',
    split: 'P',
    spCol: 'WAP',
    rpCol: 'WAP RP',
    // Everything the org holds below the majors. 'FA' rows are the free-agent
    // pool, not anybody's farm system.
    inLens: (p) => { const l = p.Lev || ''; return l !== 'MLB' && l !== 'FA' && l !== ''; },
    note: 'farm system, engine POTENTIAL WAA (no age/risk haircut)',
  },
};

export const DEFAULT_LENS = 'mlb';

const _idOf = (p) => p.ID || p.Name;
const _num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

/**
 * Bat side of one org: the everyday assignment (score) plus the assignment of
 * whoever is left (next man up, reported but never blended in).
 */
function batGroups(teamHitters, split, replWAA) {
  const scored = teamHitters.map(h => ({ ...h, _positions: getEligiblePositions(h) }));
  const starters = optimalPositionAssignment(scored, split).assignments;
  const startIds = new Set(Object.values(starters).map(_idOf));
  const backups = optimalPositionAssignment(scored.filter(h => !startIds.has(_idOf(h))), split).assignments;

  const out = {};
  for (const pos of BAT_POSITIONS) {
    const s = starters[pos] || null;
    const b = backups[pos] || null;
    const sWAA = s ? getPositionWAAForSplit(s, pos, split) : -Infinity;
    const bWAA = b ? getPositionWAAForSplit(b, pos, split) : -Infinity;
    const filled = Number.isFinite(sWAA);
    out[pos] = {
      waa: filled ? sWAA : replWAA,      // empty slot = a replacement-level body, in WAA
      filled,
      count: (filled ? 1 : 0) + (Number.isFinite(bWAA) ? 1 : 0),
      top: filled ? { name: s.Name, waa: sWAA, age: _num(s.Age), lev: s.Lev } : null,
      depth: Number.isFinite(bWAA) ? { name: b.Name, waa: bWAA, age: _num(b.Age), lev: b.Lev } : null,
    };
  }
  return out;
}

/**
 * Staff side of one org. Same order of operations the roster optimizer uses:
 * the rotation is taken first from anyone not typed as a reliever, then the pen
 * comes out of whoever is left. Slots the org cannot fill are charged at the
 * league's org replacement level for that role.
 */
function armGroups(teamPitchers, lens, repl) {
  const scored = teamPitchers.map(p => {
    const pos = (p.POS || '').toUpperCase();
    return {
      p,
      sp: _num(p[lens.spCol]),
      rp: _num(p[lens.rpCol]),
      isStarter: pos === 'SP',
      isReliever: pos === 'RP' || pos === 'CL' || pos === 'MR',
    };
  });

  const spSorted = scored
    .filter(x => (x.isStarter || !x.isReliever) && x.sp !== null)
    .sort((a, b) => b.sp - a.sp);
  const spIds = new Set(spSorted.slice(0, 5).map(x => _idOf(x.p)));
  const rpSorted = scored
    .filter(x => !spIds.has(_idOf(x.p)) && x.rp !== null)
    .sort((a, b) => b.rp - a.rp);

  const group = (sorted, key, slots, replRole) => {
    const picked = sorted.slice(0, slots);
    const vals = picked.map(x => x[key]);
    const missing = slots - vals.length;
    const waa = vals.reduce((s, v) => s + v, 0) + missing * -replRole;
    const one = (x) => (x ? { name: x.p.Name, waa: x[key], age: _num(x.p.Age), lev: x.p.Lev } : null);
    return {
      waa,
      filled: missing === 0,
      count: vals.length,
      top: one(picked[0]),
      // the first arm OUTSIDE the group — the bats' "next up" means the same thing,
      // and the column claims it is not folded into the score, so it must not be
      depth: one(sorted[slots]),
    };
  };

  return {
    SP: group(spSorted, 'sp', 5, repl.sp),
    RP: group(rpSorted, 'rp', 8, repl.rp),
  };
}

/** Population mean/SD of a league's team scores at one position. */
function moments(values) {
  const n = values.length;
  if (!n) return { mean: 0, sd: 0 };
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const sd = Math.sqrt(values.reduce((s, v) => s + (v - mean) * (v - mean), 0) / n);
  return { mean, sd };
}

/**
 * Score, z-score and rank every org in ONE league at every position.
 *
 * @param {Array} hitters   the league's shipped hitter rows
 * @param {Array} pitchers  the league's shipped pitcher rows
 * @param {Object} options  { league, knownTeams, lens }
 * @returns {{ league, lens, teams, positions, cells, summary }}
 *   cells[team][pos] = { waa, z, rank, pct, filled, count, top, depth }
 *   summary[pos]     = { mean, sd, best, worst, teamCount }
 */
export function buildPositionalStrength(hitters = [], pitchers = [], options = {}) {
  const { league = null, knownTeams = null, lens: lensKey = DEFAULT_LENS } = options;
  const lens = LENSES[lensKey] || LENSES[DEFAULT_LENS];

  // Team set comes from the FULL pools so it doesn't shrink when a lens is
  // narrow (an org with an empty farm still belongs in the league).
  const teams = leagueOrgs(hitters, pitchers, knownTeams).sort();
  if (!teams.length) return { league, lens, teams: [], positions: STRENGTH_POSITIONS, cells: {}, summary: {} };

  // ORG ("next man up") replacement, flipped into WAA: a replacement body is
  // WAR 0, i.e. WAA = −offset.
  const repl = {
    hitter: replacementOrgOffset(league, 'hitter'),
    sp: replacementOrgOffset(league, 'sp'),
    rp: replacementOrgOffset(league, 'rp'),
  };
  const replBatWAA = -repl.hitter;

  const byOrgH = {}, byOrgP = {};
  for (const h of hitters) if (lens.inLens(h) && h.ORG) (byOrgH[h.ORG] = byOrgH[h.ORG] || []).push(h);
  for (const p of pitchers) if (lens.inLens(p) && p.ORG) (byOrgP[p.ORG] = byOrgP[p.ORG] || []).push(p);

  const cells = {};
  for (const team of teams) {
    const bats = batGroups(byOrgH[team] || [], lens.split, replBatWAA);
    const arms = armGroups(byOrgP[team] || [], lens, repl);
    cells[team] = { ...bats, ...arms };
  }

  // z-score and rank WITHIN this league only.
  const summary = {};
  for (const { key } of STRENGTH_POSITIONS) {
    const rows = teams.map(t => ({ team: t, waa: cells[t][key].waa }));
    const { mean, sd } = moments(rows.map(r => r.waa));
    const sorted = [...rows].sort((a, b) => b.waa - a.waa);
    const rankOf = {};
    sorted.forEach((r, i) => {
      // competition ranking: equal scores share the better rank
      rankOf[r.team] = (i > 0 && r.waa === sorted[i - 1].waa) ? rankOf[sorted[i - 1].team] : i + 1;
    });
    for (const t of teams) {
      const c = cells[t][key];
      c.z = sd > 0 ? (c.waa - mean) / sd : 0;
      c.rank = rankOf[t];
      c.pct = teams.length > 1 ? 1 - (c.rank - 1) / (teams.length - 1) : 1;
    }
    summary[key] = {
      mean, sd, teamCount: teams.length,
      best: { team: sorted[0].team, waa: sorted[0].waa },
      worst: { team: sorted[sorted.length - 1].team, waa: sorted[sorted.length - 1].waa },
    };
  }

  return { league, lens, teams, positions: STRENGTH_POSITIONS, cells, summary };
}

/**
 * One org's row, position order preserved, with the league context each cell is
 * ranked against attached — what the org card renders.
 */
export function teamPositionalStrength(build, team) {
  if (!build || !build.cells[team]) return [];
  return build.positions.map(pos => ({
    ...pos,
    ...build.cells[team][pos.key],
    league: build.summary[pos.key],
  }));
}
