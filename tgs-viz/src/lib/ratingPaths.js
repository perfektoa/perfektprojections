/**
 * ratingPaths.js: loader for /data/<LG>/rating_paths/ (backtest/ml/rating_path.py).
 *
 * Year-by-year projections of each rating, from DEV players with the same
 * ratings, potentials and last-year movement. index.json holds the labels,
 * the pulls used and the validation numbers; the players sit in 64 buckets
 * by ID (b00.json .. b63.json), so a player panel loads one small file.
 *
 * INFORMATIONAL: nothing here feeds a projection. The WAA numbers still price
 * the current ratings as they are. Each player's "w" is the WAA change of his
 * projected (50th percentile) ratings line priced with the league's engine,
 * shown as a cross-check against the ML WAA path.
 */

const index = {};    // league -> Promise<index | null>
const buckets = {};  // `${league}|${n}` -> Promise<bucket | null>

function getJson(url) {
  return fetch(url)
    .then(res => {
      const ctype = res.headers.get('content-type') || '';
      if (!res.ok || !ctype.includes('json')) throw new Error(`${url} ${res.status}`);
      return res.json();
    })
    .catch(() => null);
}

/** Forget one league's cached files (live refresh). No league: every league. */
export function invalidateRatingPaths(league) {
  for (const k of Object.keys(index)) if (!league || k === league) delete index[k];
  for (const k of Object.keys(buckets)) if (!league || k.startsWith(`${league}|`)) delete buckets[k];
}

export function loadRatingPathIndex(league) {
  const lg = league || 'TGS';
  if (!index[lg]) index[lg] = getJson(`/data/${lg}/rating_paths/index.json`);
  return index[lg];
}

function bucketOf(id, n) {
  const s = String(id);
  if (/^\d+$/.test(s)) return Number(BigInt(s) % BigInt(n));
  let t = 0;
  for (const ch of s) t += ch.charCodeAt(0);
  return t % n;
}

/** {index, path} for one player, or null when the league has no paths or he has none. */
export async function loadRatingPath(league, id) {
  const lg = league || 'TGS';
  const idx = await loadRatingPathIndex(lg);
  if (!idx) return null;
  const n = idx.n_buckets || 64;
  const b = bucketOf(id, n);
  const key = `${lg}|${b}`;
  if (!buckets[key]) buckets[key] = getJson(`/data/${lg}/rating_paths/b${String(b).padStart(2, '0')}.json`);
  const bucket = await buckets[key];
  const path = bucket ? bucket[String(id)] : null;
  return path ? { index: idx, path } : null;
}

/** [lo, mid, hi] arrays (ranged ratings) or [null, mid, null] (50th only), by year 1..K. */
export function pathBands(p) {
  if (!Array.isArray(p) || !p.length) return null;
  if (Array.isArray(p[0])) return { lo: p[0], mid: p[1], hi: p[2] };
  return { lo: null, mid: p, hi: null };
}

/** Highest projected value and the year it is first reached (0 = now). */
export function bestOf(now, mid) {
  let best = now, at = 0;
  mid.forEach((v, i) => { if (v > best + 1e-9) { best = v; at = i + 1; } });
  return { best, at };
}

/** First year the 50th-percentile path sits below its own best by `drop` points or more. */
export function fallOffYear(now, mid, drop = 2) {
  const { best, at } = bestOf(now, mid);
  for (let i = Math.max(at, 1) - 1; i < mid.length; i++) {
    if (i + 1 > at && mid[i] <= best - drop) return i + 1;
  }
  return null;
}
