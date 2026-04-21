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
from datetime import date, datetime


def _to_datetime_mixed(x):
    """Robust datetime parsing for mixed formats (e.g., 'YYYY-MM-DD' and
    'YYYY-MM-DD HH:MM:SS.ffffff').
    
    Pandas can infer a single format from early rows and coerce later rows to NaT
    when formats differ. Using format='mixed' (when available) avoids dropping
    new snapshots that include a time component.
    """
    try:
        return pd.to_datetime(x, errors="coerce", format="mixed")
    except TypeError:
        # Older pandas versions don't support format='mixed'
        return pd.to_datetime(x, errors="coerce", infer_datetime_format=True)

# ----------------------------- FILES ------------------------------
TABLES_FILE = "pitching_rating_tables_smoothed.xlsx"
MLB_FILE    = "player_search___shortlist_player_shortlist_pitching_projections.csv"
AAA_FILE    = "player_search___shortlist_player_shortlist_pitching_projections2.csv"
OUT_FILE    = "pitching_projections.xlsx"

RATING_MASTER_FILE = "pitching_rating_changes_master.xlsx"
HISTORY_SHEET_NAME = "History"
CHANGES_SHEET_NAME = "Changes"
DATE_COL = "AsOf"

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


# --------------------- RATING HISTORY / CHANGES -------------------
import re
from datetime import timedelta

def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())

def _find_col_case_insensitive(df: pd.DataFrame, candidates: list) -> str | None:
    cols_norm = {_norm(c): c for c in df.columns}
    for cand in candidates:
        key = _norm(cand)
        if key in cols_norm:
            return cols_norm[key]
    return None
def _find_potential_col(df: pd.DataFrame, base_col: str, extra_candidates: list | None = None) -> str | None:
    """Find the column name holding the *potential* version of base_col.

    Supports common OOTP naming patterns such as:
      - "<col> P", "<col> Pot", "<col> Potential"
      - "p<col>"
      - "<col>pot" / "<col>potential" (after normalization)
    You can also pass extra_candidates (e.g., ["STU P"]) to allow a fallback search.
    """
    cols_norm = {_norm(c): c for c in df.columns}
    rn = _norm(base_col)

    # 1) Normalized patterns
    for key in [f"p{rn}", f"{rn}p", f"{rn}pot", f"{rn}potential"]:
        if key in cols_norm:
            return cols_norm[key]

    # 2) Text candidates (case-insensitive via normalization)
    cand = [
        f"{base_col} P", f"{base_col} Pot", f"{base_col} POT", f"{base_col} Potential",
        f"p{base_col}",
    ]
    if extra_candidates:
        cand.extend(extra_candidates)

    return _find_col_case_insensitive(df, cand)



def _std_trait(v):
    """Standardize trait values:
    - WE/INT: H/N/L
    - Injury proneness: Wrecked/Fragile/Normal/Durable/Iron Man
    """
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        return ""

    u = s.strip().upper()
    if u in {"H", "N", "L"}:
        return u

    n = _norm(s)
    if n in {"wrecked", "fragile", "normal", "durable"}:
        return n[:1].upper() + n[1:]
    if n in {"ironman", "iron man", "iron_man", "iron-man"} or n.replace(" ", "") == "ironman":
        return "Iron Man"

    # fallback: title-case words
    parts = re.split(r"\s+", s)
    parts = [p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper() for p in parts]
    return " ".join(parts)

def _unique_keep_order(items: list) -> list:
    seen = set()
    out = []
    for x in items:
        if x is None:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

# ---- Longitudinal tracking configuration ----
PAIRWISE_SHEET_NAME        = "Pairwise"
PLAYER_SUMMARY_SHEET_NAME  = "PlayerSummary"
TOP30_SHEET_NAME           = "TopMovers_30d"
TOP90_SHEET_NAME           = "TopMovers_90d"
TOP365_SHEET_NAME          = "TopMovers_365d"
TRAIT_IMPACT_SHEET_NAME    = "TraitImpact"
BIGGEST_JUMPS_SHEET_NAME   = "BiggestJumps"

TRAIT_METRICS_SHEET_NAME   = "TraitMetrics"
TRAIT_SPECS = [
    # Short export headers you showed: WE / INT / Prone
    ("Trait_WorkEthic",   ["WE", "Work ethic", "Work Ethic", "WorkEthic"]),
    ("Trait_BaseballIQ",  ["INT", "Intelligence", "Baseball IQ", "BaseballIQ", "IQ", "BBIQ", "Baseball Iq"]),
    ("Trait_InjuryProne", ["Prone", "Injury proneness", "Injury Proneness", "Injury Prone", "Injury", "Injury Prone (text)"]),
]

OVR_CANDIDATES = ["OVR", "Overall", "Overall Rating", "Ovr"]
POT_CANDIDATES = ["POT", "Potential", "Pot"]

def build_rating_snapshot(df_in: pd.DataFrame):
    """Create today's snapshot (ratings + traits) to append into the master history file."""
    join_cols = KEY.copy()

    meta_cols = []
    for c in ["Name", "POS", "ORG", "Age", "Role", "Level"]:
        if c in df_in.columns and c not in join_cols:
            meta_cols.append(c)

    # Standardize trait columns into fixed names (Trait_*) for consistent longitudinal analysis.
    trait_cols = []
    tmp = df_in.copy()
    for std_name, candidates in TRAIT_SPECS:
        src = _find_col_case_insensitive(tmp, candidates)
        if src is not None:
            tmp[std_name] = tmp[src].apply(_std_trait)
            trait_cols.append(std_name)

    ovr_col = _find_col_case_insensitive(tmp, OVR_CANDIDATES)
    pot_col = _find_col_case_insensitive(tmp, POT_CANDIDATES)

    rating_cols = [c for c in RATING_ATTRS if c in tmp.columns]

    # p-rating columns (potential) that match rating columns by normalized name.
    col_norm_map = {_norm(c): c for c in tmp.columns}
    pot_rating_cols = []
    for r in rating_cols:
        rn = _norm(r)
        for key in [f"p{rn}", f"{rn}pot", f"{rn}potential"]:
            if key in col_norm_map:
                pot_rating_cols.append(col_norm_map[key])

    tracked_cols = []
    if ovr_col is not None:
        tracked_cols.append(ovr_col)
    if pot_col is not None:
        tracked_cols.append(pot_col)
    tracked_cols += rating_cols + pot_rating_cols
    tracked_cols = _unique_keep_order(tracked_cols)

    snap_cols = _unique_keep_order(join_cols + meta_cols + trait_cols + tracked_cols)
    snap = tmp[snap_cols].copy()
    snap[DATE_COL] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    for c in tracked_cols:
        snap[c] = pd.to_numeric(snap[c], errors="coerce")

    return snap, join_cols, meta_cols, trait_cols, tracked_cols, ovr_col, pot_col

def _compute_pairwise(hist: pd.DataFrame, join_cols: list, meta_cols: list, trait_cols: list, tracked_cols: list) -> pd.DataFrame:
    """One row per (player, previous export -> current export) interval with deltas.

    Important: uses full timestamp granularity in DATE_COL (not just date), so multiple exports
    on the same day are treated as distinct snapshots.
    """
    if hist is None or hist.empty:
        return pd.DataFrame()

    h = hist.copy()
    h[DATE_COL] = _to_datetime_mixed(h[DATE_COL])
    h = h.dropna(subset=[DATE_COL])
    h = h.sort_values(join_cols + [DATE_COL]).reset_index(drop=True)

    g = h.groupby(join_cols, sort=False)
    prev = g.shift(1)

    pair = h[join_cols].copy()
    pair["PrevAsOf"] = prev[DATE_COL]
    pair[DATE_COL] = h[DATE_COL]

    delta_t = pair[DATE_COL] - pair["PrevAsOf"]
    pair["Days"] = delta_t.dt.total_seconds() / 86400.0

    for c in meta_cols:
        if c in h.columns:
            pair[f"{c}_curr"] = h[c]
            pair[f"{c}_prev"] = prev[c]
    for t in trait_cols:
        if t in h.columns:
            pair[f"{t}_curr"] = h[t]
            pair[f"{t}_prev"] = prev[t]

    for c in tracked_cols:
        if c in h.columns:
            cur = pd.to_numeric(h[c], errors="coerce")
            prv = pd.to_numeric(prev[c], errors="coerce")
            pair[f"Δ{c}"] = cur - prv
            pair[f"Δ{c}_365d"] = np.where(pair["Days"] > 0, pair[f"Δ{c}"] / pair["Days"] * 365.0, np.nan)

    pair = pair[pair["PrevAsOf"].notna()].copy()

    # Write-friendly strings
    pair["PrevAsOf"] = pair["PrevAsOf"].dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    pair[DATE_COL] = pair[DATE_COL].dt.strftime("%Y-%m-%d %H:%M:%S.%f")

    return pair

def _player_summary(hist: pd.DataFrame, pair: pd.DataFrame, join_cols: list, meta_cols: list, trait_cols: list, tracked_cols: list, ovr_col: str | None, pot_col: str | None) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()

    h = hist.copy()
    h[DATE_COL] = _to_datetime_mixed(h[DATE_COL])
    h = h.dropna(subset=[DATE_COL])
    h = h.sort_values(join_cols + [DATE_COL])

    g = h.groupby(join_cols, sort=False)
    first = g.first()
    last = g.last()
    n = g.size().rename("Snapshots").to_frame()

    out = n.join(first[[DATE_COL]]).rename(columns={DATE_COL: "FirstAsOf"}).join(last[[DATE_COL]]).rename(columns={DATE_COL: "LastAsOf"})
    delta_t = out["LastAsOf"] - out["FirstAsOf"]
    out["DaysTracked"] = delta_t.dt.total_seconds() / 86400.0

    for c in meta_cols:
        if c in last.columns:
            out[c] = last[c]
    for t in trait_cols:
        if t in last.columns:
            out[t] = last[t]

    def _add_primary(col):
        nonlocal out
        if col is None or col not in first.columns or col not in last.columns:
            return
        out[f"{col}_Start"] = pd.to_numeric(first[col], errors="coerce")
        out[f"{col}_End"] = pd.to_numeric(last[col], errors="coerce")
        out[f"Δ{col}_Total"] = out[f"{col}_End"] - out[f"{col}_Start"]
        out[f"Δ{col}_365d_Total"] = np.where(out["DaysTracked"] > 0, out[f"Δ{col}_Total"] / out["DaysTracked"] * 365.0, np.nan)

        if pair is not None and not pair.empty and f"Δ{col}" in pair.columns:
            d = pair.groupby(join_cols)[f"Δ{col}"].agg(["mean", "min", "max"]).rename(columns={
                "mean": f"Δ{col}_AvgStep",
                "min":  f"Δ{col}_MinStep",
                "max":  f"Δ{col}_MaxStep",
            })
            out = out.join(d, how="left")

            d365 = pair.groupby(join_cols)[f"Δ{col}_365d"].agg(["mean"]).rename(columns={"mean": f"Δ{col}_Avg365d"})
            out = out.join(d365, how="left")
        return out

    _add_primary(ovr_col)
    _add_primary(pot_col)

    if pair is not None and not pair.empty:
        delta_cols = [f"Δ{c}" for c in tracked_cols if f"Δ{c}" in pair.columns]
        if delta_cols:
            tmp = pair.copy()
            tmp["_MeanAbsΔ"] = tmp[delta_cols].abs().mean(axis=1)
            vol = tmp.groupby(join_cols)["_MeanAbsΔ"].agg(["mean", "max"]).rename(columns={
                "mean": "MeanAbsΔ_AvgStep",
                "max":  "MeanAbsΔ_MaxStep",
            })
            out = out.join(vol, how="left")

    out = out.reset_index()
    out["FirstAsOf"] = _to_datetime_mixed(out["FirstAsOf"]).dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    out["LastAsOf"] = _to_datetime_mixed(out["LastAsOf"]).dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    return out

def _top_movers(hist: pd.DataFrame, join_cols: list, meta_cols: list, trait_cols: list, primary_cols: list, days: int) -> pd.DataFrame:
    """Net change between each player's latest snapshot and their snapshot at/before (latest - days)."""
    if hist is None or hist.empty or not primary_cols:
        return pd.DataFrame()

    h = hist.copy()
    h[DATE_COL] = _to_datetime_mixed(h[DATE_COL])
    h = h.dropna(subset=[DATE_COL]).sort_values(join_cols + [DATE_COL])

    latest_ts = h[DATE_COL].max()
    cutoff = latest_ts - timedelta(days=days)

    rows = []
    for _, g in h.groupby(join_cols, sort=False):
        g = g.sort_values(DATE_COL)
        latest = g.iloc[-1]
        base = g[g[DATE_COL] <= cutoff].iloc[-1] if (g[DATE_COL] <= cutoff).any() else g.iloc[0]

        row = {c: latest[c] for c in join_cols}
        row["BaseAsOf"] = _to_datetime_mixed(base[DATE_COL]).strftime("%Y-%m-%d %H:%M:%S.%f")
        row[DATE_COL] = _to_datetime_mixed(latest[DATE_COL]).strftime("%Y-%m-%d %H:%M:%S.%f")

        for c in meta_cols:
            if c in g.columns:
                row[f"{c}_curr"] = latest.get(c, "")
        for t in trait_cols:
            if t in g.columns:
                row[t] = latest.get(t, "")

        for c in primary_cols:
            if c in g.columns:
                row[f"{c}_base"] = pd.to_numeric(base.get(c), errors="coerce")
                row[f"{c}_curr"] = pd.to_numeric(latest.get(c), errors="coerce")
                row[f"Δ{c}"] = row[f"{c}_curr"] - row[f"{c}_base"]

        rows.append(row)

    out = pd.DataFrame(rows)
    # Keep all players; caller can sort/filter in Excel.
    return out

def _trait_impact(pair: pd.DataFrame, join_cols: list, trait_cols: list, primary_cols: list) -> pd.DataFrame:
    """Trait impact table based on *previous* trait value at the time of change."""
    if pair is None or pair.empty or not trait_cols or not primary_cols:
        return pd.DataFrame()

    rows = []
    for t in trait_cols:
        tprev = f"{t}_prev"
        if tprev not in pair.columns:
            continue

        for cat, grp in pair.groupby(tprev, dropna=False):
            cat_s = "" if pd.isna(cat) else str(cat)
            rec = {
                "Trait": t,
                "Category": cat_s,
                "Events": int(len(grp)),
                "Players": int(grp[join_cols].drop_duplicates().shape[0]),
                "MeanDaysBetween": float(pd.to_numeric(grp.get("Days"), errors="coerce").mean()),
            }
            for c in primary_cols:
                d365 = f"Δ{c}_365d"
                if d365 in grp.columns:
                    rec[f"MeanΔ{c}_365d"] = float(pd.to_numeric(grp[d365], errors="coerce").mean())
                    rec[f"MedianΔ{c}_365d"] = float(pd.to_numeric(grp[d365], errors="coerce").median())
            rows.append(rec)

    out = pd.DataFrame(rows)
    sort_col = f"MeanΔ{primary_cols[0]}_365d" if primary_cols else "Events"
    if sort_col in out.columns:
        out = out.sort_values(["Trait", sort_col], ascending=[True, False])
    else:
        out = out.sort_values(["Trait", "Events"], ascending=[True, False])
    return out

def _trait_metrics(hist: pd.DataFrame, pair: pd.DataFrame, join_cols: list, trait_cols: list, tracked_cols: list) -> pd.DataFrame:
    """Long-form table by (Trait, Category, Metric).

    Includes:
      - Players_Current, Avg_Current: latest snapshot per player
      - Events, Players_Events, MeanΔ_Step, MeanΔ_365d, MedianΔ_365d: based on pairwise deltas
    """
    cols_out = [
        "Trait","Category","Metric",
        "Players_Current","Avg_Current",
        "Events","Players_Events","MeanΔ_Step","MeanΔ_365d","MedianΔ_365d",
    ]
    if hist is None or hist.empty or not trait_cols:
        return pd.DataFrame(columns=cols_out)

    h = hist.copy()
    h[DATE_COL] = _to_datetime_mixed(h[DATE_COL])
    h = h.dropna(subset=[DATE_COL]).sort_values(join_cols + [DATE_COL])

    latest = h.groupby(join_cols, sort=False).tail(1).copy()

    metrics = [c for c in tracked_cols if c in latest.columns]
    for c in metrics:
        latest[c] = pd.to_numeric(latest[c], errors="coerce")

    cur_rows = []
    for t in trait_cols:
        if t not in latest.columns:
            continue
        for cat, g in latest.groupby(t, dropna=False):
            cat_s = "" if pd.isna(cat) else str(cat)
            players = int(len(g))
            for mcol in metrics:
                cur_rows.append({
                    "Trait": t,
                    "Category": cat_s,
                    "Metric": mcol,
                    "Players_Current": players,
                    "Avg_Current": float(pd.to_numeric(g[mcol], errors="coerce").mean()),
                })
    cur = pd.DataFrame(cur_rows)
    if cur.empty:
        cur = pd.DataFrame(columns=["Trait","Category","Metric","Players_Current","Avg_Current"])

    chg_rows = []
    if pair is not None and not pair.empty:
        p = pair.copy()
        for t in trait_cols:
            tprev = f"{t}_prev"
            if tprev not in p.columns:
                continue
            for cat, g in p.groupby(tprev, dropna=False):
                cat_s = "" if pd.isna(cat) else str(cat)
                events = int(len(g))
                players_events = int(g[join_cols].drop_duplicates().shape[0])
                for mcol in metrics:
                    d_step = f"Δ{mcol}"
                    d_365  = f"Δ{mcol}_365d"
                    if d_step not in g.columns and d_365 not in g.columns:
                        continue
                    chg_rows.append({
                        "Trait": t,
                        "Category": cat_s,
                        "Metric": mcol,
                        "Events": events,
                        "Players_Events": players_events,
                        "MeanΔ_Step": float(pd.to_numeric(g.get(d_step), errors="coerce").mean()),
                        "MeanΔ_365d": float(pd.to_numeric(g.get(d_365), errors="coerce").mean()),
                        "MedianΔ_365d": float(pd.to_numeric(g.get(d_365), errors="coerce").median()),
                    })
    chg = pd.DataFrame(chg_rows)
    if chg.empty:
        chg = pd.DataFrame(columns=["Trait","Category","Metric","Events","Players_Events","MeanΔ_Step","MeanΔ_365d","MedianΔ_365d"])

    out = cur.merge(chg, on=["Trait","Category","Metric"], how="outer")
    for c in cols_out:
        if c not in out.columns:
            out[c] = np.nan
    out = out[cols_out].sort_values(["Trait","Category","Metric"], kind="stable")
    return out

def update_rating_master(snapshot: pd.DataFrame, join_cols: list, meta_cols: list, trait_cols: list, tracked_cols: list, ovr_col: str | None, pot_col: str | None):
    """Append snapshot to the master file and rebuild derived sheets.

    Key behaviors:
      - Each run is treated as a distinct export via full timestamp in DATE_COL.
      - 'Changes' captures ALL deltas between the most recent two exports (no thresholds).
      - 'Pairwise' captures ALL consecutive deltas per player across the full history.
      - No artificial head()/top-N limits are applied.
    """
    try:
        hist = pd.read_excel(RATING_MASTER_FILE, sheet_name=HISTORY_SHEET_NAME)
    except Exception:
        hist = pd.DataFrame()

    hist = pd.concat([hist, snapshot], ignore_index=True, sort=False)

    # Keep DATE_COL as a string for Excel, but compute with a datetime helper column.
    hist[DATE_COL] = hist[DATE_COL].astype(str)
    hist["_AsOf_dt"] = _to_datetime_mixed(hist[DATE_COL])
    hist = hist.dropna(subset=["_AsOf_dt"])
    # Keep every export snapshot (no de-dup)
    hist = hist.sort_values(join_cols + ["_AsOf_dt"]).reset_index(drop=True)

    # Latest-vs-previous export change view
    changes = pd.DataFrame()
    asofs = sorted(hist["_AsOf_dt"].unique())
    if len(asofs) >= 2:
        prev_ts, curr_ts = asofs[-2], asofs[-1]
        prev = hist[hist["_AsOf_dt"] == prev_ts].copy()
        curr = hist[hist["_AsOf_dt"] == curr_ts].copy()

        prev_cols = join_cols + [c for c in (meta_cols + trait_cols + tracked_cols) if c in prev.columns]
        curr_cols = join_cols + [c for c in (meta_cols + trait_cols + tracked_cols) if c in curr.columns]

        merged = prev[prev_cols].merge(curr[curr_cols], on=join_cols, how="outer", suffixes=("_prev", "_curr"))

        # Compute deltas for all tracked numeric columns
        for c in tracked_cols:
            merged[f"Δ{c}"] = (
                pd.to_numeric(merged.get(f"{c}_curr"), errors="coerce") -
                pd.to_numeric(merged.get(f"{c}_prev"), errors="coerce")
            )

        delta_cols = [f"Δ{c}" for c in tracked_cols if f"Δ{c}" in merged.columns]
        if delta_cols:
            # Count as a change event if any delta is non-zero OR player appears/disappears between exports.
            nonzero = merged[delta_cols].fillna(0).ne(0).any(axis=1)
            missing_prev = merged[[f"{c}_prev" for c in tracked_cols if f"{c}_prev" in merged.columns]].isna().all(axis=1)
            missing_curr = merged[[f"{c}_curr" for c in tracked_cols if f"{c}_curr" in merged.columns]].isna().all(axis=1)
            changed_mask = nonzero | missing_prev | missing_curr

            changes = merged.loc[changed_mask].copy()

        changes.insert(0, "PrevAsOf", pd.to_datetime(prev_ts).strftime("%Y-%m-%d %H:%M:%S.%f"))
        changes.insert(1, DATE_COL,  pd.to_datetime(curr_ts).strftime("%Y-%m-%d %H:%M:%S.%f"))

        # Stable ordering: largest absolute OVR (or first tracked col) first
        sort_key = None
        if ovr_col is not None and f"Δ{ovr_col}" in changes.columns:
            sort_key = f"Δ{ovr_col}"
        elif tracked_cols:
            sort_key = f"Δ{tracked_cols[0]}"
        if sort_key is not None:
            changes["_abs"] = changes[sort_key].abs()
            changes = changes.sort_values("_abs", ascending=False).drop(columns=["_abs"])

    # Longitudinal analytics
    hist_for_calc = hist.drop(columns=["_AsOf_dt"]).copy()
    pair = _compute_pairwise(hist_for_calc, join_cols, meta_cols, trait_cols, tracked_cols)
    player_sum = _player_summary(hist_for_calc, pair, join_cols, meta_cols, trait_cols, tracked_cols, ovr_col, pot_col)

    primary_cols = [c for c in [ovr_col, pot_col] if c is not None]
    top30  = _top_movers(hist_for_calc, join_cols, meta_cols, trait_cols, primary_cols, 30)  if primary_cols else pd.DataFrame()
    top90  = _top_movers(hist_for_calc, join_cols, meta_cols, trait_cols, primary_cols, 90)  if primary_cols else pd.DataFrame()
    top365 = _top_movers(hist_for_calc, join_cols, meta_cols, trait_cols, primary_cols, 365) if primary_cols else pd.DataFrame()

    trait_impact = _trait_impact(pair, join_cols, trait_cols, primary_cols)
    trait_metrics = _trait_metrics(hist_for_calc, pair, join_cols, trait_cols, tracked_cols)

    biggest = pd.DataFrame()
    if pair is not None and not pair.empty:
        if ovr_col is not None and f"Δ{ovr_col}_365d" in pair.columns:
            biggest = pair.sort_values(f"Δ{ovr_col}_365d", ascending=False).copy()
        else:
            delta_cols = [f"Δ{c}" for c in tracked_cols if f"Δ{c}" in pair.columns]
            if delta_cols:
                tmp = pair.copy()
                tmp["_MeanAbsΔ"] = tmp[delta_cols].abs().mean(axis=1)
                biggest = tmp.sort_values("_MeanAbsΔ", ascending=False).drop(columns=["_MeanAbsΔ"]).copy()

    # Write master workbook (history + derived)
    hist_out = hist.drop(columns=["_AsOf_dt"]).copy()
    with pd.ExcelWriter(RATING_MASTER_FILE, engine="openpyxl") as w:
        hist_out.to_excel(w, sheet_name=HISTORY_SHEET_NAME, index=False)
        changes.to_excel(w, sheet_name=CHANGES_SHEET_NAME, index=False)
        pair.to_excel(w, sheet_name=PAIRWISE_SHEET_NAME, index=False)
        player_sum.to_excel(w, sheet_name=PLAYER_SUMMARY_SHEET_NAME, index=False)
        top30.to_excel(w, sheet_name=TOP30_SHEET_NAME, index=False)
        top90.to_excel(w, sheet_name=TOP90_SHEET_NAME, index=False)
        top365.to_excel(w, sheet_name=TOP365_SHEET_NAME, index=False)
        trait_impact.to_excel(w, sheet_name=TRAIT_IMPACT_SHEET_NAME, index=False)
        trait_metrics.to_excel(w, sheet_name=TRAIT_METRICS_SHEET_NAME, index=False)
        biggest.to_excel(w, sheet_name=BIGGEST_JUMPS_SHEET_NAME, index=False)

    # GrowthWatch: all players ranked by annualized OVR gain (or first available primary)
    growth_watch = player_sum.copy()
    sort_col = None
    if ovr_col is not None and f"Δ{ovr_col}_365d_Total" in growth_watch.columns:
        sort_col = f"Δ{ovr_col}_365d_Total"
    elif pot_col is not None and f"Δ{pot_col}_365d_Total" in growth_watch.columns:
        sort_col = f"Δ{pot_col}_365d_Total"
    elif "MeanAbsΔ_AvgStep" in growth_watch.columns:
        sort_col = "MeanAbsΔ_AvgStep"

    if sort_col is not None and sort_col in growth_watch.columns:
        growth_watch = growth_watch.sort_values(sort_col, ascending=False)

    return changes, growth_watch

rating_snapshot, rating_join_cols, rating_meta_cols, rating_trait_cols, rating_cols_used, rating_ovr_col, rating_pot_col = build_rating_snapshot(df)
rating_changes, growth_watch = update_rating_master(
    rating_snapshot,
    rating_join_cols,
    rating_meta_cols,
    rating_trait_cols,
    rating_cols_used,
    rating_ovr_col,
    rating_pot_col,
)# ----------------------------- HELPERS ----------------------------
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

# --------------------- POTENTIAL ADJUSTED RATINGS (vL/vR) -------------------
# Uses OOTP potential columns when present (e.g., "STU P"). If not present, falls back to current.
STU_P_OVERALL    = _find_potential_col(df, "STU",    extra_candidates=["STU P", "Stuff P", "STU POT", "Stuff POT"])
HRR_P_OVERALL    = _find_potential_col(df, "HRR",    extra_candidates=["HRR P", "HR P", "HRR POT", "HR POT"])
CON_P_OVERALL    = _find_potential_col(df, "CON",    extra_candidates=["CON P", "Control P", "CON POT", "Control POT"])
PBABIP_P_OVERALL = _find_potential_col(df, "PBABIP", extra_candidates=["PBABIP P", "pPBABIP", "BABIP P", "pBABIP"])

for side in ["vL", "vR"]:
    # STU
    stu_side = f"STU {side}"
    stu_p_col = _find_potential_col(df, stu_side, extra_candidates=[STU_P_OVERALL] if STU_P_OVERALL else None)
    stu_p = df[stu_p_col] if stu_p_col else (df[STU_P_OVERALL] if STU_P_OVERALL else df[stu_side])
    df[f"{stu_side}_adj_P"] = adj_with_uplift_series(stu_side, stu_p, df.get(f"{stu_side}_AAA", stu_p))

    # HRR
    hrr_side = f"HRR {side}"
    hrr_p_col = _find_potential_col(df, hrr_side, extra_candidates=[HRR_P_OVERALL] if HRR_P_OVERALL else None)
    hrr_p = df[hrr_p_col] if hrr_p_col else (df[HRR_P_OVERALL] if HRR_P_OVERALL else df[hrr_side])
    df[f"{hrr_side}_adj_P"] = adj_with_uplift_series(hrr_side, hrr_p, df.get(f"{hrr_side}_AAA", hrr_p))

    # CON
    con_side = f"CON {side}"
    con_p_col = _find_potential_col(df, con_side, extra_candidates=[CON_P_OVERALL] if CON_P_OVERALL else None)
    con_p = df[con_p_col] if con_p_col else (df[CON_P_OVERALL] if CON_P_OVERALL else df[con_side])
    df[f"{con_side}_adj_P"] = adj_with_uplift_series(con_side, con_p, df.get(f"{con_side}_AAA", con_p))

    # PBABIP (no uplift table in current build)
    pb_side = f"PBABIP {side}"
    pb_p_col = _find_potential_col(df, pb_side, extra_candidates=[PBABIP_P_OVERALL] if PBABIP_P_OVERALL else None)
    pb_p = df[pb_p_col] if pb_p_col else (df[PBABIP_P_OVERALL] if PBABIP_P_OVERALL else df[pb_side])
    df[f"{pb_side}_adj_P"] = q5f_series(pb_p)

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

# potential side rates from tables
K_vL_P     = interp_arr(K_arr,     df["STU vL_adj_P"].to_numpy(float))
K_vR_P     = interp_arr(K_arr,     df["STU vR_adj_P"].to_numpy(float))
HR_vL_P    = interp_arr(HR_arr,    df["HRR vL_adj_P"].to_numpy(float))
HR_vR_P    = interp_arr(HR_arr,    df["HRR vR_adj_P"].to_numpy(float))
uBB_vL_P   = interp_arr(uBB_arr,   df["CON vL_adj_P"].to_numpy(float))
uBB_vR_P   = interp_arr(uBB_arr,   df["CON vR_adj_P"].to_numpy(float))
BABIP_vL_P = interp_arr(BABIP_arr, df["PBABIP vL_adj_P"].to_numpy(float))
BABIP_vR_P = interp_arr(BABIP_arr, df["PBABIP vR_adj_P"].to_numpy(float))

roles = df["Role"]
K_vL     = apply_role_deltas(K_vL,     "K%",     roles)
K_vR     = apply_role_deltas(K_vR,     "K%",     roles)
HR_vL    = apply_role_deltas(HR_vL,    "HR%",    roles)
HR_vR    = apply_role_deltas(HR_vR,    "HR%",    roles)
uBB_vL   = apply_role_deltas(uBB_vL,   "uBB%",   roles)
uBB_vR   = apply_role_deltas(uBB_vR,   "uBB%",   roles)
BABIP_vL = apply_role_deltas(BABIP_vL, "BABIP%", roles)
BABIP_vR = apply_role_deltas(BABIP_vR, "BABIP%", roles)

K_vL_P     = apply_role_deltas(K_vL_P,     "K%",     roles)
K_vR_P     = apply_role_deltas(K_vR_P,     "K%",     roles)
HR_vL_P    = apply_role_deltas(HR_vL_P,    "HR%",    roles)
HR_vR_P    = apply_role_deltas(HR_vR_P,    "HR%",    roles)
uBB_vL_P   = apply_role_deltas(uBB_vL_P,   "uBB%",   roles)
uBB_vR_P   = apply_role_deltas(uBB_vR_P,   "uBB%",   roles)
BABIP_vL_P = apply_role_deltas(BABIP_vL_P, "BABIP%", roles)
BABIP_vR_P = apply_role_deltas(BABIP_vR_P, "BABIP%", roles)

K_vL     = np.clip(K_vL,     0.0, 0.90)
K_vR     = np.clip(K_vR,     0.0, 0.90)
HR_vL    = np.clip(HR_vL,    0.0, 0.50)
HR_vR    = np.clip(HR_vR,    0.0, 0.50)
uBB_vL   = np.clip(uBB_vL,   0.0, 0.90)
uBB_vR   = np.clip(uBB_vR,   0.0, 0.90)
BABIP_vL = np.clip(BABIP_vL, 0.0, 0.90)
BABIP_vR = np.clip(BABIP_vR, 0.0, 0.90)

K_vL_P     = np.clip(K_vL_P,     0.0, 0.90)
K_vR_P     = np.clip(K_vR_P,     0.0, 0.90)
HR_vL_P    = np.clip(HR_vL_P,    0.0, 0.50)
HR_vR_P    = np.clip(HR_vR_P,    0.0, 0.50)
uBB_vL_P   = np.clip(uBB_vL_P,   0.0, 0.90)
uBB_vR_P   = np.clip(uBB_vR_P,   0.0, 0.90)
BABIP_vL_P = np.clip(BABIP_vL_P, 0.0, 0.90)
BABIP_vR_P = np.clip(BABIP_vR_P, 0.0, 0.90)

# -------------------------- BLENDED RATES -------------------------
wL = df["LHB_share"].to_numpy(dtype=float)
wR = 1.0 - wL

K_rate     = np.clip(K_vL*wL     + K_vR*wR,     0.0, 0.90)
HR_rate    = np.clip(HR_vL*wL    + HR_vR*wR,    0.0, 0.50)
uBB_rate   = np.clip(uBB_vL*wL   + uBB_vR*wR,   0.0, 0.90)
BABIP_rate = np.clip(BABIP_vL*wL + BABIP_vR*wR, 0.0, 0.90)

K_rate_P     = np.clip(K_vL_P*wL     + K_vR_P*wR,     0.0, 0.90)
HR_rate_P    = np.clip(HR_vL_P*wL    + HR_vR_P*wR,    0.0, 0.50)
uBB_rate_P   = np.clip(uBB_vL_P*wL   + uBB_vR_P*wR,   0.0, 0.90)
BABIP_rate_P = np.clip(BABIP_vL_P*wL + BABIP_vR_P*wR, 0.0, 0.90)

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

# ------------------------- EVENT PARTITION (POTENTIAL) ------------------------
BIP_rate_P = np.clip(1.0 - (K_rate_P + HR_rate_P + uBB_rate_P + HBP_rate + CI_rate), 0.0, 1.0)
H_on_BIP_P = BIP_rate_P * BABIP_rate_P
OIP_rate_P = BIP_rate_P - H_on_BIP_P

rate_1B_P = H_on_BIP_P * s1
rate_2B_P = H_on_BIP_P * s2
rate_3B_P = H_on_BIP_P * s3

cnt_K_P   = BF * K_rate_P
cnt_HR_P  = BF * HR_rate_P
cnt_uBB_P = BF * uBB_rate_P
cnt_HBP_P = BF * HBP_rate
cnt_CI_P  = BF * CI_rate
cnt_1B_P  = BF * rate_1B_P
cnt_2B_P  = BF * rate_2B_P
cnt_3B_P  = BF * rate_3B_P
cnt_OIP_P = BF * OIP_rate_P
cnt_SF_P  = BF * SF_rate

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

# potential (fully-developed) wOBA / RA9 estimates
BB_total_P = cnt_uBB_P + cnt_CI_P

woba_num_P = (
    WOBA_WEIGHTS["BB"]  * BB_total_P +
    WOBA_WEIGHTS["HBP"] * cnt_HBP_P +
    WOBA_WEIGHTS["1B"]  * cnt_1B_P  +
    WOBA_WEIGHTS["2B"]  * cnt_2B_P  +
    WOBA_WEIGHTS["3B"]  * cnt_3B_P  +
    WOBA_WEIGHTS["HR"]  * cnt_HR_P
)
woba_den_P = np.maximum(BF, 1e-9)
wOBA_P = woba_num_P / woba_den_P

wRAA_per_PA_P = (wOBA_P - LG_WOBA) / WOBA_SCALE
RA9_P = LG_RA9 + (wRAA_per_PA_P * BF_PER_9)
RA9_P = np.clip(RA9_P, 0.0, 20.0)


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

# --- POTENTIAL park-adjusted (CIN) @ 50% HOME ---
BIP_vL_P = np.clip(1.0 - (K_vL_P + HR_vL_P + uBB_vL_P + HBP_rate + CI_rate), 0.0, 1.0)
BIP_vR_P = np.clip(1.0 - (K_vR_P + HR_vR_P + uBB_vR_P + HBP_rate + CI_rate), 0.0, 1.0)

H_on_BIP_vL_P = BIP_vL_P * BABIP_vL_P
H_on_BIP_vR_P = BIP_vR_P * BABIP_vR_P

rate_1B_vL_P = H_on_BIP_vL_P * s1
rate_2B_vL_P = H_on_BIP_vL_P * s2
rate_3B_vL_P = H_on_BIP_vL_P * s3

rate_1B_vR_P = H_on_BIP_vR_P * s1
rate_2B_vR_P = H_on_BIP_vR_P * s2
rate_3B_vR_P = H_on_BIP_vR_P * s3

cnt_1B_L_P = BF_L * rate_1B_vL_P
cnt_2B_L_P = BF_L * rate_2B_vL_P
cnt_3B_L_P = BF_L * rate_3B_vL_P
cnt_HR_L_P = BF_L * HR_vL_P

cnt_1B_R_P = BF_R * rate_1B_vR_P
cnt_2B_R_P = BF_R * rate_2B_vR_P
cnt_3B_R_P = BF_R * rate_3B_vR_P
cnt_HR_R_P = BF_R * HR_vR_P

cnt_1B_CIN_P = (cnt_1B_L_P * CIN_AVG_LHB) + (cnt_1B_R_P * CIN_AVG_RHB)
cnt_2B_CIN_P = (cnt_2B_L_P + cnt_2B_R_P) * CIN_2B
cnt_3B_CIN_P = (cnt_3B_L_P + cnt_3B_R_P) * CIN_3B
cnt_HR_CIN_P = (cnt_HR_L_P * CIN_HR_LHB) + (cnt_HR_R_P * CIN_HR_RHB)

h = HOME_GAME_SHARE
cnt_1B_CIN50_P = (1.0 - h) * cnt_1B_P + h * cnt_1B_CIN_P
cnt_2B_CIN50_P = (1.0 - h) * cnt_2B_P + h * cnt_2B_CIN_P
cnt_3B_CIN50_P = (1.0 - h) * cnt_3B_P + h * cnt_3B_CIN_P
cnt_HR_CIN50_P = (1.0 - h) * cnt_HR_P + h * cnt_HR_CIN_P

woba_num_CIN50_P = (
    WOBA_WEIGHTS["BB"]  * BB_total_P +
    WOBA_WEIGHTS["HBP"] * cnt_HBP_P +
    WOBA_WEIGHTS["1B"]  * cnt_1B_CIN50_P +
    WOBA_WEIGHTS["2B"]  * cnt_2B_CIN50_P +
    WOBA_WEIGHTS["3B"]  * cnt_3B_CIN50_P +
    WOBA_WEIGHTS["HR"]  * cnt_HR_CIN50_P
)

wOBA_CIN50_P = woba_num_CIN50_P / woba_den_P

wRAA_per_PA_CIN50_P = (wOBA_CIN50_P - LG_WOBA) / WOBA_SCALE
RA9_CIN50_P = LG_RA9 + (wRAA_per_PA_CIN50_P * BF_PER_9)
RA9_CIN50_P = np.clip(RA9_CIN50_P, 0.0, 20.0)


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

out["wOBA"]   = wOBA
out["RA9"]    = RA9
out["wOBA_P"] = wOBA_P
out["RA9_P"]  = RA9_P

out["1B_proj_CIN50"] = cnt_1B_CIN50
out["2B_proj_CIN50"] = cnt_2B_CIN50
out["3B_proj_CIN50"] = cnt_3B_CIN50
out["HR_proj_CIN50"] = cnt_HR_CIN50
out["wOBA_CIN50"]   = wOBA_CIN50
out["RA9_CIN50"]    = RA9_CIN50
out["wOBA_CIN50_P"] = wOBA_CIN50_P
out["RA9_CIN50_P"]  = RA9_CIN50_P

with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as w:
    out.to_excel(w, sheet_name="Projections", index=False)
    rating_changes.to_excel(w, sheet_name="RatingChanges", index=False)
    growth_watch.to_excel(w, sheet_name="GrowthWatch", index=False)

print(f"Wrote {OUT_FILE}")