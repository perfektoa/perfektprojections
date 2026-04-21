#!/usr/bin/env python
# Build BF-based per-pitcher projections from rating tables.
# Output: pitching_projections.xlsx, single sheet "Projections"
#
# FIX: Your Rates sheet does NOT have "CS%". It has "SBA%" + "SB%".
# This script supports BOTH table formats:
#   A) Legacy: SB% and CS% are per-BF rates
#   B) Current (your table): SBA% = attempts per (uBB+HBP+CI+1B), SB% = success given attempt
#      -> we compute SB/CS counts from base-opps.
#
# ADD: Cincinnati park-adjusted outputs at the end (50% home games):
#   - 1B/2B/3B/HR projections adjusted for park
#   - wOBA_CIN50 and RA9_CIN50
#
# FIX (IMPORTANT): RA9 calculation was too flat. We now use a wOBA-scale based
# linear conversion instead of proportional scaling.

import pandas as pd
import numpy as np

# ----------------------------- FILES ------------------------------
TABLES_FILE = "pitching_rating_tables_smoothed.xlsx"
MLB_FILE    = "player_search___shortlist_player_shortlist_pitching_projections.csv"
AAA_FILE    = "player_search___shortlist_player_shortlist_pitching_projections2.csv"
OUT_FILE    = "pitching_projections.xlsx"

# ---------------------------- CONFIG ------------------------------
DEFAULT_BF_SP = 650
DEFAULT_BF_RP = 250

LHB_SHARE_RHP = 0.40
LHB_SHARE_LHP = 0.25

BIP_HIT_SHARE = {"1B": 0.74, "2B": 0.23, "3B": 0.03}

WOBA_WEIGHTS = {
    "BB": 0.69,
    "HBP": 0.72,
    "1B": 0.89,
    "2B": 1.27,
    "3B": 1.62,
    "HR": 2.10,
}

# ---- YOUR LEAGUE AVERAGES ----
LG_WOBA = 0.319
LG_RA9  = 4.32

# ---- NEW: RA9 calibration constants ----
# These two control how strongly wOBA translates into runs allowed.
# Start with these; you can later compute BF_PER_9 from league totals if desired.
WOBA_SCALE = 1.25
BF_PER_9   = 38.5

ROLE_DELTA_SCALER = 1.0
ROLE_DELTAS = {
    "SP": {"K%": -0.00088716, "uBB%": -0.00370694, "HR%":  0.00008642, "BABIP%": -0.00001555},
    "RP": {"K%":  0.00142773, "uBB%":  0.00586528, "HR%": -0.00012712, "BABIP%":  0.00001279},
}

# ---------------------- PARK FACTORS (CIN) ------------------------
HOME_GAME_SHARE = 0.50
CIN_AVG_LHB = 0.98
CIN_AVG_RHB = 1.00
CIN_2B      = 0.99
CIN_3B      = 0.915
CIN_HR_LHB  = 1.20
CIN_HR_RHB  = 1.22

# --------------------------- LOAD TABLES --------------------------
rates_df  = pd.read_excel(TABLES_FILE, sheet_name="Rates").copy()
uplift_df = pd.read_excel(TABLES_FILE, sheet_name="relative_adjustments").copy()

rates_df["Rating"] = rates_df["Rating"].astype(int)
rates_df = rates_df.set_index("Rating").sort_index()

grid = rates_df.index.to_numpy(dtype=float)

K_arr     = rates_df["K%"].to_numpy(dtype=float)
HR_arr    = rates_df["HR%"].to_numpy(dtype=float)
uBB_arr   = rates_df["uBB%"].to_numpy(dtype=float)
BABIP_arr = rates_df["BABIP%"].to_numpy(dtype=float)

has_cs_pct  = "CS%" in rates_df.columns
has_sba_pct = "SBA%" in rates_df.columns

if has_cs_pct:
    SB_arr = rates_df["SB%"].to_numpy(dtype=float)
    CS_arr = rates_df["CS%"].to_numpy(dtype=float)
else:
    if not has_sba_pct:
        raise KeyError("Rates sheet missing both CS% and SBA%. Need either (SB%,CS%) or (SBA%,SB%).")
    SBA_arr     = rates_df["SBA%"].to_numpy(dtype=float)
    SB_succ_arr = rates_df["SB%"].to_numpy(dtype=float)

HBP_per_BF = float(rates_df["HBP_per_BF"].iloc[0]) if "HBP_per_BF" in rates_df.columns else 0.0
CI_per_BF  = float(rates_df["CI_per_BF"].iloc[0])  if "CI_per_BF"  in rates_df.columns else 0.0
SF_per_BF  = float(rates_df["SF_per_BF"].iloc[0])  if "SF_per_BF"  in rates_df.columns else 0.0

uplift_df["mlb_rating"] = uplift_df["mlb_rating"].astype(float)
uplift_df["aaa_rating"] = uplift_df["aaa_rating"].astype(float)
UPLIFT_MAP = {
    (row["rating"], float(row["mlb_rating"]), float(row["aaa_rating"])): float(row["adj_rating"])
    for _, row in uplift_df.iterrows()
}

# ------------------------- LOAD PLAYER FILES ----------------------
mlb = pd.read_csv(MLB_FILE, low_memory=False)
aaa = pd.read_csv(AAA_FILE, low_memory=False)

KEY = ["ID"] if ("ID" in mlb.columns and "ID" in aaa.columns) else ["Name"]

RATING_ATTRS = [
    "STU vL","STU vR",
    "HRR vL","HRR vR",
    "CON vL","CON vR",
    "PBABIP vL","PBABIP vR",
    "HLD"
]

for c in RATING_ATTRS:
    if c not in mlb.columns:
        mlb[c] = 20

aaa_ratings = aaa[KEY + [c for c in RATING_ATTRS if c != "HLD"]] if not aaa.empty else None

if aaa_ratings is not None:
    df = mlb.merge(aaa_ratings, on=KEY, how="left", suffixes=("", "_AAA"))
else:
    df = mlb.copy()
    for c in [c for c in RATING_ATTRS if c != "HLD"]:
        df[c + "_AAA"] = np.nan

for c in ["BF","HP","SF","CI","SB","CS"]:
    if c not in df.columns:
        df[c] = 0
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(lower=0)

# ----------------------------- ROLE -------------------------------
def role_from_pos(pos) -> str:
    s = str(pos).upper()
    if "SP" in s:
        return "SP"
    if ("RP" in s) or ("CL" in s):
        return "RP"
    return "SP"

df["Role"] = df["POS"].apply(role_from_pos) if "POS" in df.columns else "SP"

# --------------------------- PLATOON MIX --------------------------
if "T" in df.columns:
    is_lhp = df["T"].astype(str).str.upper().str.startswith("L")
    df["LHB_share"] = np.where(is_lhp, LHB_SHARE_LHP, LHB_SHARE_RHP)
else:
    df["LHB_share"] = LHB_SHARE_RHP

# ----------------------------- HELPERS ----------------------------
def q5f_series(s: pd.Series) -> np.ndarray:
    x = pd.to_numeric(s, errors="coerce").fillna(20.0).to_numpy(dtype=float)
    x = 5.0 * np.round(x / 5.0)
    return np.clip(x, 20.0, 100.0)

def interp_arr(y_arr: np.ndarray, r: np.ndarray) -> np.ndarray:
    x = np.clip(r.astype(float), 20.0, 100.0)
    return np.interp(x, grid, y_arr)

def adj_with_uplift_series(attr: str, mlb_vals: pd.Series, aaa_vals: pd.Series) -> np.ndarray:
    mlb_q = q5f_series(mlb_vals)
    aaa_filled = aaa_vals.copy().where(pd.notna(aaa_vals), mlb_vals)
    aaa_q = q5f_series(aaa_filled)
    out = np.empty_like(mlb_q, dtype=float)
    for i, (m, a) in enumerate(zip(mlb_q, aaa_q)):
        out[i] = UPLIFT_MAP.get((attr, float(m), float(a)), float(m))
    return out

def apply_role_deltas(rate: np.ndarray, metric_key: str, roles: pd.Series) -> np.ndarray:
    d_sp = ROLE_DELTAS["SP"][metric_key] * ROLE_DELTA_SCALER
    d_rp = ROLE_DELTAS["RP"][metric_key] * ROLE_DELTA_SCALER
    r = roles.to_numpy()
    delta = np.where(r == "RP", d_rp, np.where(r == "SP", d_sp, 0.0))
    return rate + delta

# --------------------- ADJUSTED RATINGS (vL/vR) -------------------
for side in ["vL", "vR"]:
    df[f"STU {side}_adj"] = adj_with_uplift_series(
        f"STU {side}", df[f"STU {side}"], df.get(f"STU {side}_AAA", df[f"STU {side}"])
    )
    df[f"HRR {side}_adj"] = adj_with_uplift_series(
        f"HRR {side}", df[f"HRR {side}"], df.get(f"HRR {side}_AAA", df[f"HRR {side}"])
    )
    df[f"CON {side}_adj"] = adj_with_uplift_series(
        f"CON {side}", df[f"CON {side}"], df.get(f"CON {side}_AAA", df[f"CON {side}"])
    )
    df[f"PBABIP {side}_adj"] = q5f_series(df[f"PBABIP {side}"])

df["HLD_q"] = q5f_series(df["HLD"])

# --------------------- SIDE RATES FROM TABLES ---------------------
K_vL     = interp_arr(K_arr,     df["STU vL_adj"].to_numpy(float))
K_vR     = interp_arr(K_arr,     df["STU vR_adj"].to_numpy(float))
HR_vL    = interp_arr(HR_arr,    df["HRR vL_adj"].to_numpy(float))
HR_vR    = interp_arr(HR_arr,    df["HRR vR_adj"].to_numpy(float))
uBB_vL   = interp_arr(uBB_arr,   df["CON vL_adj"].to_numpy(float))
uBB_vR   = interp_arr(uBB_arr,   df["CON vR_adj"].to_numpy(float))
BABIP_vL = interp_arr(BABIP_arr, df["PBABIP vL_adj"].to_numpy(float))
BABIP_vR = interp_arr(BABIP_arr, df["PBABIP vR_adj"].to_numpy(float))

roles = df["Role"]
K_vL     = apply_role_deltas(K_vL,     "K%",     roles)
K_vR     = apply_role_deltas(K_vR,     "K%",     roles)
HR_vL    = apply_role_deltas(HR_vL,    "HR%",    roles)
HR_vR    = apply_role_deltas(HR_vR,    "HR%",    roles)
uBB_vL   = apply_role_deltas(uBB_vL,   "uBB%",   roles)
uBB_vR   = apply_role_deltas(uBB_vR,   "uBB%",   roles)
BABIP_vL = apply_role_deltas(BABIP_vL, "BABIP%", roles)
BABIP_vR = apply_role_deltas(BABIP_vR, "BABIP%", roles)

K_vL     = np.clip(K_vL,     0.0, 0.90)
K_vR     = np.clip(K_vR,     0.0, 0.90)
HR_vL    = np.clip(HR_vL,    0.0, 0.50)
HR_vR    = np.clip(HR_vR,    0.0, 0.50)
uBB_vL   = np.clip(uBB_vL,   0.0, 0.90)
uBB_vR   = np.clip(uBB_vR,   0.0, 0.90)
BABIP_vL = np.clip(BABIP_vL, 0.0, 0.90)
BABIP_vR = np.clip(BABIP_vR, 0.0, 0.90)

# -------------------------- BLENDED RATES -------------------------
wL = df["LHB_share"].to_numpy(dtype=float)
wR = 1.0 - wL

K_rate     = np.clip(K_vL*wL     + K_vR*wR,     0.0, 0.90)
HR_rate    = np.clip(HR_vL*wL    + HR_vR*wR,    0.0, 0.50)
uBB_rate   = np.clip(uBB_vL*wL   + uBB_vR*wR,   0.0, 0.90)
BABIP_rate = np.clip(BABIP_vL*wL + BABIP_vR*wR, 0.0, 0.90)

# ------------------------------ BF -------------------------------
BF = df["BF"].astype(float).to_numpy()
bf_default = np.where(df["Role"].to_numpy() == "RP", DEFAULT_BF_RP, DEFAULT_BF_SP)
BF = np.where(BF > 0, BF, bf_default)

HBP_rate = np.full_like(K_rate, HBP_per_BF, dtype=float)
CI_rate  = np.full_like(K_rate, CI_per_BF,  dtype=float)
SF_rate  = np.full_like(K_rate, SF_per_BF,  dtype=float)

# ------------------------- EVENT PARTITION ------------------------
BIP_rate = np.clip(1.0 - (K_rate + HR_rate + uBB_rate + HBP_rate + CI_rate), 0.0, 1.0)
H_on_BIP = BIP_rate * BABIP_rate
OIP_rate = BIP_rate - H_on_BIP

s1, s2, s3 = BIP_HIT_SHARE["1B"], BIP_HIT_SHARE["2B"], BIP_HIT_SHARE["3B"]
tot_s = s1 + s2 + s3
s1, s2, s3 = s1/tot_s, s2/tot_s, s3/tot_s

rate_1B = H_on_BIP * s1
rate_2B = H_on_BIP * s2
rate_3B = H_on_BIP * s3

# ------------------------------ COUNTS ----------------------------
cnt_K   = BF * K_rate
cnt_HR  = BF * HR_rate
cnt_uBB = BF * uBB_rate
cnt_HBP = BF * HBP_rate
cnt_CI  = BF * CI_rate
cnt_1B  = BF * rate_1B
cnt_2B  = BF * rate_2B
cnt_3B  = BF * rate_3B
cnt_OIP = BF * OIP_rate
cnt_SF  = BF * SF_rate

# -------------------- SB / CS (FIXED) -----------------------------
HLD_q = df["HLD_q"].to_numpy(float)

if has_cs_pct:
    SB_rate = np.clip(interp_arr(SB_arr, HLD_q), 0.0, 1.0)
    CS_rate = np.clip(interp_arr(CS_arr, HLD_q), 0.0, 1.0)
    cnt_SB  = BF * SB_rate
    cnt_CS  = BF * CS_rate
else:
    SBA_rate = np.clip(interp_arr(SBA_arr, HLD_q), 0.0, 1.0)
    SB_succ  = np.clip(interp_arr(SB_succ_arr, HLD_q), 0.0, 1.0)

    base_opp_rate = np.clip(uBB_rate + HBP_rate + CI_rate + rate_1B, 0.0, 1.0)
    cnt_base_opps = BF * base_opp_rate

    cnt_SBA = cnt_base_opps * SBA_rate
    cnt_SB  = cnt_SBA * SB_succ
    cnt_CS  = np.maximum(cnt_SBA - cnt_SB, 0.0)

# ---------------------------- wOBA & RA9 ---------------------------
BB_total = cnt_uBB + cnt_CI

woba_num = (
    WOBA_WEIGHTS["BB"]  * BB_total +
    WOBA_WEIGHTS["HBP"] * cnt_HBP +
    WOBA_WEIGHTS["1B"]  * cnt_1B  +
    WOBA_WEIGHTS["2B"]  * cnt_2B  +
    WOBA_WEIGHTS["3B"]  * cnt_3B  +
    WOBA_WEIGHTS["HR"]  * cnt_HR
)

woba_den = np.maximum(BF, 1e-9)
wOBA = woba_num / woba_den

# ---- FIXED RA9 (linear wOBA-scale conversion) ----
wRAA_per_PA = (wOBA - LG_WOBA) / WOBA_SCALE
RA9 = LG_RA9 + (wRAA_per_PA * BF_PER_9)
RA9 = np.clip(RA9, 0.0, 20.0)

# --------------- PARK-ADJUSTED (CIN) @ 50% HOME -------------------
BF_L = BF * wL
BF_R = BF * wR

BIP_vL = np.clip(1.0 - (K_vL + HR_vL + uBB_vL + HBP_rate + CI_rate), 0.0, 1.0)
BIP_vR = np.clip(1.0 - (K_vR + HR_vR + uBB_vR + HBP_rate + CI_rate), 0.0, 1.0)

H_on_BIP_vL = BIP_vL * BABIP_vL
H_on_BIP_vR = BIP_vR * BABIP_vR

rate_1B_vL = H_on_BIP_vL * s1
rate_2B_vL = H_on_BIP_vL * s2
rate_3B_vL = H_on_BIP_vL * s3

rate_1B_vR = H_on_BIP_vR * s1
rate_2B_vR = H_on_BIP_vR * s2
rate_3B_vR = H_on_BIP_vR * s3

cnt_1B_L = BF_L * rate_1B_vL
cnt_2B_L = BF_L * rate_2B_vL
cnt_3B_L = BF_L * rate_3B_vL
cnt_HR_L = BF_L * HR_vL

cnt_1B_R = BF_R * rate_1B_vR
cnt_2B_R = BF_R * rate_2B_vR
cnt_3B_R = BF_R * rate_3B_vR
cnt_HR_R = BF_R * HR_vR

cnt_1B_CIN = (cnt_1B_L * CIN_AVG_LHB) + (cnt_1B_R * CIN_AVG_RHB)
cnt_2B_CIN = (cnt_2B_L + cnt_2B_R) * CIN_2B
cnt_3B_CIN = (cnt_3B_L + cnt_3B_R) * CIN_3B
cnt_HR_CIN = (cnt_HR_L * CIN_HR_LHB) + (cnt_HR_R * CIN_HR_RHB)

h = HOME_GAME_SHARE
cnt_1B_CIN50 = (1.0 - h) * cnt_1B + h * cnt_1B_CIN
cnt_2B_CIN50 = (1.0 - h) * cnt_2B + h * cnt_2B_CIN
cnt_3B_CIN50 = (1.0 - h) * cnt_3B + h * cnt_3B_CIN
cnt_HR_CIN50 = (1.0 - h) * cnt_HR + h * cnt_HR_CIN

woba_num_CIN50 = (
    WOBA_WEIGHTS["BB"]  * BB_total +
    WOBA_WEIGHTS["HBP"] * cnt_HBP +
    WOBA_WEIGHTS["1B"]  * cnt_1B_CIN50 +
    WOBA_WEIGHTS["2B"]  * cnt_2B_CIN50 +
    WOBA_WEIGHTS["3B"]  * cnt_3B_CIN50 +
    WOBA_WEIGHTS["HR"]  * cnt_HR_CIN50
)

wOBA_CIN50 = woba_num_CIN50 / woba_den

# ---- FIXED RA9_CIN50 (same conversion) ----
wRAA_per_PA_CIN50 = (wOBA_CIN50 - LG_WOBA) / WOBA_SCALE
RA9_CIN50 = LG_RA9 + (wRAA_per_PA_CIN50 * BF_PER_9)
RA9_CIN50 = np.clip(RA9_CIN50, 0.0, 20.0)

# ------------------------------ OUTPUT ----------------------------
out = df.copy()

out["K%_vL"]     = K_vL
out["K%_vR"]     = K_vR
out["HR%_vL"]    = HR_vL
out["HR%_vR"]    = HR_vR
out["uBB%_vL"]   = uBB_vL
out["uBB%_vR"]   = uBB_vR
out["BABIP%_vL"] = BABIP_vL
out["BABIP%_vR"] = BABIP_vR

out["K%"]     = K_rate
out["uBB%"]   = uBB_rate
out["HR%"]    = HR_rate
out["BABIP%"] = BABIP_rate

out["BF_proj"]  = BF
out["K_proj"]   = cnt_K
out["uBB_proj"] = cnt_uBB
out["HBP_proj"] = cnt_HBP
out["CI_proj"]  = cnt_CI
out["HR_proj"]  = cnt_HR
out["1B_proj"]  = cnt_1B
out["2B_proj"]  = cnt_2B
out["3B_proj"]  = cnt_3B
out["OIP_proj"] = cnt_OIP
out["SB_proj"]  = cnt_SB
out["CS_proj"]  = cnt_CS
out["SF_proj"]  = cnt_SF

out["wOBA"] = wOBA
out["RA9"]  = RA9

out["1B_proj_CIN50"] = cnt_1B_CIN50
out["2B_proj_CIN50"] = cnt_2B_CIN50
out["3B_proj_CIN50"] = cnt_3B_CIN50
out["HR_proj_CIN50"] = cnt_HR_CIN50
out["wOBA_CIN50"]    = wOBA_CIN50
out["RA9_CIN50"]     = RA9_CIN50

with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as w:
    out.to_excel(w, sheet_name="Projections", index=False)

print(f"Wrote {OUT_FILE}")
