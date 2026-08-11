/**
 * market_sensitivity.mjs — how much the shipped fit depends on the MEASURED
 * service-year length (172 days). Re-runs the real fitFAMarket with the
 * service year overridden to 172 +/- 10 and prints what moves. Read-only.
 *   node tgs-viz/scripts/market_sensitivity.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fitFAMarket, resolveRate, SVC_YEAR_DAYS } from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');
const load = (lg, f) => JSON.parse(fs.readFileSync(path.join(DATA, lg, f), 'utf8'))
  .map(r => ({ ...r, _appLeague: lg }));
const M = (v) => `$${(v / 1e6).toFixed(2)}M`;

for (const lg of ['TGS', 'BLM']) {
  const hitters = load(lg, 'hitters.json');
  const pitchers = load(lg, 'pitchers.json');
  console.log(`\n########## ${lg} — service-year sensitivity ##########`);
  console.log('  L(days)  n    pooled slope   shape  hitter@3WAR  pitcher@3WAR  roles');
  for (const L of [162, 167, SVC_YEAR_DAYS, 177, 182]) {
    const fit = fitFAMarket(hitters, pitchers, { svcYearDays: L });
    const rh = resolveRate(fit, 'hitter');
    const rp = resolveRate(fit, 'pitcher');
    console.log(
      `  ${String(L).padStart(3)}${L === SVC_YEAR_DAYS ? '*' : ' '}   ` +
      `${String(fit.sample.length).padStart(3)}  ${M(fit.pooled.slope).padStart(9)}/WAR  ` +
      `${fit.pooled.shape.padEnd(5)}  ${M(rh.priceAt(3)).padStart(9)}    ` +
      `${M(rp.priceAt(3)).padStart(9)}   ` +
      `${fit.perRole ? 'split' : 'pooled'}`);
  }
  console.log('  * = the MEASURED value (identity route, see marketValue.js header)');
}
