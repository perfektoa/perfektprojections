"""
ratings_db.py — permanent per-player ratings-history database + trend analytics.

PURPOSE (informational feature — it must NOT alter any projection): keep every
recoverable scouting-ratings vintage in one SQLite store so pull-to-pull rating
movement (scout churn, player development/decline) can be tracked per player,
per rating column, across leagues — forever. Projections never read this DB.

    tgs-viz/backtest/ratings_history.db          (stdlib sqlite3, no deps)

Schema (wide table — one row per player per pull, one NUMERIC column per
rating; the rating set mirrors ingest/ratings.py SMOOTH_COLS + Ovr/Pot):

    pulls(pull_id PK, league, real_date UNIQUE-with-league, real_ts, source,
          source_files, n_players, content_hash, ingested_at)
    ratings(pull_id, player_id, name, age, pos, org, lev, c_<RATING>..., PK(pull_id, player_id))

CLI:
    python ratings_db.py --backfill            # ingest every recoverable vintage:
                                               #   ingest/.cache/history/*.json
                                               #   backtest/snapshots/<LG>/*/statsplus_*.json
                                               #   public/data/<LG>/{hitters,pitchers}.json.bak-*  (mtime = vintage date)
                                               # dedupe: one pull per league+date (best source wins);
                                               # bak vintages whose ratings are byte-identical to the
                                               # previous vintage (engine REPROCESSES, not new pulls) are skipped.
    python ratings_db.py --append <cache.json> --league TGS   # ingest one live raw pull (used by refresh.py)
    python ratings_db.py --report  [--league TGS] [--window 3]
    python ratings_db.py --export  [--league TGS]  # -> public/data/<LG>/rating_trends.json (app surface)

refresh.py calls append_pull() automatically after archiving each live pull.
"""
import os
import sys
import re
import json
import time
import glob
import sqlite3
import hashlib
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)                                  # tgs-viz
REPO = os.path.dirname(VIZ)
INGEST = os.path.join(VIZ, "ingest")
DB_PATH = os.path.join(HERE, "ratings_history.db")

sys.path.insert(0, INGEST)
import statsplus as S  # stdlib-only; supplies STATSPLUS_TO_SHEET  # noqa: E402

LEAGUES = {"TGS": "tgs", "BLM": "blm"}

# ---- rating columns (sheet-name space; mirrors ingest/ratings.py SMOOTH_COLS) --
_PIT_CORE = ["STU", "HRR", "PBABIP", "CON"]
_PIT_SPLITS = [f"{c} {s}" for c in _PIT_CORE for s in ("vR", "vL", "P")]
_PITCH_CUR = ["FB", "CH", "CB", "SL", "SI", "SP", "CT", "FO", "CC", "SC", "KC", "KN"]
_PITCH_POT = ["KNP", "FBP", "CHP", "CBP", "SLP", "SIP", "SPP", "CTP", "FOP", "CCP", "SCP", "KCP"]
_HIT_SPLITS = [f"{c} {s}" for c in ("BA", "GAP", "POW", "EYE", "K") for s in ("vR", "vL")]
_HIT_POT = ["HT P", "GAP P", "POW P", "EYE P", "K P"]
_RUN_FLD = ["SPE", "SR", "STE", "RUN",
            "IF RNG", "IF ERR", "IF ARM", "TDP", "OF RNG", "OF ERR", "OF ARM",
            "C ABI", "C FRM", "C ARM"]
SMOOTH_COLS = (_PIT_CORE + _PIT_SPLITS + ["STM", "HLD"] + _PITCH_CUR + _PITCH_POT
               + _HIT_SPLITS + _HIT_POT + _RUN_FLD)
EXTRA_COLS = ["Ovr", "Pot"]          # OOTP's own 20-80 summary grades (context only)
ALL_COLS = SMOOTH_COLS + EXTRA_COLS

COL2SQL = {c: "c_" + re.sub(r"[^A-Za-z0-9]", "_", c) for c in ALL_COLS}
SQL2COL = {v: k for k, v in COL2SQL.items()}
assert len(SQL2COL) == len(ALL_COLS), "rating column SQL names collide"

# source precedence when several files claim the same league+date vintage
SOURCE_RANK = {"live": 5, "history": 4, "snapshot": 3, "bak": 2, "recovered": 1, "live-current": 0}
# sources that are engine REPROCESS artifacts (not necessarily new pulls) —
# eligible for the identical-content skip so a re-run of the engine over the
# same ratings never fabricates a fake "vintage" with zero deltas.
REPROCESS_SOURCES = {"bak", "live-current"}


def num(v):
    """Rating value -> float or None. '-' reads as 20 (the engine's convention)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    if s == "-":
        return 20.0
    try:
        return float(s)
    except ValueError:
        return None


def _compact(x):
    """Store integral floats as ints (NUMERIC affinity keeps them small)."""
    if x is None:
        return None
    return int(x) if float(x).is_integer() else float(x)


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    rating_defs = ", ".join(f'"{COL2SQL[c]}" NUMERIC' for c in ALL_COLS)
    conn.execute("""CREATE TABLE IF NOT EXISTS pulls(
        pull_id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        real_date TEXT NOT NULL,
        real_ts TEXT,
        source TEXT NOT NULL,
        source_files TEXT,
        n_players INTEGER,
        content_hash TEXT,
        ingested_at TEXT,
        UNIQUE(league, real_date))""")
    conn.execute(f"""CREATE TABLE IF NOT EXISTS ratings(
        pull_id INTEGER NOT NULL,
        player_id TEXT NOT NULL,
        name TEXT, age REAL, pos TEXT, org TEXT, lev TEXT,
        {rating_defs},
        PRIMARY KEY(pull_id, player_id)) WITHOUT ROWID""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_player ON ratings(player_id)")
    return conn


# ---------------------------------------------------------------- row shaping
def rows_to_map(rows, translate=True):
    """Rows (raw StatsPlus schema or already sheet-schema) -> {pid: rec} where
    rec = {name, age, pos, org, lev, <sheet rating col>: float, ...}."""
    if translate:
        rows = S.translate_rows(rows)
    out = {}
    for r in rows:
        pid = str(r.get("ID") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not pid or pid in ("0", "None") or not name or name == "-":
            continue
        rec = {
            "name": name,
            "age": num(r.get("Age")),
            "pos": (str(r.get("POS") or r.get("Pos") or "").strip() or None),
            "org": (str(r.get("ORG") or r.get("Org") or "").strip() or None),
            "lev": (str(r.get("Lev") or "").strip() or None),
        }
        for c in ALL_COLS:
            if c in r:
                rec[c] = num(r.get(c))
        out[pid] = rec
    return out


def content_hash(pmap):
    """Hash of the rating CONTENT of a vintage (ids + rating values only)."""
    h = hashlib.sha1()
    for pid in sorted(pmap):
        rec = pmap[pid]
        h.update(pid.encode())
        for c in ALL_COLS:
            v = rec.get(c)
            if v is not None:
                h.update(c.encode())
                h.update(f"{v:.4f}".encode())
    return h.hexdigest()


def _same_ratings(prev_map, cand_map):
    """True when cand looks like a REPROCESS of prev: >=95%% of cand's players
    exist in prev and every shared player's shared rating values are identical."""
    shared = [pid for pid in cand_map if pid in prev_map]
    if not cand_map or len(shared) < 0.95 * len(cand_map):
        return False
    for pid in shared:
        a, b = prev_map[pid], cand_map[pid]
        for c in ALL_COLS:
            va, vb = a.get(c), b.get(c)
            if va is None or vb is None:
                continue
            if abs(va - vb) > 1e-9:
                return False
    return True


# ---------------------------------------------------------------- ingestion
def insert_pull(conn, league, real_date, real_ts, source, files, pmap):
    cur = conn.execute(
        "INSERT INTO pulls(league, real_date, real_ts, source, source_files, n_players, content_hash, ingested_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (league, real_date, real_ts, source, json.dumps(files), len(pmap),
         content_hash(pmap), datetime.datetime.now().isoformat(timespec="seconds")))
    pull_id = cur.lastrowid
    cols = ["pull_id", "player_id", "name", "age", "pos", "org", "lev"] + [COL2SQL[c] for c in ALL_COLS]
    sql = "INSERT INTO ratings({}) VALUES({})".format(
        ", ".join(f'"{c}"' for c in cols), ", ".join("?" * len(cols)))
    conn.executemany(sql, (
        [pull_id, pid, rec["name"], rec["age"], rec["pos"], rec["org"], rec["lev"]]
        + [_compact(rec.get(c)) for c in ALL_COLS]
        for pid, rec in pmap.items()))
    conn.commit()
    return pull_id


def load_pull_map(conn, pull_id):
    cols = ["player_id", "name", "age", "pos", "org", "lev"] + [COL2SQL[c] for c in ALL_COLS]
    q = "SELECT {} FROM ratings WHERE pull_id=?".format(", ".join(f'"{c}"' for c in cols))
    out = {}
    for row in conn.execute(q, (pull_id,)):
        rec = {"name": row[1], "age": row[2], "pos": row[3], "org": row[4], "lev": row[5]}
        for i, c in enumerate(ALL_COLS):
            v = row[6 + i]
            if v is not None:
                rec[c] = float(v)
        out[str(row[0])] = rec
    return out


def league_pulls(conn, league):
    return list(conn.execute(
        "SELECT pull_id, real_date, real_ts, source, n_players FROM pulls "
        "WHERE league=? ORDER BY real_date", (league,)))


def append_pull(league, raw_rows, source="live", real_ts=None, real_date=None,
                files=None, db_path=DB_PATH, translate=True):
    """Ingest one pull (raw StatsPlus rows). Same-date pull is REPLACED (one
    vintage per league+date). Used by refresh.py after each live pull; additive
    only — never touches projections. Returns pull_id or None."""
    real_ts = real_ts or datetime.datetime.now().isoformat(timespec="seconds")
    real_date = real_date or real_ts[:10]
    pmap = rows_to_map(raw_rows, translate=translate)
    if not pmap:
        return None
    conn = connect(db_path)
    try:
        old = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date=?",
                           (league, real_date)).fetchone()
        if old:
            conn.execute("DELETE FROM ratings WHERE pull_id=?", (old[0],))
            conn.execute("DELETE FROM pulls WHERE pull_id=?", (old[0],))
        return insert_pull(conn, league, real_date, real_ts, source, files or [], pmap)
    finally:
        conn.close()


# ---------------------------------------------------------------- backfill
def _slug_to_league(slug):
    for lg, sl in LEAGUES.items():
        if sl == slug:
            return lg
    return slug.upper()


def _candidates_history():
    """ingest/.cache/history/statsplus_<slug>_<stamp>.json — the immutable live
    pull archive (raw schema) + 'recovered-' vintages (sheet schema, translate
    is a no-op on those)."""
    out = []
    hist = os.path.join(INGEST, ".cache", "history")
    for path in sorted(glob.glob(os.path.join(hist, "statsplus_*_*.json"))):
        fn = os.path.basename(path)
        m = re.match(r"statsplus_([a-z0-9]+)_(recovered-)?(\d{8})(?:-(\d{4}))?\.json$", fn)
        if not m:
            continue
        slug, recovered, d, hm = m.group(1), m.group(2), m.group(3), m.group(4) or "0000"
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        ts = f"{date}T{hm[:2]}:{hm[2:]}:00"
        out.append({
            "league": _slug_to_league(slug), "date": date, "ts": ts,
            "source": "recovered" if recovered else "history",
            "files": [os.path.relpath(path, REPO)],
            "load": (lambda p=path: rows_to_map(json.load(open(p, encoding="utf-8")))),
        })
    return out


def _candidates_snapshots():
    """backtest/snapshots/<LG>/<in-game-date>/statsplus_<slug>.json (raw pull
    cache copies; real date from the manifest's snapped_at_real)."""
    out = []
    for lg in LEAGUES:
        for snapdir in sorted(glob.glob(os.path.join(HERE, "snapshots", lg, "*"))):
            raws = glob.glob(os.path.join(snapdir, "statsplus_*.json"))
            if not raws:
                continue
            path = raws[0]
            ts = None
            mpath = os.path.join(snapdir, "manifest.json")
            if os.path.exists(mpath):
                try:
                    ts = json.load(open(mpath, encoding="utf-8")).get("snapped_at_real")
                except Exception:
                    ts = None
            ts = ts or datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
            out.append({
                "league": lg, "date": ts[:10], "ts": ts[:19], "source": "snapshot",
                "files": [os.path.relpath(path, REPO)],
                "load": (lambda p=path: rows_to_map(json.load(open(p, encoding="utf-8")))),
            })
    return out


def _load_bak_pair(hit_path, pit_path):
    """Merge a hitters/pitchers .bak pair (rows already carry sheet-name rating
    columns alongside computed outputs; extra output columns are ignored)."""
    pmap = {}
    for path in (hit_path, pit_path):
        if not path:
            continue
        rows = json.load(open(path, encoding="utf-8"))
        pmap.update(rows_to_map(rows, translate=False))
    return pmap


def _candidates_baks():
    """public/data/<LG>/{hitters,pitchers}.json.bak-* — each backup's MTIME is
    the date its data went live, i.e. the ratings vintage date. One candidate
    per league+date, pairing that date's newest hitters bak with its newest
    pitchers bak. The live hitters/pitchers.json pair joins as lowest-rank
    'live-current' (it usually duplicates the newest archived pull)."""
    out = []
    for lg in LEAGUES:
        ddir = os.path.join(VIZ, "public", "data", lg)
        by_date = {}   # date -> {"hit": (mtime, path), "pit": (mtime, path)}
        pats = [("hit", "hitters.json.bak-*"), ("pit", "pitchers.json.bak-*"),
                ("hit", "hitters.json"), ("pit", "pitchers.json")]
        for kind, pat in pats:
            for path in glob.glob(os.path.join(ddir, pat)):
                mt = os.path.getmtime(path)
                date = datetime.date.fromtimestamp(mt).isoformat()
                is_live = not os.path.basename(path).count(".bak-")
                slot = by_date.setdefault(date, {"live": False})
                slot["live"] = slot["live"] or is_live
                if kind not in slot or mt > slot[kind][0]:
                    slot[kind] = (mt, path)
        for date, slot in by_date.items():
            hit = slot.get("hit", (0, None))[1]
            pit = slot.get("pit", (0, None))[1]
            mt = max(slot.get("hit", (0,))[0], slot.get("pit", (0,))[0])
            out.append({
                "league": lg, "date": date,
                "ts": datetime.datetime.fromtimestamp(mt).isoformat(timespec="seconds"),
                "source": "live-current" if slot["live"] else "bak",
                "files": [os.path.relpath(p, REPO) for p in (hit, pit) if p],
                "load": (lambda h=hit, p=pit: _load_bak_pair(h, p)),
            })
    return out


def backfill(db_path=DB_PATH, rebuild=False):
    if rebuild and os.path.exists(db_path):
        os.remove(db_path)
        for ext in ("-wal", "-shm"):
            if os.path.exists(db_path + ext):
                os.remove(db_path + ext)
    conn = connect(db_path)

    cands = _candidates_history() + _candidates_snapshots() + _candidates_baks()
    # one candidate per league+date: best source wins; ties -> latest timestamp
    best = {}
    for c in cands:
        key = (c["league"], c["date"])
        rank = (SOURCE_RANK.get(c["source"], 0), c["ts"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, c)
    chosen = sorted((c for _, c in best.values()), key=lambda c: (c["league"], c["date"]))

    ingested, skipped_dup, skipped_have = [], [], []
    prev_map_by_lg = {}
    for c in chosen:
        lg = c["league"]
        have = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date=?",
                            (lg, c["date"])).fetchone()
        if have:
            skipped_have.append(c)
            prev_map_by_lg[lg] = load_pull_map(conn, have[0])
            continue
        try:
            pmap = c["load"]()
        except Exception as e:
            print(f"  !! {lg} {c['date']} ({c['source']}): load failed — {type(e).__name__}: {e}")
            continue
        if not pmap:
            print(f"  !! {lg} {c['date']} ({c['source']}): no usable rows, skipped")
            continue
        prev = prev_map_by_lg.get(lg)
        if prev is None:
            row = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date<? "
                               "ORDER BY real_date DESC LIMIT 1", (lg, c["date"])).fetchone()
            if row:
                prev = load_pull_map(conn, row[0])
        if c["source"] in REPROCESS_SOURCES and prev and _same_ratings(prev, pmap):
            skipped_dup.append(c)
            print(f"  -- {lg} {c['date']} ({c['source']}): ratings identical to previous "
                  f"vintage (engine reprocess, not a new pull) — skipped")
            continue
        insert_pull(conn, lg, c["date"], c["ts"], c["source"], c["files"], pmap)
        prev_map_by_lg[lg] = pmap
        print(f"  ++ {lg} {c['date']} ({c['source']}): {len(pmap)} players "
              f"[{', '.join(os.path.basename(f) for f in c['files'])}]")
        ingested.append(c)
    conn.close()
    print(f"backfill: {len(ingested)} vintages ingested, {len(skipped_dup)} reprocess-duplicates "
          f"skipped, {len(skipped_have)} already in DB")
    return ingested


# ---------------------------------------------------------------- analytics
def player_deltas(conn, league, player_id):
    """Per-pull rating series for one player: [(real_date, {col: value}), ...]."""
    out = []
    for pull_id, date, _ts, _src, _n in league_pulls(conn, league):
        cols = ["name"] + [COL2SQL[c] for c in ALL_COLS]
        row = conn.execute(
            "SELECT {} FROM ratings WHERE pull_id=? AND player_id=?".format(
                ", ".join(f'"{c}"' for c in cols)),
            (pull_id, str(player_id))).fetchone()
        if row is None:
            continue
        vals = {c: float(row[1 + i]) for i, c in enumerate(ALL_COLS) if row[1 + i] is not None}
        out.append((date, vals))
    return out


def _readable(maps_newest_first, pid, field):
    """Best display value for org/lev: raw StatsPlus vintages carry NUMERIC org
    ids; prefer a non-numeric (enriched) value from the newest vintage that has
    one. Falls back to the newest value of any kind."""
    fallback = None
    for m in maps_newest_first:
        rec = m.get(pid)
        if not rec:
            continue
        v = rec.get(field)
        if v:
            if fallback is None:
                fallback = v
            if not str(v).isdigit():
                return v
    # numeric-only org id everywhere: 0 = the free-agent pool
    if field == "org" and str(fallback) == "0":
        return "FA"
    return fallback


def movers(conn, league, window=3, top=15):
    """Biggest total scouting-value change (sum of SMOOTH_COLS deltas, 20-80
    points) between the pull `window` pulls back and the latest pull.
    Returns (risers, fallers, meta); each entry:
    {id, name, pos, age, org, total, ncols, breakdown:{col: delta}}."""
    pulls = league_pulls(conn, league)
    if len(pulls) < 2:
        return [], [], {"pulls": len(pulls)}
    w = min(window, len(pulls) - 1)
    old_map = load_pull_map(conn, pulls[-1 - w][0])
    new_map = load_pull_map(conn, pulls[-1][0])
    scored = []
    for pid, nrec in new_map.items():
        orec = old_map.get(pid)
        if not orec:
            continue
        total, breakdown = 0.0, {}
        for c in SMOOTH_COLS:
            a, b = orec.get(c), nrec.get(c)
            if a is None or b is None:
                continue
            d = b - a
            if d:
                total += d
                breakdown[c] = d
        if breakdown:
            scored.append({"id": pid, "name": nrec["name"], "pos": nrec["pos"],
                           "age": nrec["age"],
                           "org": _readable((new_map, old_map), pid, "org"),
                           "total": total,
                           "ncols": len(breakdown),
                           "breakdown": dict(sorted(breakdown.items(),
                                                    key=lambda kv: -abs(kv[1]))[:6])})
    scored.sort(key=lambda x: -x["total"])
    meta = {"pulls": len(pulls), "window": w,
            "from": pulls[-1 - w][1], "to": pulls[-1][1],
            "players_changed": len(scored)}
    risers = [x for x in scored if x["total"] > 0][:top]
    fallers = [x for x in reversed(scored) if x["total"] < 0][:top]
    return risers, fallers, meta


def age_curves(conn, league):
    """Average change-by-age per rating column, from ALL consecutive pull pairs.
    A (player, col) pair counts when the player appears in both pulls with a
    known age and both values are rated (>= 20; OOTP fills absent skills with
    0). Returns ({col: {age: (mean, n)}}, meta). The mean is per PULL PAIR (not
    per year/day) — with few vintages this measures short-horizon scout churn
    more than true aging; it gets better automatically as pulls accumulate."""
    pulls = league_pulls(conn, league)
    sums = {c: {} for c in SMOOTH_COLS}
    counts = {c: {} for c in SMOOTH_COLS}
    npairs = 0
    prev = None
    gaps = []
    for i, (pull_id, date, _ts, _src, _n) in enumerate(pulls):
        cur = load_pull_map(conn, pull_id)
        if prev is not None:
            npairs += 1
            gaps.append((datetime.date.fromisoformat(date)
                         - datetime.date.fromisoformat(pulls[i - 1][1])).days)
            for pid, nrec in cur.items():
                orec = prev.get(pid)
                if not orec or orec.get("age") is None:
                    continue
                age = int(orec["age"])
                for c in SMOOTH_COLS:
                    a, b = orec.get(c), nrec.get(c)
                    if a is None or b is None or a < 20 or b < 20:
                        continue
                    sums[c][age] = sums[c].get(age, 0.0) + (b - a)
                    counts[c][age] = counts[c].get(age, 0) + 1
        prev = cur
    curves = {}
    for c in SMOOTH_COLS:
        if counts[c]:
            curves[c] = {age: (sums[c][age] / counts[c][age], counts[c][age])
                         for age in sorted(counts[c])}
    meta = {"vintages": len(pulls), "pairs": npairs,
            "mean_gap_days": (sum(gaps) / len(gaps)) if gaps else None,
            "observations": sum(n for c in counts for n in counts[c].values())}
    return curves, meta


# ---------------------------------------------------------------- report
def report(db_path=DB_PATH, leagues=None, window=3, top=10):
    conn = connect(db_path)
    for lg in (leagues or LEAGUES):
        pulls = league_pulls(conn, lg)
        print(f"\n=== {lg}: {len(pulls)} vintages ===")
        for _pid, date, _ts, src, n in pulls:
            print(f"  {date}  {src:<12} {n:>6} players")
        if len(pulls) < 2:
            print("  (need >= 2 vintages for movers/age curves)")
            continue
        risers, fallers, meta = movers(conn, lg, window=window, top=top)
        print(f"\n  Movers {meta['from']} -> {meta['to']} (last {meta['window']} pull(s); "
              f"{meta['players_changed']} players changed):")
        for label, rows in (("RISERS", risers), ("FALLERS", fallers)):
            print(f"    top {label}:")
            for x in rows:
                bd = ", ".join(f"{c} {d:+g}" for c, d in x["breakdown"].items())
                age = f"{int(x['age'])}" if x["age"] is not None else "?"
                print(f"      {x['total']:+7.1f}  {x['name']:<24} {x['pos'] or '?':<3} "
                      f"age {age:<3} {x['org'] or '?':<22} [{bd}]")
        curves, cmeta = age_curves(conn, lg)
        print(f"\n  Change-by-age curves: {cmeta['vintages']} vintages -> {cmeta['pairs']} "
              f"consecutive pull pairs, {cmeta['observations']} (player,col) observations, "
              f"mean gap {cmeta['mean_gap_days']:.1f} real days.")
        print("  CAVEAT: per-pull-pair averages over a short archive measure scout re-grade "
              "churn as much as true aging; treat as directional until many more vintages accumulate.")
        for c in ("POW P", "STU", "SPE", "CON"):
            if c not in curves:
                continue
            pts = [f"{age}:{m:+.2f}(n={n})" for age, (m, n) in curves[c].items()
                   if n >= 50 and 17 <= age <= 38]
            if pts:
                print(f"    {c:<7} " + "  ".join(pts[:12]))
    conn.close()


# ---------------------------------------------------------------- export
def _jsnum(x):
    if x is None:
        return None
    return int(x) if float(x).is_integer() else round(float(x), 2)


def export(db_path=DB_PATH, leagues=None, hist_pulls=6, mover_windows=(1, 3, 5), top=40):
    """Write public/data/<LG>/rating_trends.json — the app-facing trends file.
    Small by construction: only players with >= 1 changed rating inside the
    last `hist_pulls` vintages, only the columns that changed, values from
    those vintages only. Purely informational — projections never read it."""
    conn = connect(db_path)
    written = []
    for lg in (leagues or LEAGUES):
        pulls = league_pulls(conn, lg)
        out_path = os.path.join(VIZ, "public", "data", lg, "rating_trends.json")
        payload = {
            "v": 1, "league": lg,
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "pulls": [{"d": p[1], "s": p[3]} for p in pulls],
            "cols": ALL_COLS,
            "players": {},
            "movers": {},
            "age_curves": {},
        }
        if len(pulls) >= 2:
            win = pulls[-hist_pulls:]
            payload["window"] = [len(pulls) - len(win) + i for i in range(len(win))]
            maps = [load_pull_map(conn, p[0]) for p in win]
            latest = maps[-1]
            newest_first = list(reversed(maps))
            ids = set()
            for m in maps:
                ids.update(m)
            for pid in ids:
                series = {}
                for ci, c in enumerate(ALL_COLS):
                    vals = [m.get(pid, {}).get(c) for m in maps]
                    got = [v for v in vals if v is not None]
                    if len(got) >= 2 and max(got) - min(got) > 1e-9:
                        series[str(ci)] = [_jsnum(v) for v in vals]
                if not series:
                    continue
                meta = latest.get(pid) or next(m[pid] for m in newest_first if pid in m)
                payload["players"][pid] = {
                    "n": meta["name"], "p": meta["pos"],
                    "o": _readable(newest_first, pid, "org"),
                    "a": _jsnum(meta["age"]),
                    "l": _readable(newest_first, pid, "lev"), "s": series,
                }
            for w in mover_windows:
                if w > len(pulls) - 1:
                    continue
                risers, fallers, meta = movers(conn, lg, window=w, top=top)
                payload["movers"][str(w)] = {
                    "from": meta["from"], "to": meta["to"],
                    "changed": meta["players_changed"],
                    "risers": [{"id": x["id"], "n": x["name"], "p": x["pos"],
                                "a": _jsnum(x["age"]), "o": x["org"],
                                "t": round(x["total"], 1), "c": x["ncols"],
                                "d": {c: _jsnum(d) for c, d in x["breakdown"].items()}}
                               for x in risers],
                    "fallers": [{"id": x["id"], "n": x["name"], "p": x["pos"],
                                 "a": _jsnum(x["age"]), "o": x["org"],
                                 "t": round(x["total"], 1), "c": x["ncols"],
                                 "d": {c: _jsnum(d) for c, d in x["breakdown"].items()}}
                                for x in fallers],
                }
            curves, cmeta = age_curves(conn, lg)
            payload["age_curves"] = {
                "vintages": cmeta["vintages"], "pairs": cmeta["pairs"],
                "mean_gap_days": _jsnum(cmeta["mean_gap_days"]),
                "note": (f"Mean rating change per consecutive pull pair, by age at the earlier "
                         f"pull. Built from {cmeta['vintages']} vintages ({cmeta['pairs']} pairs, "
                         f"mean gap {cmeta['mean_gap_days']:.0f} real days). With this few "
                         f"vintages it reflects scout re-grades as much as true aging — it "
                         f"sharpens automatically as pulls accumulate."),
                "cols": {c: {str(age): [round(m, 3), n] for age, (m, n) in ages.items()}
                         for c, ages in curves.items()},
            }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        size = os.path.getsize(out_path)
        print(f"export: {lg} -> {os.path.relpath(out_path, REPO)} "
              f"({size / 1e6:.2f} MB, {len(payload['players'])} players with changes, "
              f"{len(pulls)} vintages)")
        written.append(out_path)
    conn.close()
    return written


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", help="ingest every recoverable vintage")
    ap.add_argument("--rebuild", action="store_true", help="with --backfill: drop the DB first")
    ap.add_argument("--append", metavar="CACHE_JSON", help="ingest one raw pull cache file")
    ap.add_argument("--league", help="league id (TGS/BLM); required with --append")
    ap.add_argument("--date", help="vintage date YYYY-MM-DD for --append (default today)")
    ap.add_argument("--source", default="live", help="source label for --append")
    ap.add_argument("--report", action="store_true", help="print vintages, movers, age curves")
    ap.add_argument("--export", action="store_true", help="write public/data/<LG>/rating_trends.json")
    ap.add_argument("--window", type=int, default=3, help="mover window in pulls (report)")
    ap.add_argument("--top", type=int, default=10, help="movers shown per direction (report)")
    ap.add_argument("--db", default=DB_PATH, help="database path")
    args = ap.parse_args()

    did = False
    if args.backfill:
        backfill(db_path=args.db, rebuild=args.rebuild)
        did = True
    if args.append:
        if not args.league:
            ap.error("--append requires --league")
        rows = json.load(open(args.append, encoding="utf-8"))
        pid = append_pull(args.league, rows, source=args.source, real_date=args.date,
                          files=[args.append], db_path=args.db)
        print(f"append: {args.league} {args.date or 'today'} -> pull_id {pid}")
        did = True
    lgs = [args.league] if args.league and not args.append else None
    if args.report:
        report(db_path=args.db, leagues=lgs, window=args.window, top=args.top)
        did = True
    if args.export:
        export(db_path=args.db, leagues=lgs)
        did = True
    if not did:
        ap.print_help()


if __name__ == "__main__":
    main()
