/**
 * Market Value Calculator
 *
 * Estimates $/WAA from the league salary market, then projects what players
 * should cost based on their current and projected WAA.
 *
 * METHODOLOGY:
 * We use a single $/WAA rate derived from the entire MLB payroll:
 *   $/WAA = Total MLB salary / Total positive WAA produced
 *
 * This is the "replacement level" approach — it answers "how much does the
 * league pay per win above average?" WAA already accounts for positional value
 * differences (pitchers vs hitters, SP vs RP), so one rate works for everyone.
 *
 * Two valuations per player:
 * - CURRENT: current WAA × $/WAA = what they're worth right now per year
 * - FUTURE: projected peak WAA × $/WAA = what they'd be worth at their ceiling
 */

// ============================================================
// MARKET ANALYSIS
// ============================================================

/**
 * Get the best WAA value for a player (works for both hitters and pitchers).
 */
export function getBestWAA(player) {
  const cols = ['Max WAA wtd', 'WAA wtd', 'WAA wtd RP'];
  let best = -Infinity;
  for (const col of cols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > best) best = val;
  }
  return best === -Infinity ? 0 : best;
}

/**
 * Compute the league-wide $/WAA rate.
 * Uses total MLB payroll / total positive WAA for a stable, representative number.
 *
 * @param {Array} allPlayers - All players (hitters + pitchers combined)
 * @returns {{ rate, totalSalary, totalWAA, playerCount, positiveWAACount }}
 */
function computeLeagueRate(allPlayers) {
  const mlb = allPlayers.filter(p => p.Lev === 'MLB' && p.Price > 0);

  const totalSalary = mlb.reduce((s, p) => s + p.Price, 0);
  const positiveWAA = mlb.filter(p => getBestWAA(p) > 0);
  const totalWAA = positiveWAA.reduce((s, p) => s + getBestWAA(p), 0);

  // If fewer than 10% of MLB players have positive WAA, the data is incomplete
  // (projections likely haven't been run). Fall back to a safer estimate.
  const pctWithPositiveWAA = mlb.length > 0 ? positiveWAA.length / mlb.length : 0;
  const lowConfidence = pctWithPositiveWAA < 0.10;

  const rate = totalWAA > 0 ? totalSalary / totalWAA : 0;

  return {
    rate: Math.round(rate),
    totalSalary,
    totalWAA: Math.round(totalWAA * 10) / 10,
    playerCount: mlb.length,
    positiveWAACount: positiveWAA.length,
    lowConfidence,
    pctWithPositiveWAA: Math.round(pctWithPositiveWAA * 100),
  };
}

/**
 * Analyze the salary market. Returns the $/WAA rate and supporting data
 * for the Market Value page charts.
 */
export function analyzeMarket(hitters, pitchers) {
  const allPlayers = [...hitters, ...pitchers];
  const league = computeLeagueRate(allPlayers);

  // Data points for scatter chart (positive WAA MLB players)
  const dataPoints = allPlayers
    .filter(p => p.Lev === 'MLB' && p.Price > 0 && getBestWAA(p) > 0)
    .map(p => ({
      name: p.Name, age: p.Age, pos: p.POS, org: p.ORG,
      waa: getBestWAA(p), price: p.Price,
      perWAA: p.Price / Math.max(0.1, getBestWAA(p)),
      isPreArb: p.Price < 1_000_000,
      fvScale: p._fvScale, futureValue: p._futureValue,
    }));

  const freeMarket = dataPoints.filter(d => !d.isPreArb);

  // WAA bucket analysis
  const buckets = buildWAABuckets(dataPoints);
  const tiers = buildMarketTiers(freeMarket);

  return {
    dataPoints,
    marketPlayers: freeMarket.length,
    preArbPlayers: dataPoints.length - freeMarket.length,
    totalMLBPositiveWAA: dataPoints.length,
    avgPerWAA: league.rate,
    medianPerWAA: league.rate, // single rate, no median needed
    totalSalary: league.totalSalary,
    totalWAA: league.totalWAA,
    buckets,
    tiers,
    // Keep sub-objects for the Market Value page cards
    hitter: computeGroupRate(hitters),
    sp: computeGroupRate(pitchers.filter(p => !isBetterAsRP(p)), 'WAA wtd'),
    rp: computeGroupRate(pitchers.filter(p => isBetterAsRP(p)), 'WAA wtd RP'),
  };
}

/**
 * Compute $/WAA for a sub-group (for display only, not used in valuations).
 */
function computeGroupRate(players, waaCol) {
  const mlb = players.filter(p => {
    const waa = waaCol ? (parseFloat(p[waaCol]) || 0) : getBestWAA(p);
    return p.Lev === 'MLB' && p.Price >= 1_000_000 && waa > 0;
  });
  const totalSalary = mlb.reduce((s, p) => s + p.Price, 0);
  const totalWAA = mlb.reduce((s, p) => {
    const waa = waaCol ? (parseFloat(p[waaCol]) || 0) : getBestWAA(p);
    return s + waa;
  }, 0);
  return {
    avg: totalWAA > 0 ? Math.round(totalSalary / totalWAA) : 0,
    freeMarketCount: mlb.length,
  };
}

/**
 * Get the single league-wide $/WAA rate from all players.
 * This is what the hooks use.
 * Returns { rate, lowConfidence, pctWithPositiveWAA }
 */
export function getLeagueMarketRate(hitters, pitchers) {
  const allPlayers = [...hitters, ...pitchers];
  const league = computeLeagueRate(allPlayers);
  return {
    rate: league.rate,
    lowConfidence: league.lowConfidence,
    pctWithPositiveWAA: league.pctWithPositiveWAA,
    positiveWAACount: league.positiveWAACount,
    playerCount: league.playerCount,
  };
}

export function isBetterAsRP(player) {
  const sp = parseFloat(player['WAA wtd']) || 0;
  const rp = parseFloat(player['WAA wtd RP']) || 0;
  return rp > sp;
}

// ============================================================
// WAA BUCKET / TIER ANALYSIS (for Market Value page)
// ============================================================

function buildWAABuckets(dataPoints) {
  const bucketDefs = [
    { label: '0-0.5 WAA', min: 0, max: 0.5 },
    { label: '0.5-1.0', min: 0.5, max: 1.0 },
    { label: '1.0-1.5', min: 1.0, max: 1.5 },
    { label: '1.5-2.0', min: 1.5, max: 2.0 },
    { label: '2.0-3.0', min: 2.0, max: 3.0 },
    { label: '3.0+', min: 3.0, max: Infinity },
  ];
  return bucketDefs.map(def => {
    const players = dataPoints.filter(d => d.waa >= def.min && d.waa < def.max);
    const freeMarket = players.filter(d => !d.isPreArb);
    const totalPrice = freeMarket.reduce((s, d) => s + d.price, 0);
    const totalWAA = freeMarket.reduce((s, d) => s + d.waa, 0);
    return {
      ...def, count: players.length, freeMarketCount: freeMarket.length,
      avgPrice: freeMarket.length > 0 ? Math.round(totalPrice / freeMarket.length) : 0,
      avgPerWAA: totalWAA > 0 ? Math.round(totalPrice / totalWAA) : 0,
    };
  });
}

function buildMarketTiers(freeMarketPoints) {
  if (freeMarketPoints.length === 0) return [];
  const sorted = [...freeMarketPoints].sort((a, b) => b.waa - a.waa);
  const n = sorted.length;
  const superstarCut = Math.max(1, Math.floor(n * 0.10));
  const starCut = Math.max(superstarCut + 1, Math.floor(n * 0.35));
  function tierStats(players, label) {
    const totalPrice = players.reduce((s, d) => s + d.price, 0);
    const totalWAA = players.reduce((s, d) => s + d.waa, 0);
    return {
      label, count: players.length,
      minWAA: players.length > 0 ? Math.min(...players.map(d => d.waa)) : 0,
      maxWAA: players.length > 0 ? Math.max(...players.map(d => d.waa)) : 0,
      avgPrice: players.length > 0 ? Math.round(totalPrice / players.length) : 0,
      avgPerWAA: totalWAA > 0 ? Math.round(totalPrice / totalWAA) : 0,
    };
  }
  return [
    tierStats(sorted.slice(0, superstarCut), 'Superstar (Top 10%)'),
    tierStats(sorted.slice(superstarCut, starCut), 'Star (10-35%)'),
    tierStats(sorted.slice(starCut), 'Regular (35-100%)'),
  ];
}

// ============================================================
// PLAYER VALUATION
// ============================================================

/**
 * Calculate what a player is worth — both current and future.
 *
 * CURRENT: currentWAA × $/WAA = annual value today
 * FUTURE: peakWAA × $/WAA = annual value at ceiling
 *
 * @param {Object} player - Player data (with _fvBreakdown attached)
 * @param {number} rate - League $/WAA rate
 */
export function calculatePlayerValue(player, rate) {
  const fv = player._fvBreakdown;
  if (!fv || !fv.yearByYear) {
    return {
      annualValue: 0, offerFloor: 0, offerMid: 0, offerCeiling: 0, surplus: 0,
      futureAnnualValue: 0, futureOfferFloor: 0, futureOfferMid: 0, futureOfferCeiling: 0,
      totalValue: 0, adjustedValue: 0, yearlyValues: [],
      prospectDiscount: 100, productiveYears: 0, isProspect: false,
    };
  }

  const price = player.Price || 0;
  const currentWAA = Math.max(0, fv.currentWAA || 0);
  const peakWAA = Math.max(0, fv.expectedPeakWAA || fv.peakProjectedWAA || currentWAA);
  const isProspect = fv.hasPotential && fv.yearsTilPeak > 0;

  // --- CURRENT VALUE (what they're worth right now per year) ---
  const annualValue = Math.round(currentWAA * rate);
  const offerFloor = Math.round(annualValue * 0.7);
  const offerMid = annualValue;
  const offerCeiling = Math.round(annualValue * 1.3);
  const surplus = Math.round(annualValue - price);

  // --- FUTURE VALUE (what they'd be worth per year at peak) ---
  const futureAnnualValue = Math.round(peakWAA * rate);
  const futureOfferFloor = Math.round(futureAnnualValue * 0.5);
  const futureOfferMid = Math.round(futureAnnualValue * 0.75);
  const futureOfferCeiling = futureAnnualValue;

  // --- Career total (for detail/reference) ---
  let totalValue = 0;
  const yearlyValues = fv.yearByYear.map(yr => {
    const positiveWAA = Math.max(0, yr.discountedWAA);
    const yearValue = positiveWAA * rate;
    totalValue += yearValue;
    return { age: yr.age, rawWAA: yr.rawWAA, discountedWAA: yr.discountedWAA, yearValue: Math.round(yearValue) };
  });
  const prospectDiscount = isProspect ? Math.max(0.3, 1 - (fv.yearsTilPeak * 0.08)) : 1.0;
  const adjustedValue = Math.round(totalValue * prospectDiscount);
  const productiveYears = yearlyValues.filter(y => y.rawWAA > 0).length || 1;

  return {
    annualValue, offerFloor, offerMid, offerCeiling, surplus,
    futureAnnualValue, futureOfferFloor, futureOfferMid, futureOfferCeiling,
    totalValue: Math.round(totalValue), adjustedValue,
    prospectDiscount: Math.round(prospectDiscount * 100),
    yearlyValues, currentPrice: price, productiveYears, isProspect,
  };
}

// Convenience wrappers (keep API compatible)
export function calculateHitterValue(player, rate) {
  return calculatePlayerValue(player, rate);
}
export function calculatePitcherValue(player, rate) {
  return { ...calculatePlayerValue(player, rate), role: isBetterAsRP(player) ? 'RP' : 'SP', rateUsed: rate };
}

// ============================================================
// FORMATTING
// ============================================================

export function formatMoney(value) {
  if (value === null || value === undefined) return '-';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '-';
  const abs = Math.abs(num);
  const sign = num < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${abs.toLocaleString()}`;
}
