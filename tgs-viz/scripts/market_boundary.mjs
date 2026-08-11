/**
 * market_boundary.mjs — audit of computeScarcityBoundary: how far the LOCAL
 * (LOESS) market price departs the fitted line at each observed WAR, and how
 * long the departing run is. Read-only.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fitFAMarket, resolveRate, localFit } from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');
const load = (lg, f) => JSON.parse(fs.readFileSync(path.join(DATA, lg, f), 'utf8'))
  .map(r => ({ ...r, _appLeague: lg }));

for (const lg of ['TGS', 'BLM']) {
  const fit = fitFAMarket(load(lg, 'hitters.json'), load(lg, 'pitchers.json'));
  console.log(`\n########## ${lg} ##########`);
  for (const role of ['hitter', 'pitcher']) {
    const r = resolveRate(fit, role);
    const xs = [...new Set(r.sample.map(p => p.x))].sort((a, b) => a - b);
    const top = xs.slice(-8);
    console.log(`  ${role} (sample n=${r.sample.length}, residSD $${(r.residSD / 1e6).toFixed(2)}M) ` +
      `boundary=${r.boundary === null ? 'null' : r.boundary.toFixed(2)}`);
    for (const x of top) {
      const lf = localFit(r.sample, x);
      if (!lf) continue;
      const dep = lf.mid - r.priceAt(x);
      console.log(`     WAR ${x.toFixed(2)}: local $${(lf.mid / 1e6).toFixed(2)}M vs line ` +
        `$${(r.priceAt(x) / 1e6).toFixed(2)}M  depart ${(dep / 1e6).toFixed(2)}M ` +
        `(${(dep / r.residSD).toFixed(2)} SD) ${dep > r.residSD ? '<< DEPARTS' : ''}`);
    }
  }
}
