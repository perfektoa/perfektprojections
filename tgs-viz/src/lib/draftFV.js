/**
 * TGS Draft FV Calculator
 *
 * Age-relative prospect valuation system for draft decisions.
 *
 * Unlike the existing FV (which measures cumulative projected WAA over a career),
 * Draft FV answers the draft question:
 *   1. Can this player compete against his age group RIGHT NOW?
 *   2. How high is his ceiling by maturity (~25)?
 *
 * Formula:
 *   Draft FV = (agePercentile × 0.35 + ceilingScore × 0.65) × durabilityMod × workEthicMod
 *
 * Key inputs:
 *   - Hitters: wOBA wtd (current), MAX WAA P (ceiling)
 *   - Pitchers: WAA wtd (current), WAP (ceiling)
 *   - Prone column: durability modifier (Wrecked = undraftable)
 *   - WE column: work ethic development boost
 *   - INT column: flag only (TCR lottery, does not affect number)
 *
 * Age percentile is computed against the FULL league population for statistical
 * stability (~500 players per age bucket vs ~30-130 in draft pool alone).
 */

// ============================================================
// TUNABLE DEFAULTS
// ============================================================

export const DRAFT_FV_DEFAULTS = {
  // Weighting between current competitiveness and ceiling
  CURRENT_WEIGHT: 0.25,
  CEILING_WEIGHT: 0.75,

  // Ceiling normalization — separate scales because MAX WAA P (hitters) and WAP
  // (pitchers) have different natural distributions. Calibrated to each type's
  // full-league p5 → p99 so equivalent talent percentiles score equivalently.
  HITTER_CEILING_FLOOR:  -3.0,
  HITTER_CEILING_CAP:     5.0,
  PITCHER_CEILING_FLOOR: -1.0,
  PITCHER_CEILING_CAP:    2.5,
};

// ============================================================
// DURABILITY MODIFIER
// ============================================================

const DURABILITY_MAP = {
  'Wrecked':  0,      // undraftable
  'Fragile':  0.75,   // 25% growth penalty
  'Normal':   0.95,   // 5% growth penalty (miss ~10% of time)
  'Durable':  1.0,    // no penalty
  'Iron Man': 1.0,    // no penalty, no bonus
};

/**
 * Get the growth multiplier based on injury proneness.
 * @param {string} proneValue - "Wrecked", "Fragile", "Normal", "Durable", "Iron Man"
 * @returns {number} Multiplier (0 to 1.0)
 */
export function getDurabilityModifier(proneValue) {
  if (!proneValue || typeof proneValue !== 'string') return 0.95; // default to Normal
  return DURABILITY_MAP[proneValue] ?? 0.95;
}

// ============================================================
// WORK ETHIC MODIFIER
// ============================================================

/**
 * Get the development boost from work ethic.
 * Only "H" (high) gets a boost.
 * @param {string} weValue - "H", "N", or "L"
 * @returns {number} Multiplier (1.0 or 1.02)
 */
export function getWorkEthicModifier(weValue) {
  return weValue === 'H' ? 1.02 : 1.0;
}

// ============================================================
// TOOL RATING PENALTIES
// ============================================================

// --- Pitcher: pitch repertoire ---
const PITCH_COLS = ['FB', 'CH', 'CB', 'SL', 'SI', 'SP', 'CT', 'FO', 'CC', 'SC', 'KC', 'KN'];

/**
 * Pitcher penalty: weak changeup on a 3-pitch arm.
 * Knuckleballers and 4+ pitch guys are exempt.
 */
export function getPitchPenalty(player) {
  let pitchCount = 0;
  let hasKN = false;
  let chIsWeak = false;

  for (const col of PITCH_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined || raw === '-' || raw === '') continue;
    const val = parseFloat(raw);
    if (isNaN(val) || val <= 0) continue;

    pitchCount++;
    if (col === 'KN') hasKN = true;
    if (col === 'CH' && val <= 20) chIsWeak = true;
  }

  if (hasKN) return 1.0;
  if (pitchCount >= 4) return 1.0;
  if (chIsWeak) return 0.95;
  return 1.0;
}

// --- Hitter: key offensive tool weakness ---
const HITTER_TOOL_COLS = ['POW vR', 'EYE vR', 'K vR', 'BA vR'];

/**
 * Hitter penalty: 5% age percentile penalty if any core hitting tool
 * (power, eye, avoid K, contact) is rated 20 or below.
 * 20 is the floor — you don't know how bad it really is.
 */
export function getHitterToolPenalty(player) {
  for (const col of HITTER_TOOL_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined) continue;
    const val = parseFloat(raw);
    if (!isNaN(val) && val <= 20) return 0.95;
  }
  return 1.0;
}

// --- Pitcher: core pitching tool weakness ---
const PITCHER_TOOL_COLS = ['CON vR', 'STU vR', 'HRR vR'];

/**
 * Pitcher tool penalty: 5% age percentile penalty if control, stuff,
 * or HR rate is rated 20 or below.
 */
export function getPitcherToolPenalty(player) {
  for (const col of PITCHER_TOOL_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined) continue;
    const val = parseFloat(raw);
    if (!isNaN(val) && val <= 20) return 0.95;
  }
  return 1.0;
}

// ============================================================
// AGE GROUP BUILDER
// ============================================================

/**
 * Pre-compute sorted metric arrays for each integer age.
 * Used for efficient percentile lookups.
 *
 * @param {Array} allPlayers - Full league population (e.g., data.hitters)
 * @param {string|Function} metricKeyOrFn - Column name or function(player) => number
 * @returns {Object} Map of age -> sorted number[] (ascending)
 */
export function buildAgeGroups(allPlayers, metricKeyOrFn) {
  const getValue = typeof metricKeyOrFn === 'function'
    ? metricKeyOrFn
    : (player) => parseFloat(player[metricKeyOrFn]);

  const groups = {};

  for (const player of allPlayers) {
    const age = Math.floor(parseFloat(player.Age));
    if (isNaN(age) || age <= 0) continue;

    const val = getValue(player);
    if (isNaN(val)) continue;

    if (!groups[age]) groups[age] = [];
    groups[age].push(val);
  }

  // Sort each age group ascending
  for (const age of Object.keys(groups)) {
    groups[age].sort((a, b) => a - b);
  }

  return groups;
}

// ============================================================
// AGE PERCENTILE
// ============================================================

/**
 * Compute the percentile rank of a value within its age group.
 * Higher is better for both wOBA (hitters) and WAA (pitchers).
 *
 * @param {number} value - Player's metric value
 * @param {number} age - Player's integer age
 * @param {Object} ageGroups - From buildAgeGroups()
 * @returns {number} Percentile 0-100
 */
export function getAgePercentile(value, age, ageGroups) {
  const sorted = ageGroups[age];
  if (!sorted || sorted.length <= 1) return 50; // no meaningful comparison

  // Count how many values this player is >= (rank from bottom)
  let rank = 0;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i] <= value) rank = i + 1;
    else break;
  }

  return (rank / sorted.length) * 100;
}

// ============================================================
// CEILING NORMALIZATION
// ============================================================

/**
 * Normalize a ceiling metric to 0-100 scale.
 * Uses the same floor/cap for hitters and pitchers since WAA already
 * accounts for positional value.
 *
 * @param {number} value - Raw ceiling value (MAX WAA P or WAP)
 * @param {number} floor - Value that maps to 0
 * @param {number} cap - Value that maps to 100
 * @returns {number} Normalized score 0-100
 */
function normalizeCeiling(value, floor, cap) {
  if (isNaN(value)) return 0;
  const clamped = Math.max(floor, Math.min(cap, value));
  return ((clamped - floor) / (cap - floor)) * 100;
}

// ============================================================
// DRAFT FV SCALE — 0-100 raw to 20-80 scouting scale
// ============================================================

const DRAFT_FV_ANCHORS = [
  { raw: 0,   fv: 20 },
  { raw: 15,  fv: 30 },
  { raw: 30,  fv: 35 },
  { raw: 40,  fv: 40 },
  { raw: 50,  fv: 45 },
  { raw: 60,  fv: 50 },
  { raw: 70,  fv: 55 },
  { raw: 78,  fv: 60 },
  { raw: 85,  fv: 65 },
  { raw: 92,  fv: 70 },
  { raw: 100, fv: 80 },
];

/**
 * Convert raw Draft FV score (0-100) to 20-80 scouting scale.
 * @param {number} rawScore
 * @returns {number} FV on 20-80 scale
 */
export function rawScoreToDraftFVScale(rawScore) {
  if (rawScore <= DRAFT_FV_ANCHORS[0].raw) return DRAFT_FV_ANCHORS[0].fv;

  const last = DRAFT_FV_ANCHORS[DRAFT_FV_ANCHORS.length - 1];
  if (rawScore >= last.raw) return last.fv;

  for (let i = 0; i < DRAFT_FV_ANCHORS.length - 1; i++) {
    const lo = DRAFT_FV_ANCHORS[i];
    const hi = DRAFT_FV_ANCHORS[i + 1];
    if (rawScore >= lo.raw && rawScore < hi.raw) {
      const t = (rawScore - lo.raw) / (hi.raw - lo.raw);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }

  return 40; // fallback
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate Draft FV for a single player.
 *
 * @param {Object} player - Player data object
 * @param {Object} ageGroups - Pre-built from buildAgeGroups (full league population)
 * @param {'hitter'|'pitcher'} playerType
 * @param {Object} [params] - Override DRAFT_FV_DEFAULTS
 * @returns {Object} Draft FV breakdown
 */
export function calculateDraftFV(player, ageGroups, playerType, params = {}) {
  const p = { ...DRAFT_FV_DEFAULTS, ...params };
  const age = Math.floor(parseFloat(player.Age));
  const proneValue = player.Prone || null;
  const isWrecked = proneValue === 'Wrecked';

  // Short-circuit for wrecked players
  if (isWrecked) {
    return {
      draftFV: 20,
      draftRawFV: 0,
      agePercentile: 0,
      ceilingScore: 0,
      draftCeiling: 0,
      durabilityMod: 0,
      toolPenalty: 1.0,
      proneValue: 'Wrecked',
      highINT: player.INT === 'H',
      wrecked: true,
      weBoost: player.WE === 'H',
    };
  }

  // ---- Extract metrics based on player type ----
  let currentPerf, ceiling;

  if (playerType === 'hitter') {
    currentPerf = parseFloat(player['wOBA wtd']);
    ceiling = parseFloat(player['MAX WAA P']);
    // Mature players (no potential data): current best WAA IS their ceiling
    if (isNaN(ceiling)) {
      ceiling = parseFloat(player['Max WAA wtd']);
    }
  } else {
    // Pitchers: use best of SP or RP for both current and ceiling
    const spCurrent = parseFloat(player['WAA wtd']);
    const rpCurrent = parseFloat(player['WAA wtd RP']);
    currentPerf = Math.max(isNaN(spCurrent) ? -Infinity : spCurrent, isNaN(rpCurrent) ? -Infinity : rpCurrent);
    if (!isFinite(currentPerf)) currentPerf = NaN;

    const spCeiling = parseFloat(player['WAP']);
    const rpCeiling = parseFloat(player['WAP RP']);
    ceiling = Math.max(isNaN(spCeiling) ? -Infinity : spCeiling, isNaN(rpCeiling) ? -Infinity : rpCeiling);
    if (!isFinite(ceiling)) {
      // Fallback: best current WAA as ceiling
      ceiling = currentPerf;
    }
  }

  // ---- Age-relative percentile ----
  let agePercentile = (!isNaN(currentPerf) && !isNaN(age) && age > 0)
    ? getAgePercentile(currentPerf, age, ageGroups)
    : 0;

  // ---- Tool rating penalties (applied to age percentile) ----
  let toolPenalty;
  if (playerType === 'pitcher') {
    const pitchPen = getPitchPenalty(player);
    const toolPen = getPitcherToolPenalty(player);
    toolPenalty = Math.min(pitchPen, toolPen); // worst penalty wins, don't stack
  } else {
    toolPenalty = getHitterToolPenalty(player);
  }
  agePercentile *= toolPenalty;

  // ---- Ceiling score (normalized 0-100, per-type scale) ----
  const ceilingFloor = playerType === 'hitter' ? p.HITTER_CEILING_FLOOR : p.PITCHER_CEILING_FLOOR;
  const ceilingCap = playerType === 'hitter' ? p.HITTER_CEILING_CAP : p.PITCHER_CEILING_CAP;
  const ceilingScore = normalizeCeiling(ceiling, ceilingFloor, ceilingCap);

  // ---- Modifiers ----
  const durabilityMod = getDurabilityModifier(proneValue);
  const weMod = getWorkEthicModifier(player.WE);

  // ---- Combine ----
  const rawScore = (agePercentile * p.CURRENT_WEIGHT + ceilingScore * p.CEILING_WEIGHT)
    * durabilityMod * weMod;

  const draftFV = rawScoreToDraftFVScale(rawScore);

  return {
    draftFV,
    draftRawFV: Math.round(rawScore * 100) / 100,
    agePercentile: Math.round(agePercentile * 10) / 10,
    ceilingScore: Math.round(ceilingScore * 10) / 10,
    draftCeiling: isNaN(ceiling) ? null : Math.round(ceiling * 100) / 100,
    durabilityMod,
    toolPenalty,
    proneValue: proneValue || 'Normal',
    highINT: player.INT === 'H',
    wrecked: false,
    weBoost: player.WE === 'H',
  };
}
