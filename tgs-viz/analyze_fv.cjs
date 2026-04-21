const fs = require('fs');
const path = require('path');

// Load data
const dataPath = path.join(__dirname, 'public', 'data', 'hitters.json');
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

console.log(`Loaded ${data.length} players\n`);

// Helper functions
function percentile(arr, p) {
  if (arr.length === 0) return null;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(idx);
  const upper = Math.ceil(idx);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (idx - lower);
}

function mean(arr) {
  if (arr.length === 0) return null;
  return arr.reduce((s, v) => s + v, 0) / arr.length;
}

function median(arr) {
  return percentile(arr, 50);
}

function fmt(v, decimals = 2) {
  if (v === null || v === undefined) return 'N/A';
  return v.toFixed(decimals);
}

function fmtPct(v, decimals = 1) {
  if (v === null || v === undefined) return 'N/A';
  return (v * 100).toFixed(decimals) + '%';
}

function padR(s, len) {
  s = String(s);
  return s + ' '.repeat(Math.max(0, len - s.length));
}

function padL(s, len) {
  s = String(s);
  return ' '.repeat(Math.max(0, len - s.length)) + s;
}

// Define age buckets
function getAgeBucket(age) {
  if (age === null || age === undefined) return null;
  if (age >= 35) return '35+';
  if (age < 16) return null;
  return String(age);
}

const bucketOrder = ['16', '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31', '32', '33', '34', '35+'];

// Helper: check if value is a valid number
function isNum(v) {
  return v !== null && v !== undefined && typeof v === 'number' && !isNaN(v);
}

// ============================================================
// SECTION 1: Age Bucket Analysis
// ============================================================
console.log('='.repeat(180));
console.log('SECTION 1: AGE BUCKET ANALYSIS');
console.log('='.repeat(180));

const buckets = {};
bucketOrder.forEach(b => {
  buckets[b] = { players: [], currentWAA: [], potentialWAA: [], gaps: [] };
});

data.forEach(p => {
  const bucket = getAgeBucket(p.Age);
  if (!bucket || !buckets[bucket]) return;

  buckets[bucket].players.push(p);

  if (isNum(p['Max WAA wtd'])) {
    buckets[bucket].currentWAA.push(p['Max WAA wtd']);
  }

  if (isNum(p['MAX WAA P'])) {
    buckets[bucket].potentialWAA.push(p['MAX WAA P']);
  }

  if (isNum(p['Max WAA wtd']) && isNum(p['MAX WAA P'])) {
    buckets[bucket].gaps.push(p['MAX WAA P'] - p['Max WAA wtd']);
  }
});

// Table 1a: Counts and Means
console.log('\nTable 1a: Player Counts, Mean/Median Current WAA & Potential WAA by Age');
console.log('-'.repeat(140));
const h1a = [
  padR('Age', 6),
  padL('Count', 7),
  padL('w/ Pot', 7),
  padL('Mean Cur', 10),
  padL('Med Cur', 10),
  padL('Mean Pot', 10),
  padL('Med Pot', 10),
  padL('Mean GAP', 10),
  padL('Med GAP', 10),
].join(' | ');
console.log(h1a);
console.log('-'.repeat(140));

bucketOrder.forEach(b => {
  const d = buckets[b];
  const row = [
    padR(b, 6),
    padL(d.players.length, 7),
    padL(d.potentialWAA.length, 7),
    padL(fmt(mean(d.currentWAA)), 10),
    padL(fmt(median(d.currentWAA)), 10),
    padL(fmt(mean(d.potentialWAA)), 10),
    padL(fmt(median(d.potentialWAA)), 10),
    padL(fmt(mean(d.gaps)), 10),
    padL(fmt(median(d.gaps)), 10),
  ].join(' | ');
  console.log(row);
});

// Table 1b: Percentiles of Current WAA (Max WAA wtd)
console.log('\n\nTable 1b: Percentile Distribution of Current WAA (Max WAA wtd) by Age');
console.log('-'.repeat(100));
const h1b = [
  padR('Age', 6),
  padL('Count', 7),
  padL('P10', 10),
  padL('P25', 10),
  padL('P50', 10),
  padL('P75', 10),
  padL('P90', 10),
].join(' | ');
console.log(h1b);
console.log('-'.repeat(100));

bucketOrder.forEach(b => {
  const arr = buckets[b].currentWAA;
  const row = [
    padR(b, 6),
    padL(arr.length, 7),
    padL(fmt(percentile(arr, 10)), 10),
    padL(fmt(percentile(arr, 25)), 10),
    padL(fmt(percentile(arr, 50)), 10),
    padL(fmt(percentile(arr, 75)), 10),
    padL(fmt(percentile(arr, 90)), 10),
  ].join(' | ');
  console.log(row);
});

// Table 1c: Percentiles of Potential WAA (MAX WAA P)
console.log('\n\nTable 1c: Percentile Distribution of Potential WAA (MAX WAA P) by Age');
console.log('-'.repeat(100));
const h1c = [
  padR('Age', 6),
  padL('Count', 7),
  padL('P10', 10),
  padL('P25', 10),
  padL('P50', 10),
  padL('P75', 10),
  padL('P90', 10),
].join(' | ');
console.log(h1c);
console.log('-'.repeat(100));

bucketOrder.forEach(b => {
  const arr = buckets[b].potentialWAA;
  const row = [
    padR(b, 6),
    padL(arr.length, 7),
    padL(fmt(percentile(arr, 10)), 10),
    padL(fmt(percentile(arr, 25)), 10),
    padL(fmt(percentile(arr, 50)), 10),
    padL(fmt(percentile(arr, 75)), 10),
    padL(fmt(percentile(arr, 90)), 10),
  ].join(' | ');
  console.log(row);
});

// ============================================================
// SECTION 2: Development Ratio / GAP Analysis
// ============================================================
console.log('\n\n' + '='.repeat(120));
console.log('SECTION 2: DEVELOPMENT GAP ANALYSIS (Potential - Current) for players with BOTH values');
console.log('='.repeat(120));

console.log('\nTable 2: GAP = (MAX WAA P) - (Max WAA wtd) by Age');
console.log('-'.repeat(100));
const h2 = [
  padR('Age', 6),
  padL('N', 7),
  padL('Mean GAP', 10),
  padL('Med GAP', 10),
  padL('P10 GAP', 10),
  padL('P25 GAP', 10),
  padL('P75 GAP', 10),
  padL('P90 GAP', 10),
].join(' | ');
console.log(h2);
console.log('-'.repeat(100));

bucketOrder.forEach(b => {
  const arr = buckets[b].gaps;
  const row = [
    padR(b, 6),
    padL(arr.length, 7),
    padL(fmt(mean(arr)), 10),
    padL(fmt(median(arr)), 10),
    padL(fmt(percentile(arr, 10)), 10),
    padL(fmt(percentile(arr, 25)), 10),
    padL(fmt(percentile(arr, 75)), 10),
    padL(fmt(percentile(arr, 90)), 10),
  ].join(' | ');
  console.log(row);
});

// Also compute ratio for players with positive potential
console.log('\nTable 2b: Development Ratio (Current / Potential) for players with Potential > 0');
console.log('    (Only meaningful when potential is positive)');
console.log('-'.repeat(80));
const h2b = [
  padR('Age', 6),
  padL('N', 7),
  padL('Mean Ratio', 12),
  padL('Med Ratio', 12),
  padL('P25 Ratio', 12),
  padL('P75 Ratio', 12),
].join(' | ');
console.log(h2b);
console.log('-'.repeat(80));

bucketOrder.forEach(b => {
  const ratios = [];
  buckets[b].players.forEach(p => {
    if (isNum(p['Max WAA wtd']) && isNum(p['MAX WAA P']) && p['MAX WAA P'] > 0) {
      ratios.push(p['Max WAA wtd'] / p['MAX WAA P']);
    }
  });
  const row = [
    padR(b, 6),
    padL(ratios.length, 7),
    padL(fmt(mean(ratios), 3), 12),
    padL(fmt(median(ratios), 3), 12),
    padL(fmt(percentile(ratios, 25), 3), 12),
    padL(fmt(percentile(ratios, 75), 3), 12),
  ].join(' | ');
  console.log(row);
});

// ============================================================
// SECTION 3: Top Prospects (MAX WAA P >= 3.0)
// ============================================================
console.log('\n\n' + '='.repeat(120));
console.log('SECTION 3: TOP PROSPECTS (MAX WAA P >= 3.0)');
console.log('='.repeat(120));

console.log('\nTable 3: Top Prospects by Age');
console.log('-'.repeat(90));
const h3 = [
  padR('Age', 6),
  padL('Count', 7),
  padL('Mean CurWAA', 12),
  padL('Med CurWAA', 12),
  padL('Mean PotWAA', 12),
  padL('Med PotWAA', 12),
].join(' | ');
console.log(h3);
console.log('-'.repeat(90));

let totalTopProspects = 0;
bucketOrder.forEach(b => {
  const topProspects = buckets[b].players.filter(p => isNum(p['MAX WAA P']) && p['MAX WAA P'] >= 3.0);
  totalTopProspects += topProspects.length;
  const curVals = topProspects.filter(p => isNum(p['Max WAA wtd'])).map(p => p['Max WAA wtd']);
  const potVals = topProspects.map(p => p['MAX WAA P']);

  if (topProspects.length > 0) {
    const row = [
      padR(b, 6),
      padL(topProspects.length, 7),
      padL(fmt(mean(curVals)), 12),
      padL(fmt(median(curVals)), 12),
      padL(fmt(mean(potVals)), 12),
      padL(fmt(median(potVals)), 12),
    ].join(' | ');
    console.log(row);
  }
});
console.log('-'.repeat(90));
console.log(`Total top prospects (MAX WAA P >= 3.0): ${totalTopProspects}`);

// ============================================================
// SECTION 4: Overall Distribution of MAX WAA P (Potential)
// ============================================================
console.log('\n\n' + '='.repeat(80));
console.log('SECTION 4: OVERALL DISTRIBUTION OF MAX WAA P (Potential)');
console.log('='.repeat(80));

const allPotential = data.filter(p => isNum(p['MAX WAA P'])).map(p => p['MAX WAA P']);
console.log(`\nTotal players with MAX WAA P data: ${allPotential.length} / ${data.length}`);

const thresholds = [0, 1, 2, 3, 4, 5];
console.log('\nTable 4: Cumulative Distribution of MAX WAA P');
console.log('-'.repeat(60));
console.log(padR('Threshold', 15) + ' | ' + padL('Count', 8) + ' | ' + padL('% of Total', 12) + ' | ' + padL('% of w/Data', 12));
console.log('-'.repeat(60));

thresholds.forEach(t => {
  const count = allPotential.filter(v => v >= t).length;
  const row = [
    padR(`>= ${t}.0`, 15),
    padL(count, 8),
    padL(fmtPct(count / data.length), 12),
    padL(fmtPct(count / allPotential.length), 12),
  ].join(' | ');
  console.log(row);
});

console.log('\nSummary stats for MAX WAA P:');
console.log(`  Mean:   ${fmt(mean(allPotential))}`);
console.log(`  Median: ${fmt(median(allPotential))}`);
console.log(`  P10:    ${fmt(percentile(allPotential, 10))}`);
console.log(`  P25:    ${fmt(percentile(allPotential, 25))}`);
console.log(`  P75:    ${fmt(percentile(allPotential, 75))}`);
console.log(`  P90:    ${fmt(percentile(allPotential, 90))}`);
console.log(`  Min:    ${fmt(Math.min(...allPotential))}`);
console.log(`  Max:    ${fmt(Math.max(...allPotential))}`);

// ============================================================
// SECTION 5: Overall Distribution of Max WAA wtd (Current)
// ============================================================
console.log('\n\n' + '='.repeat(80));
console.log('SECTION 5: OVERALL DISTRIBUTION OF Max WAA wtd (Current)');
console.log('='.repeat(80));

const allCurrent = data.filter(p => isNum(p['Max WAA wtd'])).map(p => p['Max WAA wtd']);
console.log(`\nTotal players with Max WAA wtd data: ${allCurrent.length} / ${data.length}`);

console.log('\nTable 5: Cumulative Distribution of Max WAA wtd');
console.log('-'.repeat(60));
console.log(padR('Threshold', 15) + ' | ' + padL('Count', 8) + ' | ' + padL('% of Total', 12) + ' | ' + padL('% of w/Data', 12));
console.log('-'.repeat(60));

thresholds.forEach(t => {
  const count = allCurrent.filter(v => v >= t).length;
  const row = [
    padR(`>= ${t}.0`, 15),
    padL(count, 8),
    padL(fmtPct(count / data.length), 12),
    padL(fmtPct(count / allCurrent.length), 12),
  ].join(' | ');
  console.log(row);
});

console.log('\nSummary stats for Max WAA wtd:');
console.log(`  Mean:   ${fmt(mean(allCurrent))}`);
console.log(`  Median: ${fmt(median(allCurrent))}`);
console.log(`  P10:    ${fmt(percentile(allCurrent, 10))}`);
console.log(`  P25:    ${fmt(percentile(allCurrent, 25))}`);
console.log(`  P75:    ${fmt(percentile(allCurrent, 75))}`);
console.log(`  P90:    ${fmt(percentile(allCurrent, 90))}`);
console.log(`  Min:    ${fmt(Math.min(...allCurrent))}`);
console.log(`  Max:    ${fmt(Math.max(...allCurrent))}`);

// ============================================================
// SECTION 6: Additional Insights
// ============================================================
console.log('\n\n' + '='.repeat(80));
console.log('SECTION 6: ADDITIONAL INSIGHTS');
console.log('='.repeat(80));

// Players with no potential data breakdown by age
console.log('\nTable 6a: Players WITHOUT potential WAA data by Age');
console.log('-'.repeat(50));
console.log(padR('Age', 6) + ' | ' + padL('Total', 7) + ' | ' + padL('No Pot', 7) + ' | ' + padL('% Missing', 10));
console.log('-'.repeat(50));

bucketOrder.forEach(b => {
  const total = buckets[b].players.length;
  const withPot = buckets[b].potentialWAA.length;
  const noPot = total - withPot;
  if (total > 0) {
    console.log(padR(b, 6) + ' | ' + padL(total, 7) + ' | ' + padL(noPot, 7) + ' | ' + padL(fmtPct(noPot / total), 10));
  }
});

// Correlation between current and potential for players who have both
console.log('\nTable 6b: Correlation insight - Mean Current WAA by Potential WAA tier');
console.log('-'.repeat(70));
const potTiers = [
  { label: 'Pot < 0', min: -Infinity, max: 0 },
  { label: '0 <= Pot < 1', min: 0, max: 1 },
  { label: '1 <= Pot < 2', min: 1, max: 2 },
  { label: '2 <= Pot < 3', min: 2, max: 3 },
  { label: '3 <= Pot < 4', min: 3, max: 4 },
  { label: '4 <= Pot < 5', min: 4, max: 5 },
  { label: 'Pot >= 5', min: 5, max: Infinity },
];
console.log(padR('Potential Tier', 18) + ' | ' + padL('Count', 7) + ' | ' + padL('Mean CurWAA', 12) + ' | ' + padL('Med CurWAA', 12) + ' | ' + padL('Mean GAP', 10));
console.log('-'.repeat(70));

potTiers.forEach(tier => {
  const players = data.filter(p => isNum(p['MAX WAA P']) && isNum(p['Max WAA wtd']) && p['MAX WAA P'] >= tier.min && p['MAX WAA P'] < tier.max);
  const curVals = players.map(p => p['Max WAA wtd']);
  const gapVals = players.map(p => p['MAX WAA P'] - p['Max WAA wtd']);
  if (players.length > 0) {
    console.log(padR(tier.label, 18) + ' | ' + padL(players.length, 7) + ' | ' + padL(fmt(mean(curVals)), 12) + ' | ' + padL(fmt(median(curVals)), 12) + ' | ' + padL(fmt(mean(gapVals)), 10));
  }
});

console.log('\n\nAnalysis complete.');
