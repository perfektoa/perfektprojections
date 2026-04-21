#!/usr/bin/env python
# Build pitcher rating tables + MLB⇆AAA adjustments.
# Edited to match the EXCEL sheet’s *event-basis* definitions:
#   uBB%  = (BB-IBB) / (BF - IBB - HBP)
#   K%    = K        / (BF - BB  - HBP)
#   HR%   = HR       / (BF - BB  - HBP)
#   BABIP = (1B+2B+3B) / (AB - HR - K + SF)
#   SBA%  = (SB+CS)  / (BB + HBP + 1B_allowed)
#   SB%   = SB       / (SB+CS)
#
# Outputs: pitching_rating_tables_smoothed.xlsx
# Sheets:
#   - Rates: Rating→K%, HR%, uBB%, BABIP%, SBA%, SB%, plus league HBP/CI/SF per BF.
#   - relative_adjustments: MLB rating, AAA rating → adjusted rating (per attribute).

import pandas as pd, numpy as np
from sklearn.isotonic import IsotonicRegression

# ---------- FILES ----------
new_file    = "player_search___shortlist_player_shortlist_pitching_table.csv"
aaa_file    = "player_search___shortlist_player_shortlist_pitching_table2.csv"
master_file = "pitching_training_master.csv"
out_file    = "pitching_rating_tables_smoothed.xlsx"

# ---------- LOAD / EXTEND MASTER ----------
df_new = pd.read_csv(new_file, low_memory=False)
try:
    df_master = pd.read_csv(master_file, low_memory=False)
    df_all    = pd.concat([df_master, df_new], ignore_index=True).drop_duplicates()
except FileNotFoundError:
    df_all = df_new.copy()
df_all.to_csv(master_file, index=False)

# ---------- FEATURE ENGINEERING (MATCH EXCEL DEFINITIONS) ----------
df = df_all.copy()

# Add AB because EXCEL BABIP uses AB - HR - K + SF
needed = ["BF","AB","1B","2B","3B","HR","BB","IBB","K","HP","SH","SF","CI","SB","CS"]
for c in needed:
    if c not in df.columns:
        df[c] = 0

for c in needed:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(lower=0)

df = df[df["BF"] > 0].copy()

# If AB is missing/zero in your exports, estimate it from BF identity.
# (IBB is included inside BB, so do NOT subtract IBB separately.)
ab_missing = (df["AB"] <= 0)
if ab_missing.any():
    df.loc[ab_missing, "AB"] = (
        df.loc[ab_missing, "BF"]
        - df.loc[ab_missing, "BB"]
        - df.loc[ab_missing, "HP"]
        - df.loc[ab_missing, "SH"]
        - df.loc[ab_missing, "SF"]
        - df.loc[ab_missing, "CI"]
    ).clip(lower=0)

df["uBB"]    = (df["BB"] - df["IBB"]).clip(lower=0)
df["H_BIP"]  = (df["1B"] + df["2B"] + df["3B"]).clip(lower=0)
df["SBA"]    = (df["SB"] + df["CS"]).clip(lower=0)

# Denominators that match the Excel sheet’s construction
df["uBB_den"]   = (df["BF"] - df["IBB"] - df["HP"]).clip(lower=0)
df["K_den"]     = (df["BF"] - df["BB"]  - df["HP"]).clip(lower=0)
df["HR_den"]    = df["K_den"]  # same basis as K%
df["BABIP_den"] = (df["AB"] - df["HR"] - df["K"] + df["SF"]).clip(lower=0)
df["SBA_den"]   = (df["BB"] + df["HP"] + df["1B"]).clip(lower=0)  # note: 1B allowed
df["SB_den"]    = df["SBA"].clip(lower=0)

# Rates (targets)
df["uBB%"]   = df["uBB"] / df["uBB_den"].replace(0, np.nan)
df["K%"]     = df["K"]   / df["K_den"].replace(0, np.nan)
df["HR%"]    = df["HR"]  / df["HR_den"].replace(0, np.nan)
df["BABIP%"] = df["H_BIP"] / df["BABIP_den"].replace(0, np.nan)

df["SBA%"]   = df["SBA"] / df["SBA_den"].replace(0, np.nan)     # attempts per (BB+HBP+1B)
df["SB%"]    = df["SB"]  / df["SB_den"].replace(0, np.nan)      # success given attempt

# Clip to valid probability range
for col in ["uBB%","K%","HR%","BABIP%","SBA%","SB%"]:
    df[col] = df[col].astype(float).clip(0.0, 1.0)

# League-average “we don’t model this per rating” constants per BF (matches your prior approach)
tot_BF = df["BF"].sum()
league_HBP_per_BF = df["HP"].sum() / tot_BF if tot_BF > 0 else 0.0
league_CI_per_BF  = df["CI"].sum() / tot_BF if tot_BF > 0 else 0.0
league_SF_per_BF  = df["SF"].sum() / tot_BF if tot_BF > 0 else 0.0

# ---------- RATINGS CLEANUP ----------
RATING_COLS = [
    "STU vL","STU vR",
    "HRR vL","HRR vR",
    "CON vL","CON vR",
    "PBABIP vL","PBABIP vR",
]
if "HLD" not in df.columns:
    df["HLD"] = np.nan

def _coerce_rating(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().replace({"-": "20", "": "20"})
    s = pd.to_numeric(s, errors="coerce").fillna(20.0)
    return s.clip(20, 100)

for col in RATING_COLS + ["HLD"]:
    if col in df.columns:
        df[col] = _coerce_rating(df[col])
    else:
        df[col] = 20.0

def _q5(s: pd.Series) -> pd.Series:
    return (5 * np.round(s / 5.0)).clip(20, 100).astype(int)

for col in RATING_COLS + ["HLD"]:
    df[col + "_q"] = _q5(df[col])

# ---------- AAA⇆MLB UPLIFT (no PBABIP) ----------
df_aaa = pd.read_csv(aaa_file, low_memory=False)
key_cols = ["ID"] if ("ID" in df_new.columns and "ID" in df_aaa.columns) else ["Name"]

UPLIFT_COLS = ["STU vL","STU vR","HRR vL","HRR vR","CON vL","CON vR"]

merged = (
    df_new[key_cols + UPLIFT_COLS]
      .merge(df_aaa[key_cols + UPLIFT_COLS],
             on=key_cols, suffixes=("_MLB","_AAA"), how="inner")
)

def _q5f(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().replace({"-": "20", "": "20"})
    s = pd.to_numeric(s, errors="coerce").fillna(20.0)
    return (5 * np.round(s / 5.0)).clip(20, 100).astype(float)

STEP_PER_5 = 1.0
EPS        = 0.01
ROUND_TO   = 0.01

rows = []
for attr in UPLIFT_COLS:
    mlb_q = _q5f(merged[f"{attr}_MLB"])
    aaa_q = _q5f(merged[f"{attr}_AAA"])
    tmp = pd.DataFrame({"mlb_q": mlb_q, "aaa_q": aaa_q})

    for mlb_val, grp in tmp.groupby("mlb_q"):
        counts   = grp["aaa_q"].value_counts().sort_index()
        a_vals   = counts.index.to_numpy(dtype=float)
        weights  = counts.values.astype(float)

        aaa_mean = float(np.average(a_vals, weights=weights))
        base = STEP_PER_5 * (a_vals - aaa_mean) / 5.0

        lower = (mlb_val - 1.25) + EPS
        upper = (mlb_val + 1.25) - EPS

        scale_pos_cap = np.inf
        scale_neg_cap = np.inf
        if (base > 0).any():
            scale_pos_cap = (upper - mlb_val) / base[base > 0].max()
        if (base < 0).any():
            scale_neg_cap = (mlb_val - lower) / (-base[base < 0].max())
        scale = min(scale_pos_cap, scale_neg_cap)
        if not np.isfinite(scale):
            scale = 1.0

        deltas = scale * base
        adjs   = mlb_val + deltas
        adjs   = np.clip(np.round(adjs / ROUND_TO) * ROUND_TO, lower, upper)

        for a, adj in zip(a_vals, adjs):
            rows.append({
                "rating": attr,
                "mlb_rating": float(mlb_val),
                "aaa_rating": float(a),
                "adj_rating": float(adj)
            })

uplift = (pd.DataFrame(rows)
          .drop_duplicates(["rating","mlb_rating","aaa_rating"])
          .sort_values(["rating","mlb_rating","aaa_rating"]))

uplift = (uplift
          .sort_values(["rating","aaa_rating","mlb_rating"])
          .assign(adj_rating=lambda d: d.groupby(["rating","aaa_rating"])["adj_rating"].cummax()))

# ---------- ISOTONIC HELPERS ----------
ratings_grid = np.arange(20, 101, 5, dtype=int)

def _logit(p, eps=1e-6):
    p = np.clip(p, eps, 1-eps)
    return np.log(p/(1-p))

def _inv_logit(z):
    return 1/(1+np.exp(-z))

def bucket_mean(df_local, rating_col_q, value_col, weight_col=None):
    X, y, w = [], [], []
    for r in ratings_grid:
        m = (df_local[rating_col_q] == r) & df_local[value_col].notna()
        if not m.any():
            continue
        s = df_local.loc[m, value_col].astype(float)

        if weight_col is not None:
            wt = df_local.loc[m, weight_col].astype(float).clip(lower=0)
            if wt.sum() > 0:
                X.append(float(r))
                y.append(float(np.average(s, weights=wt)))
                w.append(float(wt.sum()))
            else:
                X.append(float(r)); y.append(float(s.mean())); w.append(float(len(s)))
        else:
            X.append(float(r)); y.append(float(s.mean())); w.append(float(len(s)))

    return np.array(X), np.array(y), np.array(w)

def iso_smooth(df_local, rating_col_q, value_col, direction="increasing", weight_col=None):
    X, y, w = bucket_mean(df_local, rating_col_q, value_col, weight_col)
    if X.size == 0:
        return pd.Series(0.0, index=ratings_grid)
    if X.size == 1:
        return pd.Series(np.repeat(y[0], len(ratings_grid)), index=ratings_grid)

    z = _logit(y)
    flip = -1.0 if direction == "decreasing" else 1.0
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(X, flip*z, sample_weight=w)
    z_grid = iso.predict(ratings_grid.astype(float))
    y_hat = _inv_logit(flip*z_grid)
    return pd.Series(np.clip(y_hat, 0.0, 1.0), index=ratings_grid)

# ---------- FIT RATES (MATCH EXCEL TARGETS + WEIGHTS) ----------
# Use weights that match the *denominator* used for each rate.
k_L    = iso_smooth(df, "STU vL_q",    "K%",     direction="increasing", weight_col="K_den")
k_R    = iso_smooth(df, "STU vR_q",    "K%",     direction="increasing", weight_col="K_den")

hr_L   = iso_smooth(df, "HRR vL_q",    "HR%",    direction="decreasing", weight_col="HR_den")
hr_R   = iso_smooth(df, "HRR vR_q",    "HR%",    direction="decreasing", weight_col="HR_den")

ubb_L  = iso_smooth(df, "CON vL_q",    "uBB%",   direction="decreasing", weight_col="uBB_den")
ubb_R  = iso_smooth(df, "CON vR_q",    "uBB%",   direction="decreasing", weight_col="uBB_den")

# BABIP is modeled off PBABIP (Excel does this; you previously hard-anchored it).
babip_L = iso_smooth(df, "PBABIP vL_q", "BABIP%", direction="decreasing", weight_col="BABIP_den")
babip_R = iso_smooth(df, "PBABIP vR_q", "BABIP%", direction="decreasing", weight_col="BABIP_den")

# Running game off Hold: attempt rate and success rate
sba_H  = iso_smooth(df, "HLD_q", "SBA%", direction="decreasing", weight_col="SBA_den")
sb_H   = iso_smooth(df, "HLD_q", "SB%",  direction="decreasing", weight_col="SB_den")

# Clean tiny SBA/SB for nicer output
MIN_TINY = 1e-4
sba_H[sba_H < MIN_TINY] = 0.0
sb_H[sb_H < MIN_TINY] = 0.0

# Average vL/vR tables (keep your prior behavior)
k_avg     = ((k_L + k_R) / 2.0).rename("K%")
hr_avg    = ((hr_L + hr_R) / 2.0).rename("HR%")
ubb_avg   = ((ubb_L + ubb_R) / 2.0).rename("uBB%")
babip_avg = ((babip_L + babip_R) / 2.0).rename("BABIP%")

rates_df = pd.DataFrame({
    "Rating": ratings_grid,
    "K%":     k_avg.values,
    "HR%":    hr_avg.values,
    "uBB%":   ubb_avg.values,
    "BABIP%": babip_avg.values,
    "SBA%":   sba_H.values,
    "SB%":    sb_H.values,
    "HBP_per_BF": league_HBP_per_BF,
    "CI_per_BF":  league_CI_per_BF,
    "SF_per_BF":  league_SF_per_BF,
})

# ---------- WRITE ----------
with pd.ExcelWriter(out_file, engine="openpyxl") as w:
    rates_df.to_excel(w, "Rates", index=False)
    uplift.to_excel(w, sheet_name="relative_adjustments", index=False)
