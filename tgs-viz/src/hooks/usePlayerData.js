import { useState, useEffect, useMemo, useCallback } from 'react';
import { calculateFutureValue } from '../lib/futureValue';
import { controlWindow } from '../lib/serviceTime';
import { buildAgeGroups, calculateDraftFV } from '../lib/draftFV';
import { replacementOffset } from '../lib/leagueCalib.js';
import { buildDevPercentileData, calculateG5FV } from '../lib/g5FV';
import { calculateHybridFV } from '../lib/hybridFV';
import { getBestWAA, getPlayerWAR, calculatePlayerValue, calculatePitcherValue, fitFAMarket, resolveRate } from '../lib/marketValue';

/**
 * Build data file paths for a given league.
 * With a league: /data/{league}/hitters.json
 * Without (fallback): /data/hitters.json
 */
function getDataFiles(league) {
  const prefix = league ? `/data/${league}` : '/data';
  return {
    hitters: `${prefix}/hitters.json`,
    pitchers: `${prefix}/pitchers.json`,
    hitters_draft: `${prefix}/hitters_draft.json`,
    pitchers_draft: `${prefix}/pitchers_draft.json`,
    hitters_fa: `${prefix}/hitters_fa.json`,
    pitchers_fa: `${prefix}/pitchers_fa.json`,
  };
}

/**
 * Per-league feature flags. Anything not declared in the manifest defaults to
 * true so legacy manifests keep today's behavior (everything shown).
 */
export const DEFAULT_FEATURES = { draft: true, fa: true, contracts: true };

// Hardcoded fallback when /data/leagues.json is missing or unreadable —
// the two leagues the app originally shipped with. Guarantees the app
// always boots even if the manifest was never generated.
const FALLBACK_LEAGUES = [
  { id: 'TGS', name: 'TGS', features: { draft: true, fa: true, contracts: true } },
  { id: 'BLM', name: 'BLM', features: { draft: true, fa: false, contracts: true } },
];

/**
 * Accept both manifest schemas:
 *   new:    { "leagues": [{ id, name, features: {draft, fa, contracts}, ... }] }
 *   legacy: [{ id, name, folder, datasets }]
 * Legacy entries derive features from their dataset list (contracts unknowable
 * from the old schema, so assumed present — columns are null-safe anyway).
 */
function normalizeLeagues(raw) {
  const list = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.leagues) ? raw.leagues : []);
  return list
    .filter(lg => lg && lg.id)
    .map(lg => {
      let features = lg.features;
      if (!features && Array.isArray(lg.datasets)) {
        features = {
          draft: lg.datasets.some(d => String(d).endsWith('_draft')),
          fa: lg.datasets.some(d => String(d).endsWith('_fa')),
          contracts: true,
        };
      }
      return {
        ...lg,
        name: lg.name || lg.id,
        features: { ...DEFAULT_FEATURES, ...(features || {}) },
      };
    });
}

/**
 * Hook to load the leagues manifest (/data/leagues.json).
 * Returns { leagues, loading }. Never fails: if the manifest is missing,
 * unreadable, or empty, it falls back to the built-in TGS/BLM list.
 */
export function useLeagues() {
  const [leagues, setLeagues] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/data/leagues.json')
      .then(res => {
        // Non-JSON = dev-server SPA fallback for a missing file — same as 404.
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) {
          throw new Error(`leagues.json fetch failed (${res.status})`);
        }
        return res.json();
      })
      .then(data => {
        const normalized = normalizeLeagues(data);
        setLeagues(normalized.length ? normalized : FALLBACK_LEAGUES);
        setLoading(false);
      })
      .catch(e => {
        console.warn('leagues.json unavailable — using built-in TGS/BLM fallback:', e);
        setLeagues(FALLBACK_LEAGUES);
        setLoading(false);
      });
  }, []);

  return { leagues, loading };
}

/**
 * Main data loading hook.
 * Loads all player data for the given league.
 * Re-fetches when league changes.
 */
export function usePlayerData(league) {
  const [data, setData] = useState({
    hitters: [],
    pitchers: [],
    hitters_draft: [],
    pitchers_draft: [],
    hitters_fa: [],
    pitchers_fa: [],
    metadata: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadProgress, setLoadProgress] = useState({});

  useEffect(() => {
    let cancelled = false;

    // Reset state when league changes
    setLoading(true);
    setError(null);
    setLoadProgress({});
    setData({
      hitters: [], pitchers: [],
      hitters_draft: [], pitchers_draft: [],
      hitters_fa: [], pitchers_fa: [],
      metadata: null,
    });

    const dataFiles = getDataFiles(league);

    async function loadAll() {
      const results = {};

      for (const [key, url] of Object.entries(dataFiles)) {
        try {
          setLoadProgress(prev => ({ ...prev, [key]: 'loading' }));
          const res = await fetch(url);
          // Dev server SPA-fallback returns index.html (200, text/html) for
          // missing files — treat non-JSON responses as missing, same as a 404.
          const ctype = res.headers.get('content-type') || '';
          if (!res.ok || !ctype.includes('json')) {
            setLoadProgress(prev => ({ ...prev, [key]: 'missing' }));
            results[key] = [];
            continue;
          }
          const json = await res.json();
          // Filter out blank/empty rows (no Name) that come from empty sheet rows.
          // Stamp the app's league id (M5): the raw 'League' field is StatsPlus's
          // NUMERIC OOTP id (e.g. 112), useless for keying leagueCalib — the
          // per-league replacement offsets in futureValue/draftFV read _appLeague.
          results[key] = json
            .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-')
            .map(p => ({ ...p, _appLeague: league || 'TGS' }));
          setLoadProgress(prev => ({ ...prev, [key]: 'loaded' }));
        } catch (e) {
          console.warn(`Failed to load ${key}:`, e);
          setLoadProgress(prev => ({ ...prev, [key]: 'error' }));
          results[key] = [];
        }
      }

      // Per-league metadata (matchup shares etc.) — an object, not a player array.
      try {
        const mres = await fetch(`${league ? `/data/${league}` : '/data'}/metadata.json`);
        const mtype = mres.headers.get('content-type') || '';
        results.metadata = (mres.ok && mtype.includes('json')) ? await mres.json() : null;
      } catch {
        results.metadata = null;
      }

      if (!cancelled) {
        setData(results);
        setLoading(false);
      }
    }

    loadAll().catch(e => {
      if (!cancelled) {
        setError(e.message);
        setLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [league]);

  return { data, loading, error, loadProgress };
}

/**
 * Hook for filtering and sorting player data.
 */
export function useFilteredPlayers(players, initialFilters = {}) {
  const [filters, setFilters] = useState({
    search: '',
    position: 'ALL',
    org: 'ALL',
    level: 'ALL',
    minAge: 0,
    maxAge: 50,
    minOVR: 0,
    minPOT: 0,
    ...initialFilters,
  });

  const [sortConfig, setSortConfig] = useState({
    key: null,
    direction: 'desc',
  });

  const organizations = useMemo(() => {
    const orgs = new Set(players.map(p => p.ORG).filter(Boolean));
    return ['ALL', ...Array.from(orgs).sort()];
  }, [players]);

  const levels = useMemo(() => {
    const lvls = new Set(players.map(p => p.Lev).filter(Boolean));
    return ['ALL', ...Array.from(lvls).sort()];
  }, [players]);

  const positions = useMemo(() => {
    const pos = new Set(players.map(p => p.POS).filter(Boolean));
    return ['ALL', ...Array.from(pos).sort()];
  }, [players]);

  const filtered = useMemo(() => {
    let result = players;

    if (filters.search) {
      const s = filters.search.toLowerCase();
      result = result.filter(p =>
        (p.Name || '').toLowerCase().includes(s) ||
        (p.ID || '').toString().includes(s)
      );
    }

    if (filters.position !== 'ALL') {
      result = result.filter(p => (p.POS || '') === filters.position);
    }

    if (filters.org !== 'ALL') {
      result = result.filter(p => (p.ORG || '') === filters.org);
    }

    if (filters.level !== 'ALL') {
      result = result.filter(p => (p.Lev || '') === filters.level);
    }

    if (filters.minAge > 0) {
      result = result.filter(p => parseFloat(p.Age) >= filters.minAge);
    }
    if (filters.maxAge < 50) {
      result = result.filter(p => parseFloat(p.Age) <= filters.maxAge);
    }
    if (filters.minOVR > 0) {
      result = result.filter(p => parseFloat(p.OVR) >= filters.minOVR);
    }
    if (filters.minPOT > 0) {
      result = result.filter(p => parseFloat(p.POT) >= filters.minPOT);
    }

    // Sort
    if (sortConfig.key) {
      result = [...result].sort((a, b) => {
        let aVal = a[sortConfig.key];
        let bVal = b[sortConfig.key];

        // Try numeric sort
        const aNum = parseFloat(aVal);
        const bNum = parseFloat(bVal);

        if (!isNaN(aNum) && !isNaN(bNum)) {
          return sortConfig.direction === 'asc' ? aNum - bNum : bNum - aNum;
        }

        // String sort
        aVal = String(aVal || '');
        bVal = String(bVal || '');
        return sortConfig.direction === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      });
    }

    return result;
  }, [players, filters, sortConfig]);

  const handleSort = useCallback((key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    }));
  }, []);

  const updateFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters({
      search: '',
      position: 'ALL',
      org: 'ALL',
      level: 'ALL',
      minAge: 0,
      maxAge: 50,
      minOVR: 0,
      minPOT: 0,
    });
  }, []);

  return {
    filtered,
    filters,
    updateFilter,
    resetFilters,
    sortConfig,
    handleSort,
    organizations,
    levels,
    positions,
  };
}

/**
 * Hook that adds Future Value calculations to player data.
 */
export function usePlayersWithFV(players) {
  return useMemo(() => {
    return players.map(p => {
      // Value only the seasons this club actually holds. Every board used to
      // count six for everyone, which is right for a prospect (his clock hasn't
      // started) and badly wrong for a veteran with one year to free agency.
      const cw = controlWindow(p);
      const fv = calculateFutureValue(p, cw.controlYears);
      // Value Gap = our projection-based FV minus OOTP's POT (what other GMs eyeball).
      // Positive → we rate him higher than his potential shows → undervalued / a buy.
      const pot = parseFloat(p.Pot);
      // DISPLAY BASIS = WAA (vs average), per user preference: in a league this deep,
      // "better than an average starter" is the decision-relevant question — replacement
      // is only the right zero for PRICING. The FV engine computes internally on the WAR
      // basis (its scale anchors are calibrated there, and $ math needs a replacement
      // zero) and hands back a matching WAA track in fv.displayWAA.
      // marketValue.js keeps its own WAR basis untouched.
      //
      // Do NOT go back to "subtract fv.offsetUsed" here. That offset belongs to the
      // player's best CURRENT role; expectedPeak/potential are anchored on his best
      // PEAK role, and for ~1/3 of pitchers those are different roles (RP now, SP at
      // peak). Subtracting the RP offset from an SP-anchored peak inflated "Pot WAA"
      // by ~2.2 wins and inverted the board against its own Ceiling column.
      const d = fv.displayWAA || {};
      const toWAA = (v) => (Number.isFinite(v) ? v : null);
      return {
        ...p,
        _futureValue: fv.futureValue,
        _fvScale: fv.fvScale,
        _fvGap: (Number.isFinite(fv.fvScale) && Number.isFinite(pot)) ? fv.fvScale - pot : null,
        _peakWAA: toWAA(d.peakProjected),
        _pctToPeak: fv.pctToPeak,
        _yearsTilPeak: fv.yearsTilPeak,
        _projYears: fv.projectionYears,
        _currentWAA: toWAA(d.current),
        // "Proj Peak" = the REALISTIC age-adjusted peak (what we project he'll actually reach),
        // i.e. the raw ceiling AFTER the gap-factor and risk haircut. So a 26+ player past
        // development shows his current WAA — no credit for potential he'll never fill.
        // The un-haircut scouting ceiling is the board's "Ceiling (WAA)" column.
        _potentialWAA: toWAA(d.expectedPeak),
        _rawPotentialWAA: toWAA(d.potential),
        _controlYears: cw.controlYears,
        _controlSource: cw.source,
        _svcYears: cw.serviceYears,
        _controlWindow: cw,
        _fvBreakdown: fv,
      };
    });
  }, [players]);
}

/**
 * Hook that adds Draft FV calculations to player data.
 * Requires the full league population for age-relative percentile calculation.
 *
 * @param {Array} draftPlayers - Players to compute Draft FV for (already enriched with FV)
 * @param {Array} allPlayers - Full league population for percentile calculation
 * @param {'hitter'|'pitcher'} playerType
 */
export function usePlayersWithDraftFV(draftPlayers, allPlayers, playerType) {
  // Pitchers: best of SP or RP WAR for age comparison (audit M5 — same
  // role-offset currency calculateDraftFV uses, so a swingman's percentile is
  // taken on the same value that scores him; league read off the data itself).
  const metricKeyOrFn = useMemo(() => {
    if (playerType === 'hitter') return 'wOBA wtd';
    const lg = (allPlayers && allPlayers[0] && allPlayers[0]._appLeague) || undefined;
    const spOff = replacementOffset(lg, 'sp');
    const rpOff = replacementOffset(lg, 'rp');
    return (player) => {
      const sp = parseFloat(player['WAA wtd']);
      const rp = parseFloat(player['WAA wtd RP']);
      const best = Math.max(isNaN(sp) ? -Infinity : sp + spOff, isNaN(rp) ? -Infinity : rp + rpOff);
      return isFinite(best) ? best : NaN;
    };
  }, [playerType, allPlayers]);

  const ageGroups = useMemo(() => {
    if (!allPlayers || allPlayers.length === 0) return {};
    return buildAgeGroups(allPlayers, metricKeyOrFn);
  }, [allPlayers, metricKeyOrFn]);

  return useMemo(() => {
    if (!draftPlayers || draftPlayers.length === 0) return [];
    return draftPlayers.map(p => {
      const dfv = calculateDraftFV(p, ageGroups, playerType);
      return {
        ...p,
        _draftFV: dfv.draftFV,
        _draftRawFV: dfv.draftRawFV,
        _agePercentile: dfv.agePercentile,
        _ceilingScore: dfv.ceilingScore,
        _draftCeiling: dfv.draftCeiling,          // WAR — what Draft FV is scored on
        _draftCeilingWAA: dfv.draftCeilingWAA,    // WAA — what the board displays
        _ceilingRole: dfv.ceilingRole,
        _durability: dfv.proneValue,
        _toolPenalty: dfv.toolPenalty,
        _highINT: dfv.highINT,
        _wrecked: dfv.wrecked,
        _weBoost: dfv.weBoost,
      };
    });
  }, [draftPlayers, ageGroups, playerType]);
}

/**
 * Hook that adds G5 FV calculations to player data.
 * G5 uses Gaussian kernel-weighted devPercentile among age-peers.
 * Requires the full league population for comparison.
 *
 * @param {Array} players - Players to compute G5 FV for (already enriched with FV)
 * @param {Array} allPlayers - Full league population for devPercentile
 * @param {'hitter'|'pitcher'} playerType
 */
export function usePlayersWithG5FV(players, allPlayers, playerType) {
  // G5 uses BatR wtd for hitters, WAA wtd for pitchers (per FINDINGS.md)
  const devMetricKey = playerType === 'hitter' ? 'BatR wtd' : 'WAA wtd';

  const devPercentileData = useMemo(() => {
    if (!allPlayers || allPlayers.length === 0) return {};
    return buildDevPercentileData(allPlayers, devMetricKey);
  }, [allPlayers, devMetricKey]);

  return useMemo(() => {
    if (!players || players.length === 0) return [];
    return players.map(p => {
      const g5 = calculateG5FV(p, devPercentileData);
      return {
        ...p,
        _g5FV: g5.g5FV,
        _g5Raw: g5.g5Raw,
        _g5DevPct: g5.g5DevPct,
        _g5GapFactor: g5.g5GapFactor,
        _g5RiskFactor: g5.g5RiskFactor,
      };
    });
  }, [players, devPercentileData]);
}

/**
 * Hook that adds Hybrid FV calculations to player data.
 * Requires players to already have _fvScale, _g5FV, and _draftFV.
 *
 * @param {Array} players - Players enriched with FV, G5, and Draft FV
 */
export function usePlayersWithHybridFV(players) {
  return useMemo(() => {
    if (!players || players.length === 0) return [];
    return players.map(p => {
      const hfv = calculateHybridFV(p);
      return {
        ...p,
        _hybridFV: hfv.hybridFV,
        _hybridRaw: hfv.hybridRaw,
        _hybridWFV: hfv.hybridWeightFV,
        _hybridWG5: hfv.hybridWeightG5,
        _hybridWDraft: hfv.hybridWeightDraft,
      };
    });
  }, [players]);
}

/**
 * Hook that fits the FA salary market for the loaded league (marketValue.js
 * fitFAMarket: salary ~ slope * WAR + floor over fresh FA signings only).
 * Re-fits automatically whenever the league data refreshes.
 * Call once in App and pass down to pages. Name kept for App.jsx compat.
 */
export function useMarketRate(hitters, pitchers) {
  return useMemo(() => {
    if (!hitters.length && !pitchers.length) return null;
    return fitFAMarket(hitters, pitchers);
  }, [hitters, pitchers]);
}

/** Shared enrichment for both market-value hooks. */
function withMarketValue(p, val, war) {
  return {
    ...p,
    _bestWAA: getBestWAA(p),
    _war: war,
    _marketValue: val.adjustedValue,
    _annualValue: val.annualValue,          // line value (replaceable tier)
    _mktPrice: val.marketPrice,             // tier-local market price
    _mktSurplus: val.marketSurplus,         // tier-local surplus
    _mktTier: val.tier,                     // 'replaceable' | 'scarcity'
    _offerFloor: val.offerFloor,
    _offerMid: val.offerMid,
    _offerCeiling: val.offerCeiling,
    _surplus: val.surplus,
    _ctrSurplus: val.contract ? val.contract.surplus : null,
    _ctrYears: val.contract ? val.contract.yearsRemaining : null,
    _futureAAV: val.futureAnnualValue,
    _futureOfferLow: val.futureOfferFloor,
    _futureOfferMid: val.futureOfferMid,
    _futureOfferHigh: val.futureOfferCeiling,
    _perWAA: p.Price > 0 && war > 0 ? Math.round(p.Price / war) : null,
  };
}

/**
 * Hook that adds market value calculations to HITTER data.
 * v2: prices with the hitter's OWN fitted line (market-WAR basis — see
 * marketValue.js resolveRate); offers are tier-local (LOESS over
 * comparable-WAR signings).
 */
export function useHittersWithMarketValue(players, marketFit) {
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'hitter');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePlayerValue(p, rate);
      return withMarketValue(p, val, getPlayerWAR(p) ?? 0);
    });
  }, [players, marketFit]);
}

/**
 * Hook that adds market value calculations to PITCHER data.
 * Same fitted line resolution; shows SP/RP role for reference.
 */
export function usePitchersWithMarketValue(players, marketFit) {
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'pitcher');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePitcherValue(p, rate);
      return { ...withMarketValue(p, val, getPlayerWAR(p) ?? 0), _marketRole: val.role };
    });
  }, [players, marketFit]);
}

/**
 * Detect WAA-like columns from player data.
 */
export function detectWAAColumns(players) {
  if (!players.length) return { hitter: [], pitcher: [] };

  const allCols = Object.keys(players[0]);
  const waaCols = allCols.filter(c => {
    const cl = c.toLowerCase();
    return cl.includes('waa') || cl.includes('war') ||
           (cl.includes('wtd') && !cl.includes('pot'));
  });

  return waaCols;
}
