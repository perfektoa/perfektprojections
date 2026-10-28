/**
 * draftValue.js: reads /data/<LG>/draft_value.json (backtest/ml/draft_value.py)
 * and puts the DEV-measured draft value on player rows.
 *
 * User, 2026-10-27: "i dont understand how we can do so many seasons of
 * projecting where draft picks will eventually be and not like have something
 * worth using". Ctrl wins = the wins above a replacement-level player (DEV-measured
 * per role and season) a prospect gives over his first six MLB-level seasons,
 * learned from the DEV players' real careers (amateurs included) and scored
 * from his card today. The draft board ranks on the Board score below.
 *
 * STALE GUARD (as devMl.js): the file is used only when its pull equals the
 * pull of dev_signals.json (basis.to_pull_id) and its league matches.
 *
 * Fields on a row with an entry (ages 16-26):
 *   Dev_CtrlWins   expected wins over his control years (what you draft on)
 *   Dev_CtrlQ90    the 90th percentile of the same (upside)
 *   Dev_CtrlWords  one line for the hovers
 *
 * Pure module apart from fetchDraftValue, so a node check can import it.
 */

const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Why the file cannot be used with these signals, or '' when it can. */
export function draftValueStaleReason(dv, signals) {
  if (!dv || !dv.players) return 'no draft value file';
  const sb = signals && signals.basis;
  if (!sb) return 'no dev_signals file to check the pull against';
  if (signals.league && dv.league && signals.league !== dv.league) {
    return `league ${dv.league} does not match dev_signals league ${signals.league}`;
  }
  if (dv.pull !== undefined && dv.pull !== null && sb.to_pull_id !== undefined
      && String(dv.pull) !== String(sb.to_pull_id)) {
    return `draft value pull ${dv.pull} does not match dev_signals pull ${sb.to_pull_id}`;
  }
  return '';
}

/** One line for the hovers. */
export function draftValueWords(dv) {
  const d = (dv && dv.definition && dv.definition.ctrl) || '';
  return d || 'expected wins above a replacement-level player over his first six MLB-level seasons (DEV-measured)';
}

/**
 * Put the draft value on every row whose ID has an entry. Returns the same
 * array when the file is missing, stale or has no entry for any row.
 */
export function applyDraftValue(rows, dv, signals) {
  if (!Array.isArray(rows) || !rows.length || !dv || !dv.players) return rows;
  if (draftValueStaleReason(dv, signals)) return rows;
  const words = draftValueWords(dv);
  let touched = false;
  const out = rows.map(p => {
    const e = dv.players[String(p.ID)];
    if (!e || num(e.ctrl) === null) return p;
    touched = true;
    return { ...p, Dev_CtrlWins: num(e.ctrl), Dev_CtrlQ90: num(e.q90), Dev_CtrlWords: words };
  });
  return touched ? out : rows;
}

// Board score, in wins. User, 2026-10-27: "ctrl wins 70% weight draft fv 30%
// weight"; 2026-10-28, after "we are perhaps missing some major upside type
// guys": halfway to the 90th percentile, then "50/40/10 so
// ML/top10percentile/draftfv", then "40ML/20TOP10%/20DRAFTFV/20Ceiling". So:
// Ctrl wins (expected) 40% + Upside (the 90th percentile) 20% + Draft FV 20% +
// Ceiling (WAA, _draftCeilingWAA) 20%. In the BLM 2026 pool the gap from
// expected to the 90th percentile was +11 to +14 wins for the 17-18-year-old
// hitters and +3 for college starters, so the Upside and Ceiling weights are
// where the board gambles. Draft FV and Ceiling are each first put on the
// scale of the ML part (same average and spread across the pool), so 20% of
// either means 20% and the gaps at the top stay in wins. A row with no Ctrl
// wins or no Draft FV gets no score; one with no Upside uses Ctrl wins for
// both, one with no Ceiling takes the pool average there.
// The weights are editable on the Draft Board page (user, 2026-10-28: "edit the
// weights of each of those 4 then like have a refresh button"); the edited set
// is saved in the browser (loadBoardWeights / saveBoardWeights) and the Mock
// Draft follows it. These are the defaults.
export const BOARD_WEIGHTS = Object.freeze({ ctrl: 0.4, q90: 0.2, fv: 0.2, ceil: 0.2 });
export const BOARD_PARTS = [
  ['ctrl', 'Ctrl wins', 'expected wins over his control years'],
  ['q90', 'Upside', 'the 90th percentile of Ctrl wins'],
  ['fv', 'Draft FV', 'age percentile + ceiling + projected peak, red flags multiply'],
  ['ceil', 'Ceiling', 'best-case peak WAA'],
];
const WEIGHTS_KEY = 'tgs.boardWeights';

const pct = w => Math.round(w * 100);

/** Clean a weight set: numbers at or above 0, scaled to sum 1; the defaults when nothing is left. */
export function normalizeWeights(w) {
  const out = {};
  let sum = 0;
  for (const [k] of BOARD_PARTS) {
    const v = Number(w && w[k]);
    out[k] = Number.isFinite(v) && v > 0 ? v : 0;
    sum += out[k];
  }
  if (sum <= 0) return { ...BOARD_WEIGHTS };
  for (const k of Object.keys(out)) out[k] /= sum;
  return out;
}

/** One line for the header and hovers: the blend at these weights. */
export function boardWords(w = BOARD_WEIGHTS) {
  const n = normalizeWeights(w);
  const parts = BOARD_PARTS.filter(([k]) => n[k] > 0).map(([k, name]) => `${name} ${pct(n[k])}%`);
  return `${parts.join(' + ')}, in wins (Draft FV and Ceiling put on the Ctrl wins scale first)`;
}
export const BOARD_WORDS = boardWords();

/** The saved weights, or the defaults. Browser storage can be missing or blocked. */
export function loadBoardWeights() {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(WEIGHTS_KEY) : null;
    if (!raw) return { ...BOARD_WEIGHTS };
    return normalizeWeights(JSON.parse(raw));
  } catch {
    return { ...BOARD_WEIGHTS };
  }
}

/** Save a weight set for the next visit and tell the open pages. Returns the cleaned set. */
export function saveBoardWeights(w) {
  const n = normalizeWeights(w);
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(WEIGHTS_KEY, JSON.stringify(n));
  } catch { /* storage blocked: the page keeps the weights until a reload */ }
  try {
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('tgs:boardWeights', { detail: n }));
  } catch { /* no window (node check) */ }
  return n;
}

/** The ML part of the Board score: Ctrl wins and Upside at their weights, in wins; null without Ctrl wins. */
export function mlPart(p, w = BOARD_WEIGHTS) {
  if (!(w.ctrl + w.q90 > 0)) return null;
  const c = p && p.Dev_CtrlWins;
  if (!Number.isFinite(c)) return null;
  const q = Number.isFinite(p.Dev_CtrlQ90) ? p.Dev_CtrlQ90 : c;
  return (w.ctrl * c + w.q90 * q) / (w.ctrl + w.q90);
}

export function boardScores(players, weights = BOARD_WEIGHTS) {
  const out = new Map();
  const w = normalizeWeights(weights);
  const rows = (players || [])
    .map(p => ({ p, m: mlPart(p, w), f: parseFloat(p._draftRawFV), c: parseFloat(p._draftCeilingWAA) }))
    .filter(r => Number.isFinite(r.m) && Number.isFinite(r.f));
  if (rows.length < 2) return out;
  const mean = a => a.reduce((s, v) => s + v, 0) / a.length;
  const sd = (a, m) => Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / a.length);
  const m = rows.map(r => r.m);
  const mm = mean(m), sm = sd(m, mm);
  // Put another number on the ML part's scale: same average, same spread.
  const onScale = vals => {
    const mv = mean(vals), sv = sd(vals, mv);
    return v => (Number.isFinite(v) && sv > 0 ? mm + (v - mv) * sm / sv : mm);
  };
  const fvWins = onScale(rows.map(r => r.f));
  const ceilRows = rows.filter(r => Number.isFinite(r.c)).map(r => r.c);
  const ceilWins = ceilRows.length >= 2 ? onScale(ceilRows) : () => mm;
  const wMl = w.ctrl + w.q90;
  for (const r of rows) {
    out.set(String(r.p.ID), wMl * r.m + w.fv * fvWins(r.f) + w.ceil * ceilWins(r.c));
  }
  return out;
}

export async function fetchDraftValue(base) {
  try {
    const res = await fetch(`${base}/draft_value.json`);
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok || !ctype.includes('json')) return null;
    const json = await res.json();
    return json && json.players ? json : null;
  } catch {
    return null;
  }
}
