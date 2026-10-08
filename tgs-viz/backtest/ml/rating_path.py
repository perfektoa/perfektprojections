"""
rating_path.py - year-by-year projections of each rating (user, 2026-10-08:
"along with what we project the waa to be what we also project each
individual rating to be ... and our expected growth rates").

What it projects, for every player 16-39, each year from now until age 40:
  hitters   BABIP, Gap, Power, Eye, Avoid K (the mean of the vR and vL
            rating), Speed, and the fielding of his position group: infield
            range / error / arm / turn DP, outfield range / error / arm,
            catcher blocking / framing / arm
  pitchers  Stuff, HR allowed, pBABIP, Control (vR / vL mean), Stamina, Hold
No age is fixed (user: "why specify any age at all"): the path shows where
each rating rises, holds and falls. The inputs are the player's ratings now,
his potentials and his own movement over the last year, each rating's and each
potential's (user: "why not predictive based on ratings movement"; potential
movement added the same day), so a fall-off shows as the path
turning down, not as a separate yes / no.

How, in two parts (DEV league, where every player's true ratings are known
at every age; XGBoost on the GPU, xgb_models.py):
  to age 24   one model per rating and quantile learns "this rating k years
              from now minus now" (k is an input, so one model covers every
              horizon). BABIP / Gap / Power / Eye / Avoid K / Stuff / HR
              allowed / pBABIP / Control / Stamina get a 25th, 50th and 75th
              percentile; Speed, fielding and Hold the 50th only (they barely
              move: DEV, measured 2026-10-08).
  after 24    the path steps one year at a time with an aging model (one per
              rating, the mean one-year change) trained on every player present
              in two seasons in a row, from his ratings, potentials, age and
              position. Why (measured 2026-10-08): of a DEV cohort first seen at
              18, 95% are still in the league at 24, then hitters 88% / 73% /
              53% / 33% at 25 / 26 / 27 / 28 (pitchers 92 / 88 / 65 / 36%), and
              the ones left are the ones who kept improving. From 26 the cohort's
              mean Gap still "rises" +0.9, +1.2, +1.9 a year while the same
              players present in both seasons move -0.1, -0.3, -0.3; pitchers'
              control rises 8 points 26 -> 30 from who is left, while players in
              both seasons hold it flat and lose 2 Stuff per 3 years from 30,
              4.3 from 33. A direct jump past 24 learns from the survivors;
              stepping one season at a time keeps the retirements out. The
              range after 24 widens from the last direct range by each step's
              typical miss (half the 25th-75th spread of the aging model's
              one-year errors, by age band), as a random walk.
The path is conditional on the player still being in the league, the same
rule as the WAA path models.

The ratings models read no WAA, so one set serves every league (TGS, BLM and
any exported league): nothing here is priced, nothing is basis-specific.

Cross-check (user: "it would help me see ok this ML is full of shit or not"):
the 50th-percentile ratings line of each future year is priced with the
league's own engine (the same pass agecurve_fit uses: neutral park, the
league's calibration) and written next to the path as a WAA change from
today. The app shows it beside the ML WAA path; a large gap means the WAA
model and the ratings it implies disagree for that player. Pricing a median
ratings line is not the median WAA (the engine is not linear), so read it as
a smell test.

Same-person rules: a DEV pair needs the same name and an age step within one
year of k; a league's earlier pull is dev_signals.choose_clean_pulls, its
movement is blanked for a reused ID (dev_signals.same_person) and for the
card-replaced failsafe (dev_signals.replaced_cards).

    py -3.14 tgs-viz/backtest/ml/rating_path.py build
    py -3.14 tgs-viz/backtest/ml/rating_path.py train [--quick]
    py -3.14 tgs-viz/backtest/ml/rating_path.py score --league TGS [--write]

Outputs:
  .dev_cache/ml/data/ratings_dev.pkl         DEV rows, one per player-year
  .dev_cache/ml/models/ratings/*.pkl         the models + manifest.json
  .dev_cache/ml/report/ratings/validation.json
  public/data/<LG>/rating_paths/index.json   + b00.json .. b63.json (64
                                             buckets by player id; the app
                                             loads one bucket per player panel)
"""
import argparse
import csv
import datetime
import glob
import gzip
import json
import os
import re
import sqlite3
import sys
import time

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")      # the user keeps CPU load light: one thread

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C                                         # noqa: E402
import xgb_models as XM                                    # noqa: E402

sys.path.insert(0, C.BT)
import dev_signals as DSIG                                 # noqa: E402

ENGINE = os.path.join(C.VIZ, "engine")

# ---------------------------------------------------------------- what is projected
# (name, vintage columns: two = the vR / vL pair, projected as their mean, potential column or None)
SPLIT = {
    "H": [("babip", ("c_BA_vR", "c_BA_vL"), "c_HT_P"), ("gap", ("c_GAP_vR", "c_GAP_vL"), "c_GAP_P"),
          ("pow", ("c_POW_vR", "c_POW_vL"), "c_POW_P"), ("eye", ("c_EYE_vR", "c_EYE_vL"), "c_EYE_P"),
          ("avk", ("c_K_vR", "c_K_vL"), "c_K_P")],
    "P": [("stu", ("c_STU_vR", "c_STU_vL"), "c_STU_P"), ("hrr", ("c_HRR_vR", "c_HRR_vL"), "c_HRR_P"),
          ("pbabip", ("c_PBABIP_vR", "c_PBABIP_vL"), "c_PBABIP_P"),
          ("con", ("c_CON_vR", "c_CON_vL"), "c_CON_P")],
}
SINGLE = {
    "H": [("speed", "c_SPE"), ("ifr", "c_IF_RNG"), ("ife", "c_IF_ERR"), ("ifa", "c_IF_ARM"), ("tdp", "c_TDP"),
          ("ofr", "c_OF_RNG"), ("ofe", "c_OF_ERR"), ("ofa", "c_OF_ARM"),
          ("cblk", "c_C_ABI"), ("cfrm", "c_C_FRM"), ("carm", "c_C_ARM")],
    "P": [("stm", "c_STM"), ("hold", "c_HLD")],
}
# read as inputs only (not projected)
EXTRA_IN = {"H": [("sr", "c_SR"), ("ste", "c_STE"), ("run", "c_RUN")], "P": []}
PITCHES = ["FB", "CH", "CB", "SL", "SI", "SP", "CT", "FO", "CC", "SC", "KC", "KN"]
RANGED = {"babip", "gap", "pow", "eye", "avk", "stu", "hrr", "pbabip", "con", "stm"}
QUANTS = (0.25, 0.5, 0.75)
LABELS = {"babip": "BABIP", "gap": "Gap", "pow": "Power", "eye": "Eye", "avk": "Avoid K", "speed": "Speed",
          "ifr": "IF range", "ife": "IF error", "ifa": "IF arm", "tdp": "Turn DP", "ofr": "OF range",
          "ofe": "OF error", "ofa": "OF arm", "cblk": "C blocking", "cfrm": "C framing", "carm": "C arm",
          "stu": "Stuff", "hrr": "HR allowed", "pbabip": "pBABIP", "con": "Control", "stm": "Stamina",
          "hold": "Hold"}
# fielding shown for a hitter's position group (all are projected; the app shows his group's)
POS_GROUP = {"C": "C", "1B": "IF", "2B": "IF", "3B": "IF", "SS": "IF", "LF": "OF", "CF": "OF", "RF": "OF"}
GROUP_FIELDING = {"IF": ["ifr", "ife", "ifa", "tdp"], "OF": ["ofr", "ofe", "ofa"], "C": ["cblk", "cfrm", "carm"]}

MAX_AGE = 40              # the path runs to this age (DEV thins out beyond it)
SCALE_FLOOR = 20.0        # the bottom of the 20-80 display scale
POT_RESET_AGE = 30        # OOTP sets every potential to the current rating from this age (DEV, TGS, BLM)
DIRECT_MAX_AGE = 24       # direct k-year models up to this age, the aging model after it
AGING_MIN_AGE = 22        # aging model anchors: 22 and older (covers the hand-over at 24)
AGING_BANDS = ((22, 26, "22-26"), (27, 30, "27-30"), (31, 34, "31-34"), (35, MAX_AGE, "35+"))
MAX_K = 26                # a 14-year-old's path to 40
SCORE_MAX_AGE = 39
N_BUCKETS = 64
TRAIN_ROWS = {"H": 6_000_000, "P": 6_000_000}       # (anchor, k) pairs sampled per role
QUICK_ROWS = 300_000
SETTINGS = {"learning_rate": 0.08, "max_iter": 2000, "max_leaf_nodes": 63, "min_samples_leaf": 200,
            "l2_regularization": 1.0, "max_bins": 255, "n_iter_no_change": 50}

DATA_PATH = os.path.join(C.DATA_DIR, "ratings_dev.pkl")
MODEL_DIR = os.path.join(C.MODELS_ROOT, "ratings")
REPORT_DIR = os.path.join(C.REPORT_ROOT, "ratings")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def targets(role):
    return [n for n, _c, _p in SPLIT[role]] + [n for n, _c in SINGLE[role]]


def model_specs(role):
    """[(rating, quantile)] of one role."""
    return [(t, q) for t in targets(role) for q in (QUANTS if t in RANGED else (0.5,))]


def model_file(role, rating, q):
    return f"{role}_{rating}_q{int(round(q * 100)):02d}.pkl"


# ---------------------------------------------------------------- vintage rows -> base table
def vintage_cols():
    cols = ["player_id", "name", "age", "pos", "org", "lev", "c_Ovr", "c_Pot"]
    for role in C.ROLES:
        for _n, pair, pot in SPLIT[role]:
            cols += list(pair) + [pot]
        cols += [c for _n, c in SINGLE[role] + EXTRA_IN[role]]
    cols += [f"c_{p}" for p in PITCHES] + [f"c_{p}P" for p in PITCHES]
    return list(dict.fromkeys(cols))


def base_table(df):
    """Vintage columns -> the rating table: one column per projected rating
    (split ratings as the vR / vL mean, plus the lean vR - vL), potentials,
    inputs, context. Keeps player_id / name / age / pos / lev / org."""
    num = lambda c: pd.to_numeric(df[c], errors="coerce").astype("float32") if c in df.columns \
        else pd.Series(np.nan, index=df.index, dtype="float32")
    # a rating or potential of 0 is a missing value, not a rating: the earliest DEV dumps
    # hold thousands of 0s (2026-01-01_p74: 2,549 Hold, 164 Stamina) and BLM a few 0 Control.
    # Pitch columns keep 0: there it means "does not throw it".
    rate = lambda c: num(c).where(num(c) > 0)
    out = pd.DataFrame({"pid": df["player_id"].astype(str), "name": df["name"].astype(str),
                        "age": num("age"), "pos": df["pos"].fillna("").astype(str).str.upper(),
                        "lev": df["lev"].fillna("").astype(str).str.strip(),
                        "org": df["org"].fillna("").astype(str).str.strip(),
                        "ovr": num("c_Ovr"), "pot": num("c_Pot")})
    for role in C.ROLES:
        for n, (r, l), pot in SPLIT[role]:
            vr, vl = rate(r), rate(l)
            out[n] = (vr + vl) / 2
            out[f"{n}_lean"] = vr - vl
            out[f"pot_{n}"] = rate(pot)
        for n, c in SINGLE[role] + EXTRA_IN[role]:
            out[n] = rate(c)
    cur = np.stack([num(f"c_{p}").to_numpy() for p in PITCHES], axis=1)
    potp = np.stack([num(f"c_{p}P").to_numpy() for p in PITCHES], axis=1)
    out["n_pitches45"] = (np.nan_to_num(cur, nan=0) >= 45).sum(axis=1).astype("float32")
    with np.errstate(all="ignore"):
        out["best_pitch"] = np.nanmax(np.where(np.isnan(cur), -1, cur), axis=1).astype("float32")
        out["best_pitch_pot"] = np.nanmax(np.where(np.isnan(potp), -1, potp), axis=1).astype("float32")
    for c in ("best_pitch", "best_pitch_pot"):
        out.loc[out[c] < 0, c] = np.nan
    return out


def level_rank(lev):
    """LEVEL_RANK of a level string; 0 for none / unknown. common.score_level
    reads a TGS winter-league player (WL) as R, the rule of the rest of the ML
    scoring (DEV has no WL; without it 899 TGS prospects read as amateurs)."""
    lv = C.score_level(lev)
    return float(C.LEVEL_RANK.get(lv, 0)) if lv else 0.0


# ---------------------------------------------------------------- features
def feature_names(role):
    f = ["age", "k", "age_t", "level_rank", "in_org", "pos_code", "bats_code", "throws_code", "height",
         "ovr", "pot", "pot_minus_ovr", "pot_scale", "d1_ovr", "d1_pot", "has_prev"]
    for n, _p, _pot in SPLIT[role]:
        f += [n, f"{n}_lean", f"pot_{n}", f"room_{n}", f"d1_{n}", f"d1_pot_{n}"]
    for n, _c in SINGLE[role]:
        f += [n, f"d1_{n}"]
    f += [n for n, _c in EXTRA_IN[role]]
    if role == "P":
        f += ["n_pitches45", "best_pitch", "best_pitch_pot"]
    return f


def aging_feature_names(role):
    """Inputs of the one-year aging model: only what a projected ratings line
    carries forward (no level, OVR or last-year movement)."""
    f = ["age", "pos_code", "bats_code", "throws_code", "height"]
    for n, _p, _pot in SPLIT[role]:
        f += [n, f"{n}_lean", f"pot_{n}", f"room_{n}"]
    f += [n for n, _c in SINGLE[role]] + [n for n, _c in EXTRA_IN[role]]
    if role == "P":
        f += ["n_pitches45", "best_pitch", "best_pitch_pot"]
    return f


def age_band(age):
    for lo, hi, lab in AGING_BANDS:
        if lo <= age <= hi:
            return lab
    return AGING_BANDS[0][2] if age < AGING_BANDS[0][0] else AGING_BANDS[-1][2]


def add_static(t, static):
    codes = {"B": {"R": 0.0, "L": 1.0, "S": 2.0}, "T": {"R": 0.0, "L": 1.0}}
    st = [static.get(p) or {} for p in t["pid"]]
    t["bats_code"] = np.array([codes["B"].get(str(s.get("B") or "").upper()[:1], np.nan) for s in st],
                              dtype="float32")
    t["throws_code"] = np.array([codes["T"].get(str(s.get("T") or "").upper()[:1], np.nan) for s in st],
                                dtype="float32")
    t["height"] = np.array([C.to_num(s.get("HT")) if s.get("HT") not in (None, "") else np.nan for s in st],
                           dtype="float32")


def add_context(t, pot_scale):
    t["level_rank"] = np.array([level_rank(x) for x in t["lev"]], dtype="float32")
    t["in_org"] = np.array([0.0 if DSIG.lev_out_of_org(x) else 1.0 for x in t["lev"]], dtype="float32")
    t["pos_code"] = np.array([float(C.POS_CATS.index(p)) if p in C.POS_CATS else np.nan for p in t["pos"]],
                             dtype="float32")
    t["pot_minus_ovr"] = t["pot"] - t["ovr"]
    t["pot_scale"] = np.float32(pot_scale) if np.isscalar(pot_scale) else pot_scale
    for role in C.ROLES:
        for n, _p, _pot in SPLIT[role]:
            t[f"room_{n}"] = t[f"pot_{n}"] - t[n]


def movement_cols():
    """Ratings whose last-year change is an input: OVR, POT, every projected
    rating, and each split rating's potential (user, 2026-10-08: a potential
    that keeps rising "can absolutely help predict how high a guy might fly";
    OOTP re-rolls potentials as players develop)."""
    return (["ovr", "pot"] + [n for role in C.ROLES for n in targets(role)]
            + [f"pot_{n}" for role in C.ROLES for n, _p, _pot in SPLIT[role]])


def add_movement(t, prev, span, ok):
    """d1_<x> = (now - earlier) / span game-years; NaN where ok is False or
    the earlier value is missing. has_prev = 1 where any movement is known."""
    for c in movement_cols():
        d = (t[c].to_numpy(dtype=np.float64) - prev[c].to_numpy(dtype=np.float64)) / span
        t[f"d1_{c}"] = np.where(ok, d, np.nan).astype("float32")
    t["has_prev"] = ok.astype("float32")


# ---------------------------------------------------------------- DEV build
def dev_files():
    out = []
    for p in glob.glob(os.path.join(C.DEV_VINT, "*_p*.csv.gz")):
        m = re.match(r"(\d+)-01-01_p\d+\.csv\.gz$", os.path.basename(p))
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def build():
    import reprice as RP
    files = dev_files()
    log(f"DEV vintages: {len(files)} ({files[0][0]}..{files[-1][0]})")
    want = vintage_cols()
    parts = []
    for i, (year, p) in enumerate(files):
        df = pd.read_csv(p, dtype=str, usecols=lambda c: c in want)
        t = base_table(df)
        t["year"] = np.int32(year - 1)          # dump dated Jan 1 of year: the season just played
        parts.append(t)
        if i % 50 == 0:
            log(f"  read {i + 1}/{len(files)}")
    t = pd.concat(parts, ignore_index=True)
    del parts
    log(f"rows {len(t):,}; bats / throws / height from the DEV raw dumps")
    add_static(t, RP.load_static())
    add_context(t, C.dev_pot_scale(t["year"].to_numpy()))
    t["role"] = np.where(t["pos"].isin(C.PITCHER_POS), "P", "H")
    t = t.sort_values(["pid", "year"]).reset_index(drop=True)
    # one-year movement: the row one season back, same person
    prev = t.groupby("pid", sort=False).shift(1)
    ok = ((t["year"] - prev["year"]) == 1) & (t["name"] == prev["name"]) & \
         ((t["age"] - prev["age"]).between(0.0, 2.0))
    add_movement(t, prev, 1.0, ok.to_numpy())
    # an OVR / POT change across the DEV scale switch is not development (common.dev_pot_scale)
    cross = C.dev_pot_scale(t["year"].to_numpy()) != C.dev_pot_scale(t["year"].to_numpy() - 1)
    t.loc[cross, ["d1_ovr", "d1_pot"]] = np.nan
    for c in ("lev", "org", "name"):
        t[c] = t[c].astype("category")
    C.save_table(t, DATA_PATH)
    log(f"wrote {DATA_PATH} ({len(t):,} rows, {t['pid'].nunique():,} players)")
    return 0


# ---------------------------------------------------------------- training pairs
def pair_index(t, role, min_age, max_age, ks, max_target_age):
    """(anchor rows, target rows, k) of one role: anchors aged min_age..max_age,
    targets k seasons on (k in ks) at age <= max_target_age, same person (same
    name, age step within a year of k). Rows are sorted by pid, year, so the
    k-th next row is k seasons on only when no season is missing."""
    age = t["age"].to_numpy()
    idx = np.flatnonzero((t["role"].to_numpy() == role) & (age >= min_age) & (age <= max_age))
    pid = t["pid"].to_numpy()
    year = t["year"].to_numpy()
    name = t["name"].cat.codes.to_numpy()
    n = len(t)
    a_list, b_list, k_list = [], [], []
    for k in ks:
        j = idx + k
        good = j < n
        i2, j2 = idx[good], j[good]
        m = (pid[j2] == pid[i2]) & (year[j2] - year[i2] == k) & (name[j2] == name[i2]) & \
            (np.abs(age[j2] - age[i2] - k) <= 1.0) & (age[i2] + k <= max_target_age + 0.5)
        a_list.append(i2[m])
        b_list.append(j2[m])
        k_list.append(np.full(m.sum(), k, dtype=np.int16))
    return np.concatenate(a_list), np.concatenate(b_list), np.concatenate(k_list)


def sample(a, b, kk, n_rows, seed=0):
    if len(a) > n_rows:
        pick = np.sort(np.random.default_rng(seed).choice(len(a), n_rows, replace=False))
        a, b, kk = a[pick], b[pick], kk[pick]
    return a, b, kk


def deltas(t, role, a, b):
    return pd.DataFrame({r: (t[r].to_numpy()[b] - t[r].to_numpy()[a]).astype("float32") for r in targets(role)})


def direct_pairs(t, role, n_rows):
    """Direct k-year pairs whose target is at most DIRECT_MAX_AGE."""
    a, b, kk = pair_index(t, role, 0, DIRECT_MAX_AGE - 1, range(1, MAX_K + 1), DIRECT_MAX_AGE)
    log(f"{role}: {len(a):,} direct (anchor, k) pairs, targets to age {DIRECT_MAX_AGE}")
    a, b, kk = sample(a, b, kk, n_rows)
    X = t.iloc[a].copy()
    X["k"] = kk.astype("float32")
    X["age_t"] = (X["age"] + X["k"]).astype("float32")
    return X[feature_names(role)].reset_index(drop=True), deltas(t, role, a, b), X["pid"].to_numpy()


def save_model(m, fn):
    import pickle
    with open(os.path.join(MODEL_DIR, fn), "wb") as fh:
        pickle.dump(m, fh)


def by_k_report(yv, kv, p50, base, preds):
    out = {}
    for lo, hi, lab in ((1, 1, "1"), (2, 3, "2-3"), (4, 6, "4-6"), (7, 12, "7-12")):
        sel = (kv >= lo) & (kv <= hi)
        if sel.sum() < 100:
            continue
        e = {"n": int(sel.sum()),
             "mae_model": round(float(np.mean(np.abs(yv[sel] - p50[sel]))), 3),
             "mae_no_change": round(float(np.mean(np.abs(yv[sel]))), 3),
             "mae_age_average": round(float(np.mean(np.abs(yv[sel] - base[sel]))), 3),
             "mean_change": round(float(np.mean(yv[sel])), 3)}
        if 0.25 in preds:
            lo_ = np.minimum(preds[0.25][sel], preds[0.75][sel])
            hi_ = np.maximum(preds[0.25][sel], preds[0.75][sel])
            e["inside_25_75"] = round(float(np.mean((yv[sel] >= lo_) & (yv[sel] <= hi_))), 3)
        out[lab] = e
    return out


def train_direct(t, role, st, quick, rinfo, rrep):
    X, Y, pids = direct_pairs(t, role, QUICK_ROWS if quick else TRAIN_ROWS[role])
    val = np.array([C.fold_of(p) == 0 for p in pids])
    log(f"{role} direct: train {(~val).sum():,} val {val.sum():,} rows, {X.shape[1]} inputs")
    key = X["age"].round().astype(int).astype(str) + "_" + X["k"].astype(int).astype(str)
    rinfo.update({"features": list(X.columns), "models": {}})
    for rating in targets(role):
        y = Y[rating].to_numpy()
        ok = ~np.isnan(y)
        tr, va = ok & ~val, ok & val
        base_mean = pd.Series(y[tr]).groupby(key[tr].to_numpy()).mean()
        base = key[va].map(base_mean).fillna(float(np.nanmean(y[tr]))).to_numpy()
        preds = {}
        for q in (QUANTS if rating in RANGED else (0.5,)):
            t0 = time.time()
            m = XM.fit(XM.regressor(st, "quantile", q), X[tr], y[tr], X[va], y[va])
            fn = model_file(role, rating, q)
            save_model(m, fn)
            preds[q] = m.predict(X[va])
            rinfo["models"][f"{rating}_q{int(q * 100):02d}"] = {"file": fn, "rating": rating, "quantile": q,
                                                               "n_iter": XM.n_iter(m), "n_train": int(tr.sum())}
            log(f"  {role} {rating} q{int(q * 100)}: iters {XM.n_iter(m)} {time.time() - t0:.0f}s")
        rr = {"n_val": int(va.sum()), "by_k": by_k_report(y[va], X["k"].to_numpy()[va], preds[0.5], base, preds)}
        rrep.setdefault(rating, {}).update(rr)
        log(f"  {role} {rating} to {DIRECT_MAX_AGE}: " + ", ".join(
            f"k {lab} miss {e['mae_model']} (no change {e['mae_no_change']}, age avg {e['mae_age_average']})"
            for lab, e in rr["by_k"].items()))
    del X, Y


def aging_step(models, feats, state):
    """One season of aging: state (DataFrame of aging inputs) -> next season's
    ratings (dict rating -> array). Room follows the new ratings."""
    X = state[feats]
    return {r: m.predict(X) for r, m in models.items()}


def train_aging(t, role, st, quick, rinfo, rrep):
    feats = aging_feature_names(role)
    a, b, kk = pair_index(t, role, AGING_MIN_AGE, MAX_AGE - 1, (1,), MAX_AGE)
    log(f"{role}: {len(a):,} one-year aging pairs from age {AGING_MIN_AGE}")
    a, b, kk = sample(a, b, kk, QUICK_ROWS if quick else TRAIN_ROWS[role])
    X = t.iloc[a][feats].reset_index(drop=True)
    Y = deltas(t, role, a, b)
    pids = t["pid"].to_numpy()[a]
    val = np.array([C.fold_of(p) == 0 for p in pids])
    ages = X["age"].round().to_numpy()
    bands = np.array([age_band(x) for x in ages])
    info = {"features": feats, "models": {}, "spread": {}}
    models = {}
    for rating in targets(role):
        y = Y[rating].to_numpy()
        ok = ~np.isnan(y)
        tr, va = ok & ~val, ok & val
        t0 = time.time()
        m = XM.fit(XM.regressor(st, "squared_error"), X[tr], y[tr], X[va], y[va])
        fn = f"{role}_{rating}_aging.pkl"
        save_model(m, fn)
        models[rating] = m
        info["models"][rating] = {"file": fn, "n_iter": XM.n_iter(m), "n_train": int(tr.sum())}
        res = y[va] - m.predict(X[va])
        base = pd.Series(y[tr]).groupby(ages[tr]).mean()
        bv = pd.Series(ages[va]).map(base).fillna(float(np.nanmean(y[tr]))).to_numpy()
        info["spread"][rating] = {}
        rr = {"n_val": int(va.sum()), "by_band": {}}
        for _lo, _hi, lab in AGING_BANDS:
            sel = bands[va] == lab
            if sel.sum() < 50:
                continue
            q25, q75 = np.percentile(res[sel], [25, 75])
            info["spread"][rating][lab] = round(float((q75 - q25) / 2), 3)
            # a mean model: judged by root mean square error (most players do not move in a
            # given season, so the average miss always favours "no change")
            rms = lambda v: round(float(np.sqrt(np.mean(np.square(v)))), 3)
            rr["by_band"][lab] = {"n": int(sel.sum()),
                                  "rmse_model": rms(res[sel]),
                                  "rmse_no_change": rms(y[va][sel]),
                                  "rmse_age_average": rms(y[va][sel] - bv[sel]),
                                  "mean_change": round(float(np.mean(y[va][sel])), 3),
                                  "mean_predicted": round(float(np.mean(y[va][sel] - res[sel])), 3)}
        rrep.setdefault(rating, {})["aging_one_year"] = rr
        log(f"  {role} {rating} aging: " + ", ".join(
            f"{lab} rmse {e['rmse_model']} (no change {e['rmse_no_change']}, age avg {e['rmse_age_average']}; "
            f"change {e['mean_predicted']:+.2f} vs {e['mean_change']:+.2f})"
            for lab, e in rr["by_band"].items()) + f" ({time.time() - t0:.0f}s)")
    rinfo["aging"] = info
    # chained check: val players at 30, stepped 3 seasons, against what they had 3 seasons on
    a3, b3, _k = pair_index(t, role, 30, 30, (3,), MAX_AGE)
    keep = np.array([C.fold_of(p) == 0 for p in t["pid"].to_numpy()[a3]])
    a3, b3 = a3[keep], b3[keep]
    if len(a3) > 100:
        state = t.iloc[a3][feats].reset_index(drop=True).copy()
        bounds = rinfo["bounds"]
        for _step in range(3):
            nxt = aging_step(models, feats, state)
            for r, d in nxt.items():
                state[r] = np.clip(state[r].to_numpy() + d, *bounds[r])
            for n, _pp, _pot in SPLIT[role]:
                state[f"room_{n}"] = state[f"pot_{n}"] - state[n]
            state["age"] = state["age"] + 1
        chk = {}
        for r in targets(role):
            act = t[r].to_numpy()[b3]
            now = t[r].to_numpy()[a3]
            okr = ~np.isnan(act) & ~np.isnan(now)
            chk[r] = {"n": int(okr.sum()),
                      "mae_stepped": round(float(np.mean(np.abs(act[okr] - state[r].to_numpy()[okr]))), 3),
                      "mae_no_change": round(float(np.mean(np.abs(act[okr] - now[okr]))), 3),
                      "mean_actual_change": round(float(np.mean(act[okr] - now[okr])), 3),
                      "mean_stepped_change": round(float(np.mean(state[r].to_numpy()[okr] - now[okr])), 3)}
            rrep.setdefault(r, {})["stepped_30_to_33"] = chk[r]
        log(f"  {role} stepped 30 -> 33 check: " + ", ".join(
            f"{r} {e['mean_stepped_change']:+.1f} vs actual {e['mean_actual_change']:+.1f}" for r, e in chk.items()))


def train(quick=False):
    t = C.load_table(DATA_PATH)
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    st = dict(SETTINGS)
    if quick:
        st.update(max_iter=200, n_iter_no_change=20)
    manifest = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                "library": f"xgboost {XM.version()}", "device": XM.backend()[1], "quick": quick,
                "settings": st, "max_age": MAX_AGE, "max_k": MAX_K, "direct_max_age": DIRECT_MAX_AGE,
                "aging_min_age": AGING_MIN_AGE, "roles": {}}
    report = {"generated": manifest["generated"], "quick": quick, "direct_max_age": DIRECT_MAX_AGE, "roles": {}}
    for role in C.ROLES:
        rinfo = {"bounds": {r: [max(SCALE_FLOOR, float(np.nanmin(t[r]))), float(np.nanmax(t[r]))]
                            for r in targets(role)}}
        rrep = {}
        train_direct(t, role, st, quick, rinfo, rrep)
        train_aging(t, role, st, quick, rinfo, rrep)
        manifest["roles"][role] = rinfo
        report["roles"][role] = rrep
    with open(os.path.join(MODEL_DIR, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    with open(os.path.join(REPORT_DIR, "validation.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    log(f"wrote {MODEL_DIR}\\manifest.json and {REPORT_DIR}\\validation.json")
    return 0


# ---------------------------------------------------------------- scoring
def load_models():
    import pickle
    p = os.path.join(MODEL_DIR, "manifest.json")
    if not os.path.exists(p):
        raise SystemExit(f"no rating-path models ({p}); run: py -3.14 tgs-viz/backtest/ml/rating_path.py train")
    with open(p, encoding="utf-8") as fh:
        man = json.load(fh)
    if "aging" not in next(iter(man["roles"].values())):
        raise SystemExit("rating-path models predate the aging model (2026-10-08); run: "
                         "py -3.14 tgs-viz/backtest/ml/rating_path.py train")
    models = {}

    def load(fn):
        path = os.path.join(MODEL_DIR, fn)
        C.check_downloaded(path)
        with open(path, "rb") as fh:
            return pickle.load(fh)
    for role, rinfo in man["roles"].items():
        for info in rinfo["models"].values():
            models[(role, info["rating"], info["quantile"])] = load(info["file"])
        for rating, info in rinfo["aging"]["models"].items():
            models[(role, rating, "aging")] = load(info["file"])
    return man, models


def vintage_path(league, pull_id):
    hits = glob.glob(os.path.join(C.LEAGUE_VINT, league, f"*_p{pull_id}.csv.gz"))
    return hits[0] if hits else None


def league_static(league):
    static = {}
    for fn in ("hitters.json", "pitchers.json"):
        p = os.path.join(C.APP_DATA, league, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                rows = json.load(fh)
            for r in rows.get("rows", rows) if isinstance(rows, dict) else rows:
                static[str(r.get("ID"))] = {"B": r.get("B"), "T": r.get("T"), "HT": r.get("HT")}
    return static


def league_rows(league):
    """(table, note, raw vintage rows by id) of the league's latest pull with
    one-year movement from the choose_clean_pulls earlier pull."""
    conn = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
    try:
        pulls = DSIG.league_pulls(conn, league)
        gdates = DSIG.game_dates(league, pulls)
        choice = DSIG.choose_clean_pulls(conn, league, pulls, gdates)
        replaced = DSIG.replaced_cards(conn, pulls, gdates, choice) if choice.get("from_id") else {}
    finally:
        conn.close()
    to_p = vintage_path(league, choice["to_id"])
    if not to_p:
        raise SystemExit(f"{league}: no archived vintage for the latest pull {choice['to_id']}")
    want = vintage_cols()
    cur_df = pd.read_csv(to_p, dtype=str, usecols=lambda c: c in want)
    t = base_table(cur_df)
    add_static(t, league_static(league))
    add_context(t, C.LEAGUE_OVR_POT_SCALE.get(league, 0.0))
    t["role"] = np.where(t["pos"].isin(C.PITCHER_POS), "P", "H")
    note = {"to_pull": choice["to_id"], "to_date": str(choice["to_date"]), "from_pull": choice.get("from_id"),
            "from_date": str(choice["from_date"]) if choice.get("from_date") else None,
            "span_game_years": round(choice["span"], 3) if choice.get("span") else None,
            "to_file": os.path.basename(to_p)}
    from_p = vintage_path(league, choice["from_id"]) if choice.get("from_id") else None
    span = choice.get("span") or 1.0
    if from_p:
        prev_df = pd.read_csv(from_p, dtype=str, usecols=lambda c: c in want)
        prev = base_table(prev_df).drop_duplicates("pid").set_index("pid").reindex(t["pid"]).reset_index()
        same = np.array([DSIG.same_person({"name": n, "age": a}, {"name": n0, "age": a0}, span)
                         if isinstance(n0, str) else False
                         for n, a, n0, a0 in zip(t["name"], t["age"], prev["name"], prev["age"])])
        rep = t["pid"].isin(set(map(str, replaced))).to_numpy()
        ok = same & ~rep
        add_movement(t, prev, span, ok)
        note["movement"] = {"players_with_movement": int(ok.sum()), "reused_id": int((~same & prev["name"].notna()).sum()),
                            "card_replaced": int((rep & same).sum())}
    else:
        nan_prev = t.copy()
        for c in movement_cols():
            nan_prev[c] = np.nan
        add_movement(t, nan_prev, 1.0, np.zeros(len(t), dtype=bool))
        note["movement"] = "no earlier pull: movement unknown for every player"
    # the engine reads the vintage the way agecurve_fit.load_vintage does: strings, blanks as ""
    with gzip.open(to_p, "rt", encoding="utf-8") as fh:
        raw = {str(r["player_id"]): r for r in csv.DictReader(fh)}
    return t, note, raw


def league_cap(t):
    """Top of the league's rating scale: the highest rating in its pull
    (TGS 80, BLM 85). Projections never go above it."""
    cols = [n for role in C.ROLES for n in targets(role)]
    v = np.nanmax(t[cols].to_numpy(dtype=np.float64))
    return float(v) if np.isfinite(v) else 80.0


def project(t, man, models):
    """{pid: {role, k, p: {rating: [lo, mid, hi] or [mid] arrays over years
    1..k}}}. Years to DIRECT_MAX_AGE: the direct models. Later years: the
    aging model, one season at a time from the last direct year's middle line
    (or from today for a player already DIRECT_MAX_AGE or older). From
    POT_RESET_AGE every potential follows the projected rating, as OOTP does
    (review 2026-10-08: the aging model never saw room above 0 at 30+)."""
    out = {}
    cap = league_cap(t)
    for role in C.ROLES:
        rows = t[(t["role"] == role) & (t["age"] <= SCORE_MAX_AGE) & t["age"].notna()].reset_index(drop=True)
        if not len(rows):
            continue
        rinfo = man["roles"][role]
        bounds = {r: [max(SCALE_FLOOR, b0), min(cap, b1)] for r, (b0, b1) in rinfo["bounds"].items()}
        aging = rinfo["aging"]
        age0 = rows["age"].round().to_numpy().astype(int)
        ks = np.clip(MAX_AGE - age0, 1, MAX_K).astype(int)
        kd = np.clip(DIRECT_MAX_AGE - age0, 0, None).astype(int)      # direct years per player
        kd = np.minimum(kd, ks)
        n, K = len(rows), int(ks.max())
        rts = targets(role)
        mid = {r: np.full((n, K), np.nan) for r in rts}
        lo = {r: np.full((n, K), np.nan) for r in rts if r in RANGED}
        hi = {r: np.full((n, K), np.nan) for r in rts if r in RANGED}
        # direct years
        if kd.sum():
            rep_ = np.repeat(np.arange(n), kd)
            kk = np.concatenate([np.arange(1, k + 1) for k in kd if k]).astype("float32")
            X = rows.iloc[rep_].reset_index(drop=True)
            X["k"] = kk
            X["age_t"] = (X["age"] + X["k"]).astype("float32")
            X = X[rinfo["features"]]
            col = kk.astype(int) - 1
            for r in rts:
                now = rows[r].to_numpy(dtype=np.float64)[rep_]
                b0, b1 = bounds[r]
                qs = QUANTS if r in RANGED else (0.5,)
                vals = [np.clip(now + models[(role, r, q)].predict(X), b0, b1) for q in qs]
                if len(vals) == 3:
                    vals = list(np.sort(np.stack(vals), axis=0))
                    lo[r][rep_, col], mid[r][rep_, col], hi[r][rep_, col] = vals
                else:
                    mid[r][rep_, col] = vals[0]
        # aging years: start from the last direct middle line (or today)
        state = rows[aging["features"]].copy()
        last = kd - 1
        has_d = kd > 0
        for r in rts:
            v = state[r].to_numpy(dtype=np.float64)
            v[has_d] = mid[r][np.flatnonzero(has_d), last[has_d]]
            state[r] = v
        state["age"] = (age0 + kd).astype("float32")
        for nm, _pp, _pot in SPLIT[role]:
            state[f"room_{nm}"] = state[f"pot_{nm}"] - state[nm]
        # the range carried forward: the last direct half-range each side, then one step's spread per season
        var_lo = {r: np.zeros(n) for r in lo}
        var_hi = {r: np.zeros(n) for r in hi}
        for r in lo:
            var_lo[r][has_d] = (mid[r][np.flatnonzero(has_d), last[has_d]]
                                - lo[r][np.flatnonzero(has_d), last[has_d]]) ** 2
            var_hi[r][has_d] = (hi[r][np.flatnonzero(has_d), last[has_d]]
                                - mid[r][np.flatnonzero(has_d), last[has_d]]) ** 2
        amods = {r: models[(role, r, "aging")] for r in rts}
        for j in range(1, K + 1):
            act = (j > kd) & (j <= ks)
            if not act.any():
                continue
            ia = np.flatnonzero(act)
            reset = ia[state["age"].to_numpy()[ia] >= POT_RESET_AGE]
            if len(reset):
                for nm, _pp, _pot in SPLIT[role]:
                    pv = state[f"pot_{nm}"].to_numpy(dtype=np.float64)
                    pv[reset] = state[nm].to_numpy(dtype=np.float64)[reset]
                    state[f"pot_{nm}"] = pv
                    state[f"room_{nm}"] = state[f"pot_{nm}"] - state[nm]
                if "best_pitch_pot" in state.columns:
                    bp = state["best_pitch_pot"].to_numpy(dtype=np.float64)
                    bp[reset] = state["best_pitch"].to_numpy(dtype=np.float64)[reset]
                    state["best_pitch_pot"] = bp
            sub = state.iloc[ia]
            step = aging_step(amods, aging["features"], sub)
            bands = [age_band(a) for a in sub["age"].to_numpy()]
            for r in rts:
                b0, b1 = bounds[r]
                v = np.clip(sub[r].to_numpy(dtype=np.float64) + step[r], b0, b1)
                mid[r][ia, j - 1] = v
                cur = state[r].to_numpy(dtype=np.float64)
                cur[ia] = v
                state[r] = cur
                if r in lo:
                    u = np.array([aging["spread"][r].get(bd, 0.0) for bd in bands]) ** 2
                    var_lo[r][ia] += u
                    var_hi[r][ia] += u
                    lo[r][ia, j - 1] = np.clip(v - np.sqrt(var_lo[r][ia]), b0, b1)
                    hi[r][ia, j - 1] = np.clip(v + np.sqrt(var_hi[r][ia]), b0, b1)
            ages_ = state["age"].to_numpy()
            ages_[ia] += 1
            state["age"] = ages_
            for nm, _pp, _pot in SPLIT[role]:
                state[f"room_{nm}"] = state[f"pot_{nm}"] - state[nm]
        for i, pid in enumerate(rows["pid"]):
            k = int(ks[i])
            out[pid] = {"role": role, "k": k, "kd": int(kd[i]),
                        "p": {r: ([lo[r][i, :k], mid[r][i, :k], hi[r][i, :k]] if r in lo else [mid[r][i, :k]])
                              for r in rts}}
    return out


def price_paths(league, t, raw, proj):
    """{pid: [WAA change from now at k = 1..K]} pricing each future year's
    50th-percentile ratings line with the league's engine (neutral park).
    WAA = hitters Max WAA wtd, pitchers the larger of WAA wtd and WAA wtd RP
    (the same 'now' the ML models use). Ratings not projected stay as today."""
    sys.path.insert(0, ENGINE)
    import agecurve_fit as AF
    import ratings as R
    static = league_static(league)
    lg = C.league_basis(league) if league not in C.BASES else league
    cur = R.live_currency(lg)
    tails, fld, sc, rs = R.live_hitter_tails(lg), R.live_fielding(lg), R.live_scurves(lg), R.live_role_stuff(lg)
    cols = {n: pair for role in C.ROLES for n, pair, _pot in SPLIT[role]}
    single = {n: c for role in C.ROLES for n, c in SINGLE[role]}
    now_vals = {p: row for p, row in zip(t["pid"], t.to_dict("records"))}

    def one_pass(vint):
        hit, pit = AF.to_records(vint, static)
        res = {}
        for r in R.run_hitters(hit, lg, currency=cur, tails=tails, fielding=fld, park_mode="neutral"):
            res[str(r["ID"])] = AF._num(r.get("Max WAA wtd"))
        for r in R.run_pitchers(pit, lg, scurves=sc, currency=cur, park_mode="neutral", role_stuff=rs,
                                observed=(lg == league)):
            v = [x for x in (AF._num(r.get("WAA wtd")), AF._num(r.get("WAA wtd RP"))) if x is not None]
            res[str(r["ID"])] = max(v) if v else None
        return res

    ids = [p for p in proj if p in raw]
    base = one_pass({p: raw[p] for p in ids})
    out = {p: [] for p in ids}
    for k in range(1, MAX_K + 1):
        vint = {}
        for p in ids:
            e = proj[p]
            if e["k"] < k:
                continue
            r = dict(raw[p])
            r["age"] = str(C.to_num(r.get("age")) + k)
            nv = now_vals[p]
            for rating, vals in e["p"].items():
                mid = vals[len(vals) // 2][k - 1]
                if mid != mid:
                    continue                  # a rating missing today has no path: it stays as it is
                mid = float(int(round(mid)))  # the value the table shows
                if rating in cols:
                    d = mid - float(nv[rating])
                    for c in cols[rating]:
                        x = C.to_num(r.get(c))
                        if x == x:
                            r[c] = f"{x + d:.2f}"
                else:
                    r[single[rating]] = f"{mid:.0f}"
            vint[p] = r
        if not vint:
            break
        res = one_pass(vint)
        for p in vint:
            b, v = base.get(p), res.get(p)
            out[p].append(round(v - b, 2) if b is not None and v is not None else None)
        log(f"  priced year +{k}: {len(vint):,} players")
    return out, base


def score(league, write=False):
    man, models = load_models()
    t, note, raw = league_rows(league)
    log(f"{league}: {len(t):,} players in pull {note['to_pull']}; movement {note['movement']}")
    proj = project(t, man, models)
    log(f"{league}: projected {len(proj):,} players")
    priced, base = price_paths(league, t, raw, proj)
    tv = t.drop_duplicates("pid").set_index("pid")
    buckets = [{} for _ in range(N_BUCKETS)]
    for pid, e in proj.items():
        row = tv.loc[pid]
        role = e["role"]
        if role == "H":
            grp = POS_GROUP.get(row["pos"])
            shown = [n for n, _p, _q in SPLIT["H"]] + ["speed"] + GROUP_FIELDING.get(grp, [])
        else:
            grp = None
            shown = targets("P")
        rec = {"r": role, "age": int(round(float(row["age"]))), "now": {}, "p": {}}
        if grp:
            rec["g"] = grp
        for r in shown:
            v = row[r]
            if v != v:
                continue
            rec["now"][r] = round(float(v), 1)
            vals = e["p"][r]
            rec["p"][r] = [[int(round(x)) for x in arr] for arr in vals] if len(vals) == 3 \
                else [int(round(x)) for x in vals[0]]
        if pid in priced:
            rec["w"] = priced[pid]
            rec["w0"] = round(base[pid], 2) if base.get(pid) is not None else None
        try:
            b = int(pid) % N_BUCKETS
        except ValueError:
            b = sum(map(ord, pid)) % N_BUCKETS
        buckets[b][pid] = rec
    val = None
    vp = os.path.join(REPORT_DIR, "validation.json")
    if os.path.exists(vp):
        with open(vp, encoding="utf-8") as fh:
            val = json.load(fh)
    index = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "league": league,
             "direct_max_age": man.get("direct_max_age", DIRECT_MAX_AGE),
             "models_generated": man["generated"], "quick_models": man.get("quick", False),
             "n_buckets": N_BUCKETS, "max_age": MAX_AGE, "labels": LABELS,
             "ranged": sorted(RANGED), "quantiles": list(QUANTS), "note": note,
             "players": len(proj), "validation": val}
    if not write:
        log(f"(dry run) {len(proj):,} players; pass --write to save public/data/{league}/rating_paths/")
        return 0
    d = os.path.join(C.APP_DATA, league, "rating_paths")
    os.makedirs(d, exist_ok=True)
    for i, bk in enumerate(buckets):
        tmp = os.path.join(d, f"b{i:02d}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(bk, fh, separators=(",", ":"))
        os.replace(tmp, os.path.join(d, f"b{i:02d}.json"))
    tmp = os.path.join(d, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    os.replace(tmp, os.path.join(d, "index.json"))
    size = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
    log(f"wrote {d} ({size / 1e6:.1f} MB)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Year-by-year rating projections (DEV-trained).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="DEV vintages -> ratings_dev.pkl")
    tr = sub.add_parser("train", help="train the models (GPU when available)")
    tr.add_argument("--quick", action="store_true", help="small sample, few rounds: a smoke test")
    sc = sub.add_parser("score", help="project one league's players")
    sc.add_argument("--league", required=True)
    sc.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        return build()
    if a.cmd == "train":
        return train(a.quick)
    return score(a.league, a.write)


if __name__ == "__main__":
    sys.exit(main())
