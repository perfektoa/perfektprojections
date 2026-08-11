// Sanity report for src/lib/positionalStrength.js — per league, per lens:
// the user's own club's rank at every position, plus the league's strongest and
// weakest club at two positions. Read-only; touches nothing but public/data.
import fs from 'node:fs';
import { buildPositionalStrength, teamPositionalStrength } from '../src/lib/positionalStrength.js';

const MY_TEAM = { TGS: 'Chicago Cubs', BLM: 'Chicago (N) Cubs' };
const SHOWCASE = ['SS', 'C'];
const f = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));

for (const lg of ['TGS', 'BLM']) {
  const hitters = JSON.parse(fs.readFileSync(`public/data/${lg}/hitters.json`, 'utf8'))
    .map(p => ({ ...p, _appLeague: lg }));
  const pitchers = JSON.parse(fs.readFileSync(`public/data/${lg}/pitchers.json`, 'utf8'))
    .map(p => ({ ...p, _appLeague: lg }));

  for (const lens of ['mlb', 'farm']) {
    const build = buildPositionalStrength(hitters, pitchers, { league: lg, lens });
    console.log(`\n=== ${lg} / ${build.lens.label} (${build.lens.note}) — ${build.teams.length} teams ===`);
    const me = MY_TEAM[lg];
    if (!build.cells[me]) { console.log(`  !! ${me} not in team list: ${build.teams.join(', ')}`); continue; }
    console.log(`  ${me}`);
    for (const r of teamPositionalStrength(build, me)) {
      console.log(
        `    ${r.key.padEnd(3)} WAA ${f(r.waa).padStart(7)}  z ${f(r.z).padStart(6)}  rank ${String(r.rank).padStart(2)}/${r.league.teamCount}` +
        `  top: ${(r.top ? `${r.top.name} ${f(r.top.waa)}` : 'none — replacement').padEnd(30)}` +
        `  next: ${r.depth ? `${r.depth.name} ${f(r.depth.waa)}` : '—'}`
      );
    }
    for (const pos of SHOWCASE) {
      const s = build.summary[pos];
      console.log(`  ${pos}: best ${s.best.team} ${f(s.best.waa)} | worst ${s.worst.team} ${f(s.worst.waa)} | mean ${f(s.mean)} sd ${f(s.sd)}`);
    }
  }
}
