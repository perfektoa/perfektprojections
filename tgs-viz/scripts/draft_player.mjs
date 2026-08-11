// Dump one draft prospect's full Draft FV breakdown and his rank on the board.
// Replicates usePlayersWithDraftFV exactly.
import fs from 'node:fs';
import { buildAgeGroups, calculateDraftFV } from '../src/lib/draftFV.js';
import { replacementOffset } from '../src/lib/leagueCalib.js';

const NEEDLE = (process.argv[2] || '').toLowerCase();

for (const LEAGUE of ['BLM', 'TGS']) {
  for (const TYPE of ['pitcher', 'hitter']) {
    const base = new URL(`../public/data/${LEAGUE}/`, import.meta.url);
    const read = (f) => {
      try { return JSON.parse(fs.readFileSync(new URL(f, base), 'utf8')); } catch { return null; }
    };
    const rows = (d) => (!d ? [] : Array.isArray(d) ? d : d.rows || []);
    const all = rows(read(TYPE === 'hitter' ? 'hitters.json' : 'pitchers.json'));
    const draft = rows(read(TYPE === 'hitter' ? 'hitters_draft.json' : 'pitchers_draft.json'));
    if (!all.length || !draft.length) continue;

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

    const ageGroups = buildAgeGroups(all, metric);
    const scored = draft.map((p) => ({ p, d: calculateDraftFV(p, ageGroups, TYPE) }))
      .filter((x) => Number.isFinite(x.d.draftRawFV))
      .sort((a, b) => b.d.draftRawFV - a.d.draftRawFV);

    const hits = scored.map((x, i) => ({ ...x, rank: i + 1 }))
      .filter((x) => (x.p.Name || '').toLowerCase().includes(NEEDLE));
    for (const h of hits) {
      const { p, d, rank } = h;
      console.log(`\n=== ${p.Name} — ${LEAGUE} ${TYPE} board, RANK ${rank} of ${scored.length} ===`);
      console.log(`  Age ${p.Age}  POS ${p.POS}  Prone ${d.proneValue}  WE ${p.WE}  INT ${p.INT}`);
      console.log(`  agePercentile ${d.agePercentile}   ceilingScore ${d.ceilingScore}`);
      console.log(`  ceiling WAR ${d.draftCeiling}   ceiling WAA ${d.draftCeilingWAA}   role ${d.ceilingRole}`);
      console.log(`  base = ${d.agePercentile}*0.30 + ${d.ceilingScore}*0.70 = ${(d.agePercentile * 0.30 + d.ceilingScore * 0.70).toFixed(2)}`);
      console.log(`  toolPenalty ${d.toolPenalty}  durabilityMod ${d.durabilityMod}  weBoost ${d.weBoost}  highINT ${d.highINT}  wrecked ${d.wrecked}`);
      console.log(`  RAW ${d.draftRawFV}   (20-80 FV ${d.draftFV})`);
      const better = scored.slice(0, Math.min(rank - 1, 5)).map((x) =>
        `${x.p.Name} raw ${x.d.draftRawFV.toFixed(1)} [age% ${x.d.agePercentile} ceil ${x.d.ceilingScore} WAR ${x.d.draftCeiling?.toFixed(2)}]`);
      console.log('  ranked above him (top 5): ' + (better.join('\n     ') || '—'));
    }
  }
}
