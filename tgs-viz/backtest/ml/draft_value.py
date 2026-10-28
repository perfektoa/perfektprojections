"""
draft_value.py - DEV-measured draft value: the wins a prospect gives over his
control years, from his card today.

User, 2026-10-27: "i dont understand how we can do so many seasons of
projecting where draft picks will eventually be and not like have something
worth using". Draft FV ranked on a blend with picked weights (age percentile
30 / ceiling 60 / median peak 10). This measures one number instead.

Target (ctrl): for a DEV player-dump at ages 16-26, the sum of (now_WAA - bar)
over his first CTRL_SEASONS (6) seasons above the bar, whenever they come: wins
above a replacement-level player over the years a team controls him after the
draft (the minors years, then six service years, at any age). The bar is the
replacement level of his role group (hitter, SP, RP) that season, measured in
the DEV dump: the best player of the group not on an MLB roster (role_bars). A
player who never reaches it gives 0. Known when he has the six seasons or is retired (or CTRL_WINDOW seasons
passed, which no career outlives); else NaN (censored) and the row does not
train. A season he is in the dumps but not priced counts as below the bar.

Rows (ROWS = 'drafted', user 2026-10-27): every player who ever appeared as an
amateur in a DEV dump (he came through a draft class), all his dumps at 16-26
with a known ctrl. A player never seen as an amateur was made with the league
and is left out. 'amateur' keeps only the amateur dumps; 'all' takes every DEV
row at 16-26 with the amateur flag as a feature.

Models (one set per basis league; XGBoost on the GPU, one CPU thread, the
peak models' tuned settings):
  ctrl_mean   squared loss: the expected wins (what you draft on)
  ctrl_q90    quantile 0.90: the upside
Features: the schema's usable_for_scoring columns + 'amateur' (as peak.py).

Check (fit): fit on time_split 'train', then on the 'test' amateurs at the
draft ages (17-24) compare the model's order with the ceiling, Pot and now
orders: rank correlation with the realized ctrl, and "draft 30": the mean
realized ctrl of the top 30 amateurs per dump year under each order. Then fit
on every row (final) and save models/<basis>/draft_<role>_*.pkl.

Score: the league's scoring rows at 16-26 (score_<LG>_<role>.pkl, the same
rows score.py uses) -> public/data/<LG>/draft_value.json
{players: {pid: {ctrl, q90, now, age, r}}}. The app shows ctrl on the draft
board as Ctrl wins and ranks the board on it.

  py -3.14 draft_value.py --basis BLM build      target tables (data/ctrl_<basis>_<role>.pkl)
  py -3.14 draft_value.py --basis BLM fit        check + final models
  py -3.14 draft_value.py --basis BLM train      build + fit (the Add Dev Seasons / retrain step)
  py -3.14 draft_value.py --basis BLM check-oof  5-fold check over every class (report/<basis>/draft_value_oof.json)
  py -3.14 draft_value.py --basis BLM score [--league BLM] [--write]
  py -3.14 draft_value.py --basis BLM all [--league BLM] [--write]

score.py runs the scoring itself after every ML scoring (a pull, a rescore, a
retrain), so the app file follows the pull without a step of its own.
"""
import argparse
import datetime
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import predict as PR  # noqa: E402
import xgb_models as XM  # noqa: E402

CTRL_SEASONS = 6
# No year cap (user, 2026-10-27: "why stop at 14"): his first six MLB-level seasons count
# whenever they come. The loop still needs a bound: 25 seasons after the youngest card
# (16) reaches age 41, past any DEV career, so it caps nothing in practice.
CTRL_WINDOW = 25
# The bar is the REPLACEMENT level of his role group that season, measured in the
# DEV dump itself: among every priced player of the group (hitters; SP; RP and CL)
# in that dump, the value at the rank equal to the number of them on an MLB roster,
# i.e. the best player who is NOT on an MLB roster. One flat bar of -1 WAA for
# everyone over-counted relievers (user, 2026-10-27: "we always over draft
# pitchers"): a reliever's WAA covers 60-70 innings, so half of DEV's MLB relievers
# sit above -1 while starters and hitters have to climb far further. The app's
# market offsets (leagueCalib.js replacementMarket) could not be used as the bar:
# the DEV price files keep ONE number per pitcher, the better of his starter and
# reliever lines, so a bad starter's number is his reliever value and a starter bar
# over-credits it. A bar measured on the same numbers cancels that. A season counts
# when he is above his group's bar; the credit is the wins above it.
PITCHER_GROUP = {"SP": "SP", "RP": "RP", "CL": "RP"}    # the P table; the H table is one group, H
MLB_LEV = "MLB"
BAR_WORDS = ("per DEV season and role group (hitter / SP / RP), the value of the best player of the group "
             "not on an MLB roster (role_bars)")
TRAIN_AGES = (16, 26)
DRAFT_AGES = (17, 24)
DRAFT_PER_YEAR = 30
TARGETS = {"ctrl_mean": ("squared_error", None), "ctrl_q90": ("quantile", 0.90)}
VAL_SALT = "draft_value"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def r3(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 3)


# ---------------------------------------------------------------- target
def role_groups(df, role):
    """Each row's group: 'H' for the H table; SP / RP (RP and CL; anything
    else reads RP) for the P table."""
    if role == "H":
        return np.full(len(df), "H", dtype=object)
    pos = df["pos"].astype(str).str.strip().str.upper().to_numpy()
    return np.array([PITCHER_GROUP.get(p, "RP") for p in pos], dtype=object)


def role_bars(df, role, log_out=None):
    """Each row's replacement bar (WAA): per dump year and group, the value at
    the rank equal to the number of the group's players on an MLB roster that
    year (the best player not on an MLB roster). NaN where a year has no
    MLB rows of the group (then no season of that year counts)."""
    group = role_groups(df, role)
    year = df["dump_year"].to_numpy(np.int64)
    now = df["now_waa"].to_numpy(np.float64)
    mlb = df["lev_raw"].astype(str).str.strip().str.upper().eq(MLB_LEV).to_numpy()
    bars = np.full(len(df), np.nan, np.float64)
    table = {}
    for g in np.unique(group):
        gm = group == g
        for y in np.unique(year[gm]):
            m = gm & (year == y) & np.isfinite(now)
            n_mlb = int((m & mlb).sum())
            vals = now[m]
            if n_mlb == 0 or len(vals) <= n_mlb:
                continue
            bar = float(np.partition(vals, len(vals) - n_mlb)[len(vals) - n_mlb])   # n_mlb-th largest
            bars[gm & (year == y)] = bar
            table[(g, int(y))] = (bar, n_mlb)
    if log_out is not None:
        for g in sorted({k[0] for k in table}):
            bs = np.array([v[0] for k, v in table.items() if k[0] == g])
            ns = np.array([v[1] for k, v in table.items() if k[0] == g])
            log_out(f"    bar {g}: median {np.median(bs):.2f} WAA (p10 {np.percentile(bs, 10):.2f}, "
                    f"p90 {np.percentile(bs, 90):.2f}) over {len(bs)} seasons; MLB-rostered per season "
                    f"median {int(np.median(ns))}")
    return bars


def ctrl_target(df, role, log_out=None):
    """ctrl and ctrl_known for every row of one role table (df index order).
    Vectorized: a sorted key (pid, dump_year) of the priced rows, then one
    searchsorted per season ahead. Each later season is judged against the
    bar of the group he was in THAT season (a pitcher may move SP <-> RP)."""
    pid = df["pid"].to_numpy(np.int64)
    year = df["dump_year"].to_numpy(np.int64)
    now = df["now_waa"].to_numpy(np.float64)
    bars = role_bars(df, role, log_out)
    last_dump = int(year.max())
    key = pid * 10_000 + year
    priced = np.isfinite(now)
    k_sorted = key[priced]
    order = np.argsort(k_sorted, kind="stable")
    k_sorted, w_sorted, b_sorted = k_sorted[order], now[priced][order], bars[priced][order]
    n_level = np.zeros(len(df), np.int32)
    ctrl = np.zeros(len(df), np.float64)
    for k in range(1, CTRL_WINDOW + 1):
        want = key + k
        j = np.searchsorted(k_sorted, want)
        j = np.minimum(j, len(k_sorted) - 1)
        hit = k_sorted[j] == want
        wk = np.where(hit, w_sorted[j], np.nan)
        bk = np.where(hit, b_sorted[j], np.nan)
        level = np.isfinite(wk) & (wk >= bk)
        take = level & (n_level < CTRL_SEASONS)
        ctrl += np.where(take, wk - bk, 0.0)      # wins above his role's bar that season
        n_level += take.astype(np.int32)
    retired = df["retired"].to_numpy() == 1 if "retired" in df.columns else np.zeros(len(df), bool)
    known = (n_level >= CTRL_SEASONS) | retired | (year + CTRL_WINDOW <= last_dump)
    return ctrl.astype(np.float32), known, n_level


def target_path(basis, role):
    return C.table_path(f"ctrl_{basis}_{role}")


def cmd_build(args):
    for role in C.ROLES:
        t0 = time.time()
        df = C.load_table(C.dev_table(role))
        log(f"[{role}] {len(df):,} rows loaded ({time.time() - t0:.0f}s); columns {len(df.columns)}")
        ctrl, known, n_level = ctrl_target(df, role, log)
        out = pd.DataFrame({"pid": df["pid"].to_numpy(), "dump_year": df["dump_year"].to_numpy(),
                            "ctrl": np.where(known, ctrl, np.nan).astype(np.float32),
                            "ctrl_known": known.astype(np.int8), "ctrl_seasons": n_level})
        young = (df["age"] >= TRAIN_AGES[0]) & (df["age"] <= TRAIN_AGES[1])
        ama = C.amateur_flag(df) == 1
        m = young.to_numpy() & known
        log(f"[{role}] ages 16-26: {int(young.sum()):,} rows, ctrl known {int(m.sum()):,} "
            f"({m.sum() / max(young.sum(), 1):.0%}); amateurs known {int((m & ama).sum()):,}; "
            f"mean ctrl (known, 16-26) {float(np.nanmean(out['ctrl'].to_numpy()[m])):.2f}, "
            f"share > 0 {float(np.mean(out['ctrl'].to_numpy()[m] > 0)):.1%}, "
            f"amateurs 17-24 mean {float(np.nanmean(out['ctrl'].to_numpy()[m & ama & (df['age'] >= 17).to_numpy() & (df['age'] <= 24).to_numpy()])):.2f}")
        C.save_table(out, target_path(C.BASIS, role))
        log(f"[{role}] wrote {target_path(C.BASIS, role)} ({time.time() - t0:.0f}s)")
        del df


# ---------------------------------------------------------------- fit
def settings(role):
    for d in (C.MODELS_DIR, C.MODELS_ROOT):
        p = os.path.join(d, "peak_settings.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)[role]
    raise SystemExit("no peak_settings.json (run peak.py tune first)")


def features_of(role):
    schema = C.load_schema()
    feats = C.usable_features(role, schema) + list(C.MODEL_EXTRA_FEATURES)
    cats = {f: C.CATEGORICAL[f] for f in feats if f in C.CATEGORICAL}
    return feats, cats


# Training rows (user, 2026-10-27: "every single player of every single draft
# gets studied ... if they were never in a draft ... that would mean they were
# already premade into the game"):
#   'drafted'  every player who was ever an amateur in a DEV dump (he came through a
#              draft class), every one of his dumps at 16-26: his amateur cards and his
#              later minors / majors cards. A player never seen as an amateur was made
#              with the league (the 2025 dump) and is left out.
#   'amateur'  only the amateur dumps of those players
#   'all'      every DEV row at 16-26, with the amateur flag as a feature
ROWS = "drafted"
ROWS_WORDS = {"drafted": "every player who came through a DEV draft class, all his seasons at 16-26",
              "amateur": "every amateur of every DEV class", "all": "every DEV player at 16-26"}


def load_rows(role, rows=None):
    """Role rows at 16-26 with a known ctrl, the ctrl columns joined, under the
    ROWS rule (see above)."""
    rows = rows or ROWS
    df = C.load_table(C.dev_table(role))
    tg = C.load_table(target_path(C.BASIS, role))
    if len(tg) != len(df):
        raise SystemExit(f"{target_path(C.BASIS, role)} has {len(tg):,} rows, the table {len(df):,}: rerun build")
    for c in ("ctrl", "ctrl_known", "ctrl_seasons"):
        df[c] = tg[c].to_numpy()
    m = (df["age"] >= TRAIN_AGES[0]) & (df["age"] <= TRAIN_AGES[1]) & (df["ctrl_known"] == 1)
    ama = C.amateur_flag(df) == 1
    if rows == "amateur":
        m &= ama
    elif rows == "drafted":
        came_through = df["pid"].isin(df.loc[ama, "pid"].unique()).to_numpy()
        log(f"[{role}] players ever seen as an amateur: {int(df.loc[came_through, 'pid'].nunique()):,} of "
            f"{int(df['pid'].nunique()):,}; their rows at 16-26 with a known ctrl: {int((m & came_through).sum()):,} "
            f"of {int(m.sum()):,}")
        m &= came_through
    g = df.loc[m].reset_index(drop=True)
    del df, tg
    C.add_model_extras(g, C.MODEL_EXTRA_FEATURES)
    return g


def val_mask(pids, share):
    import peak as PK
    k = int(round(1.0 / share))
    return PK.hash_bucket(pids, VAL_SALT, k) == 0


def fit_models(g, feats, cats, st, log_prefix=""):
    X = PR.feature_frame(g, feats, cats)
    y = g["ctrl"].to_numpy(np.float32)
    val = val_mask(g["pid"].to_numpy(), st["val_share"])
    hp = dict(st["quantile"], max_iter=st["max_iter"], max_bins=st["max_bins"],
              n_iter_no_change=st["n_iter_no_change"])
    out = {}
    for name, (loss, q) in TARGETS.items():
        t0 = time.time()
        m = XM.regressor(hp, loss, q)
        XM.fit(m, X[~val], y[~val], X[val], y[val])
        pv = m.predict(X[val])
        if loss == "quantile":
            r = y[val] - pv
            vloss = float(np.mean(np.maximum(q * r, (q - 1) * r)))
        else:
            vloss = float(np.sqrt(np.mean((y[val] - pv) ** 2)))
        log(f"{log_prefix}{name}: train {int((~val).sum()):,} val {int(val.sum()):,} iters {XM.n_iter(m)} "
            f"val {'pinball' if q else 'rmse'} {vloss:.4f} ({time.time() - t0:.0f}s)")
        out[name] = {"model": m, "n_train": int((~val).sum()), "n_iter": XM.n_iter(m), "val_loss": vloss}
    return out


def predict_models(models, df, feats, cats):
    X = PR.feature_frame(df, feats, cats)
    p = {name: f["model"].predict(X).astype(np.float32) for name, f in models.items()}
    p["ctrl_mean"] = np.maximum(p["ctrl_mean"], 0.0)
    p["ctrl_q90"] = np.maximum(p["ctrl_q90"], p["ctrl_mean"])
    return p


def spearman(a, b):
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


DRAFT_TOPS = (30, 100, 300)


def draft_check(te, pred):
    """The draft question on held-out amateurs at 17-24: how much realized
    ctrl do the top 30 / 100 / 300 per dump year earn under each order (the
    model, Pot, now WAA, the ceiling when DEV priced one for amateurs), with
    the hindsight best for scale; plus the rank correlation over every row."""
    ama = (te["amateur"] == 1) & (te["age"] >= DRAFT_AGES[0]) & (te["age"] <= DRAFT_AGES[1])
    sel = ama.to_numpy()
    d = te.loc[ama, ["pid", "dump_year", "age", "ctrl", "pot", "now_waa"]].copy()
    d["model"] = pred["ctrl_mean"][sel]
    orders = {"model": d["model"], "pot": d["pot"], "now": d["now_waa"]}
    if "ctrl_q90" in pred:
        d["q90"] = pred["ctrl_q90"][sel]
        orders["q90"] = d["q90"]
    rep = {"rows": int(len(d)), "years": int(d["dump_year"].nunique()),
           "mean_ctrl": r3(d["ctrl"].mean()), "share_ctrl_gt0": r3((d["ctrl"] > 0).mean()),
           "rmse_model": r3(np.sqrt(np.mean((d["ctrl"] - d["model"]) ** 2))),
           "rmse_zero": r3(np.sqrt(np.mean(d["ctrl"] ** 2)))}
    if "ceil" in te.columns:
        c = te.loc[ama, "ceil"].to_numpy(dtype=np.float64)
        if np.isfinite(c).mean() > 0.5:
            d["ceil"] = c
            orders["ceiling"] = d["ceil"]
        else:
            rep["ceiling"] = f"not compared: DEV priced a ceiling for {np.isfinite(c).mean():.0%} of these rows"
    rep["spearman"] = {k: r3(spearman(v.to_numpy(), d["ctrl"].to_numpy())) for k, v in orders.items()}
    rep["draft"] = {}
    groups = list(d.groupby("dump_year"))
    for n in DRAFT_TOPS:
        row = {}
        for k, v in orders.items():
            dd = d.assign(_o=v.to_numpy())
            got = [float(grp.sort_values("_o", ascending=False).head(n)["ctrl"].mean())
                   for _, grp in dd.groupby("dump_year")]
            row[k] = r3(np.mean(got))
        row["hindsight"] = r3(np.mean([float(grp.sort_values("ctrl", ascending=False).head(n)["ctrl"].mean())
                                      for _, grp in groups]))
        rep["draft"][f"top{n}"] = row
    return rep


def cmd_check_oof(args):
    """5-fold out-of-fold check of ctrl_mean (fold = player): every DEV row at
    16-26 is predicted by a model that never saw the player; the draft check
    then covers every amateur at 17-24 in every class."""
    report = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "basis": C.BASIS,
              "target": {"ctrl_seasons": CTRL_SEASONS, "ctrl_window": CTRL_WINDOW, "bar": BAR_WORDS},
              "folds": 5, "roles": {}}
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    for role in C.ROLES:
        t0 = time.time()
        g = load_rows(role)
        feats, cats = features_of(role)
        st = settings(role)
        X = PR.feature_frame(g, feats, cats)
        y = g["ctrl"].to_numpy(np.float32)
        folds = g["fold"].to_numpy()
        val = val_mask(g["pid"].to_numpy(), st["val_share"])
        hp = dict(st["quantile"], max_iter=st["max_iter"], max_bins=st["max_bins"],
                  n_iter_no_change=st["n_iter_no_change"])
        pred = np.full(len(g), np.nan, np.float32)
        log(f"[{role}] oof: {len(g):,} rows, {len(feats)} features ({time.time() - t0:.0f}s)")
        for f in range(5):
            t1 = time.time()
            tr = folds != f
            m = XM.regressor(hp, "squared_error")
            XM.fit(m, X[tr & ~val], y[tr & ~val], X[tr & val], y[tr & val])
            pred[~tr] = np.maximum(m.predict(X[~tr]), 0.0)
            log(f"[{role}] fold {f}: fit {int((tr & ~val).sum()):,} predicted {int((~tr).sum()):,} "
                f"iters {XM.n_iter(m)} ({time.time() - t1:.0f}s)")
        chk = draft_check(g, {"ctrl_mean": pred})
        log(f"[{role}] oof draft check: {json.dumps(chk)}")
        report["roles"][role] = chk
        del g, X
    with open(os.path.join(C.REPORT_DIR, "draft_value_oof.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    log(f"wrote {C.REPORT_DIR}/draft_value_oof.json")


def cmd_fit(args):
    report = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "basis": C.BASIS,
              "target": {"ctrl_seasons": CTRL_SEASONS, "ctrl_window": CTRL_WINDOW, "bar": BAR_WORDS},
              "roles": {}}
    manifest = {"generated": report["generated"], "basis": C.BASIS, "xgboost": XM.version(),
                "backend": list(XM.backend()), "targets": list(TARGETS), "rows": ROWS, "roles": {}}
    report["rows"] = ROWS
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    for role in C.ROLES:
        t0 = time.time()
        g = load_rows(role)
        feats, cats = features_of(role)
        st = settings(role)
        log(f"[{role}] {len(g):,} training rows, {len(feats)} features ({time.time() - t0:.0f}s)")
        tr = (g["time_split"] == "train").to_numpy()
        te = g.loc[~tr].reset_index(drop=True)
        log(f"[{role}] check: fit on {int(tr.sum()):,} (time_split train), test {len(te):,}")
        models = fit_models(g.loc[tr].reset_index(drop=True), feats, cats, st, f"[{role}] check ")
        chk = draft_check(te, predict_models(models, te, feats, cats))
        log(f"[{role}] draft check: {json.dumps(chk)}")
        log(f"[{role}] final: fit on every row")
        models = fit_models(g, feats, cats, st, f"[{role}] final ")
        for name, f in models.items():
            with open(os.path.join(C.MODELS_DIR, f"draft_{role}_{name}.pkl"), "wb") as fh:
                pickle.dump(f["model"], fh)
        manifest["roles"][role] = {"features": feats, "categorical": cats, "n_rows": int(len(g)),
                                   "fits": {n: {k: v for k, v in f.items() if k != "model"} for n, f in models.items()}}
        report["roles"][role] = {"check": chk, "n_rows": int(len(g)),
                                 "fits": manifest["roles"][role]["fits"]}
        del g, te
    with open(os.path.join(C.MODELS_DIR, "draft_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    with open(os.path.join(C.REPORT_DIR, "draft_value.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    log(f"wrote {C.MODELS_DIR}/draft_manifest.json and {C.REPORT_DIR}/draft_value.json")


# ---------------------------------------------------------------- score
def load_models():
    with open(os.path.join(C.MODELS_DIR, "draft_manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    models = {}
    for role in C.ROLES:
        models[role] = {}
        for name in manifest["targets"]:
            with open(os.path.join(C.MODELS_DIR, f"draft_{role}_{name}.pkl"), "rb") as fh:
                models[role][name] = {"model": pickle.load(fh)}
    return manifest, models


def models_ready(basis=None):
    """True when the basis has saved draft value models (draft_manifest.json)."""
    if basis is not None:
        C.use_basis(basis)
    return os.path.exists(os.path.join(C.MODELS_DIR, "draft_manifest.json"))


def cmd_score(args):
    score(args.league or C.BASIS, args.write, C.BASIS)


def score(lg, write, basis=None):
    """Score one league's rows with the basis' draft models and write
    public/data/<LG>/draft_value.json (write=True). score.py calls this after
    every ML scoring, so a pull or rescore carries Ctrl wins (user, 2026-10-27)."""
    C.use_basis(basis or C.BASIS or C.league_basis(lg))
    manifest, models = load_models()
    rep_path = os.path.join(C.REPORT_DIR, "draft_value.json")
    report = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    schema = C.load_schema()
    note = (schema.get("scoring") or {}).get(lg) or {}
    players, counts = {}, {}
    for role in C.ROLES:
        sp = C.table_path(f"score_{lg}_{role}")
        if not os.path.exists(sp):
            raise SystemExit(f"no {sp}; run: py -3.14 tgs-viz/backtest/ml/dataset.py --basis {lg} --score-only --write")
        sc = C.load_table(sp)
        keep = (sc["age"] >= TRAIN_AGES[0]) & (sc["age"] <= TRAIN_AGES[1])
        sub = sc.loc[keep].reset_index(drop=True)
        mr = manifest["roles"][role]
        p = predict_models(models[role], sub, mr["features"], mr["categorical"])
        n = 0
        for i in range(len(sub)):
            pid = str(int(sub["pid"].iloc[i]))
            if pid in players:
                continue
            players[pid] = {"r": role, "age": int(sub["age"].iloc[i]), "now": r3(sub["now_waa"].iloc[i]),
                            "ctrl": r3(p["ctrl_mean"][i]), "q90": r3(p["ctrl_q90"][i])}
            n += 1
        counts[role] = {"rows": int(len(sc)), "scored": n}
        log(f"[{role}] scored {n:,} of {len(sc):,} rows (ages 16-26)")
    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "league": lg, "basis": C.BASIS,
        "pull": note.get("to_pull"), "pull_date": note.get("to_date") or note.get("to_pull_date"),
        "definition": {
            "ctrl": f"expected wins above replacement over his first {CTRL_SEASONS} seasons above it, whenever "
                    f"they come, from his card today; replacement = the best hitter / starter / reliever not on "
                    f"an MLB roster that season, measured in the DEV league; learned from every DEV player who "
                    f"came through a draft class, scored on this league's rows",
            "q90": "the 90th percentile of the same (upside); never below ctrl",
            "now": "his current WAA the models start from (neutral park)",
        },
        "model": {"trained_on": f"DEV league, {(schema.get('source') or {}).get('dumps', '?')} dumps; rows: "
                               + ROWS_WORDS.get(manifest.get("rows", ROWS), manifest.get("rows", ROWS)),
                  "rows": manifest.get("rows", ROWS), "n_rows": {r: manifest["roles"][r]["n_rows"] for r in C.ROLES},
                  "fit_date": manifest.get("generated"), "xgboost": manifest.get("xgboost"),
                  "check": {r: (report.get("roles", {}).get(r) or {}).get("check") for r in C.ROLES}},
        "counts": counts,
        "players": players,
    }
    path = os.path.join(C.APP_DATA, lg, "draft_value.json")
    if not write:
        log(f"(dry run) {len(players):,} players scored; pass --write to write {path}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    log(f"wrote {path} ({len(players):,} players)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", required=True, help="TGS or BLM: the DEV tables priced with that calibration")
    ap.add_argument("cmd", choices=["build", "fit", "train", "check-oof", "score", "all"])
    ap.add_argument("--league", help="league to score (default: the basis)")
    ap.add_argument("--write", action="store_true", help="score: write public/data/<LG>/draft_value.json")
    args = ap.parse_args(argv)
    C.use_basis(args.basis)
    log(f"draft_value {args.cmd} basis {C.BASIS} backend {XM.backend()}")
    if args.cmd in ("build", "train", "all"):
        cmd_build(args)
    if args.cmd in ("fit", "train", "all"):
        cmd_fit(args)
    if args.cmd == "check-oof":
        cmd_check_oof(args)
    if args.cmd in ("score", "all"):
        cmd_score(args)


if __name__ == "__main__":
    main()
