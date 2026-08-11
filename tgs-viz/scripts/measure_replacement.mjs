/**
 * measure_replacement.mjs — M5: MEASURE each league's replacement level from
 * the live app data through the real optimizer, and verify the win zero-sum.
 *
 * Replacement level per role = the mean value of the MARGINAL rostered player
 * when every org fields its best 26 (the audit's "fringe-roster" framing):
 *   hitter: the lowest Max-WAA bat among each org's rostered 13
 *   sp:     the 5th starter's SP WAA
 *   rp:     the 8th reliever's RP WAA (post-D6 calibration slope)
 * averaged across all MLB orgs. WAR offsets = -(these means). Numbers go into
 * src/lib/leagueCalib.js **replacementOrg** block — this measures the ORG
 * ("next man up") level only. The MARKET level (replacementMarket, the $-layer
 * currency) is measured from the freely-available FA/waiver pool instead —
 * do NOT overwrite it with these numbers. Re-run this after any engine
 * recalibration or data refresh and update that file.
 *
 * Also prints the zero-sum gate: sum over orgs of optimized wins with the
 * league offset applied must equal orgs * G/2.
 *
 *   node tgs-viz/scripts/measure_replacement.mjs [TGS|BLM|both]
 */
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const VIZ = path.dirname(HERE);
const { optimizeRoster, leagueOrgs, leagueWinOffset } =
  await import(url.pathToFileURL(path.join(VIZ, 'src/lib/rosterOptimizer.js')).href);
const { leagueGames } = await import(url.pathToFileURL(path.join(VIZ, 'src/lib/rosterOptimizer.js')).href);

const which = process.argv[2] || 'both';
const leagues = which === 'both' ? ['TGS', 'BLM'] : [which];

for (const league of leagues) {
  const load = (f) => JSON.parse(fs.readFileSync(path.join(VIZ, 'public/data', league, f), 'utf-8'))
    .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-');
  const hitters = load('hitters.json');
  const pitchers = load('pitchers.json');
  const orgs = leagueOrgs(hitters, pitchers);
  const G = leagueGames(league);

  const cutH = [], cutSP = [], cutRP = [];
  const nextH = [], nextSP = [], nextRP = [];
  let winsBasisSum = 0;
  const results = [];
  const num = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : -99; };
  for (const org of orgs) {
    const r = optimizeRoster(hitters, pitchers, { teamOrg: org, league });
    const bats = r.rosteredHitters.map(h => h._maxWAA).filter(Number.isFinite);
    if (bats.length) cutH.push(Math.min(...bats));
    const sp5 = r.startingPitchers[r.startingPitchers.length - 1];
    const rp8 = r.reliefPitchers[r.reliefPitchers.length - 1];
    if (sp5) cutSP.push(sp5._spWAA);
    if (rp8) cutRP.push(rp8._rpWAA);
    // "next man up": best in-org player NOT on the optimized 26 (freely
    // available replacement — not distorted by the forced bench-role picks)
    const rostered = new Set([
      ...r.rosteredHitters.map(h => h.ID || h.Name),
      ...r.startingPitchers.map(p => p.ID || p.Name),
      ...r.reliefPitchers.map(p => p.ID || p.Name),
    ]);
    const orgH = hitters.filter(h => (h.ORG || '') === org && !rostered.has(h.ID || h.Name));
    const orgP = pitchers.filter(p => (p.ORG || '') === org && !rostered.has(p.ID || p.Name));
    const bh = Math.max(...orgH.map(h => num(h['Max WAA wtd'])));
    const bs = Math.max(...orgP.map(p => num(p['WAA wtd'])));
    const br = Math.max(...orgP.map(p => num(p['WAA wtd RP'])));
    if (bh > -99) nextH.push(bh);
    if (bs > -99) nextSP.push(bs);
    if (br > -99) nextRP.push(br);
    winsBasisSum += r.totals.weightedLineupWAA + r.totals.totalPitcherWAA;
    results.push({ org, basis: r.totals.weightedLineupWAA + r.totals.totalPitcherWAA });
  }
  const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
  const offset = winsBasisSum / orgs.length;

  // zero-sum gate: wins with the offset applied
  let winSum = 0;
  for (const { basis } of results) winSum += G / 2 + basis - offset;

  console.log(`== ${league}: ${orgs.length} orgs, G=${G}`);
  console.log(`   worst rostered (26-man cut line):  hitter ${mean(cutH).toFixed(3)}  SP ${mean(cutSP).toFixed(3)}  RP ${mean(cutRP).toFixed(3)}`);
  console.log(`   best non-rostered (next man up):   hitter ${mean(nextH).toFixed(3)}  SP ${mean(nextSP).toFixed(3)}  RP ${mean(nextRP).toFixed(3)}`);
  const rep = { hitter: -(mean(cutH) + mean(nextH)) / 2, sp: -(mean(cutSP) + mean(nextSP)) / 2, rp: -(mean(cutRP) + mean(nextRP)) / 2 };
  console.log(`   replacement = midpoint of the two -> WAR offsets: hitter ${rep.hitter.toFixed(2)}  SP ${rep.sp.toFixed(2)}  RP ${rep.rp.toFixed(2)}`);
  console.log(`   zero-sum: league win sum ${winSum.toFixed(2)} vs ${orgs.length} * ${G / 2} = ${orgs.length * G / 2}`);
}
