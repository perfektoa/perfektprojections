/**
 * TGS Hybrid Value Calculator
 *
 * Combines the best elements of all three valuation systems into a single
 * composite grade. Each system answers a different question:
 *
 *   FV (futureValue.js):  "How much total value will this player produce?"
 *                         Cumulative career projection, great for trades/roster.
 *
 *   G5 (g5FV.js):         "How good will this player BE at peak?"
 *                         Single-point expected peak WAA with devPercentile.
 *
 *   Draft FV (draftFV.js): "How does this player compare to his age group?"
 *                         Age-relative scouting grade, great for drafting.
 *
 * The Hybrid blends these three perspectives into one number:
 *
 *   HybridRaw = (wFV × norm(FV) + wG5 × norm(G5) + wDraft × norm(DraftFV))
 *
 * Weights shift by player age:
 *   - Young prospects (16-20): Draft FV weight is higher (age-relative matters most)
 *   - Mid-range (21-24): Even blend, all three matter
 *   - Established (25+): FV weight dominates (career value matters most)
 *
 * Each input is normalized to a 0-100 scale before blending so the different
 * scales (cumulative WAA, peak WAA, 20-80 grade) are comparable.
 */

// ============================================================
// DEFAULTS
// ============================================================

export const HYBRID_DEFAULTS = {
  // Base weights (before age adjustment)
  FV_WEIGHT: 0.40,       // Cumulative career value
  G5_WEIGHT: 0.30,       // Expected peak WAA
  DRAFT_WEIGHT: 0.30,    // Age-relative scouting grade

  // Age-based weight shifts
  // Young prospects get more Draft FV weight, established get more FV weight
  YOUNG_AGE: 20,         // Below this, shift weight toward Draft FV
  MATURE_AGE: 25,        // Above this, shift weight toward FV
  AGE_SHIFT: 0.15,       // How much weight shifts (max)
};

// ============================================================
// NORMALIZATION — Convert each system to 0-100
// ============================================================

/**
 * Normalize cumulative FV (20-80 scale) to 0-100.
 * FV 20 → 0, FV 50 → 50, FV 80 → 100
 */
function normFV(fvScale) {
  if (fvScale === null || fvScale === undefined || isNaN(fvScale)) return 25;
  return Math.max(0, Math.min(100, ((fvScale - 20) / 60) * 100));
}

/**
 * Normalize G5 FV (20-80 scale) to 0-100.
 * Same mapping as FV since both use 20-80 scale.
 */
function normG5(g5Scale) {
  if (g5Scale === null || g5Scale === undefined || isNaN(g5Scale)) return 25;
  return Math.max(0, Math.min(100, ((g5Scale - 20) / 60) * 100));
}

/**
 * Normalize Draft FV (20-80 scale) to 0-100.
 * Same 20-80 → 0-100 mapping.
 */
function normDraft(draftFV) {
  if (draftFV === null || draftFV === undefined || isNaN(draftFV)) return 25;
  return Math.max(0, Math.min(100, ((draftFV - 20) / 60) * 100));
}

// ============================================================
// AGE-ADJUSTED WEIGHTS
// ============================================================

/**
 * Compute age-adjusted blend weights.
 *
 * Young players (under 20): shift weight from FV toward Draft FV
 *   - Career projection is heavily discounted for youth, making FV compress
 *   - Age-relative performance is the best signal we have
 *
 * Established players (25+): shift weight from Draft FV toward FV
 *   - Career projection is concrete and reliable
 *   - Age-relative comparison is less meaningful when "age group" is all MLBers
 *
 * Mid-range (21-24): use base weights — all three views are useful
 *
 * @param {number} age
 * @param {Object} [params]
 * @returns {Object} { wFV, wG5, wDraft } summing to 1.0
 */
function getAgeWeights(age, params = {}) {
  const p = { ...HYBRID_DEFAULTS, ...params };

  let wFV = p.FV_WEIGHT;
  let wG5 = p.G5_WEIGHT;
  let wDraft = p.DRAFT_WEIGHT;

  if (age <= p.YOUNG_AGE) {
    // Young: Draft FV gets boost, FV loses (career projections are noisy for youth)
    const shift = p.AGE_SHIFT;
    wFV -= shift;
    wDraft += shift;
  } else if (age >= p.MATURE_AGE) {
    // Established: FV gets boost, Draft FV loses (age-relative less meaningful)
    const shift = p.AGE_SHIFT;
    wFV += shift;
    wDraft -= shift;
  } else {
    // Mid-range (21-24): gradual interpolation
    // Linear from YOUNG_AGE to MATURE_AGE
    const t = (age - p.YOUNG_AGE) / (p.MATURE_AGE - p.YOUNG_AGE);
    // At t=0 (young): shift = -AGE_SHIFT for FV, +AGE_SHIFT for draft
    // At t=0.5 (mid): shift = 0 (base weights)
    // At t=1 (mature): shift = +AGE_SHIFT for FV, -AGE_SHIFT for draft
    const shift = p.AGE_SHIFT * (2 * t - 1);
    wFV += shift;
    wDraft -= shift;
  }

  // Ensure no negative weights and normalize to sum=1
  wFV = Math.max(0.05, wFV);
  wG5 = Math.max(0.05, wG5);
  wDraft = Math.max(0.05, wDraft);
  const total = wFV + wG5 + wDraft;
  return {
    wFV: wFV / total,
    wG5: wG5 / total,
    wDraft: wDraft / total,
  };
}

// ============================================================
// HYBRID SCALE — 0-100 raw to 20-80 scouting scale
// ============================================================

const HYBRID_ANCHORS = [
  { raw: 0,   fv: 20 },
  { raw: 10,  fv: 25 },
  { raw: 20,  fv: 30 },
  { raw: 30,  fv: 35 },
  { raw: 40,  fv: 40 },
  { raw: 50,  fv: 45 },
  { raw: 58,  fv: 50 },
  { raw: 66,  fv: 55 },
  { raw: 74,  fv: 60 },
  { raw: 82,  fv: 65 },
  { raw: 90,  fv: 70 },
  { raw: 95,  fv: 75 },
  { raw: 100, fv: 80 },
];

function hybridRawToScale(rawScore) {
  if (rawScore <= HYBRID_ANCHORS[0].raw) return HYBRID_ANCHORS[0].fv;
  const last = HYBRID_ANCHORS[HYBRID_ANCHORS.length - 1];
  if (rawScore >= last.raw) return last.fv;

  for (let i = 0; i < HYBRID_ANCHORS.length - 1; i++) {
    const lo = HYBRID_ANCHORS[i];
    const hi = HYBRID_ANCHORS[i + 1];
    if (rawScore >= lo.raw && rawScore < hi.raw) {
      const t = (rawScore - lo.raw) / (hi.raw - lo.raw);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }
  return 40;
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate Hybrid FV for a player that already has FV, G5, and Draft FV computed.
 *
 * @param {Object} player - Player with _fvScale, _g5FV, and _draftFV fields
 * @param {Object} [params] - Override HYBRID_DEFAULTS
 * @returns {Object} Hybrid FV breakdown
 */
export function calculateHybridFV(player, params = {}) {
  const p = { ...HYBRID_DEFAULTS, ...params };
  const age = parseFloat(player.Age) || 25;

  // Get the three input grades (all on 20-80 scale)
  const fvScale = player._fvScale ?? 40;
  const g5Scale = player._g5FV ?? 40;
  const draftScale = player._draftFV ?? 40;

  // Normalize each to 0-100
  const nFV = normFV(fvScale);
  const nG5 = normG5(g5Scale);
  const nDraft = normDraft(draftScale);

  // Age-adjusted weights
  const { wFV, wG5, wDraft } = getAgeWeights(age, p);

  // Weighted blend
  const hybridRaw = nFV * wFV + nG5 * wG5 + nDraft * wDraft;

  // Convert to 20-80 scale
  const hybridFV = hybridRawToScale(hybridRaw);

  return {
    hybridFV,
    hybridRaw: Math.round(hybridRaw * 10) / 10,
    hybridInputFV: fvScale,
    hybridInputG5: g5Scale,
    hybridInputDraft: draftScale,
    hybridWeightFV: Math.round(wFV * 100),
    hybridWeightG5: Math.round(wG5 * 100),
    hybridWeightDraft: Math.round(wDraft * 100),
  };
}
