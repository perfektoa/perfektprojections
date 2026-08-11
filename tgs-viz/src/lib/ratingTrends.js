/**
 * ratingTrends.js — loader/helpers for /data/<LG>/rating_trends.json, the
 * ratings-history export built by backtest/ratings_db.py --export.
 *
 * INFORMATIONAL ONLY: this data shows how scouting ratings moved across pulls.
 * Nothing here feeds any projection — projections are ratings-only from the
 * CURRENT pull, exactly as before.
 */

const cache = {};

/** Fetch (once per league) the trends file. Resolves to null when missing. */
export function loadRatingTrends(league) {
  const lg = league || 'TGS';
  if (!cache[lg]) {
    cache[lg] = fetch(`/data/${lg}/rating_trends.json`)
      .then(res => {
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) throw new Error(`rating_trends.json ${res.status}`);
        return res.json();
      })
      .catch(() => null);
  }
  return cache[lg];
}

/**
 * Per-rating history for one player.
 * Returns null when the trends file is missing, or
 * { dates, rows: [{col, values (aligned to dates, null = not in that pull),
 *   first, last, delta}], vintages } — rows sorted by |delta| desc.
 * A player absent from the file had NO rating changes in the window.
 */
export function playerHistory(trends, playerId) {
  if (!trends || !trends.players) return null;
  const entry = trends.players[String(playerId)];
  const windowIdx = trends.window || [];
  const dates = windowIdx.map(i => (trends.pulls[i] ? trends.pulls[i].d : ''));
  if (!entry) return { dates, rows: [], vintages: trends.pulls.length };
  const rows = Object.entries(entry.s).map(([ci, values]) => {
    const present = values.filter(v => v !== null && v !== undefined);
    const first = present.length ? present[0] : null;
    const last = present.length ? present[present.length - 1] : null;
    return {
      col: trends.cols[Number(ci)] || `#${ci}`,
      values,
      first,
      last,
      delta: (first !== null && last !== null) ? last - first : 0,
    };
  });
  rows.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  return { dates, rows, vintages: trends.pulls.length };
}
