const fs = require('fs');
const path = require('path');

// Load data
const dataPath = path.join(__dirname, 'public', 'data', 'pitchers.json');
const pitchers = JSON.parse(fs.readFileSync(dataPath, 'utf-8'));

console.log(`Total pitchers loaded: ${pitchers.length}\n`);

// ─── Helper functions ───────────────────────────────────────────────────────

function median(arr) {
  if (arr.length === 0) return null;
  const sorted = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function mean(arr) {
  if (arr.length === 0) return null;
  return arr.reduce((s, v) => s + v, 0) / arr.length;
}

function fmt(v, decimals = 2) {
  if (v === null || v === undefined) return 'N/A';
  return v.toFixed(decimals);
}

function padLeft(str, len) {
  str = String(str);
  while (str.length < len) str = ' ' + str;
  return str;
}

function padRight(str, len) {
  str = String(str);
  while (str.length < len) str += ' ';
  return str;
}

// ─── Compute best WAA and best WAP per pitcher ─────────────────────────────

const processed = pitchers.map(p => {
  const waaSP = typeof p['WAA wtd'] === 'number' ? p['WAA wtd'] : null;
  const waaRP = typeof p['WAA wtd RP'] === 'number' ? p['WAA wtd RP'] : null;
  const wapSP = typeof p['WAP'] === 'number' ? p['WAP'] : null;
  const wapRP = typeof p['WAP RP'] === 'number' ? p['WAP RP'] : null;

  let bestWAA = null;
  if (waaSP !== null && waaRP !== null) bestWAA = Math.max(waaSP, waaRP);
  else if (waaSP !== null) bestWAA = waaSP;
  else if (waaRP !== null) bestWAA = waaRP;

  let bestWAP = null;
  if (wapSP !== null && wapRP !== null) bestWAP = Math.max(wapSP, wapRP);
  else if (wapSP !== null) bestWAP = wapSP;
  else if (wapRP !== null) bestWAP = wapRP;

  const age = typeof p['Age'] === 'number' ? p['Age'] : null;

  return { age, bestWAA, bestWAP, name: p['Name'] };
});

// ─── Age buckets ────────────────────────────────────────────────────────────

const ageBuckets = {};
for (let a = 16; a <= 34; a++) {
  ageBuckets[String(a)] = { label: String(a), players: [] };
}
ageBuckets['35+'] = { label: '35+', players: [] };

for (const p of processed) {
  if (p.age === null) continue;
  if (p.age >= 35) {
    ageBuckets['35+'].players.push(p);
  } else if (p.age >= 16) {
    ageBuckets[String(p.age)].players.push(p);
  }
}

// ─── Table 1: Age bucket analysis ──────────────────────────────────────────

console.log('=' .repeat(120));
console.log('AGE BUCKET ANALYSIS');
console.log('=' .repeat(120));

const headers = [
  padRight('Age', 6),
  padLeft('Count', 6),
  padLeft('Mean WAA', 10),
  padLeft('Med WAA', 10),
  padLeft('WAP Count', 10),
  padLeft('Mean WAP', 10),
  padLeft('Med WAP', 10),
  padLeft('Mean GAP', 10),
  padLeft('Med GAP', 10),
];
console.log(headers.join(' | '));
console.log('-'.repeat(120));

const bucketOrder = [];
for (let a = 16; a <= 34; a++) bucketOrder.push(String(a));
bucketOrder.push('35+');

const allBestWAAs = [];
const allBestWAPs = [];
const allGAPs = [];

for (const key of bucketOrder) {
  const bucket = ageBuckets[key];
  const players = bucket.players;
  if (players.length === 0) continue;

  const waaVals = players.filter(p => p.bestWAA !== null).map(p => p.bestWAA);
  const wapVals = players.filter(p => p.bestWAP !== null).map(p => p.bestWAP);
  const gapVals = players.filter(p => p.bestWAA !== null && p.bestWAP !== null)
    .map(p => p.bestWAP - p.bestWAA);

  allBestWAAs.push(...waaVals);
  allBestWAPs.push(...wapVals);
  allGAPs.push(...gapVals);

  const row = [
    padRight(bucket.label, 6),
    padLeft(String(players.length), 6),
    padLeft(fmt(mean(waaVals)), 10),
    padLeft(fmt(median(waaVals)), 10),
    padLeft(String(wapVals.length), 10),
    padLeft(fmt(mean(wapVals)), 10),
    padLeft(fmt(median(wapVals)), 10),
    padLeft(fmt(mean(gapVals)), 10),
    padLeft(fmt(median(gapVals)), 10),
  ];
  console.log(row.join(' | '));
}

// Totals row
console.log('-'.repeat(120));
const totalPlayers = processed.filter(p => p.age !== null);
const totalWaaVals = totalPlayers.filter(p => p.bestWAA !== null).map(p => p.bestWAA);
const totalWapVals = totalPlayers.filter(p => p.bestWAP !== null).map(p => p.bestWAP);
const totalGapVals = totalPlayers.filter(p => p.bestWAA !== null && p.bestWAP !== null)
  .map(p => p.bestWAP - p.bestWAA);

const totalRow = [
  padRight('TOTAL', 6),
  padLeft(String(totalPlayers.length), 6),
  padLeft(fmt(mean(totalWaaVals)), 10),
  padLeft(fmt(median(totalWaaVals)), 10),
  padLeft(String(totalWapVals.length), 10),
  padLeft(fmt(mean(totalWapVals)), 10),
  padLeft(fmt(median(totalWapVals)), 10),
  padLeft(fmt(mean(totalGapVals)), 10),
  padLeft(fmt(median(totalGapVals)), 10),
];
console.log(totalRow.join(' | '));

// ─── Table 2: Overall potential WAA (WAP) distribution ─────────────────────

console.log('\n');
console.log('=' .repeat(80));
console.log('POTENTIAL WAA (WAP) DISTRIBUTION — All Pitchers with WAP data');
console.log('=' .repeat(80));

const withWAP = processed.filter(p => p.bestWAP !== null);
const totalWithWAP = withWAP.length;

const thresholds = [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8];
console.log(padRight('Threshold', 20) + ' | ' + padLeft('Count', 8) + ' | ' + padLeft('% of Total', 12));
console.log('-'.repeat(50));

for (const t of thresholds) {
  const count = withWAP.filter(p => p.bestWAP >= t).length;
  const pct = (count / totalWithWAP * 100);
  const label = `WAP >= ${t}`;
  console.log(padRight(label, 20) + ' | ' + padLeft(String(count), 8) + ' | ' + padLeft(fmt(pct, 1) + '%', 12));
}

// ─── Table 3: WAP distribution by age ──────────────────────────────────────

console.log('\n');
console.log('=' .repeat(100));
console.log('POTENTIAL WAA (WAP) >= THRESHOLDS BY AGE — Count (% of age group with WAP)');
console.log('=' .repeat(100));

const ageThresholds = [0, 1, 2, 3, 5];

const ageHeaders = [
  padRight('Age', 6),
  padLeft('w/ WAP', 8),
  ...ageThresholds.map(t => padLeft(`>=${t}`, 14))
];
console.log(ageHeaders.join(' | '));
console.log('-'.repeat(100));

for (const key of bucketOrder) {
  const bucket = ageBuckets[key];
  const players = bucket.players;
  if (players.length === 0) continue;

  const wapPlayers = players.filter(p => p.bestWAP !== null);
  if (wapPlayers.length === 0) continue;

  const cols = [
    padRight(bucket.label, 6),
    padLeft(String(wapPlayers.length), 8),
  ];

  for (const t of ageThresholds) {
    const cnt = wapPlayers.filter(p => p.bestWAP >= t).length;
    const pct = (cnt / wapPlayers.length * 100).toFixed(1);
    cols.push(padLeft(`${cnt} (${pct}%)`, 14));
  }

  console.log(cols.join(' | '));
}

// ─── Table 4: Percentile distribution of best WAA ─────────────────────────

console.log('\n');
console.log('=' .repeat(70));
console.log('PERCENTILE DISTRIBUTION — Best Current WAA (all pitchers)');
console.log('=' .repeat(70));

const sortedWAA = totalWaaVals.sort((a, b) => a - b);
const percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99];

console.log(padRight('Percentile', 15) + ' | ' + padLeft('WAA Value', 12));
console.log('-'.repeat(35));

for (const pct of percentiles) {
  const idx = Math.min(Math.floor(pct / 100 * sortedWAA.length), sortedWAA.length - 1);
  console.log(padRight(`P${pct}`, 15) + ' | ' + padLeft(fmt(sortedWAA[idx], 3), 12));
}

// ─── Table 5: Percentile distribution of best WAP ─────────────────────────

console.log('\n');
console.log('=' .repeat(70));
console.log('PERCENTILE DISTRIBUTION — Best Potential WAA / WAP (pitchers with WAP)');
console.log('=' .repeat(70));

const sortedWAP = totalWapVals.sort((a, b) => a - b);

console.log(padRight('Percentile', 15) + ' | ' + padLeft('WAP Value', 12));
console.log('-'.repeat(35));

for (const pct of percentiles) {
  const idx = Math.min(Math.floor(pct / 100 * sortedWAP.length), sortedWAP.length - 1);
  console.log(padRight(`P${pct}`, 15) + ' | ' + padLeft(fmt(sortedWAP[idx], 3), 12));
}

// ─── Summary stats ─────────────────────────────────────────────────────────

console.log('\n');
console.log('=' .repeat(70));
console.log('SUMMARY STATISTICS');
console.log('=' .repeat(70));
console.log(`Total pitchers:                  ${processed.length}`);
console.log(`Pitchers with valid age:         ${totalPlayers.length}`);
console.log(`Pitchers with best WAA:          ${totalWaaVals.length}`);
console.log(`Pitchers with best WAP:          ${totalWapVals.length}`);
console.log(`Pitchers with both (GAP calc):   ${totalGapVals.length}`);
console.log(`Mean best WAA:                   ${fmt(mean(totalWaaVals), 3)}`);
console.log(`Mean best WAP:                   ${fmt(mean(totalWapVals), 3)}`);
console.log(`Mean GAP (WAP - WAA):            ${fmt(mean(totalGapVals), 3)}`);
console.log(`Median GAP:                      ${fmt(median(totalGapVals), 3)}`);

// ─── Top 20 pitchers by best WAP ───────────────────────────────────────────

console.log('\n');
console.log('=' .repeat(80));
console.log('TOP 20 PITCHERS BY BEST POTENTIAL WAA (WAP)');
console.log('=' .repeat(80));

const topWAP = processed
  .filter(p => p.bestWAP !== null)
  .sort((a, b) => b.bestWAP - a.bestWAP)
  .slice(0, 20);

const topHeaders = [
  padLeft('#', 4),
  padRight('Name', 28),
  padLeft('Age', 5),
  padLeft('Best WAA', 10),
  padLeft('Best WAP', 10),
  padLeft('GAP', 8),
];
console.log(topHeaders.join(' | '));
console.log('-'.repeat(80));

topWAP.forEach((p, i) => {
  const gap = (p.bestWAA !== null && p.bestWAP !== null) ? p.bestWAP - p.bestWAA : null;
  const row = [
    padLeft(String(i + 1), 4),
    padRight(p.name || 'Unknown', 28),
    padLeft(p.age !== null ? String(p.age) : '?', 5),
    padLeft(fmt(p.bestWAA), 10),
    padLeft(fmt(p.bestWAP), 10),
    padLeft(fmt(gap), 8),
  ];
  console.log(row.join(' | '));
});

console.log('\nDone.');
