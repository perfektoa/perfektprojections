/**
 * TGS Roster Optimizer
 *
 * Builds optimal 26-man roster to maximize wins:
 * - 13 position players selected by WEIGHTED WAA
 *   - 9 starters (C, SS, CF, 2B, 3B, LF, RF, 1B, DH)
 *   - Backup C
 *   - Utility IF (can play SS + 2B + 3B)
 *   - Utility OF (can play CF + corner OF)
 *   - Platoon bat (biggest split WAA advantage over a starter)
 *
 * - 13 pitchers
 *   - 5 SP (starting pitchers)
 *   - 8 RP (relief pitchers)
 *
 * Two batting lineups generated: vs RHP and vs LHP
 * Each uses split-specific WAA to pick the best 9 starters, then
 * orders them using "The Book" sabermetric methodology:
 *
 * The Book batting order (user-corrected):
 *   Slot 1: Best OBP (leadoff / table setter)
 *   Slot 2: Best wOBA (best pure hitter)
 *   Then rank all 9 by wOBA (1=best, 9=worst):
 *   Slot 3: wOBA rank #5
 *   Slot 4: wOBA rank #3
 *   Slot 5: wOBA rank #4
 *   Slot 6: wOBA rank #6
 *   Slot 7: wOBA rank #7
 *   Slot 8: wOBA rank #9 (worst)
 *   Slot 9: wOBA rank #8
 *
 * Uses OPTIMAL ASSIGNMENT to maximize total position-specific WAA
 * across all 9 positions simultaneously, rather than greedy assignment
 * which can put players in suboptimal positions.
 *
 * Roster selection uses WAA (offense + defense).
 * Batting order uses wOBA (pure hitting) and OBP (on-base ability).
 */

// ============================================================
// Column Constants
// ============================================================

const WAA_COLUMNS = {
  wtd: ['C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd', 'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd', 'DH WAA wtd', 'Max WAA wtd'],
  vR: ['C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR', 'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR', 'DH WAA vR', 'Max WAA vR'],
  vL: ['C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL', 'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL', 'DH WAA vL', 'Max WAA vL'],
};

const OBP_COLUMNS = { vR: 'OBP vR', vL: 'OBP vL', wtd: 'OBP wtd' };
const WOBA_COLUMNS = { vR: 'wOBA vR', vL: 'wOBA vL', wtd: 'wOBA wtd' };

const PITCHER_WAA_SP_COL = 'WAA wtd';
const PITCHER_WAA_RP_COL = 'WAA wtd RP';

// Positions to fill (C assigned separately, DH is open to anyone)
const FIELD_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'LF', 'RF', '1B'];
const ALL_LINEUP_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'LF', 'RF', '1B', 'DH'];

// ============================================================
// Helper Functions
// ============================================================

/**
 * Find the best WAA value from a set of columns for a player.
 */
function findBestWAA(player, columns) {
  let bestWAA = -Infinity;
  let bestCol = null;

  for (const col of columns) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > bestWAA) {
      bestWAA = val;
      bestCol = col;
    }
  }

  return bestWAA === -Infinity ? { waa: null, column: null } : { waa: bestWAA, column: bestCol };
}

/**
 * Determine what positions a hitter can play based on eligibility columns.
 */
function getEligiblePositions(player) {
  const positions = [];
  const posMap = {
    'C': 'C Eligible',
    '1B': '1B Eligible',
    '2B': '2B Eligible',
    '3B': '3B Eligible',
    'SS': 'SS Eligible',
    'LF': 'LF Eligible',
    'CF': 'CF Eligible',
    'RF': 'RF Eligible',
  };

  for (const [pos, eligCol] of Object.entries(posMap)) {
    const eligible = player[eligCol];
    if (eligible === true || eligible === 'True' || eligible === 'TRUE') {
      positions.push(pos);
    } else {
      // Fallback: check if there's a non-zero WAA at this position
      const waaCol = `${pos} WAA wtd`;
      const waaVal = parseFloat(player[waaCol]);
      if (!isNaN(waaVal) && waaVal !== 0) {
        positions.push(pos);
      }
    }
  }

  // Everyone can DH
  positions.push('DH');
  return positions;
}

/**
 * Get WAA for a specific player at a specific position for a specific split.
 */
function getPositionWAAForSplit(player, position, split) {
  const col = `${position} WAA ${split}`;
  const val = parseFloat(player[col]);
  return isNaN(val) ? -Infinity : val;
}

/**
 * Get the WAA for a specific player at a specific position.
 */
function getPositionWAA(player, position, waaColumns) {
  for (const col of waaColumns) {
    const colLower = col.toLowerCase();
    const posLower = position.toLowerCase();
    if (colLower.includes(posLower) && (colLower.includes('waa') || colLower.includes('war'))) {
      const val = parseFloat(player[col]);
      if (!isNaN(val)) return val;
    }
  }
  return getMaxWAA(player, waaColumns);
}

/**
 * Get the maximum WAA value from a set of columns.
 */
function getMaxWAA(player, waaColumns) {
  let max = -Infinity;
  for (const col of waaColumns) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > max) max = val;
  }
  return max === -Infinity ? 0 : max;
}

// ============================================================
// Position Eligibility Checks
// ============================================================

function isEligible(player, pos) {
  const eligible = player[`${pos} Eligible`];
  return eligible === true || eligible === 'True' || eligible === 'TRUE';
}

function canPlaySS(player) {
  return isEligible(player, 'SS');
}

function canPlayCF(player) {
  return isEligible(player, 'CF');
}

function canPlayIF(player) {
  return ['2B', '3B', 'SS'].some(pos => isEligible(player, pos));
}

function canPlayOF(player) {
  return ['LF', 'CF', 'RF'].some(pos => isEligible(player, pos));
}

/**
 * Can play ALL three non-1B infield positions: SS, 2B, 3B.
 * Required for Utility Infielder bench role.
 */
function canPlayAllIF(player) {
  return ['SS', '2B', '3B'].every(pos => isEligible(player, pos));
}

/**
 * Can play CF plus at least one corner OF position (LF or RF).
 * Required for Utility Outfielder bench role.
 */
function canPlayCFAndCornerOF(player) {
  if (!isEligible(player, 'CF')) return false;
  return isEligible(player, 'LF') || isEligible(player, 'RF');
}

// ============================================================
// Optimal Position Assignment (replaces greedy)
// ============================================================

/**
 * Optimally assign players to positions to maximize total position-specific WAA.
 *
 * Uses a branch-and-bound approach: fill positions from most constrained
 * (fewest eligible players) to least constrained. For each position, try
 * each eligible player and recurse. Prune branches where remaining
 * upper bound can't beat current best.
 *
 * For the DH slot, any unassigned player can fill it (everyone is DH eligible),
 * and we pick whoever has the best DH WAA (or max WAA) among the remaining.
 *
 * @param {Array} candidates - scored hitters (with _positions, etc.)
 * @param {string} split - 'wtd', 'vR', or 'vL'
 * @param {Set} excludeIds - player IDs already taken (e.g., catchers)
 * @param {Object} preAssigned - positions already assigned { pos: player }
 * @returns {Object} - { assignments: { pos: player }, totalWAA: number }
 */
function optimalPositionAssignment(candidates, split, excludeIds = new Set(), preAssigned = {}) {
  // Determine which positions still need filling
  const positionsToFill = ALL_LINEUP_POSITIONS.filter(p => !preAssigned[p]);

  // Get available players (not excluded, not pre-assigned)
  const preAssignedIds = new Set(Object.values(preAssigned).map(p => p.ID || p.Name));
  const available = candidates.filter(h =>
    !excludeIds.has(h.ID || h.Name) && !preAssignedIds.has(h.ID || h.Name)
  );

  // For each position, find eligible players and their WAA at that position
  const positionCandidates = {};
  for (const pos of positionsToFill) {
    positionCandidates[pos] = available
      .filter(h => h._positions.includes(pos))
      .map(h => ({
        player: h,
        waa: getPositionWAAForSplit(h, pos, split),
      }))
      .filter(e => e.waa !== -Infinity)
      .sort((a, b) => b.waa - a.waa);
  }

  // Sort positions by number of eligible candidates (most constrained first)
  // DH always goes last since everyone can play DH
  const fieldPositionsToFill = positionsToFill.filter(p => p !== 'DH');
  fieldPositionsToFill.sort((a, b) =>
    (positionCandidates[a]?.length || 0) - (positionCandidates[b]?.length || 0)
  );

  // Add DH at the end
  const orderedPositions = [...fieldPositionsToFill];
  if (positionsToFill.includes('DH')) orderedPositions.push('DH');

  let bestAssignment = null;
  let bestTotalWAA = -Infinity;

  /**
   * Recursive branch-and-bound search.
   * @param {number} posIdx - current index in orderedPositions
   * @param {Object} current - current assignments { pos: { player, waa } }
   * @param {Set} usedIds - player IDs already assigned
   * @param {number} currentWAA - sum of WAA so far
   */
  function search(posIdx, current, usedIds, currentWAA) {
    if (posIdx >= orderedPositions.length) {
      // All positions filled
      if (currentWAA > bestTotalWAA) {
        bestTotalWAA = currentWAA;
        bestAssignment = { ...current };
      }
      return;
    }

    const pos = orderedPositions[posIdx];
    const candidates = positionCandidates[pos] || [];

    // Filter to unused players
    const viable = candidates.filter(c => !usedIds.has(c.player.ID || c.player.Name));

    if (viable.length === 0) {
      // No one can play this position; still try to fill remaining
      search(posIdx + 1, current, usedIds, currentWAA);
      return;
    }

    // Upper bound pruning: even if we take the best available for all
    // remaining positions, can we beat the current best?
    const remainingPositions = orderedPositions.slice(posIdx);
    let upperBound = currentWAA;
    for (const rPos of remainingPositions) {
      const rCands = (positionCandidates[rPos] || [])
        .filter(c => !usedIds.has(c.player.ID || c.player.Name));
      if (rCands.length > 0) upperBound += rCands[0].waa;
    }
    if (upperBound <= bestTotalWAA) return; // Prune

    // Try each viable candidate for this position
    // Limit branching: only try top N candidates to keep runtime reasonable
    const maxBranches = pos === 'DH' ? 3 : Math.min(viable.length, 5);
    for (let i = 0; i < maxBranches; i++) {
      const { player, waa } = viable[i];
      const id = player.ID || player.Name;

      current[pos] = { player, waa };
      usedIds.add(id);

      search(posIdx + 1, current, usedIds, currentWAA + waa);

      delete current[pos];
      usedIds.delete(id);
    }
  }

  search(0, {}, new Set(), 0);

  // Build result
  const assignments = {};
  let totalWAA = 0;

  // Include pre-assigned positions
  for (const [pos, player] of Object.entries(preAssigned)) {
    assignments[pos] = player;
    const waa = getPositionWAAForSplit(player, pos, split);
    totalWAA += waa === -Infinity ? 0 : waa;
  }

  // Add optimally assigned positions
  if (bestAssignment) {
    for (const [pos, entry] of Object.entries(bestAssignment)) {
      assignments[pos] = entry.player;
      totalWAA += entry.waa;
    }
  }

  return { assignments, totalWAA };
}

// ============================================================
// The Book Batting Order
// ============================================================

/**
 * Build a batting order using the corrected "The Book" methodology.
 *
 * Uses wOBA to rank hitters (pure offensive production).
 * Uses OBP to select the leadoff hitter.
 *
 * Slot mapping after OBP leadoff and Best wOBA (#2):
 *   Slot 3 = wOBA rank #5
 *   Slot 4 = wOBA rank #3
 *   Slot 5 = wOBA rank #4
 *   Slot 6 = wOBA rank #6
 *   Slot 7 = wOBA rank #7
 *   Slot 8 = wOBA rank #9 (worst)
 *   Slot 9 = wOBA rank #8
 *
 * @param {Array<{player, position}>} starters - 9 starter entries
 * @param {string} split - 'vR' or 'vL'
 * @returns {Array<{player, position, slot, role, waa, woba, obp}>}
 */
function optimizeBattingOrder(starters, split) {
  if (starters.length === 0) return [];

  const obpCol = OBP_COLUMNS[split];
  const wobaCol = WOBA_COLUMNS[split];

  // Score each starter
  const scored = starters.map(({ player, position }) => ({
    player,
    position,
    splitWAA: getPositionWAAForSplit(player, position, split),
    splitOBP: parseFloat(player[obpCol]) || 0,
    splitWOBA: parseFloat(player[wobaCol]) || 0,
  }));

  // Rank all 9 by wOBA descending (rank 1 = best hitter)
  const rankedByWOBA = [...scored].sort((a, b) => b.splitWOBA - a.splitWOBA);

  // Rank by OBP descending
  const rankedByOBP = [...scored].sort((a, b) => b.splitOBP - a.splitOBP);

  const getId = (s) => s.player.ID || s.player.Name;

  // Per "The Book" (Tango): best 3 hitters go in slots 1, 2, 4.
  // Distribute so OBP is higher in the order, SLG lower.
  // KEY: If the best OBP guy is ALSO the best wOBA guy, he bats 2nd (not 1st).
  // The 2nd slot gets more PAs with runners on (45% vs 36%), so the best
  // all-around hitter does more damage there. Leadoff goes to the 2nd-best OBP guy.
  const bestOBP = rankedByOBP[0];
  const bestWOBA = rankedByWOBA[0];
  const samePlayer = getId(bestOBP) === getId(bestWOBA);

  let leadoff, slotTwo;
  if (samePlayer) {
    // Best OBP = best wOBA → he bats 2nd, second-best OBP leads off
    slotTwo = bestOBP;
    leadoff = rankedByOBP[1] || rankedByWOBA[1];
  } else {
    // Different players → best OBP leads off, best wOBA bats 2nd
    leadoff = bestOBP;
    slotTwo = bestWOBA;
  }

  // Slot-to-rank mapping (1-indexed): slot -> wOBA rank (for slots 3-9)
  const SLOT_TO_RANK = { 3: 5, 4: 3, 5: 4, 6: 6, 7: 7, 8: 9, 9: 8 };

  const order = new Array(10).fill(null); // index 1-9
  const usedIds = new Set();

  // Slot 1: Leadoff
  order[1] = leadoff;
  usedIds.add(getId(leadoff));

  // Slot 2: Best hitter
  order[2] = slotTwo;
  usedIds.add(getId(slotTwo));

  // Slots 3-9: map by wOBA rank
  for (let slot = 3; slot <= 9; slot++) {
    const targetRank = SLOT_TO_RANK[slot]; // 1-based
    let candidate = rankedByWOBA[targetRank - 1]; // 0-based index

    if (!candidate || usedIds.has(getId(candidate))) {
      candidate = rankedByWOBA.find(r => !usedIds.has(getId(r)));
    }

    if (candidate) {
      order[slot] = candidate;
      usedIds.add(getId(candidate));
    }
  }

  // Build labeled result
  const SLOT_LABELS = {
    1: samePlayer ? 'Leadoff (2nd OBP)' : 'Leadoff (OBP)',
    2: samePlayer ? 'Best Hitter (OBP+wOBA)' : 'Best Hitter (wOBA)',
    3: '#5 Hitter',
    4: '#3 Hitter',
    5: '#4 Hitter',
    6: '#6',
    7: '#7',
    8: '#9 (Weakest)',
    9: '#8',
  };

  return order.slice(1).filter(Boolean).map((entry, idx) => ({
    player: entry.player,
    position: entry.position,
    slot: idx + 1,
    role: SLOT_LABELS[idx + 1] || `#${idx + 1}`,
    waa: entry.splitWAA === -Infinity ? 0 : entry.splitWAA,
    woba: entry.splitWOBA,
    obp: entry.splitOBP,
  }));
}

// ============================================================
// Split Lineup Selection (Optimal)
// ============================================================

/**
 * From the 13 rostered hitters, pick the optimal 9 starters for a given split.
 * Uses optimal position assignment to maximize total position-specific WAA.
 *
 * @param {Array} rosteredHitters - The 13 hitters on the roster (enriched)
 * @param {string} split - 'vR' or 'vL'
 * @returns {{ starters: Array<{player, position}>, bench: Array }}
 */
function selectSplitStarters(rosteredHitters, split) {
  // Use optimal assignment to find best player-to-position mapping
  const { assignments } = optimalPositionAssignment(rosteredHitters, split);

  const selectedIds = new Set();
  const starterEntries = [];

  for (const [pos, player] of Object.entries(assignments)) {
    starterEntries.push({ player, position: pos });
    selectedIds.add(player.ID || player.Name);
  }

  const bench = rosteredHitters.filter(h => !selectedIds.has(h.ID || h.Name));

  return { starters: starterEntries, bench };
}

// ============================================================
// Platoon Bat Detection
// ============================================================

/**
 * Identify the best platoon bat candidate from remaining bench players.
 *
 * A platoon bat is a bench player who significantly outperforms a starter
 * at a shared position in one split (vR or vL).
 *
 * @param {Array} benchCandidates - bench players not yet assigned a bench role
 * @param {Object} starters - position -> player map (from weighted roster)
 * @returns {Object|null} - { player, platoonSplit, platoonPosition, waaAdvantage, replacesStarter }
 */
function identifyPlatoonBat(benchCandidates, starters) {
  let bestCandidate = null;
  let bestAdvantage = 0;

  for (const benchPlayer of benchCandidates) {
    const benchPositions = benchPlayer._positions || getEligiblePositions(benchPlayer);

    for (const split of ['vR', 'vL']) {
      for (const pos of benchPositions) {
        const starter = starters[pos];
        if (!starter) continue;

        const benchWAA = getPositionWAAForSplit(benchPlayer, pos, split);
        const starterWAA = getPositionWAAForSplit(starter, pos, split);

        if (benchWAA === -Infinity || starterWAA === -Infinity) continue;

        const advantage = benchWAA - starterWAA;
        if (advantage > bestAdvantage) {
          bestAdvantage = advantage;
          bestCandidate = {
            player: benchPlayer,
            platoonSplit: split,
            platoonPosition: pos,
            waaAdvantage: Math.round(advantage * 100) / 100,
            replacesStarter: starter.Name,
          };
        }
      }
    }
  }

  return bestCandidate;
}

// ============================================================
// Main Roster Optimization
// ============================================================

/**
 * Build the optimal 26-man roster and generate split lineups.
 *
 * @param {Array} hitters - All available hitter data
 * @param {Array} pitchers - All available pitcher data
 * @param {Object} options - { teamOrg, levelFilter }
 * @returns {Object} Optimized roster with split lineups
 */
export function optimizeRoster(hitters, pitchers, options = {}) {
  const {
    numCatchers = 2,
    numStartingPitchers = 5,
    numReliefPitchers = 8,
    totalBatters = 13,
    teamOrg = null,
    levelFilter = null,
  } = options;

  // ---- Filter players by org/level ----
  let availableHitters = [...hitters];
  let availablePitchers = [...pitchers];

  if (teamOrg) {
    availableHitters = availableHitters.filter(h =>
      (h.ORG || '').toLowerCase().includes(teamOrg.toLowerCase())
    );
    availablePitchers = availablePitchers.filter(p =>
      (p.ORG || '').toLowerCase().includes(teamOrg.toLowerCase())
    );
  }

  if (levelFilter) {
    availableHitters = availableHitters.filter(h =>
      (h.Lev || '').toLowerCase().includes(levelFilter.toLowerCase())
    );
    availablePitchers = availablePitchers.filter(p =>
      (p.Lev || '').toLowerCase().includes(levelFilter.toLowerCase())
    );
  }

  // ---- Score all hitters by WEIGHTED WAA ----
  const wtdColumns = WAA_COLUMNS.wtd;
  const scoredHitters = availableHitters
    .map(h => ({
      ...h,
      _maxWAA: getMaxWAA(h, wtdColumns),
      _positions: getEligiblePositions(h),
      _canPlaySS: canPlaySS(h),
      _canPlayCF: canPlayCF(h),
      _canPlayIF: canPlayIF(h),
      _canPlayOF: canPlayOF(h),
      _canPlayAllIF: canPlayAllIF(h),
      _canPlayCFAndCornerOF: canPlayCFAndCornerOF(h),
    }))
    .filter(h => h._maxWAA !== 0 || h._positions.length > 1)
    .sort((a, b) => b._maxWAA - a._maxWAA);

  // ---- STEP 1: Select Catchers (2) ----
  // Use position-specific WAA at C to pick catchers
  const catcherCandidates = scoredHitters
    .filter(h => h._positions.includes('C'))
    .map(h => ({
      ...h,
      _catcherWAA: getPositionWAAForSplit(h, 'C', 'wtd'),
    }))
    .filter(h => h._catcherWAA !== -Infinity)
    .sort((a, b) => b._catcherWAA - a._catcherWAA);

  const catchers = catcherCandidates.slice(0, numCatchers);
  const selectedIds = new Set(catchers.map(c => c.ID || c.Name));

  // ---- STEP 2: Optimal positional assignment (weighted WAA) ----
  // Pre-assign the starting catcher, then optimally assign the rest
  const preAssigned = {};
  if (catchers[0]) preAssigned['C'] = catchers[0];

  // Get top candidates by max WAA for consideration (limit pool size for performance)
  const candidatePool = scoredHitters.slice(0, Math.min(scoredHitters.length, 30));

  const { assignments: starterAssignments } = optimalPositionAssignment(
    candidatePool, 'wtd', new Set(), preAssigned
  );

  const starters = { ...starterAssignments };
  // Update selectedIds with all starters
  for (const player of Object.values(starters)) {
    selectedIds.add(player.ID || player.Name);
  }

  // ---- STEP 3: Select Bench (4 spots) ----

  // Backup C (already selected as catchers[1])
  const backupC = catchers[1] || null;

  // Utility IF: must be able to play SS + 2B + 3B (all three)
  let utilityIF = scoredHitters.find(h =>
    !selectedIds.has(h.ID || h.Name) && h._canPlayAllIF
  );
  // Fallback: can play SS + at least one other IF position
  if (!utilityIF) {
    utilityIF = scoredHitters.find(h =>
      !selectedIds.has(h.ID || h.Name) && h._canPlaySS && h._canPlayIF
    );
  }
  if (utilityIF) selectedIds.add(utilityIF.ID || utilityIF.Name);

  // Utility OF: must be able to play CF + at least one corner OF
  let utilityOF = scoredHitters.find(h =>
    !selectedIds.has(h.ID || h.Name) && h._canPlayCFAndCornerOF
  );
  // Fallback: can play CF + any OF
  if (!utilityOF) {
    utilityOF = scoredHitters.find(h =>
      !selectedIds.has(h.ID || h.Name) && h._canPlayCF && h._canPlayOF
    );
  }
  if (utilityOF) selectedIds.add(utilityOF.ID || utilityOF.Name);

  // Platoon bat: find bench player with biggest split advantage over a starter
  const platoonCandidates = scoredHitters.filter(h => !selectedIds.has(h.ID || h.Name));
  const platoonBat = identifyPlatoonBat(platoonCandidates, starters);
  if (platoonBat) {
    selectedIds.add(platoonBat.player.ID || platoonBat.player.Name);
  }

  // ---- STEP 4: Fill remaining bench spots to reach totalBatters ----
  const benchPlayers = [];
  while (selectedIds.size < totalBatters) {
    const next = scoredHitters.find(h => !selectedIds.has(h.ID || h.Name));
    if (!next) break;
    benchPlayers.push(next);
    selectedIds.add(next.ID || next.Name);
  }

  // ---- Collect all 13 rostered hitters ----
  const rosteredHitters = scoredHitters.filter(h => selectedIds.has(h.ID || h.Name));

  // ---- STEP 5: Generate split lineups ----
  const vRSplit = selectSplitStarters(rosteredHitters, 'vR');
  const vRBattingOrder = optimizeBattingOrder(vRSplit.starters, 'vR');

  const vLSplit = selectSplitStarters(rosteredHitters, 'vL');
  const vLBattingOrder = optimizeBattingOrder(vLSplit.starters, 'vL');

  // ---- STEP 6: Select Pitchers ----
  const scoredPitchers = availablePitchers.map(p => {
    const pos = (p.POS || '').toUpperCase();
    const spWAA = parseFloat(p[PITCHER_WAA_SP_COL]);
    const rpWAA = parseFloat(p[PITCHER_WAA_RP_COL]);
    return {
      ...p,
      _spWAA: isNaN(spWAA) ? 0 : spWAA,
      _rpWAA: isNaN(rpWAA) ? 0 : rpWAA,
      _bestWAA: Math.max(isNaN(spWAA) ? 0 : spWAA, isNaN(rpWAA) ? 0 : rpWAA),
      _isStarter: pos === 'SP',
      _isReliever: pos === 'RP' || pos === 'CL' || pos === 'MR',
    };
  });

  const spCandidates = scoredPitchers
    .filter(p => p._isStarter || !p._isReliever)
    .sort((a, b) => b._spWAA - a._spWAA);

  const startingPitchers = spCandidates.slice(0, numStartingPitchers);
  const spIds = new Set(startingPitchers.map(p => p.ID || p.Name));

  const rpCandidates = scoredPitchers
    .filter(p => !spIds.has(p.ID || p.Name))
    .sort((a, b) => b._rpWAA - a._rpWAA);

  const reliefPitchers = rpCandidates.slice(0, numReliefPitchers);

  // ---- Calculate totals ----
  const totalHitterWAA = rosteredHitters.reduce((sum, p) => sum + (p._maxWAA || 0), 0);
  const totalSPWAA = startingPitchers.reduce((sum, p) => sum + (p._spWAA || 0), 0);
  const totalRPWAA = reliefPitchers.reduce((sum, p) => sum + (p._rpWAA || 0), 0);
  const totalPitcherWAA = totalSPWAA + totalRPWAA;
  const totalRosterWAA = totalHitterWAA + totalPitcherWAA;

  const lineupWAA_vR = vRBattingOrder.reduce((sum, e) => sum + (e.waa || 0), 0);
  const lineupWAA_vL = vLBattingOrder.reduce((sum, e) => sum + (e.waa || 0), 0);

  const estimatedWins = Math.round(81 + totalRosterWAA);

  return {
    rosteredHitters,
    starters,
    bench: {
      backupC,
      utilityIF,
      utilityOF,
      platoonBat,
      extraBench: benchPlayers,
    },
    lineupVsRHP: {
      battingOrder: vRBattingOrder,
      bench: vRSplit.bench,
      totalLineupWAA: Math.round(lineupWAA_vR * 100) / 100,
    },
    lineupVsLHP: {
      battingOrder: vLBattingOrder,
      bench: vLSplit.bench,
      totalLineupWAA: Math.round(lineupWAA_vL * 100) / 100,
    },
    startingPitchers,
    reliefPitchers,
    totals: {
      totalHitterWAA: Math.round(totalHitterWAA * 100) / 100,
      totalSPWAA: Math.round(totalSPWAA * 100) / 100,
      totalRPWAA: Math.round(totalRPWAA * 100) / 100,
      totalPitcherWAA: Math.round(totalPitcherWAA * 100) / 100,
      totalRosterWAA: Math.round(totalRosterWAA * 100) / 100,
      estimatedWins,
      lineupWAA_vR: Math.round(lineupWAA_vR * 100) / 100,
      lineupWAA_vL: Math.round(lineupWAA_vL * 100) / 100,
    },
  };
}

export {
  getEligiblePositions,
  getMaxWAA,
  getPositionWAA,
  getPositionWAAForSplit,
  optimizeBattingOrder,
  selectSplitStarters,
  identifyPlatoonBat,
  optimalPositionAssignment,
  canPlaySS,
  canPlayCF,
  canPlayIF,
  canPlayOF,
  canPlayAllIF,
  canPlayCFAndCornerOF,
  WAA_COLUMNS,
  OBP_COLUMNS,
  WOBA_COLUMNS,
};
