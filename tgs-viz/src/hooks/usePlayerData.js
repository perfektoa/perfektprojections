import { useState, useEffect, useMemo, useCallback } from 'react';
import { calculateFutureValue } from '../lib/futureValue';
import { buildAgeGroups, calculateDraftFV } from '../lib/draftFV';
import { buildDevPercentileData, calculateG5FV } from '../lib/g5FV';
import { calculateHybridFV } from '../lib/hybridFV';
import { getBestWAA, isBetterAsRP, calculatePlayerValue, calculatePitcherValue, getLeagueMarketRate } from '../lib/marketValue';

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
 * Hook to load the leagues manifest (/data/leagues.json).
 * Returns { leagues, loading, error }.
 */
export function useLeagues() {
  const [leagues, setLeagues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/data/leagues.json')
      .then(res => {
        if (!res.ok) throw new Error('leagues.json not found — run python extract_data.py');
        return res.json();
      })
      .then(data => {
        setLeagues(data);
        setLoading(false);
      })
      .catch(e => {
        console.warn('Failed to load leagues.json:', e);
        setError(e.message);
        setLoading(false);
      });
  }, []);

  return { leagues, loading, error };
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
    setData({ hitters: [], pitchers: [], hitters_draft: [], pitchers_draft: [] });

    const dataFiles = getDataFiles(league);

    async function loadAll() {
      const results = {};

      for (const [key, url] of Object.entries(dataFiles)) {
        try {
          setLoadProgress(prev => ({ ...prev, [key]: 'loading' }));
          const res = await fetch(url);
          if (!res.ok) {
            setLoadProgress(prev => ({ ...prev, [key]: 'missing' }));
            results[key] = [];
            continue;
          }
          const json = await res.json();
          // Filter out blank/empty rows (no Name) that come from empty sheet rows
          results[key] = json.filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-');
          setLoadProgress(prev => ({ ...prev, [key]: 'loaded' }));
        } catch (e) {
          console.warn(`Failed to load ${key}:`, e);
          setLoadProgress(prev => ({ ...prev, [key]: 'error' }));
          results[key] = [];
        }
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
      const fv = calculateFutureValue(p);
      return {
        ...p,
        _futureValue: fv.futureValue,
        _fvScale: fv.fvScale,
        _peakWAA: fv.peakProjectedWAA,
        _pctToPeak: fv.pctToPeak,
        _yearsTilPeak: fv.yearsTilPeak,
        _projYears: fv.projectionYears,
        _currentWAA: fv.currentWAA,
        _potentialWAA: fv.potentialWAA,
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
  // Pitchers: best of SP or RP WAA for age comparison (same as what calculateDraftFV uses)
  const metricKeyOrFn = useMemo(() => {
    if (playerType === 'hitter') return 'wOBA wtd';
    return (player) => {
      const sp = parseFloat(player['WAA wtd']);
      const rp = parseFloat(player['WAA wtd RP']);
      const best = Math.max(isNaN(sp) ? -Infinity : sp, isNaN(rp) ? -Infinity : rp);
      return isFinite(best) ? best : NaN;
    };
  }, [playerType]);

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
        _draftCeiling: dfv.draftCeiling,
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
 * Hook that computes the league-wide $/WAA rate.
 * Single rate for everyone: total MLB payroll / total positive WAA.
 * Call once in App and pass down to pages.
 */
export function useMarketRate(hitters, pitchers) {
  return useMemo(() => {
    if (!hitters.length && !pitchers.length) return { rate: 0, lowConfidence: true };
    return getLeagueMarketRate(hitters, pitchers);
  }, [hitters, pitchers]);
}

/**
 * Hook that adds market value calculations to HITTER data.
 * Uses the single league $/WAA rate.
 */
export function useHittersWithMarketValue(players, marketInfo) {
  const rate = marketInfo?.rate || 0;
  return useMemo(() => {
    if (!players || players.length === 0 || !rate) return players;
    return players.map(p => {
      const waa = getBestWAA(p);
      const val = calculatePlayerValue(p, rate);
      return {
        ...p,
        _bestWAA: waa,
        _marketValue: val.adjustedValue,
        _annualValue: val.annualValue,
        _offerFloor: val.offerFloor,
        _offerMid: val.offerMid,
        _offerCeiling: val.offerCeiling,
        _surplus: val.surplus,
        _futureAAV: val.futureAnnualValue,
        _futureOfferLow: val.futureOfferFloor,
        _futureOfferMid: val.futureOfferMid,
        _futureOfferHigh: val.futureOfferCeiling,
        _perWAA: p.Price > 0 && waa > 0 ? Math.round(p.Price / waa) : null,
      };
    });
  }, [players, rate]);
}

/**
 * Hook that adds market value calculations to PITCHER data.
 * Uses the single league $/WAA rate. Shows SP/RP role for reference.
 */
export function usePitchersWithMarketValue(players, marketInfo) {
  const rate = marketInfo?.rate || 0;
  return useMemo(() => {
    if (!players || players.length === 0 || !rate) return players;
    return players.map(p => {
      const waa = getBestWAA(p);
      const val = calculatePitcherValue(p, rate);
      return {
        ...p,
        _bestWAA: waa,
        _marketValue: val.adjustedValue,
        _annualValue: val.annualValue,
        _offerFloor: val.offerFloor,
        _offerMid: val.offerMid,
        _offerCeiling: val.offerCeiling,
        _surplus: val.surplus,
        _futureAAV: val.futureAnnualValue,
        _futureOfferLow: val.futureOfferFloor,
        _futureOfferMid: val.futureOfferMid,
        _futureOfferHigh: val.futureOfferCeiling,
        _perWAA: p.Price > 0 && waa > 0 ? Math.round(p.Price / waa) : null,
        _marketRole: val.role,
      };
    });
  }, [players, rate]);
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
