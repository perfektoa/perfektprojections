/**
 * TGS G5 Future Value Calculator
 *
 * Implementation of the G5 model from FINDINGS.md — a single-point FV
 * that answers: "What will this player's WAA be when he reaches maturity?"
 *
 * Formula:
 *   FV = currentWAA + gap × riskFactor × gapFactor
 *
 * Equivalent to:
 *   FV = currentWAA × (1 - w) + potentialWAA × w
 *   where w = riskFactor × gapFactor
 *
 * Key differences from the cumulative FV (futureValue.js):
 *   - Single-point: produces expected peak WAA, not cumulative career value
 *   - DevPercentile: compares player against age-peers using Gaussian kernel
 *   - Power-law risk: riskExp=30 makes it a near-step function (philosophical choice)
 *   - No aging curve or time discounting
 *
 * This gives a complementary view — "how good will this player BE"
 * vs futureValue.js's "how much value will this player PRODUCE over his career."
 */

// ============================================================
// G5 DEFAULTS — from FINDINGS.md
// ============================================================

export const G5_DEFAULTS = {
  MAX_CURRENT_AGE: 27,    // Maturity age — no gap credit beyond this
  GAP_MAX: 0.95,          // Y-intercept at age 14 (max gap credit for youngest)
  GAP_EXP: 6,             // Gap curve steepness (power-law exponent)
  RISK_MIN: 0.82,         // Floor risk multiplier (worst developers)
  RISK_MAX: 0.90,         // Ceiling risk multiplier (best developers)
  RISK_EXP: 30,           // Power-law exponent for devPercentile (near-step function)
  BANDWIDTH: 2.0,         // Gaussian kernel bandwidth for devPercentile
  MIN_AGE: 14,            // Youngest possible player age
};

// ============================================================
// GAP FACTOR — Power-law age-driven gap discount
// ============================================================

/**
 * Compute the age-driven gap discount factor.
 * gapFactor = gapMax × (1 - t^gapExp)
 * where t = (age - 14) / (maxCurrentAge - 14), clamped to [0, 1]
 *
 * With gapExp=6, the curve is essentially flat from 16-22
 * then drops sharply toward 0 at maxCurrentAge (27).
 *
 * @param {number} age
 * @param {Object} [params]
 * @returns {number} gapFactor (0 to gapMax)
 */
export function getG5GapFactor(age, params = {}) {
  const p = { ...G5_DEFAULTS, ...params };
  const t = Math.max(0, Math.min(1, (age - p.MIN_AGE) / (p.MAX_CURRENT_AGE - p.MIN_AGE)));
  return p.GAP_MAX * (1 - Math.pow(t, p.GAP_EXP));
}

// ============================================================
// DEV PERCENTILE — Gaussian kernel-weighted percentile
// ============================================================

/**
 * Build Gaussian kernel-weighted age groups for devPercentile computation.
 * Unlike draftFV's buildAgeGroups (exact age buckets), this uses a Gaussian
 * kernel so nearby ages contribute to the comparison pool with decaying weight.
 *
 * @param {Array} allPlayers - Full league population
 * @param {string} metricKey - Column to rank by ('BatR wtd' for hitters, 'WAA wtd' for pitchers)
 * @returns {Object} Map of age -> [{value, weight}] sorted ascending by value
 */
export function buildDevPercentileData(allPlayers, metricKey) {
  const playersByAge = {};

  for (const player of allPlayers) {
    const age = Math.floor(parseFloat(player.Age));
    if (isNaN(age) || age <= 0) continue;

    const val = parseFloat(player[metricKey]);
    if (isNaN(val)) continue;

    if (!playersByAge[age]) playersByAge[age] = [];
    playersByAge[age].push(val);
  }

  return playersByAge;
}

/**
 * Compute the Gaussian kernel-weighted devPercentile for a player.
 *
 * For each other player in the population, their contribution is weighted by:
 *   weight = exp(-(ageDiff^2) / (2 × bandwidth^2))
 *
 * This means:
 *   - Same-age players: weight = 1.0
 *   - 1 year apart: weight ≈ 0.88 (bandwidth=2)
 *   - 2 years apart: weight ≈ 0.61
 *   - 3 years apart: weight ≈ 0.32
 *   - 5 years apart: weight ≈ 0.04
 *
 * @param {number} value - Player's metric value
 * @param {number} playerAge - Player's age
 * @param {Object} playersByAge - From buildDevPercentileData()
 * @param {number} [bandwidth=2.0] - Gaussian kernel bandwidth
 * @returns {number} Percentile 0-1
 */
export function getDevPercentile(value, playerAge, playersByAge, bandwidth = 2.0) {
  let weightedBelow = 0;
  let totalWeight = 0;

  for (const [ageStr, values] of Object.entries(playersByAge)) {
    const age = parseInt(ageStr);
    const ageDiff = playerAge - age;
    const weight = Math.exp(-(ageDiff * ageDiff) / (2 * bandwidth * bandwidth));

    if (weight < 0.01) continue; // Skip negligible contributions

    for (const v of values) {
      totalWeight += weight;
      if (v <= value) weightedBelow += weight;
    }
  }

  if (totalWeight === 0) return 0.5; // No comparison data
  return weightedBelow / totalWeight;
}

// ============================================================
// RISK FACTOR — Power-law devPercentile-driven
// ============================================================

/**
 * Compute the risk factor from devPercentile.
 * riskFactor = riskMin + (riskMax - riskMin) × devPct^riskExp
 *
 * With riskExp=30, this is essentially a step function:
 *   - devPct < 0.90 → riskFactor ≈ riskMin (0.82)
 *   - devPct = 0.99 → riskFactor ≈ 0.879
 *   - Only the elite few (99th+) get meaningful risk differentiation
 *
 * This is philosophically intentional: we don't punish young players
 * for being underdeveloped. DevPct is a tiebreaker between similar players,
 * not a harsh penalty.
 *
 * @param {number} devPct - Dev percentile (0 to 1)
 * @param {Object} [params]
 * @returns {number} Risk factor
 */
export function getG5RiskFactor(devPct, params = {}) {
  const p = { ...G5_DEFAULTS, ...params };
  const scaled = Math.pow(Math.max(0, Math.min(1, devPct)), p.RISK_EXP);
  return p.RISK_MIN + (p.RISK_MAX - p.RISK_MIN) * scaled;
}

// ============================================================
// WAA EXTRACTION
// ============================================================

/**
 * Get current and potential WAA values for G5 calculation.
 * Hitters: currentWAA from Max WAA wtd, potential from MAX WAA P
 * Pitchers SP: currentWAA from WAA wtd, potential from WAP
 *
 * For mature players (no potential data), potential = current.
 */
function getG5WAAValues(player) {
  // Hitter columns
  const maxWAAwtd = parseFloat(player['Max WAA wtd']);
  const maxWAAP = parseFloat(player['MAX WAA P']);

  // Pitcher columns
  const waaWtd = parseFloat(player['WAA wtd']);
  const wap = parseFloat(player['WAP']);
  const waaWtdRP = parseFloat(player['WAA wtd RP']);
  const wapRP = parseFloat(player['WAP RP']);

  // Detect player type and pick best values
  const isHitter = !isNaN(maxWAAwtd);
  const isPitcherSP = !isNaN(waaWtd) && !isNaN(wap);
  const isPitcherRP = !isNaN(waaWtdRP) && !isNaN(wapRP);

  let currentWAA, potentialWAA, hasPotential, devMetricKey;

  if (isHitter) {
    currentWAA = maxWAAwtd;
    hasPotential = !isNaN(maxWAAP);
    potentialWAA = hasPotential ? maxWAAP : currentWAA;
    devMetricKey = 'BatR wtd'; // G5 uses batting runs for hitter devPercentile
  } else if (isPitcherSP) {
    currentWAA = waaWtd;
    hasPotential = true;
    potentialWAA = wap;
    devMetricKey = 'WAA wtd';
  } else if (isPitcherRP) {
    currentWAA = waaWtdRP;
    hasPotential = true;
    potentialWAA = wapRP;
    devMetricKey = 'WAA wtd RP';
  } else {
    // Fallback: try any available WAA column
    currentWAA = maxWAAwtd || waaWtd || waaWtdRP || 0;
    hasPotential = false;
    potentialWAA = currentWAA;
    devMetricKey = 'BatR wtd';
  }

  if (isNaN(currentWAA)) currentWAA = 0;
  if (isNaN(potentialWAA)) potentialWAA = currentWAA;

  return { currentWAA, potentialWAA, hasPotential, devMetricKey };
}

// ============================================================
// G5 FV SCALE — Convert raw WAA to 20-80 scouting scale
// ============================================================

/**
 * Convert G5 FV (expected peak WAA) to 20-80 scouting scale.
 * Anchored to single-season WAA values, not cumulative.
 *
 * Context:
 *   WAA  0 = ~2 WAR, useful MLB regular
 *   WAA  1 = solid starter
 *   WAA  3 = All-Star caliber
 *   WAA  5 = MVP candidate
 *   WAA -2 = replacement level
 */
const G5_FV_ANCHORS = [
  { raw: -8,  fv: 20 },
  { raw: -5,  fv: 25 },
  { raw: -2,  fv: 30 },
  { raw: -0.5, fv: 35 },
  { raw: 0,   fv: 40 },
  { raw: 0.5, fv: 45 },
  { raw: 1.5, fv: 50 },
  { raw: 2.5, fv: 55 },
  { raw: 3.5, fv: 60 },
  { raw: 4.5, fv: 65 },
  { raw: 5.5, fv: 70 },
  { raw: 7,   fv: 75 },
  { raw: 9,   fv: 80 },
];

export function g5RawToScale(rawFV) {
  if (rawFV <= G5_FV_ANCHORS[0].raw) return G5_FV_ANCHORS[0].fv;

  const last = G5_FV_ANCHORS[G5_FV_ANCHORS.length - 1];
  if (rawFV >= last.raw) return last.fv;

  for (let i = 0; i < G5_FV_ANCHORS.length - 1; i++) {
    const lo = G5_FV_ANCHORS[i];
    const hi = G5_FV_ANCHORS[i + 1];
    if (rawFV >= lo.raw && rawFV < hi.raw) {
      const t = (rawFV - lo.raw) / (hi.raw - lo.raw);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }
  return 40;
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate G5 FV for a single player.
 *
 * @param {Object} player - Player data object
 * @param {Object} devPercentileData - From buildDevPercentileData()
 * @param {Object} [params] - Override G5_DEFAULTS
 * @returns {Object} G5 FV breakdown
 */
export function calculateG5FV(player, devPercentileData, params = {}) {
  const p = { ...G5_DEFAULTS, ...params };
  const age = parseFloat(player.Age) || 25;

  // Extract WAA values
  const { currentWAA, potentialWAA, hasPotential, devMetricKey } = getG5WAAValues(player);
  const gap = potentialWAA - currentWAA;

  // Dev percentile (Gaussian kernel-weighted)
  const devMetricValue = parseFloat(player[devMetricKey]);
  let devPct = 0.5; // default
  if (!isNaN(devMetricValue) && devPercentileData) {
    devPct = getDevPercentile(devMetricValue, Math.floor(age), devPercentileData, p.BANDWIDTH);
  }

  // Gap factor (age-driven)
  const gapFactor = age >= p.MAX_CURRENT_AGE ? 0 : getG5GapFactor(age, p);

  // Risk factor (devPercentile-driven)
  const riskFactor = getG5RiskFactor(devPct, p);

  // G5 FV: expected peak WAA
  let g5Raw;
  if (!hasPotential || gap <= 0 || age >= p.MAX_CURRENT_AGE) {
    // Mature player or no upside: FV = current WAA
    g5Raw = currentWAA;
  } else {
    g5Raw = currentWAA + gap * riskFactor * gapFactor;
  }

  const g5Scale = g5RawToScale(g5Raw);

  return {
    g5FV: g5Scale,
    g5Raw: Math.round(g5Raw * 100) / 100,
    g5DevPct: Math.round(devPct * 1000) / 10, // as percentage (0-100)
    g5GapFactor: Math.round(gapFactor * 1000) / 1000,
    g5RiskFactor: Math.round(riskFactor * 1000) / 1000,
    g5CurrentWAA: Math.round(currentWAA * 100) / 100,
    g5PotentialWAA: Math.round(potentialWAA * 100) / 100,
    g5Gap: Math.round(gap * 100) / 100,
    g5HasPotential: hasPotential,
  };
}
