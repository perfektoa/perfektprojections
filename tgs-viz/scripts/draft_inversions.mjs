// Find draft-board pairs where one player is >= on BOTH scoring inputs
// (age percentile and ceiling) yet scores LOWER on raw Draft FV.
// Replicates usePlayersWithDraftFV exactly: same metric, same age groups.
import fs from 'node:fs';
import { buildAgeGroups, calculateDraftFV } from '../src/lib/draftFV.js';
import { replacementOffset } from '../src/lib/leagueCalib.js';

const LEAGUE = process.argv[2] || 'BLM';
const TYPE = process.argv[3] || 'hitter';   // hitter | pitcher

const base = new URL(`../public/data/${LEAGUE}/`, import.meta.url);
const read = (f) => JSON.parse(fs.readFileSync(new URL(f, base), 'utf8'));
const rows = (d) => (Array.isArray(d) ? d : d.rows || []);

const allPlayers = rows(read(TYPE === 'hitter' ? 'hitters.json' : 'pitchers.json'));
const draft = rows(read(TYPE === 'hitter' ? 'hitters_draft.json' : 'pitchers_draft.json'));

const metric = TYPE === 'hitter'
  ? 'wOBA wtd'
  : (() => {
      const spOff = replacementOffset(LEAGUE, 'sp');
      const rpOff = replacementOffset(LEAGUE, 'rp');
      return (p) => {
        const sp = parseFloat(p['WAA wtd']);
        const rp = parseFloat(p['WAA wtd RP']);
        const best = Math.max(isNaN(sp) ? -Infinity : sp + spOff, isNaN(rp) ? -Infinity : rp + rpOff);
        return isFinite(best) ? best : NaN;
      };
    })();

const ageGroups = buildAgeGroups(allPlayers, metric);
const scored = draft.map((p) => {
  const d = calculateDraftFV(p, ageGroups, TYPE);
  return {
    name: p.Name, age: parseFloat(p.Age), pos: p.POS,
    ap: d.agePercentile, cs: d.ceilingScore, raw: d.draftRawFV,
    ceilWAR: d.draftCeiling, ceilWAA: d.draftCeilingWAA,
    tool: d.toolPenalty, dur: d.durabilityMod, prone: d.proneValue,
    we: p.WrkEthic, int: p.Int, weBoost: d.weBoost, wrecked: d.wrecked,
    flagged: d.proneValue === 'Fragile' || d.proneValue === 'Wrecked' || p.WrkEthic === 'L' || p.Int === 'L',
  };
}).filter((x) => Number.isFinite(x.raw));

console.log(`${LEAGUE} ${TYPE}: ${scored.length} draft players scored`);

// strict inversion: A >= B on both inputs, strictly greater on at least one, but raw lower
const inv = [];
for (const a of scored) {
  for (const b of scored) {
    if (a === b) continue;
    if (a.ap >= b.ap && a.cs >= b.cs && (a.ap > b.ap || a.cs > b.cs) && a.raw < b.raw) {
      inv.push({ a, b, gap: b.raw - a.raw });
    }
  }
}
inv.sort((x, y) => y.gap - x.gap);
const clean = inv.filter(({ a, b }) => !a.flagged && !b.flagged);
console.log(`strict inversions total: ${inv.length}   involving a RED FLAG (allowed): ${inv.length - clean.length}   among CLEAN prospects (must be 0): ${clean.length}`);

const seen = new Set();
let shown = 0;
for (const { a, b, gap } of inv) {
  const k = a.name + '|' + b.name;
  if (seen.has(k) || shown >= 12) continue;
  seen.add(k); shown++;
  const base_a = a.ap * 0.30 + a.cs * 0.70;
  const base_b = b.ap * 0.30 + b.cs * 0.70;
  console.log(
    `\n  ${a.name} (${a.pos} ${a.age}) raw ${a.raw.toFixed(2)}  <  ${b.name} (${b.pos} ${b.age}) raw ${b.raw.toFixed(2)}   gap ${gap.toFixed(2)}`
    + `\n    age%    ${a.ap.toFixed(1).padStart(6)} vs ${b.ap.toFixed(1).padStart(6)}`
    + `\n    ceiling ${a.cs.toFixed(1).padStart(6)} vs ${b.cs.toFixed(1).padStart(6)}   (WAR ${a.ceilWAR?.toFixed(2)} vs ${b.ceilWAR?.toFixed(2)})`
    + `\n    base    ${base_a.toFixed(2).padStart(6)} vs ${base_b.toFixed(2).padStart(6)}  <- before multipliers`
    + `\n    tool    ${a.tool} vs ${b.tool}   durability ${a.dur} (${a.prone}) vs ${b.dur} (${b.prone})   WE ${a.we}/${a.weBoost} vs ${b.we}/${b.weBoost}`
  );
}

// how much of the board does each multiplier move?
const tally = (key) => {
  const m = new Map();
  for (const s of scored) m.set(s[key], (m.get(s[key]) || 0) + 1);
  return [...m.entries()].sort((x, y) => y[1] - x[1]).map(([k, v]) => `${k}:${v}`).join('  ');
};
console.log(`\nmultiplier spread across the board:`);
console.log(`  durabilityMod  ${tally('dur')}`);
console.log(`  toolPenalty    ${tally('tool')}`);
console.log(`  weBoost        ${tally('weBoost')}`);
