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

import { replacementOffset } from './leagueCalib.js';

export const DRAFT_FV_DEFAULTS = {
  // Weighting between current competitiveness and ceiling
  CURRENT_WEIGHT: 0.30,
  CEILING_WEIGHT: 0.70,

  // Ceiling normalization — unified scale: WAA is WAA. More WAA = better player,
  // no clamping at the top so elite outliers keep getting credit.
  CEILING_FLOOR:   -3.0,   // anchors the bottom of the scale (floor for below-replacement)
  CEILING_ANCHOR:   5.0,   // anchors raw WAA of 5.0 = score 100 (linear above)
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
 * Normalize a ceiling metric to a comparable 0-100+ scale.
 * Linear map: floor → 0, anchor → 100. Above the anchor scores >100 so elite
 * outliers (e.g., WAP 4.2 vs 5.0) keep getting differentiated credit. Below
 * floor is clamped to 0 (you can't be MORE useless than the floor).
 *
 * @param {number} value - Raw ceiling (MAX WAA P or WAP)
 * @param {number} floor - Raw value that maps to 0
 * @param {number} anchor - Raw value that maps to 100 (NOT clamped above)
 * @returns {number} Score (0 at floor, 100 at anchor, can exceed 100)
 */
function normalizeCeiling(value, floor, anchor) {
  if (isNaN(value)) return 0;
  const clampedLow = Math.max(floor, value);
  return ((clampedLow - floor) / (anchor - floor)) * 100;
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
      draftCeilingWAA: 0,
      ceilingOffset: 0,
      ceilingRole: null,
      durabilityMod: 0,
      toolPenalty: 1.0,
      proneValue: 'Wrecked',
      highINT: player.INT === 'H',
      wrecked: true,
      weBoost: player.WE === 'H',
    };
  }

  // ---- Extract metrics based on player type ----
  // audit M5: WAA -> WAR. Every value below carries its role's MEASURED
  // replacement offset (leagueCalib.js, per league via player.League), so the
  // shared CEILING_FLOOR/CEILING_ANCHOR normalization compares hitters and
  // pitchers (and SP-vs-RP swingmen) in the same freely-available-talent
  // currency — an average RP ceiling no longer normalizes like an average
  // hitter ceiling.
  const _lg = player._appLeague;   // stamped by usePlayerData (raw 'League' is a numeric id)
  const _hOff = replacementOffset(_lg, 'hitter');
  const _spOff = replacementOffset(_lg, 'sp');
  const _rpOff = replacementOffset(_lg, 'rp');
  let currentPerf, ceiling;
  // ceilingOffset = the role offset baked into `ceiling`. Scoring stays on WAR
  // (shared normalization across roles — audit M5), but the BOARD displays WAA per
  // user directive, so we hand back ceiling - ceilingOffset as well. Subtracting it
  // recovers the sheet's own raw ceiling column exactly (MAX WAA P / WAP / WAP RP).
  let ceilingOffset = 0;
  let ceilingRole = null;

  if (playerType === 'hitter') {
    currentPerf = parseFloat(player['wOBA wtd']);
    ceiling = parseFloat(player['MAX WAA P']);
    // Mature players (no potential data): current best WAA IS their ceiling
    if (isNaN(ceiling)) {
      ceiling = parseFloat(player['Max WAA wtd']);
    }
    if (!isNaN(ceiling)) { ceiling += _hOff; ceilingOffset = _hOff; ceilingRole = 'hitter'; }
  } else {
    // Pitchers: best of SP or RP for both current and ceiling, in WAR
    const spCurrent = parseFloat(player['WAA wtd']);
    const rpCurrent = parseFloat(player['WAA wtd RP']);
    currentPerf = Math.max(isNaN(spCurrent) ? -Infinity : spCurrent + _spOff,
                           isNaN(rpCurrent) ? -Infinity : rpCurrent + _rpOff);
    if (!isFinite(currentPerf)) currentPerf = NaN;

    const spCeiling = parseFloat(player['WAP']);
    const rpCeiling = parseFloat(player['WAP RP']);
    const spCeilWAR = isNaN(spCeiling) ? -Infinity : spCeiling + _spOff;
    const rpCeilWAR = isNaN(rpCeiling) ? -Infinity : rpCeiling + _rpOff;
    ceiling = Math.max(spCeilWAR, rpCeilWAR);
    if (isFinite(ceiling)) {
      ceilingOffset = spCeilWAR >= rpCeilWAR ? _spOff : _rpOff;
      ceilingRole = spCeilWAR >= rpCeilWAR ? 'sp' : 'rp';
    } else {
      // Fallback: best current WAR as ceiling — same role that won currentPerf
      ceiling = currentPerf;
      const spCurWAR = isNaN(spCurrent) ? -Infinity : spCurrent + _spOff;
      const rpCurWAR = isNaN(rpCurrent) ? -Infinity : rpCurrent + _rpOff;
      ceilingOffset = spCurWAR >= rpCurWAR ? _spOff : _rpOff;
      ceilingRole = spCurWAR >= rpCurWAR ? 'sp' : 'rp';
    }
  }

  // ---- Age-relative percentile ----
  // B11 (audit): an UNPARSEABLE/MISSING current-performance value (or age) is
  // "no information", not "worst in class" — default to the 50th percentile,
  // matching getAgePercentile's own no-comparison fallback. The old 0th-
  // percentile default cratered every prospect whose current-perf column was
  // blank, purely on data plumbing.
  let agePercentile = (!isNaN(currentPerf) && !isNaN(age) && age > 0)
    ? getAgePercentile(currentPerf, age, ageGroups)
    : 50;

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

  // ---- Ceiling score (unified WAA scale, no upper clamp) ----
  const ceilingScore = normalizeCeiling(ceiling, p.CEILING_FLOOR, p.CEILING_ANCHOR);

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
    // draftCeiling is WAR (what ceilingScore/draftFV are actually scored on, and what
    // the board's membership filter + above/below-zero sort tier key off — unchanged).
    draftCeiling: isNaN(ceiling) ? null : Math.round(ceiling * 100) / 100,
    // draftCeilingWAA is the SAME ceiling in the board's display currency.
    draftCeilingWAA: isNaN(ceiling) ? null : Math.round((ceiling - ceilingOffset) * 100) / 100,
    ceilingOffset,
    ceilingRole,
    durabilityMod,
    toolPenalty,
    proneValue: proneValue || 'Normal',
    highINT: player.INT === 'H',
    wrecked: false,
    weBoost: player.WE === 'H',
  };
}
