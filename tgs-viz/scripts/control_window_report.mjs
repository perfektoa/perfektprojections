/**
 * Measure serviceTime.controlWindow on the shipped data — per league, never
 * pooled. Reports the control-year distribution, the fallback rate, and
 * before/after (6-year assumption vs real control) for named players.
 *
 *   node scripts/control_window_report.mjs
 */
import { readFileSync } from 'node:fs';
import { controlWindow } from '../src/lib/serviceTime.js';
import { calculateFutureValue } from '../src/lib/futureValue.js';
import { fitFAMarket, resolveRate, calculatePlayerValue, getPlayerRole, formatMoney } from '../src/lib/marketValue.js';

const BASE = new URL('../public/data/', import.meta.url);
const load = (lg, f) => JSON.parse(readFileSync(new URL(`${lg}/${f}.json`, BASE), 'utf8'))
  .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-')
  .map(p => ({ ...p, _appLeague: lg }));

const schedTotal = (p) => (Array.isArray(p.SalarySchedule)
  ? p.SalarySchedule.filter(Number.isFinite).reduce((s, v) => s + v, 0) : 0);

for (const lg of ['TGS', 'BLM']) {
  const hitters = load(lg, 'hitters');
  const pitchers = load(lg, 'pitchers');
  const all = [...hitters, ...pitchers];

  console.log(`\n=========== ${lg} — ${all.length} rows (${hitters.length} H / ${pitchers.length} P) ===========`);

  const dist = new Map(), distMLB = new Map(), src = new Map(), srcMLB = new Map();
  let mlb = 0;
  for (const p of all) {
    const cw = controlWindow(p);
    dist.set(cw.controlYears, (dist.get(cw.controlYears) || 0) + 1);
    src.set(cw.source, (src.get(cw.source) || 0) + 1);
    if (p.Lev === 'MLB') {
      mlb += 1;
      distMLB.set(cw.controlYears, (distMLB.get(cw.controlYears) || 0) + 1);
      srcMLB.set(cw.source, (srcMLB.get(cw.source) || 0) + 1);
    }
  }
  const show = (m, tot) => [...m.entries()].sort((a, b) => a[0] - b[0])
    .map(([k, v]) => `${k}y:${v} (${(100 * v / tot).toFixed(1)}%)`).join('  ');
  console.log('control-yr dist ALL :', show(dist, all.length));
  console.log('control-yr dist MLB :', show(distMLB, mlb), `  [n=${mlb}]`);
  console.log('source ALL          :', [...src].map(([k, v]) => `${k}:${v} (${(100 * v / all.length).toFixed(1)}%)`).join('  '));
  console.log('source MLB          :', [...srcMLB].map(([k, v]) => `${k}:${v} (${(100 * v / mlb).toFixed(1)}%)`).join('  '));
  const changed = all.filter(p => controlWindow(p).controlYears !== 6).length;
  console.log(`rows no longer valued at 6y: ${changed} / ${all.length} (${(100 * changed / all.length).toFixed(1)}%)`);
  const fallback = all.filter(p => controlWindow(p).source === 'default');
  console.log(`rows on the 6y DEFAULT fallback (no service, no contract): ${fallback.length}`);
  const overTable = all.filter(p => {
    const cw = controlWindow(p);
    const age = Math.round(parseFloat(p.Age) || 25);
    return Math.max(1, Math.min(cw.controlYears, 34 - age)) > Math.max(1, Math.min(8, 34 - age));
  });
  console.log(`rows whose control horizon exceeds the 8-yr offer table: ${overTable.length}` +
    (overTable.length ? ` (e.g. ${overTable.slice(0, 3).map(p => `${p.Name} age ${p.Age}`).join(', ')})` : ''));

  // --- before/after on the $ layer. Fit the FA market once per league. ---
  const withFV = (p, yoc) => ({ ...p, _fvBreakdown: calculateFutureValue(p, yoc) });
  const fit = fitFAMarket(hitters.map(p => withFV(p, controlWindow(p).controlYears)),
                          pitchers.map(p => withFV(p, controlWindow(p).controlYears)));
  const rateFor = (p) => resolveRate(fit, getPlayerRole(p) === 'pitcher' ? 'pitcher' : 'hitter');

  const evaluate = (p, yoc) => {
    const row = withFV(p, yoc);
    // OLD offer horizon was a flat 6 clipped at career end; emulate it by
    // reading the offerByLength row the old code would have selected.
    const v = calculatePlayerValue(row, rateFor(p));
    return v;
  };
  const oldHorizon = (age) => Math.max(1, Math.min(6, 34 - age));

  const pick = (name) => all.find(p => p.Name === name);
  const examples = [];
  const mlbRows = all.filter(p => p.Lev === 'MLB' && schedTotal(p) > 0);
  const cwOf = (p) => controlWindow(p);
  // a vet whose control collapsed the most, a mid-career guy, a pre-arb kid,
  // a player extended past free agency, and the biggest 1-year-left name.
  const byDrop = [...mlbRows].sort((a, b) => cwOf(a).controlYears - cwOf(b).controlYears
    || (b._fvBreakdown ? 0 : 0) || (parseFloat(b['Max WAA wtd'] ?? b['WAA wtd']) || -9)
     - (parseFloat(a['Max WAA wtd'] ?? a['WAA wtd']) || -9));
  examples.push(byDrop[0], byDrop[1]);
  const preArb = mlbRows.filter(p => cwOf(p).isPreArb && cwOf(p).controlYears >= 5)
    .sort((a, b) => (parseFloat(b['Max WAA wtd'] ?? b['WAA wtd']) || -9) - (parseFloat(a['Max WAA wtd'] ?? a['WAA wtd']) || -9));
  examples.push(preArb[0]);
  const extended = mlbRows.filter(p => cwOf(p).source === 'contract' && cwOf(p).contractYears > (cwOf(p).yearsToFA ?? 0))
    .sort((a, b) => cwOf(b).controlYears - cwOf(a).controlYears);
  examples.push(extended[0]);
  const mid = mlbRows.filter(p => cwOf(p).controlYears === 3)
    .sort((a, b) => (parseFloat(b['Max WAA wtd'] ?? b['WAA wtd']) || -9) - (parseFloat(a['Max WAA wtd'] ?? a['WAA wtd']) || -9));
  examples.push(mid[0]);

  console.log('\n  --- named before/after (6-yr assumption -> real control) ---');
  for (const p of examples.filter(Boolean)) {
    const cw = cwOf(p);
    const age = Math.round(parseFloat(p.Age) || 25);
    const before = evaluate(p, 6);
    const after = evaluate(p, cw.controlYears);
    const oh = oldHorizon(age);
    const offBefore = before.offerByLength.find(o => o.years === oh) || before.offerByLength[0];
    const offAfter = after.offerByLength.find(o => o.years === after.offerYears) || after.offerByLength[0];
    const salary = schedTotal(p);
    console.log(
      `  ${p.Name} (${p.POS}, age ${age}, ${p.ORG}) svc ${cw.serviceYears?.toFixed(2)} | deal ${cw.contractYears}y | control ${cw.controlYears}y [${cw.source}]\n` +
      `      window value   ${formatMoney(before.totalValue)} -> ${formatMoney(after.totalValue)}` +
      `   (vs remaining salary ${formatMoney(salary)}: surplus ${formatMoney(before.totalValue - salary)} -> ${formatMoney(after.totalValue - salary)})\n` +
      `      FV 20-80       ${before.rateUsed ? '' : ''}${withFV(p, 6)._fvBreakdown.fvScale} -> ${withFV(p, cw.controlYears)._fvBreakdown.fvScale}\n` +
      `      fair offer     ${oh}y @ ${formatMoney(offBefore.aav)} (tot ${formatMoney(offBefore.total)})` +
      ` -> ${after.offerYears}y @ ${formatMoney(offAfter.aav)} (tot ${formatMoney(offAfter.total)})`
    );
  }

  // aggregate impact on MLB rows
  let dv = 0, n = 0;
  for (const p of mlbRows) {
    const cw = cwOf(p);
    if (cw.controlYears === 6) continue;
    const b = withFV(p, 6)._fvBreakdown.futureValue;
    const a = withFV(p, cw.controlYears)._fvBreakdown.futureValue;
    dv += a - b; n += 1;
  }
  console.log(`\n  MLB contracted rows whose FV window changed: ${n}; mean raw-FV change ${(dv / Math.max(1, n)).toFixed(2)} WAR-seasons`);
}
