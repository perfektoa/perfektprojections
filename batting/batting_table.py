#!/usr/bin/env python
# Build batting & fielding rating tables from 2016 stats.
# Output: batting_fielding_rating_tables.xlsx
#
# Sheets:
#   BattingRates:
#       Rating, K%, BB%, HR%, BABIP%, XBH_on_HIP, TRIPLE_on_XBH,
#       HBP_per_PA, SF_per_PA, CI_per_PA
#   FieldingRates:
#       Rating, IF_RNG_play%, IF_ARM_play%, OF_RNG_play%,
#               C_FRM_perG, C_RTO%, IF_ch_per_G, OF_ch_per_G, C_SBA_per_G

import pandas as pd
import numpy as np
from sklearn.isotonic import IsotonicRegression

# ---------- FILES ----------
NEW_FILE    = "player_search___shortlist_player_shortlist_batting_table.csv"
MASTER_FILE = "batting_training_master.csv"
OUT_FILE    = "batting_fielding_rating_tables.xlsx"

# ---------- LOAD / EXTEND MASTER ----------
df_new = pd.read_csv(NEW_FILE, low_memory=False)

try:
    df_master = pd.read_csv(MASTER_FILE, low_memory=False)
    df_all = pd.concat([df_master, df_new], ignore_index=True).drop_duplicates()
except FileNotFoundError:
    df_all = df_new.copy()

df_all.to_csv(MASTER_FILE, index=False)
df = df_all.copy()

# ---------- BASIC STAT CLEANUP ----------
needed = [
    "AB","BB","IBB","HP","SF","CI","SO",
    "1B","2B","3B","HR","SB","CS","G",
    "SBA","RTO",
    "BIZ-R","BIZ-Rm","BIZ-L","BIZ-Lm",
    "BIZ-E","BIZ-Em","BIZ-U","BIZ-Um","BIZ-Z","BIZ-Zm",
    "FRM",
]

for c in needed:
    if c not in df.columns:
        df[c] = 0

for c in needed:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(lower=0)

# Plate appearances
df["PA"] = df["AB"] + df["BB"] + df["HP"] + df["SF"] + df["CI"]
df = df[df["PA"] > 0].copy()

# League-average HBP / SF / CI per PA (for projections)
tot_PA = df["PA"].sum()
if tot_PA > 0:
    HBP_per_PA = df["HP"].sum() / tot_PA
    SF_per_PA  = df["SF"].sum() / tot_PA
    CI_per_PA  = df["CI"].sum() / tot_PA
else:
    HBP_per_PA = SF_per_PA = CI_per_PA = 0.0

# Batting event rates (avoid name clash with BABIP rating)
df["uBB"]      = (df["BB"] - df["IBB"]).clip(lower=0)
df["K_rate"]   = df["SO"] / df["PA"]
df["BB_rate"]  = df["uBB"] / df["PA"]
df["HR_rate"]  = df["HR"] / df["PA"]

df["BIP"]        = (df["AB"] - df["SO"] - df["HR"]).clip(lower=0)
df["H_BIP"]      = df["1B"] + df["2B"] + df["3B"]
df["BABIP_stat"] = df["H_BIP"] / df["BIP"].replace(0, np.nan)

df["XBH_on_HIP"]    = (df["2B"] + df["3B"]) / df["H_BIP"].replace(0, np.nan)
df["TRIPLE_on_XBH"] = df["3B"] / (df["2B"] + df["3B"]).replace(0, np.nan)

# Catcher framing rate (runs per game)
df["C_FRM_rate"] = df["FRM"] / df["G"].replace(0, np.nan)

# Fielding chances & plays from BIZ columns
df["BIZ_chances"] = df[["BIZ-R","BIZ-L","BIZ-E","BIZ-U","BIZ-Z"]].sum(axis=1)
df["BIZ_plays"]   = df[["BIZ-Rm","BIZ-Lm","BIZ-Em","BIZ-Um","BIZ-Zm"]].sum(axis=1)
df["BIZ_play_pct"] = df["BIZ_plays"] / df["BIZ_chances"].replace(0, np.nan)

# Catcher arm: runners thrown out per attempt
df["C_RTO_pct"] = df["RTO"] / df["SBA"].replace(0, np.nan)

# ---------- POSITION MASKS + LEAGUE CHANCES PER GAME ----------
infield_rng_pos  = {"2B","3B","SS"}      # 1B excluded from regression
outfield_rng_pos = {"LF","CF","RF"}

def pos_mask(positions):
    if "POS" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["POS"].astype(str).isin(positions)

mask_if = pos_mask(infield_rng_pos) & (df["BIZ_chances"] > 0)
mask_of = pos_mask(outfield_rng_pos) & (df["BIZ_chances"] > 0)
mask_c  = df.get("POS", pd.Series("", index=df.index)).astype(str).eq("C")

def _safe_ratio(num, den):
    num = float(num); den = float(den)
    if not np.isfinite(num) or not np.isfinite(den) or den <= 0:
        return 0.0
    return num / den

IF_ch_per_G = _safe_ratio(
    df.loc[mask_if, "BIZ_chances"].sum(),
    df.loc[mask_if, "G"].replace(0, np.nan).sum()
)
OF_ch_per_G = _safe_ratio(
    df.loc[mask_of, "BIZ_chances"].sum(),
    df.loc[mask_of, "G"].replace(0, np.nan).sum()
)
C_SBA_per_G = _safe_ratio(
    df.loc[mask_c, "SBA"].sum(),
    df.loc[mask_c, "G"].replace(0, np.nan).sum()
)

# ---------- RATING CLEANUP ----------
def _coerce_rating(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().replace({"-": "20", "": "20"})
    s = pd.to_numeric(s, errors="coerce").fillna(20.0)
    return s.clip(20, 100)

rating_cols = [
    "BABIP","GAP","POW","EYE","K's",
    "C FRM","C ARM","IF RNG","IF ARM","OF RNG",
]

for col in rating_cols:
    if col in df.columns:
        df[col] = _coerce_rating(df[col])
    else:
        df[col] = 20.0

def _q5(s: pd.Series) -> pd.Series:
    return (5 * np.round(s / 5.0)).clip(20, 100).astype(int)

for col in rating_cols:
    df[col + "_q"] = _q5(df[col])

ratings_grid = np.arange(20, 101, 5, dtype=int)

# ---------- ISOTONIC HELPERS ----------
def _logit(p, eps=1e-6):
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))

def _inv_logit(z):
    return 1.0 / (1.0 + np.exp(-z))

def bucket_mean(df_local, rating_col_q, value_col, mask=None, denom_col=None):
    if mask is not None:
        df_local = df_local[mask].copy()

    X, y, w = [], [], []

    for r in ratings_grid:
        m = (df_local[rating_col_q] == r) & df_local[value_col].notna()
        if not m.any():
            continue

        s = df_local.loc[m, value_col].astype(float)

        if denom_col:
            d = df_local.loc[m, denom_col].astype(float).clip(lower=0)
            if d.sum() > 0:
                X.append(float(r))
                y.append(float(np.average(s, weights=d)))
                w.append(float(d.sum()))
            else:
                X.append(float(r))
                y.append(float(s.mean()))
                w.append(float(len(s)))
        else:
            X.append(float(r))
            y.append(float(s.mean()))
            w.append(float(len(s)))

    return np.array(X), np.array(y), np.array(w)

def iso_smooth(df_local, rating_col_q, value_col,
               direction="increasing", mask=None, denom_col=None):
    X, y, w = bucket_mean(df_local, rating_col_q, value_col,
                          mask=mask, denom_col=denom_col)

    if X.size == 0:
        return pd.Series(0.0, index=ratings_grid)
    if X.size == 1:
        return pd.Series(np.repeat(y[0], len(ratings_grid)), index=ratings_grid)

    # probs via logit, raw rates otherwise
    if ("pct" in value_col) or value_col.endswith("rate") or "BABIP" in value_col or "XBH" in value_col:
        z = _logit(y)
        flip = -1.0 if direction == "decreasing" else 1.0
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
        iso.fit(X, flip * z, sample_weight=w)
        z_grid = iso.predict(ratings_grid.astype(float))
        y_hat = _inv_logit(flip * z_grid)
        return pd.Series(np.clip(y_hat, 0.0, 1.0), index=ratings_grid)
    else:
        iso = IsotonicRegression(
            increasing=(direction == "increasing"),
            out_of_bounds="clip"
        )
        iso.fit(X, y, sample_weight=w)
        y_hat = iso.predict(ratings_grid.astype(float))
        return pd.Series(y_hat, index=ratings_grid)

# ---------- BATTING CURVES ----------
k_curve   = iso_smooth(df, "K's_q",   "K_rate",      direction="decreasing", denom_col="PA")
bb_curve  = iso_smooth(df, "EYE_q",   "BB_rate",     direction="increasing", denom_col="PA")
hr_curve  = iso_smooth(df, "POW_q",   "HR_rate",     direction="increasing", denom_col="PA")
bab_curve = iso_smooth(df, "BABIP_q", "BABIP_stat",  direction="increasing", denom_col="BIP")
xbh_curve = iso_smooth(df, "GAP_q",   "XBH_on_HIP",  direction="increasing", denom_col="H_BIP")
tri_curve = iso_smooth(df, "GAP_q",   "TRIPLE_on_XBH", direction="increasing")

# ---------- FIELDING CURVES ----------
if_rng_curve = iso_smooth(
    df, "IF RNG_q", "BIZ_play_pct",
    direction="increasing", mask=mask_if, denom_col="BIZ_chances"
)
of_rng_curve = iso_smooth(
    df, "OF RNG_q", "BIZ_play_pct",
    direction="increasing", mask=mask_of, denom_col="BIZ_chances"
)
c_frm_curve  = iso_smooth(
    df, "C FRM_q", "C_FRM_rate",
    direction="increasing", mask=mask_c, denom_col="G"
)
c_arm_curve  = iso_smooth(
    df, "C ARM_q", "C_RTO_pct",
    direction="increasing", mask=mask_c, denom_col="SBA"
)

# ---------- TABLE DATAFRAMES ----------
rates_batting = pd.DataFrame({
    "Rating":        ratings_grid,
    "K%":            k_curve.values,
    "BB%":           bb_curve.values,
    "HR%":           hr_curve.values,
    "BABIP%":        bab_curve.values,
    "XBH_on_HIP":    xbh_curve.values,
    "TRIPLE_on_XBH": tri_curve.values,
    "HBP_per_PA":    HBP_per_PA,
    "SF_per_PA":     SF_per_PA,
    "CI_per_PA":     CI_per_PA,
})

rates_fielding = pd.DataFrame({
    "Rating":        ratings_grid,
    "IF_RNG_play%":  if_rng_curve.values,
    "IF_ARM_play%":  if_rng_curve.values,  # same curve for now
    "OF_RNG_play%":  of_rng_curve.values,
    "C_FRM_perG":    c_frm_curve.values,
    "C_RTO%":        c_arm_curve.values,
    "IF_ch_per_G":   IF_ch_per_G,
    "OF_ch_per_G":   OF_ch_per_G,
    "C_SBA_per_G":   C_SBA_per_G,
})

# ---------- WRITE ----------
with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as w:
    rates_batting.to_excel(w, sheet_name="BattingRates", index=False)
    rates_fielding.to_excel(w, sheet_name="FieldingRates", index=False)
