#!/usr/bin/env python
# Build per-batter batting + fielding projections from rating tables, with vR/vL splits.
# Output: batting_fielding_projections.xlsx

import pandas as pd
import numpy as np
from bisect import bisect_left

# ---------- FILES ----------
TABLES_FILE = "batting_fielding_rating_tables.xlsx"
MLB_FILE    = "player_search___shortlist_player_shortlist_batting_proj.csv"
AAA_FILE    = "player_search___shortlist_player_shortlist_batting_proj2.csv"
OUT_FILE    = "batting_fielding_projections.xlsx"

DEFAULT_PA  = 600

# 2016 env (approx)
WOBA_WEIGHTS = {
    "BB":  0.69,
    "HBP": 0.72,
    "1B":  0.89,
    "2B":  1.27,
    "3B":  1.62,
    "HR":  2.10,
}
LEAGUE_WOBA = 0.318
WOBA_SCALE  = 1.21       # 2016-ish wOBA scale
RUNS_PER_WIN = 9.2
REPLACEMENT_RUNS_PER_600_PA = 20.0

# ---------- LOAD TABLES ----------
bat_rates = pd.read_excel(TABLES_FILE, sheet_name="BattingRates")
fld_rates = pd.read_excel(TABLES_FILE, sheet_name="FieldingRates")

bat_rates["Rating"] = bat_rates["Rating"].astype(int)
fld_rates["Rating"] = fld_rates["Rating"].astype(int)

grid = np.array(sorted(bat_rates["Rating"].unique()), dtype=float)

def _curve(col):
    return bat_rates.set_index("Rating")[col]

K_curve      = _curve("K%")
BB_curve     = _curve("BB%")
HR_curve     = _curve("HR%")
BABIP_curve  = _curve("BABIP%")
XBH_curve    = _curve("XBH_on_HIP")
TRI_curve    = _curve("TRIPLE_on_XBH")

# league-average small-ball rates from table
HBP_rate_const = float(bat_rates["HBP_per_PA"].iloc[0])
SF_rate_const  = float(bat_rates["SF_per_PA"].iloc[0])
CI_rate_const  = float(bat_rates["CI_per_PA"].iloc[0])

fld_idx       = fld_rates.set_index("Rating")
IF_rng_curve  = fld_idx["IF_RNG_play%"]
OF_rng_curve  = fld_idx["OF_RNG_play%"]
C_FRM_curve   = fld_idx["C_FRM_perG"]
C_RTO_curve   = fld_idx["C_RTO%"]

IF_ch_per_G   = float(fld_rates["IF_ch_per_G"].iloc[0])
OF_ch_per_G   = float(fld_rates["OF_ch_per_G"].iloc[0])
C_SBA_per_G   = float(fld_rates["C_SBA_per_G"].iloc[0])

# sanity caps on chances per game so fielding can't blow up
IF_ch_per_G = min(IF_ch_per_G, 4.0)   # per infielder
OF_ch_per_G = min(OF_ch_per_G, 2.7)   # per outfielder

def interp(series_by_grid, r):
    x = float(np.clip(r, 20.0, 100.0))
    i = bisect_left(grid, x)
    if i == 0:
        return float(series_by_grid.loc[int(grid[0])])
    if i >= len(grid):
        return float(series_by_grid.loc[int(grid[-1])])
    x0, x1 = grid[i-1], grid[i]
    y0 = float(series_by_grid.loc[int(x0)])
    y1 = float(series_by_grid.loc[int(x1)])
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)

# ---------- LOAD PLAYERS ----------
mlb = pd.read_csv(MLB_FILE, low_memory=False)
try:
    aaa = pd.read_csv(AAA_FILE, low_memory=False)
except FileNotFoundError:
    aaa = pd.DataFrame(columns=mlb.columns)

KEY = ["ID"] if ("ID" in mlb.columns and "ID" in aaa.columns) else ["Name"]

RATING_COLS = [
    "BABIP","GAP","POW","EYE","K's",
    "C FRM","C ARM","IF RNG","OF RNG",
    "BA vL","GAP vL","POW vL","EYE vL","K vL",
    "BA vR","GAP vR","POW vR","EYE vR","K vR",
]

if not aaa.empty:
    df = mlb.merge(
        aaa[KEY + [c for c in RATING_COLS if c in aaa.columns]],
        on=KEY,
        how="left",
        suffixes=("", "_AAA"),
    )
else:
    df = mlb.copy()
    for c in RATING_COLS:
        df[c + "_AAA"] = np.nan

# ---------- RATING CLEANUP ----------
def _coerce_rating(v):
    try:
        v = float(v)
    except Exception:
        v = 20.0
    if np.isnan(v):
        v = 20.0
    return float(np.clip(v, 20.0, 100.0))

def q5f(x):
    v = _coerce_rating(x)
    return float(np.clip(5.0 * np.round(v / 5.0), 20.0, 100.0))

base_cols = ["BABIP","GAP","POW","EYE","K's","C FRM","C ARM","IF RNG","OF RNG"]
for col in base_cols:
    if col in df.columns:
        df[col] = df[col].apply(_coerce_rating)
    else:
        df[col] = 20.0

# fill split ratings from overall where missing
for side in ["vL","vR"]:
    for base, split_name in [
        ("BABIP","BA"),
        ("GAP","GAP"),
        ("POW","POW"),
        ("EYE","EYE"),
        ("K's","K"),
    ]:
        col = f"{split_name} {side}"
        if col not in df.columns:
            df[col] = df[base]
        else:
            df[col] = [
                _coerce_rating(x) if not pd.isna(x) else b
                for x, b in zip(df[col], df[base])
            ]

# ---------- PA / GAMES ----------
for c in ["AB","BB","HP","SF","CI"]:
    if c not in df.columns:
        df[c] = 0
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(lower=0)

if "PA" in df.columns:
    df["PA_calc"] = pd.to_numeric(df["PA"], errors="coerce").fillna(0)
else:
    df["PA_calc"] = df["AB"] + df["BB"] + df["HP"] + df["SF"] + df["CI"]

PA = df["PA_calc"].astype(float)
PA[PA <= 0] = DEFAULT_PA

if "G" not in df.columns:
    df["G"] = 0
df["G"] = pd.to_numeric(df["G"], errors="coerce").fillna(0).clip(lower=0)
G_raw = df["G"].astype(float)

# estimate games if missing (~4.25 PA/G)
G_proj = np.where(G_raw > 0, G_raw, np.round(PA / 4.25))

# HBP/SF/CI rates – constant from tables
HBP_rate = np.full(len(df), HBP_rate_const, dtype=float)
SF_rate  = np.full(len(df), SF_rate_const,  dtype=float)
CI_rate  = np.full(len(df), CI_rate_const,  dtype=float)

# ---------- HAND EXPOSURE (RHP/LHP) ----------
hand = df.get("B", pd.Series("R", index=df.index)).astype(str).str.upper()

share_RHP = np.where(
    hand.str.startswith("L"), 0.80,
    np.where(hand.str.startswith("R"), 0.60, 0.70)   # S = 70/30
)
share_LHP = 1.0 - share_RHP

PA_R = PA * share_RHP
PA_L = PA * share_LHP

# ---------- RATES vR / vL FROM SPLIT RATINGS ----------
def side_rates(row, side):
    if side == "vR":
        BA_col,  GAP_col,  POW_col,  EYE_col,  K_col  = "BA vR","GAP vR","POW vR","EYE vR","K vR"
    else:
        BA_col,  GAP_col,  POW_col,  EYE_col,  K_col  = "BA vL","GAP vL","POW vL","EYE vL","K vL"

    K_q   = q5f(row[K_col])
    BB_q  = q5f(row[EYE_col])
    POW_q = q5f(row[POW_col])
    BA_q  = q5f(row[BA_col])
    GAP_q = q5f(row[GAP_col])

    K     = interp(K_curve,      K_q)
    BB    = interp(BB_curve,     BB_q)
    HR    = interp(HR_curve,     POW_q)
    BABIP = interp(BABIP_curve,  BA_q)
    XBH   = interp(XBH_curve,    GAP_q)
    TRI   = interp(TRI_curve,    GAP_q)

    K     = np.clip(K,     0.0, 0.5)
    BB    = np.clip(BB,    0.0, 0.4)
    HR    = np.clip(HR,    0.0, 0.2)
    BABIP = np.clip(BABIP, 0.20, 0.40)
    XBH   = np.clip(XBH,   0.05, 0.60)
    TRI   = np.clip(TRI,   0.0,  0.5)

    return K, BB, HR, BABIP, XBH, TRI

def collect_side(side):
    K_lst, BB_lst, HR_lst = [], [], []
    BAB_lst, XBH_lst, TRI_lst = [], [], []
    for _, row in df.iterrows():
        k, bb, hr, bab, xbh, tri = side_rates(row, side)
        K_lst.append(k); BB_lst.append(bb); HR_lst.append(hr)
        BAB_lst.append(bab); XBH_lst.append(xbh); TRI_lst.append(tri)
    return (np.array(K_lst), np.array(BB_lst), np.array(HR_lst),
            np.array(BAB_lst), np.array(XBH_lst), np.array(TRI_lst))

K_vR, BB_vR, HR_vR, BABIP_vR, XBH_vR, TRI_vR = collect_side("vR")
K_vL, BB_vL, HR_vL, BABIP_vL, XBH_vL, TRI_vL = collect_side("vL")

# ---------- EVENT RATES & COUNTS PER SIDE ----------
def side_counts(PA_side, K_s, BB_s, HR_s, BABIP_s, XBH_s, TRI_s,
                HBP_rate_s, SF_rate_s, CI_rate_s):
    BIP_s = 1.0 - (K_s + BB_s + HBP_rate_s + HR_s + SF_rate_s + CI_rate_s)
    BIP_s = np.clip(BIP_s, 0.0, 1.0)

    H_on_BIP = BIP_s * BABIP_s
    XBH_rate = H_on_BIP * XBH_s
    TRI_rate = XBH_rate * TRI_s
    DBL_rate = XBH_rate - TRI_rate
    SGL_rate = H_on_BIP - XBH_rate

    K   = PA_side * K_s
    BB  = PA_side * BB_s
    HBP = PA_side * HBP_rate_s
    SF  = PA_side * SF_rate_s
    CI  = PA_side * CI_rate_s
    HR  = PA_side * HR_s
    s1  = PA_side * SGL_rate
    s2  = PA_side * DBL_rate
    s3  = PA_side * TRI_rate

    return K, BB, HBP, SF, CI, HR, s1, s2, s3

K_R, BB_R, HBP_R, SF_R, CI_R, HR_R, S1_R, S2_R, S3_R = side_counts(
    PA_R, K_vR, BB_vR, HR_vR, BABIP_vR, XBH_vR, TRI_vR,
    HBP_rate, SF_rate, CI_rate
)
K_L, BB_L, HBP_L, SF_L, CI_L, HR_L, S1_L, S2_L, S3_L = side_counts(
    PA_L, K_vL, BB_vL, HR_vL, BABIP_vL, XBH_vL, TRI_vL,
    HBP_rate, SF_rate, CI_rate
)

# ---------- SPLIT OBP ----------
# H = all hits (1B+2B+3B+HR); AB = PA - (BB+HBP+SF+CI)
H_R = S1_R + S2_R + S3_R + HR_R
H_L = S1_L + S2_L + S3_L + HR_L

AB_R = PA_R - (BB_R + HBP_R + SF_R + CI_R)
AB_L = PA_L - (BB_L + HBP_L + SF_L + CI_L)

den_R = AB_R + BB_R + HBP_R + SF_R
den_L = AB_L + BB_L + HBP_L + SF_L

OBP_vR = np.divide(H_R + BB_R + HBP_R, den_R,
                   out=np.zeros_like(den_R), where=den_R > 1e-9)
OBP_vL = np.divide(H_L + BB_L + HBP_L, den_L,
                   out=np.zeros_like(den_L), where=den_L > 1e-9)

# blended totals
K_tot   = K_R + K_L
BB_tot  = BB_R + BB_L
HBP_tot = HBP_R + HBP_L
SF_tot  = SF_R + SF_L
CI_tot  = CI_R + CI_L
HR_tot  = HR_R + HR_L
S1_tot  = S1_R + S1_L
S2_tot  = S2_R + S2_L
S3_tot  = S3_R + S3_L

# ---------- wOBA & wRAA ----------
wBB  = WOBA_WEIGHTS["BB"]
wHBP = WOBA_WEIGHTS["HBP"]
w1B  = WOBA_WEIGHTS["1B"]
w2B  = WOBA_WEIGHTS["2B"]
w3B  = WOBA_WEIGHTS["3B"]
wHR  = WOBA_WEIGHTS["HR"]

def woba_from_counts(PA_side, BB_s, HBP_s, s1, s2, s3, HR_s):
    num = (wBB*BB_s + wHBP*HBP_s +
           w1B*s1 + w2B*s2 + w3B*s3 + wHR*HR_s)
    den = np.maximum(PA_side, 1e-9)
    return num / den

wOBA_vR = woba_from_counts(PA_R, BB_R, HBP_R, S1_R, S2_R, S3_R, HR_R)
wOBA_vL = woba_from_counts(PA_L, BB_L, HBP_L, S1_L, S2_L, S3_L, HR_L)

wOBA_tot = woba_from_counts(PA, BB_tot, HBP_tot, S1_tot, S2_tot, S3_tot, HR_tot)
wRAA_off = (wOBA_tot - LEAGUE_WOBA) / WOBA_SCALE * PA

# split wRAA (runs above average vs R/L)
wRAA_vR = (wOBA_vR - LEAGUE_WOBA) / WOBA_SCALE * PA_R
wRAA_vL = (wOBA_vL - LEAGUE_WOBA) / WOBA_SCALE * PA_L

# ---------- FIELDING PROJECTIONS ----------
POS = df.get("POS", pd.Series("", index=df.index)).astype(str)

infield_pos  = {"1B","2B","3B","SS"}
outfield_pos = {"LF","CF","RF"}

IF_mask = POS.isin(infield_pos)
OF_mask = POS.isin(outfield_pos)
C_mask  = POS.eq("C")

IF_RNG_q = df["IF RNG"].apply(q5f)
OF_RNG_q = df["OF RNG"].apply(q5f)
C_FRM_q  = df["C FRM"].apply(q5f)
C_ARM_q  = df["C ARM"].apply(q5f)

# position-average baselines (0 = average defender at that bucket)
def _safe_mean(a):
    a = np.array(a, dtype=float)
    a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else 50.0

base_IF_rating   = _safe_mean(IF_RNG_q[IF_mask])
base_OF_rating   = _safe_mean(OF_RNG_q[OF_mask])
base_CFRM_rating = _safe_mean(C_FRM_q[C_mask])
base_CARM_rating = _safe_mean(C_ARM_q[C_mask])

base_IF_play   = interp(IF_rng_curve, base_IF_rating)
base_OF_play   = interp(OF_rng_curve, base_OF_rating)
base_FRM_perG  = interp(C_FRM_curve,  base_CFRM_rating)
base_RTO_pct   = interp(C_RTO_curve,  base_CARM_rating)

IF_play_pct = np.array([interp(IF_rng_curve, r) for r in IF_RNG_q])
OF_play_pct = np.array([interp(OF_rng_curve, r) for r in OF_RNG_q])
C_FRM_perG  = np.array([interp(C_FRM_curve,  r) for r in C_FRM_q])
C_RTO_pct   = np.array([interp(C_RTO_curve,  r) for r in C_ARM_q])

# compress around baseline so stars aren't +50 runs
IF_play_pct = base_IF_play + (IF_play_pct - base_IF_play) * 1.0
OF_play_pct = base_OF_play + (OF_play_pct - base_OF_play) * 1.0

IF_play_pct = np.clip(IF_play_pct, 0.50, 0.99)
OF_play_pct = np.clip(OF_play_pct, 0.50, 0.99)
C_RTO_pct   = np.clip(C_RTO_pct,   0.00, 0.70)

IF_chances_proj = G_proj * IF_ch_per_G * IF_mask.astype(float)
OF_chances_proj = G_proj * OF_ch_per_G * OF_mask.astype(float)
C_SBA_proj      = G_proj * C_SBA_per_G * C_mask.astype(float)

IF_extra_outs = IF_chances_proj * (IF_play_pct - base_IF_play)
OF_extra_outs = OF_chances_proj * (OF_play_pct - base_OF_play)
C_FRM_extra   = G_proj * (C_FRM_perG - base_FRM_perG) * C_mask.astype(float)
C_extra_RTO   = C_SBA_proj * (C_RTO_pct - base_RTO_pct)

IF_def_runs = IF_extra_outs * 0.6
OF_def_runs = OF_extra_outs * 0.8
C_FRM_runs  = C_FRM_extra * 1.0
C_ARM_runs  = C_extra_RTO * 0.3

DEF_runs_total = IF_def_runs + OF_def_runs + C_FRM_runs + C_ARM_runs

# ---------- WAR (above replacement) ----------
rep_runs_per_PA = REPLACEMENT_RUNS_PER_600_PA / 600.0
rep_runs        = rep_runs_per_PA * PA

bat_runs_total  = wRAA_off + rep_runs   # offense + replacement
WAR_off         = bat_runs_total / RUNS_PER_WIN

WAR_br          = np.zeros(len(df))    # placeholder
WAR_def         = DEF_runs_total / RUNS_PER_WIN
WAR_total       = WAR_off + WAR_br + WAR_def

# ---------- BUILD OUTPUT ----------
out = df.copy()

out["PA_proj"]  = PA
out["G_proj"]   = G_proj

# splits
out["PA_vsR"]     = PA_R
out["PA_vsL"]     = PA_L
out["K%_vsR"]     = K_vR
out["BB%_vsR"]    = BB_vR
out["HR%_vsR"]    = HR_vR
out["BABIP%_vsR"] = BABIP_vR
out["OBP_vsR"]    = OBP_vR
out["wobavR"]     = wOBA_vR   # <- for lineup tool

out["K%_vsL"]     = K_vL
out["BB%_vsL"]    = BB_vL
out["HR%_vsL"]    = HR_vL
out["BABIP%_vsL"] = BABIP_vL
out["OBP_vsL"]    = OBP_vL
out["wobavL"]     = wOBA_vL   # <- for lineup tool

# totals
out["K_proj"]   = K_tot
out["BB_proj"]  = BB_tot
out["HBP_proj"] = HBP_tot
out["SF_proj"]  = SF_tot
out["CI_proj"]  = CI_tot
out["HR_proj"]  = HR_tot
out["1B_proj"]  = S1_tot
out["2B_proj"]  = S2_tot
out["3B_proj"]  = S3_tot
out["wOBA"]     = wOBA_tot
out["wRAA_off"] = wRAA_off
out["Bat_runs_total"] = bat_runs_total

# fielding
out["IF_outs_extra"]    = IF_extra_outs
out["OF_outs_extra"]    = OF_extra_outs
out["C_FRM_runs_proj"]  = C_FRM_runs
out["C_RTO_extra"]      = C_extra_RTO
out["IF_def_runs"]      = IF_def_runs
out["OF_def_runs"]      = OF_def_runs
out["C_ARM_runs"]       = C_ARM_runs
out["DEF_runs_total"]   = DEF_runs_total

# WAR
out["WAR_off"]   = WAR_off
out["WAR_br"]    = WAR_br
out["WAR_def"]   = WAR_def
out["WAR_total"] = WAR_total

# split wRAA vs R/L
out["wRAAvR"]    = wRAA_vR
out["wRAAvL"]    = wRAA_vL

# ---------- WRITE (pretty Excel) ----------
import xlsxwriter
from xlsxwriter.utility import xl_range

nrows, ncols = out.shape
col_idx = {name: i for i, name in enumerate(out.columns)}

with pd.ExcelWriter(OUT_FILE, engine="xlsxwriter") as writer:
    out.to_excel(writer, sheet_name="BattingFieldingProjections", index=False)
    workbook  = writer.book
    ws        = writer.sheets["BattingFieldingProjections"]

    # Make the whole range a table
    table_range = xl_range(0, 0, nrows, ncols - 1)
    ws.add_table(table_range, {
        "name": "ProjTable",
        "header_row": True,
        "style": "TableStyleMedium9",
        "columns": [{"header": col} for col in out.columns]
    })

    # Freeze header row
    ws.freeze_panes(1, 0)

    # Some sensible column widths
    if "ID" in col_idx:
        ws.set_column(col_idx["ID"], col_idx["ID"], 7)
    if "Name" in col_idx:
        ws.set_column(col_idx["Name"], col_idx["Name"], 22)
    if "POS" in col_idx:
        ws.set_column(col_idx["POS"], col_idx["POS"], 6)
    if "ORG" in col_idx:
        ws.set_column(col_idx["ORG"], col_idx["ORG"], 6)

    # Helper to apply a 3-color scale to a column by name
    def color_scale(col_name):
        if col_name not in col_idx:
            return
        c = col_idx[col_name]
        data_range = xl_range(1, c, nrows, c)  # skip header
        ws.conditional_format(data_range, {"type": "3_color_scale"})

    # Highlight main performance columns
    for cname in [
        "wOBA", "wobavR", "wobavL",
        "wRAAvR", "wRAAvL",
        "DEF_runs_total", "WAR_off", "WAR_def", "WAR_total"
    ]:
        color_scale(cname)

print(f"Wrote {OUT_FILE}")
