/**
 * TGS Future Value Calculator v2
 *
 * Research-backed model using actual WAA data from the TGS sheets.
 *
 * Key design decisions (backed by data analysis + sabermetric research):
 * - Development S-curve (logistic) with maturity at age 25 (OOTP default)
 * - Peak plateau ages 25-28 (research: peak WAR at ~27)
 * - Smooth decline after 28: ~4%/yr to 33, then ~8%/yr after (cliff)
 * - Risk factor 0.80-0.95 range (generous — sheets already discount via conservative potential ratings)
 * - 3% annual time discount (mild — we're rating talent, not contract surplus)
 * - NO positional scarcity bonus (WAA already includes defense)
 * - Percentile-based 20-80 FV scale calibration
 *
 * Data insights:
 * - Potential data only exists for ages 16-23 (hard cutoff)
 * - Only 3.2% of hitters currently above 0 WAA; 20% of prospects have potential >= 0
 * - Development GAP: ~8 WAA at age 16, ~2 WAA at age 23 (hitters)
 * - 56 hitters (1.5%) have potential >= 3.0 WAA (elite tier)
 *
 * Sources:
 * - FanGraphs aging curve research (peak ~27, decline ~0.5 WAR/yr after 30)
 * - Yale study (Fair, April 2025): peak performance age ~27.5 hitters, ~26.5 pitchers
 * - OOTP mechanics: development stops at 25, aging curve kicks in ~30
 * - FanGraphs prospect valuation: 8% discount for contract surplus (we use 3% for talent rating)
 */

// ============================================================
// MODEL PARAMETERS — all tunable from Dev Analysis page
// ============================================================

export const FV_DEFAULTS = {
  // Development curve (Gap Factor)
  MATURITY_AGE: 25,       // Age when development stops (OOTP default)
  GAP_MAX: 0.95,          // Max fraction of potential gap reached at maturity
  GAP_STEEPNESS: 0.6,     // Logistic curve steepness (higher = sharper S)

  // Risk factor
  RISK_FLOOR: 0.80,       // Minimum risk credit (worst-case percentile)
  RISK_CEILING: 0.95,     // Maximum risk credit (best-case percentile)

  // Aging curve — NO plateau. Decline starts at maturity (25).
  // OOTP aging settings are normal — players fall off fast.
  // You get ~3 good years out of a prospect, superstars might last into 30s.
  PEAK_END: 25,           // Peak = maturity age. No plateau — decline starts immediately.
  DECLINE_RATE: 0.06,     // Annual decline rate after peak (6% — aggressive)
  CLIFF_AGE: 30,          // Age when decline accelerates
  CLIFF_RATE: 0.12,       // Annual decline rate after cliff (12% — steep)

  // Time value
  DISCOUNT_RATE: 0.03,    // Annual discount rate (3%)

  // Projection window
  MAX_CAREER_AGE: 34,     // Don't project beyond this age (shorter careers)
  DEFAULT_YEARS_OF_CONTROL: 6,
};

// ============================================================
// GAP FACTOR — Logistic S-curve for development
// ============================================================

/**
 * Compute the development gap factor at a given age.
 * Returns 0 to GAP_MAX, following a logistic S-curve.
 *
 * At age 16: ~0.05 (barely developed)
 * At inflection (~20.5): ~GAP_MAX/2 (50% developed)
 * At maturity (25): ~GAP_MAX (95% developed)
 *
 * @param {number} age - Player's current age
 * @param {Object} [params] - Override default parameters
 * @returns {number} Gap factor (0 to GAP_MAX)
 */
export function getGapFactor(age, params = {}) {
  const {
    MATURITY_AGE = FV_DEFAULTS.MATURITY_AGE,
    GAP_MAX = FV_DEFAULTS.GAP_MAX,
    GAP_STEEPNESS = FV_DEFAULTS.GAP_STEEPNESS,
  } = params;

  // Inflection point: midpoint of typical development range (16 to MATURITY_AGE)
  const inflectionAge = (16 + MATURITY_AGE) / 2;

  // Raw logistic
  const raw = 1 / (1 + Math.exp(-GAP_STEEPNESS * (age - inflectionAge)));

  // Normalize: we want gapFactor(MATURITY_AGE) ≈ GAP_MAX and gapFactor(16) ≈ small
  const rawAtMaturity = 1 / (1 + Math.exp(-GAP_STEEPNESS * (MATURITY_AGE - inflectionAge)));
  const rawAt16 = 1 / (1 + Math.exp(-GAP_STEEPNESS * (16 - inflectionAge)));

  // Scale raw to [0, GAP_MAX] range based on the 16-to-maturity window
  const normalized = (raw - rawAt16) / (rawAtMaturity - rawAt16);
  return Math.max(0, Math.min(GAP_MAX, normalized * GAP_MAX));
}

// ============================================================
// AGING FACTOR — Smooth decline curve
// ============================================================

/**
 * Compute the aging factor at a given age.
 * Returns 1.0 during peak years, declining after PEAK_END.
 *
 * 25-28: 1.0 (plateau)
 * 29-33: gradual decline at DECLINE_RATE per year
 * 33+: steeper decline at CLIFF_RATE per year
 *
 * @param {number} age - Player's age
 * @param {Object} [params] - Override default parameters
 * @returns {number} Aging factor (0 to 1.0)
 */
export function getAgingFactor(age, params = {}) {
  const {
    PEAK_END = FV_DEFAULTS.PEAK_END,
    DECLINE_RATE = FV_DEFAULTS.DECLINE_RATE,
    CLIFF_AGE = FV_DEFAULTS.CLIFF_AGE,
    CLIFF_RATE = FV_DEFAULTS.CLIFF_RATE,
  } = params;

  if (age <= PEAK_END) return 1.0;

  if (age <= CLIFF_AGE) {
    return Math.pow(1 - DECLINE_RATE, age - PEAK_END);
  }

  // Factor at cliff age, then steeper decline beyond
  const atCliff = Math.pow(1 - DECLINE_RATE, CLIFF_AGE - PEAK_END);
  return atCliff * Math.pow(1 - CLIFF_RATE, age - CLIFF_AGE);
}

/**
 * Apply aging to a WAA value correctly for both positive and negative WAA.
 *
 * The raw agingFactor is a multiplier (0 to 1), which works for positive WAA
 * (e.g., 5 * 0.73 = 3.65, a decline). But for negative WAA it breaks:
 * -3 * 0.73 = -2.19 looks like improvement.
 *
 * Fix: compute the WAA lost as an absolute amount, then subtract it.
 * For positive WAA this gives identical results to the multiplicative model.
 * For negative WAA it correctly makes the player worse.
 *
 * @param {number} peakWAA - The player's expected peak WAA
 * @param {number} futureAge - Age to project to
 * @param {Object} [params] - Override default parameters
 * @returns {number} Projected WAA at futureAge
 */
export function applyAging(peakWAA, futureAge, params = {}) {
  const af = getAgingFactor(futureAge, params);
  // Use at least 0.5 as reference so even 0-WAA players decline slightly
  const reference = Math.max(0.5, Math.abs(peakWAA));
  return peakWAA - reference * (1 - af);
}

// ============================================================
// RISK FACTOR — Development credit
// ============================================================

/**
 * Compute the risk-adjusted credit factor from a percentile.
 * Used by the Dev Analysis percentile table for what-if exploration.
 *
 *   percentile 0 → RISK_FLOOR
 *   percentile 100 → RISK_CEILING
 *
 * @param {number} [percentile=50] - Development percentile (0-100)
 * @param {Object} [params] - Override default parameters
 * @returns {number} Risk factor
 */
export function getRiskFactor(percentile = 50, params = {}) {
  const {
    RISK_FLOOR = FV_DEFAULTS.RISK_FLOOR,
    RISK_CEILING = FV_DEFAULTS.RISK_CEILING,
  } = params;

  const t = Math.max(0, Math.min(100, percentile)) / 100;
  return RISK_FLOOR + t * (RISK_CEILING - RISK_FLOOR);
}

/**
 * Compute a per-player risk factor based on their development state.
 *
 * Two components that BOTH inform certainty:
 *
 * 1. Development progress (age-based):
 *    - How far along the S-curve is this player?
 *    - A 22-year-old near maturity has less uncertainty than a 16-year-old.
 *    - progress = gapFactor(age) / GAP_MAX → 0 to 1
 *    - Players at/past maturity → progress = 1 (fully developed)
 *
 * 2. Gap magnitude (skill-based):
 *    - Larger gaps have more uncertainty — more things have to go right.
 *    - A player closing a 2 WAA gap is much safer than one closing 13 WAA.
 *    - We map gap size to a 0-1 penalty where bigger gaps pull risk down.
 *    - GAP_RISK_SCALE controls sensitivity (default: 10 WAA = max penalty).
 *
 * Final risk = RISK_FLOOR + combinedScore * (RISK_CEILING - RISK_FLOOR)
 * where combinedScore = average of progress and gap certainty, 0 to 1.
 *
 * For established players (no gap), returns RISK_CEILING (no development risk).
 *
 * @param {number} age - Player's current age
 * @param {number} gap - potentialWAA - currentWAA (the development gap)
 * @param {boolean} hasPotential - Whether the player has potential data
 * @param {Object} [params] - Override default parameters
 * @returns {number} Risk factor between RISK_FLOOR and RISK_CEILING
 */
export function getPlayerRisk(age, gap, hasPotential, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };

  // Established players have no development uncertainty
  if (!hasPotential || gap <= 0) return p.RISK_CEILING;

  // 1. Development progress: how far along the S-curve
  const gapFactorNow = getGapFactor(age, p);
  const progress = Math.min(1, gapFactorNow / p.GAP_MAX);

  // 2. Gap certainty: smaller gaps are safer bets
  //    gap=0 → certainty=1 (no gap to close), gap=10+ → certainty≈0
  const GAP_RISK_SCALE = 10; // WAA gap at which certainty bottoms out
  const gapCertainty = Math.max(0, 1 - (gap / GAP_RISK_SCALE));

  // Combine: 60% weight on progress (age is the biggest risk factor),
  //          40% weight on gap size
  const combinedScore = 0.6 * progress + 0.4 * gapCertainty;

  return p.RISK_FLOOR + combinedScore * (p.RISK_CEILING - p.RISK_FLOOR);
}

// ============================================================
// WAA EXTRACTION from player data
// ============================================================

/**
 * Get the best current WAA and best potential WAA from player data.
 */
function getPlayerWAAValues(player) {
  const currentWAACols = ['Max WAA wtd', 'Max WAA vR', 'WAA wtd', 'WAA wtd RP'];
  const potentialWAACols = ['MAX WAA P', 'WAP', 'WAP RP'];

  let currentWAA = -Infinity;
  for (const col of currentWAACols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > currentWAA) currentWAA = val;
  }
  if (currentWAA === -Infinity) currentWAA = 0;

  let potentialWAA = null;
  for (const col of potentialWAACols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && (potentialWAA === null || val > potentialWAA)) {
      potentialWAA = val;
    }
  }

  // If no potential data (age 24+), potential = current (no development upside)
  const hasPotential = potentialWAA !== null;
  if (!hasPotential) potentialWAA = currentWAA;

  return { currentWAA, potentialWAA, hasPotential };
}

// ============================================================
// FV SCALE — Percentile-based 20-80 calibration
// ============================================================

/**
 * Convert raw future value (cumulative projected WAA) to 20-80 scouting scale.
 * Uses piecewise linear interpolation between calibration anchors.
 *
 * Calibrated against actual data distribution:
 * - FV 80: elite/generational (top ~0.1%)
 * - FV 70: franchise player (top ~0.5%)
 * - FV 60: solid regular (top ~5%)
 * - FV 50: fringe regular (top ~20%)
 * - FV 40: replacement level
 * - FV 20: no future value
 */
const FV_ANCHORS = [
  { rawFV: -15, fv: 20 },
  { rawFV: -8,  fv: 25 },
  { rawFV: -3,  fv: 30 },
  { rawFV: 0,   fv: 40 },
  { rawFV: 2,   fv: 45 },
  { rawFV: 5,   fv: 50 },
  { rawFV: 9,   fv: 55 },
  { rawFV: 14,  fv: 60 },
  { rawFV: 20,  fv: 65 },
  { rawFV: 28,  fv: 70 },
  { rawFV: 45,  fv: 80 },
];

function rawFVtoScale(rawFV) {
  // Below minimum anchor
  if (rawFV <= FV_ANCHORS[0].rawFV) return FV_ANCHORS[0].fv;

  // Above maximum anchor
  const last = FV_ANCHORS[FV_ANCHORS.length - 1];
  if (rawFV >= last.rawFV) return last.fv;

  // Interpolate between anchors
  for (let i = 0; i < FV_ANCHORS.length - 1; i++) {
    const lo = FV_ANCHORS[i];
    const hi = FV_ANCHORS[i + 1];
    if (rawFV >= lo.rawFV && rawFV < hi.rawFV) {
      const t = (rawFV - lo.rawFV) / (hi.rawFV - lo.rawFV);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }

  return 40; // fallback
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate Future Value for a player using WAA data from the TGS sheets.
 *
 * @param {Object} player - Player data object with WAA columns
 * @param {number} [yearsOfControl] - Years of team control remaining
 * @param {Object} [params] - Override model parameters (for Dev Analysis tuning)
 * @returns {Object} Future value breakdown
 */
export function calculateFutureValue(player, yearsOfControl, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };
  const yoc = yearsOfControl || p.DEFAULT_YEARS_OF_CONTROL;
  const age = parseFloat(player.Age) || 25;

  // Extract WAA values
  const { currentWAA, potentialWAA, hasPotential } = getPlayerWAAValues(player);

  // Per-player risk factor based on age + gap size
  const gap = potentialWAA - currentWAA;
  const riskFactor = getPlayerRisk(age, gap, hasPotential, p);

  // Expected peak WAA (what we think they'll actually reach)
  const expectedPeakWAA = hasPotential && gap > 0
    ? currentWAA + gap * p.GAP_MAX * riskFactor
    : currentWAA;

  // Projection window — always project through age 37 for year-by-year chart
  const projToAge = Math.min(p.MAX_CAREER_AGE, Math.max(age + yoc, p.PEAK_END + 2));
  const projectionYears = Math.max(1, projToAge - age);
  let peakProjectedWAA = -Infinity;
  const yearByYear = [];

  // Build year-by-year projection (for the development curve chart)
  for (let y = 0; y < projectionYears; y++) {
    const futureAge = age + y;
    let yearWAA;

    if (hasPotential && futureAge < p.MATURITY_AGE && gap > 0) {
      const gf = getGapFactor(futureAge, p);
      yearWAA = currentWAA + gap * gf * riskFactor;
    } else if (futureAge <= p.PEAK_END) {
      yearWAA = expectedPeakWAA;
    } else {
      yearWAA = applyAging(expectedPeakWAA, futureAge, p);
    }

    const discountFactor = Math.pow(1 - p.DISCOUNT_RATE, y);
    peakProjectedWAA = Math.max(peakProjectedWAA, yearWAA);

    yearByYear.push({
      age: futureAge,
      rawWAA: Math.round(yearWAA * 100) / 100,
      discountedWAA: Math.round((yearWAA * discountFactor) * 100) / 100,
    });
  }

  if (peakProjectedWAA === -Infinity) peakProjectedWAA = 0;

  // ---- FUTURE VALUE CALCULATION ----
  // Two different approaches:
  //
  // PROSPECTS (hasPotential & gap > 0):
  //   FV = expectedPeakWAA × productive years (from maturity through decline)
  //   Discounted for time-to-reach-peak and risk.
  //   We DON'T count the negative development years — a 17-year-old in Rookie ball
  //   shouldn't be penalized for not being MLB-ready. What matters is what they'll
  //   produce once they arrive.
  //
  // ESTABLISHED PLAYERS (no potential data, age 24+):
  //   FV = sum of projected WAA from current age through career end.
  //   They are what they are — no development upside to factor in.

  let totalProjectedWAA = 0;

  if (hasPotential && gap > 0) {
    // Prospect valuation: count from maturity age onward
    const startAge = Math.max(age, p.MATURITY_AGE);
    const yearsToStart = startAge - age;

    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      if (futureAge < startAge) continue; // skip development years

      const yearWAA = futureAge <= p.PEAK_END
        ? expectedPeakWAA
        : applyAging(expectedPeakWAA, futureAge, p);

      // Discount from TODAY (not from startAge), so more distant peak = lower present value
      const discountFactor = Math.pow(1 - p.DISCOUNT_RATE, y);
      totalProjectedWAA += yearWAA * discountFactor;
    }
  } else {
    // Established player: sum all projected years
    for (const entry of yearByYear) {
      totalProjectedWAA += entry.discountedWAA;
    }
  }

  const futureValue = totalProjectedWAA;
  const fvScale = rawFVtoScale(futureValue);

  // % to Peak: how close is their current WAA to their potential?
  // -8 current / 5 potential → they're nowhere near peak
  // 4 current / 5 potential → they're 80% there
  // For established players (no potential data), they ARE at their peak → 100%
  // For players with negative potential, cap at 0%
  let pctToPeak;
  if (!hasPotential || potentialWAA <= 0) {
    pctToPeak = 100; // established or no upside
  } else if (currentWAA <= 0) {
    // Negative current, positive potential — use gap factor progress
    // This gives a meaningful 0-95% based on age/development
    pctToPeak = Math.round(getGapFactor(age, p) / p.GAP_MAX * 100);
  } else {
    // Both positive — simple ratio
    pctToPeak = Math.min(100, Math.round((currentWAA / potentialWAA) * 100));
  }

  // Years til peak: how many years until they hit maturity (or 0 if already there)
  const yearsTilPeak = Math.max(0, p.MATURITY_AGE - age);

  return {
    futureValue: Math.round(futureValue * 100) / 100,
    fvScale,
    currentWAA: Math.round(currentWAA * 100) / 100,
    potentialWAA: Math.round(potentialWAA * 100) / 100,
    hasPotential,
    expectedPeakWAA: Math.round(expectedPeakWAA * 100) / 100,
    peakProjectedWAA: Math.round(peakProjectedWAA * 100) / 100,
    pctToPeak,
    yearsTilPeak,
    projectionYears,
    totalProjectedWAA: Math.round(totalProjectedWAA * 100) / 100,
    yearByYear,
  };
}

// ============================================================
// DEV ANALYSIS HELPERS — for the impact table
// ============================================================

/**
 * Median current WAA by age bucket (from data analysis).
 * Used in the Dev Analysis impact table to show realistic "curr:" values.
 */
export const MEDIAN_CURRENT_WAA_BY_AGE = {
  16: -9.4, 17: -9.3, 18: -9.0, 19: -7.7, 20: -7.5,
  21: -5.6, 22: -4.9, 23: -3.8, 24: -3.2, 25: -2.8,
  26: -2.8, 27: -3.2, 28: -3.7, 29: -4.5, 30: -5.0,
};

/**
 * Compute FV impact for a given age, potential WAA, and development percentile.
 * Used by the Dev Analysis impact table.
 *
 * @param {number} age - Player age
 * @param {number} potentialWAA - Assumed potential WAA
 * @param {number} percentile - Development percentile (0-100)
 * @param {Object} [params] - Override model parameters
 * @returns {Object} { futureValue, fvScale, currentWAA }
 */
export function computeImpact(age, potentialWAA, percentile, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };

  // Use median current WAA for this age
  const currentWAA = MEDIAN_CURRENT_WAA_BY_AGE[age] || MEDIAN_CURRENT_WAA_BY_AGE[30];

  // Risk factor at specified percentile
  const risk = getRiskFactor(percentile, p);

  // For the impact table, we have two regimes:
  //
  // DEVELOPING (age < MATURITY_AGE): Player has a gap between current and potential.
  //   The expected peak WAA is currentWAA + gap * GAP_MAX * risk.
  //   We only count WAA from maturity onward (skip the negative development years).
  //
  // MATURE (age >= MATURITY_AGE): Player has REACHED their potential.
  //   Their peak WAA IS the potentialWAA (the "what-if" scenario).
  //   We project potentialWAA forward through the aging curve.
  //   This answers "what is a 3.0 WAA player worth at age 25/26/28/30?"

  const isDeveloping = age < p.MATURITY_AGE;
  const gap = potentialWAA - currentWAA;

  let peakWAA;
  if (isDeveloping && gap > 0) {
    // Young prospect: expected peak based on gap closing with risk
    peakWAA = currentWAA + gap * p.GAP_MAX * risk;
  } else {
    // Mature player: they've reached potential, so peak = potentialWAA
    peakWAA = potentialWAA;
  }

  const projToAge = Math.min(p.MAX_CAREER_AGE, Math.max(age + p.DEFAULT_YEARS_OF_CONTROL, p.PEAK_END + 2));
  const projectionYears = Math.max(1, projToAge - age);
  let totalProjectedWAA = 0;

  if (isDeveloping) {
    // Prospect: only count from maturity onward (skip development years)
    const startAge = p.MATURITY_AGE;
    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      if (futureAge < startAge) continue;
      const yearWAA = futureAge <= p.PEAK_END
        ? peakWAA
        : applyAging(peakWAA, futureAge, p);
      totalProjectedWAA += yearWAA * Math.pow(1 - p.DISCOUNT_RATE, y);
    }
  } else {
    // Mature: project potentialWAA through aging curve from current age
    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      const yearWAA = futureAge <= p.PEAK_END
        ? peakWAA
        : applyAging(peakWAA, futureAge, p);
      totalProjectedWAA += yearWAA * Math.pow(1 - p.DISCOUNT_RATE, y);
    }
  }

  return {
    futureValue: Math.round(totalProjectedWAA * 100) / 100,
    fvScale: rawFVtoScale(totalProjectedWAA),
    currentWAA: Math.round(currentWAA * 100) / 100,
  };
}

export { getPlayerWAAValues, rawFVtoScale, FV_ANCHORS };
