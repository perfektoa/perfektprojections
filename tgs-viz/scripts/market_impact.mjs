/**
 * market_impact.mjs — how the v3 fit moves actual player valuations, and how
 * far the no-extrapolation clamp reaches. Read-only.
 *   node tgs-viz/scripts/market_impact.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fitFAMarket, resolveRate, getPlayerWAR, getPlayerRole } from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');
const load = (lg, f) => JSON.parse(fs.readFileSync(path.join(DATA, lg, f), 'utf8'))
  .map(r => ({ ...r, _appLeague: lg }));

for (const lg of ['TGS', 'BLM']) {
  const hitters = load(lg, 'hitters.json');
  const pitchers = load(lg, 'pitchers.json');
  const fit = fitFAMarket(hitters, pitchers);
  const rates = { hitter: resolveRate(fit, 'hitter'), pitcher: resolveRate(fit, 'pitcher') };
  console.log(`\n########## ${lg} ##########`);
  for (const role of ['hitter', 'pitcher']) {
    const r = rates[role];
    const pool = (role === 'hitter' ? hitters : pitchers).filter(p => p.Lev === 'MLB');
    const wars = pool.map(getPlayerWAR).filter(w => w !== null);
    const above = wars.filter(w => w > r.maxX).length;
    console.log(`  ${role.padEnd(8)} shape=${r.shape} floor=${r.floorMode} ` +
      `maxObservedWAR=${r.maxX.toFixed(2)}  MLB players above it: ${above}/${wars.length}` +
      (r.curv ? ' (CLAMPED — curve)' : ' (line: not clamped)'));
    const q = [...wars].sort((a, b) => a - b);
    console.log(`      MLB WAR percentiles p50 ${q[Math.floor(q.length * 0.5)].toFixed(2)} ` +
      `p90 ${q[Math.floor(q.length * 0.9)].toFixed(2)} ` +
      `p99 ${q[Math.floor(q.length * 0.99)].toFixed(2)} max ${q[q.length - 1].toFixed(2)}`);
  }
  // role sanity: what a 2-WAR and a 4-WAR player costs
  for (const w of [1, 2, 3, 4, 5]) {
    console.log(`   WAR ${w}: hitter $${(rates.hitter.priceAt(w) / 1e6).toFixed(2)}M  ` +
      `pitcher $${(rates.pitcher.priceAt(w) / 1e6).toFixed(2)}M`);
  }
  void getPlayerRole;
}
