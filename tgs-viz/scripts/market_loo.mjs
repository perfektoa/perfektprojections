/**
 * market_loo.mjs — robustness of the SHAPE decision: re-run the fit with each
 * single signing removed and count how often the curvature still clears its
 * gates. A shape that depends on one contract is not a shape. Read-only.
 *   node tgs-viz/scripts/market_loo.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fitFAMarket } from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');
const load = (lg, f) => JSON.parse(fs.readFileSync(path.join(DATA, lg, f), 'utf8'))
  .map(r => ({ ...r, _appLeague: lg }));

for (const lg of ['TGS', 'BLM']) {
  const hitters = load(lg, 'hitters.json');
  const pitchers = load(lg, 'pitchers.json');
  const base = fitFAMarket(hitters, pitchers);
  const keys = new Set(base.sample.map(s => `${s.name}|${s.org}`));
  console.log(`\n########## ${lg}  base pooled shape = ${base.pooled.shape} ` +
    `(n=${base.sample.length}) ##########`);
  let quad = 0, line = 0;
  const flips = [];
  for (const key of keys) {
    const drop = (arr) => arr.filter(p => `${p.Name}|${p.ORG}` !== key);
    const f = fitFAMarket(drop(hitters), drop(pitchers));
    if (f.pooled.shape === 'quad') quad += 1; else line += 1;
    if (f.pooled.shape !== base.pooled.shape) flips.push(key);
  }
  console.log(`  leave-one-out over the ${keys.size} signings: ` +
    `quad ${quad} / line ${line}  -> the shipped shape survives ` +
    `${Math.round(100 * (base.pooled.shape === 'quad' ? quad : line) / keys.size)}% of drops`);
  if (flips.length) {
    console.log(`  flips when dropped (${flips.length}): ${flips.slice(0, 12).join(', ')}` +
      (flips.length > 12 ? ' ...' : ''));
  }
}
