/**
 * market_report.mjs — runs the REAL src/lib/marketValue.js fit against the
 * REAL public/data JSON for both leagues and prints the shipped numbers:
 * sample size, per-role slope/floor/curvature + CI, the price schedule at
 * WAR 0..5, the role-agreement gate, and the scarcity boundary.
 *
 *   node tgs-viz/scripts/market_report.mjs
 *
 * Used as the BEFORE/AFTER gate for the market-fit work. Read-only.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  fitFAMarket, resolveRate, computeScarcityBoundary, getPlayerWAR,
} from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');

const m = (v) => (v === null || v === undefined || !Number.isFinite(v)
  ? '    -   ' : `${(v / 1e6).toFixed(2).padStart(7)}M`);

function load(league, file) {
  const p = path.join(DATA, league, file);
  const rows = JSON.parse(fs.readFileSync(p, 'utf8'));
  return rows.map(r => ({ ...r, _appLeague: league }));
}

for (const league of ['TGS', 'BLM']) {
  const hitters = load(league, 'hitters.json');
  const pitchers = load(league, 'pitchers.json');
  const fit = fitFAMarket(hitters, pitchers);

  console.log(`\n########## ${league} ##########`);
  console.log(`  sample n=${fit.sample.length}` +
    (fit.minSalary ? `  measured league minimum ${m(fit.minSalary)}` : '') +
    (fit.svcYearDays ? `  service year = ${fit.svcYearDays} d` : '') +
    (fit.serviceBasis ? `  service basis: ${fit.serviceBasis}` : ''));
  for (const n of fit.notes || []) console.log(`    - ${n}`);

  for (const key of ['pooled', 'hitter', 'pitcher']) {
    const f = fit[key];
    if (!f) { console.log(`  ${key}: (degenerate)`); continue; }
    if (f.cvShape) {
      console.log(`    [${key} curve gates] monotone=${f.cvShape.monotone} ` +
        `measurable=${f.cvShape.measurable} ` +
        `CI=[${(f.curveCI?.lo / 1e6).toFixed(2)},${(f.curveCI?.hi / 1e6).toFixed(2)}] ` +
        `OOS quad ${(f.cvShape.rmseQuad / 1e6).toFixed(3)}M vs line ` +
        `${(f.cvShape.rmseLine / 1e6).toFixed(3)}M (t=${f.cvShape.t.toFixed(2)}, needs<-1) ` +
        `-> ${f.cvShape.adopted ? 'ADOPTED' : 'rejected'}`);
    }
    const ciLo = f.slope - 1.96 * f.seSlope;
    const ciHi = f.slope + 1.96 * f.seSlope;
    console.log(`  ${key.padEnd(8)} n=${String(f.n).padStart(3)} ` +
      `slope ${m(f.slope)}/WAR [${(ciLo / 1e6).toFixed(2)},${(ciHi / 1e6).toFixed(2)}] ` +
      `floor ${m(f.floor)} ` +
      (f.curv ? `curv ${m(f.curv)}/WAR^2 ` : 'curv     -    ') +
      `shape=${f.shape || 'line'} r2 ${f.r2.toFixed(3)} residSD ${m(f.residSD)}`);
  }
  console.log(`  perRole=${fit.perRole}  slopeDiffT=${fit.slopeDiffT?.toFixed(2)}  ` +
    `ratioP/H=${fit.ratioPH?.toFixed(3)}  lowConfidence=${fit.lowConfidence}`);

  for (const role of ['hitter', 'pitcher']) {
    const rate = resolveRate(fit, role);
    const sched = [0, 1, 2, 3, 4, 5].map(w => (
      rate.priceAt ? rate.priceAt(w) : Math.max(0, rate.floor + rate.slope * w)));
    console.log(`  price schedule ${role.padEnd(8)} WAR 0..5: ` +
      sched.map(v => m(v)).join(' '));
    console.log(`      usingRole=${rate.perRole} boundary=${rate.boundary} ` +
      `maxObservedWAR=${rate.maxX !== undefined ? rate.maxX.toFixed(2) : 'n/a'} ` +
      `sampleN=${rate.sample.length}`);
  }

  // role agreement gate (on whatever line each role actually prices with)
  const rh = resolveRate(fit, 'hitter');
  const rp = resolveRate(fit, 'pitcher');
  const at = (r, w) => (r.priceAt ? r.priceAt(w) : Math.max(0, r.floor + r.slope * w));
  const gap3 = Math.abs(at(rp, 3) - at(rh, 3)) / Math.max(at(rh, 3), 1);
  console.log(`  ROLE AGREEMENT at 3 WAR: hitter ${m(at(rh, 3))} vs pitcher ${m(at(rp, 3))} ` +
    `-> ${(gap3 * 100).toFixed(0)}% apart`);
}
