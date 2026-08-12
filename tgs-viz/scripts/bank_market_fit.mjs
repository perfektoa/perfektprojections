/**
 * bank_market_fit.mjs — banks the FA market fit per league so that the price
 * of a win survives free agency opening.
 *
 * When FA opens, OOTP resets ContractYr on the whole league. fitFAMarket's
 * open-market filter (MLB, ContractYr 1, >= 6 service years at signing) then
 * has almost nothing left to fit, and the $/WAR line refits onto noise at the
 * exact moment the user is signing free agents. The bank holds the
 * best-supported fit this league has ever produced; marketValue.js prefers it
 * whenever the live sample is smaller.
 *
 *   node scripts/bank_market_fit.mjs                 both leagues, from live data
 *   node scripts/bank_market_fit.mjs TGS             one league
 *   node scripts/bank_market_fit.mjs --from 20260811-174756 TGS
 *   node scripts/bank_market_fit.mjs --force TGS
 *
 * Write rule: only overwrite an existing bank when the new fit rests on at
 * least as many open-market signings (n >= banked n). No threshold to tune —
 * the bank simply keeps the best-supported fit seen so far, and a recovered
 * live sample takes over on its own. --force overrides.
 *
 * --from <YYYYMMDD-HHMMSS> fits the timestamped hitters/pitchers .bak- pair
 * instead of the live JSON. Needed once per league whose FA period had already
 * opened before banking existed: fitting live there would bank the collapsed
 * sample and defend nothing.
 *
 * Leagues are independent: one bank file per league, one decision per league,
 * never a number crossing between them.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fitFAMarket, marketFitSupport } from '../src/lib/marketValue.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, '..', 'public', 'data');
const BANK = 'market_fit.json';
const STAMP = /^\d{8}-\d{6}$/;

const argv = process.argv.slice(2);
const force = argv.includes('--force');
const fromIdx = argv.indexOf('--from');
const fromStamp = fromIdx >= 0 ? argv[fromIdx + 1] : null;
const leagues = argv.filter((a, i) => !a.startsWith('--') && !(fromIdx >= 0 && i === fromIdx + 1));
if (fromStamp && !STAMP.test(fromStamp)) {
  console.error(`--from expects a backup stamp like 20260811-174756, got "${fromStamp}"`);
  process.exit(1);
}
if (!leagues.length) {
  // The app's own manifest, so stray folders under public/data are not banked.
  const manifest = JSON.parse(fs.readFileSync(path.join(DATA, 'leagues.json'), 'utf8'));
  const list = Array.isArray(manifest) ? manifest : manifest.leagues || [];
  leagues.push(...list.map(lg => lg.id).filter(Boolean));
}
if (fromStamp && leagues.length !== 1) {
  console.error('--from banks one specific snapshot — name exactly one league.');
  process.exit(1);
}

const m = (v) => (Number.isFinite(v) ? `$${(v / 1e6).toFixed(2)}M` : '-');

/** Load a league file the way the app does: rows stamped with _appLeague. */
function load(league, file) {
  const rows = JSON.parse(fs.readFileSync(path.join(DATA, league, file), 'utf8'));
  return rows
    .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-')
    .map(p => ({ ...p, _appLeague: league }));
}

/** Backup suffix in the project's convention, e.g. 20260811-184809. */
function stampNow() {
  return new Date().toISOString().replace(/\D/g, '').slice(0, 14).replace(/^(\d{8})/, '$1-');
}

/** ISO date the fit describes: the backup's own date, or today for a live fit. */
function fitDate(stamp) {
  if (!stamp) return new Date().toISOString().slice(0, 10);
  return `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)}`;
}

for (const league of leagues) {
  const dir = path.join(DATA, league);
  const suffix = fromStamp ? `.bak-${fromStamp}` : '';
  const hFile = `hitters.json${suffix}`;
  const pFile = `pitchers.json${suffix}`;
  if (!fs.existsSync(path.join(dir, hFile)) || !fs.existsSync(path.join(dir, pFile))) {
    console.log(`${league}: SKIP — ${hFile} / ${pFile} not found`);
    continue;
  }

  const fit = fitFAMarket(load(league, hFile), load(league, pFile));
  const n = marketFitSupport(fit);
  if (!n || !fit.pooled || !(fit.pooled.slope > 0)) {
    console.log(`${league}: SKIP — nothing worth banking (n=${n}, no usable pooled slope)`);
    continue;
  }

  const bankPath = path.join(dir, BANK);
  let prev = null;
  if (fs.existsSync(bankPath)) {
    try { prev = JSON.parse(fs.readFileSync(bankPath, 'utf8')); } catch { prev = null; }
  }
  const prevN = prev ? marketFitSupport(prev.fit) : 0;

  const what = `n=${n} slope ${m(fit.pooled.slope)}/WAR floor ${m(fit.pooled.floor)} `
    + `r2 ${fit.pooled.r2.toFixed(3)}${fromStamp ? ` (from backup ${fromStamp})` : ''}`;

  if (prev && n < prevN && !force) {
    console.log(`${league}: KEPT the banked fit — banked n=${prevN} `
      + `slope ${m(prev.fit.pooled.slope)}/WAR from ${prev.bankedAt}; new fit is only ${what}`);
    continue;
  }

  const record = {
    fit,
    n,
    bankedAt: fitDate(fromStamp),
    writtenAt: new Date().toISOString(),
    source: fromStamp ? `backup-${fromStamp}` : 'live-fit',
    leagueId: league,
  };
  if (prev) fs.copyFileSync(bankPath, `${bankPath}.bak-${stampNow()}`);
  fs.writeFileSync(bankPath, `${JSON.stringify(record, null, 2)}\n`);
  console.log(`${league}: WROTE ${path.relative(process.cwd(), bankPath)} — ${what}`
    + (prev ? ` (replaces banked n=${prevN} from ${prev.bankedAt}${force && n < prevN ? ', FORCED' : ''})`
      : ' (first bank)'));
}
