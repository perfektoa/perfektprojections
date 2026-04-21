#!/usr/bin/env python
# Build per-batter batting + fielding projections from rating tables, with vR/vL splits.
# Output: batting_fielding_projections.xlsx

import pandas as pd
import numpy as np
from datetime import date, datetime
from bisect import bisect_left

# ---------- FILES ----------
TABLES_FILE = "batting_fielding_rating_tables.xlsx"
MLB_FILE    = "player_search___shortlist_player_shortlist_batting_proj.csv"
AAA_FILE    = "player_search___shortlist_player_shortlist_batting_proj2.csv"
OUT_FILE    = "batting_fielding_projections.xlsx"

RATING_MASTER_FILE = "batting_rating_changes_master.xlsx"
HISTORY_SHEET_NAME = "History"
CHANGES_SHEET_NAME = "Changes"
DATE_COL = "AsOf"

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


# ---------- RATING HISTORY / LONGITUDINAL ANALYTICS ----------
from datetime import timedelta
import re

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

# ---------- POTENTIAL COLUMN MAPS ----------
# If your OOTP export includes potential ratings for individual skills (e.g., "POW P"),
# we use them to compute a "fully-developed" wOBA estimate. If not present, we fall back
# to current ratings.
BASE_POT_COL = {
    "BABIP": _find_potential_col(df, "BABIP"),
    "GAP":   _find_potential_col(df, "GAP"),
    "POW":   _find_potential_col(df, "POW"),
    "EYE":   _find_potential_col(df, "EYE"),
    "K's":   _find_potential_col(df, "K's", extra_candidates=["K P", "K Pot", "K Potential"]),
}

SPLIT_POT_COL = {}
for side in ["vL", "vR"]:
    # Platoon split potential columns, if your export has them (e.g., "POW vL P").
    for col in [f"BA {side}", f"GAP {side}", f"POW {side}", f"EYE {side}", f"K {side}"]:
        SPLIT_POT_COL[col] = _find_potential_col(df, col)



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

def build_rating_snapshot(df_in: pd.DataFrame):
    """Create today's snapshot (ratings + traits) to append into the master history file."""
    join_cols = KEY.copy()

    meta_cols = []
    for c in ["Name", "POS", "ORG", "Age", "Level"]:
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

    # Track: OVR, POT, your existing rating columns, and any matching p-rating (potential) columns.
    ovr_col = _find_col_case_insensitive(tmp, OVR_CANDIDATES)
    pot_col = _find_col_case_insensitive(tmp, POT_CANDIDATES)

    rating_cols = [c for c in RATING_COLS if c in tmp.columns]

    # p-rating columns (potential) that match rating columns by normalized name.
    col_norm_map = {_norm(c): c for c in tmp.columns}
    pot_rating_cols = []
    for r in rating_cols:
        rn = _norm(r)
        # Common patterns: p<rating>, <rating>pot, <rating>potential
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

    # Coerce tracked numeric columns.
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
    h[DATE_COL] = pd.to_datetime(h[DATE_COL], errors="coerce")
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
    h[DATE_COL] = pd.to_datetime(h[DATE_COL], errors="coerce")
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
    out["FirstAsOf"] = pd.to_datetime(out["FirstAsOf"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    out["LastAsOf"] = pd.to_datetime(out["LastAsOf"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    return out

def _top_movers(hist: pd.DataFrame, join_cols: list, meta_cols: list, trait_cols: list, primary_cols: list, days: int) -> pd.DataFrame:
    """Net change between each player's latest snapshot and their snapshot at/before (latest - days)."""
    if hist is None or hist.empty or not primary_cols:
        return pd.DataFrame()

    h = hist.copy()
    h[DATE_COL] = pd.to_datetime(h[DATE_COL], errors="coerce")
    h = h.dropna(subset=[DATE_COL]).sort_values(join_cols + [DATE_COL])

    latest_ts = h[DATE_COL].max()
    cutoff = latest_ts - timedelta(days=days)

    rows = []
    for _, g in h.groupby(join_cols, sort=False):
        g = g.sort_values(DATE_COL)
        latest = g.iloc[-1]
        base = g[g[DATE_COL] <= cutoff].iloc[-1] if (g[DATE_COL] <= cutoff).any() else g.iloc[0]

        row = {c: latest[c] for c in join_cols}
        row["BaseAsOf"] = pd.to_datetime(base[DATE_COL], errors="coerce").strftime("%Y-%m-%d %H:%M:%S.%f")
        row[DATE_COL] = pd.to_datetime(latest[DATE_COL], errors="coerce").strftime("%Y-%m-%d %H:%M:%S.%f")

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
    h[DATE_COL] = pd.to_datetime(h[DATE_COL], errors="coerce")
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
    hist["_AsOf_dt"] = pd.to_datetime(hist[DATE_COL], errors="coerce")
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
)# ---------- PA / GAMES ----------
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

def _pot_rating(row, col: str, base_key: str | None = None) -> float:
    """Return potential rating value for a given column if available, else current."""
    pot_col = SPLIT_POT_COL.get(col)
    if pot_col is not None:
        try:
            v = row[pot_col]
            if not pd.isna(v):
                return float(v)
        except Exception:
            pass

    if base_key is not None:
        base_pot = BASE_POT_COL.get(base_key)
        if base_pot is not None:
            try:
                v = row[base_pot]
                if not pd.isna(v):
                    return float(v)
            except Exception:
                pass

    return float(row[col]) if col in row else 20.0

def side_rates_potential(row, side):
    """Same as side_rates(), but uses potential columns when they exist."""
    if side == "vR":
        BA_col,  GAP_col,  POW_col,  EYE_col,  K_col  = "BA vR","GAP vR","POW vR","EYE vR","K vR"
    else:
        BA_col,  GAP_col,  POW_col,  EYE_col,  K_col  = "BA vL","GAP vL","POW vL","EYE vL","K vL"

    # Map split skills back to overall potential if split potentials aren't exported.
    K_q   = q5f(_pot_rating(row, K_col,   base_key="K's"))
    BB_q  = q5f(_pot_rating(row, EYE_col, base_key="EYE"))
    POW_q = q5f(_pot_rating(row, POW_col, base_key="POW"))
    BA_q  = q5f(_pot_rating(row, BA_col,  base_key="BABIP"))
    GAP_q = q5f(_pot_rating(row, GAP_col, base_key="GAP"))

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


def collect_side(side, use_potential: bool = False):
    fn = side_rates_potential if use_potential else side_rates
    K_lst, BB_lst, HR_lst = [], [], []
    BAB_lst, XBH_lst, TRI_lst = [], [], []
    for _, row in df.iterrows():
        k, bb, hr, bab, xbh, tri = fn(row, side)
        K_lst.append(k); BB_lst.append(bb); HR_lst.append(hr)
        BAB_lst.append(bab); XBH_lst.append(xbh); TRI_lst.append(tri)
    return (np.array(K_lst), np.array(BB_lst), np.array(HR_lst),
            np.array(BAB_lst), np.array(XBH_lst), np.array(TRI_lst))

K_vR, BB_vR, HR_vR, BABIP_vR, XBH_vR, TRI_vR = collect_side("vR", use_potential=False)
K_vL, BB_vL, HR_vL, BABIP_vL, XBH_vL, TRI_vL = collect_side("vL", use_potential=False)

# Potential-based (fully-developed) rate curves
K_vR_P, BB_vR_P, HR_vR_P, BABIP_vR_P, XBH_vR_P, TRI_vR_P = collect_side("vR", use_potential=True)
K_vL_P, BB_vL_P, HR_vL_P, BABIP_vL_P, XBH_vL_P, TRI_vL_P = collect_side("vL", use_potential=True)

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

K_R_P, BB_R_P, HBP_R_P, SF_R_P, CI_R_P, HR_R_P, S1_R_P, S2_R_P, S3_R_P = side_counts(
    PA_R, K_vR_P, BB_vR_P, HR_vR_P, BABIP_vR_P, XBH_vR_P, TRI_vR_P,
    HBP_rate, SF_rate, CI_rate
)
K_L_P, BB_L_P, HBP_L_P, SF_L_P, CI_L_P, HR_L_P, S1_L_P, S2_L_P, S3_L_P = side_counts(
    PA_L, K_vL_P, BB_vL_P, HR_vL_P, BABIP_vL_P, XBH_vL_P, TRI_vL_P,
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

# potential (fully-developed) wOBA estimates (uses potential ratings when exported)
BB_tot_P  = BB_R_P  + BB_L_P
HBP_tot_P = HBP_R_P + HBP_L_P
SF_tot_P  = SF_R_P  + SF_L_P
CI_tot_P  = CI_R_P  + CI_L_P
HR_tot_P  = HR_R_P  + HR_L_P
S1_tot_P  = S1_R_P  + S1_L_P
S2_tot_P  = S2_R_P  + S2_L_P
S3_tot_P  = S3_R_P  + S3_L_P

wOBA_vR_P  = woba_from_counts(PA_R, BB_R_P, HBP_R_P, S1_R_P, S2_R_P, S3_R_P, HR_R_P)
wOBA_vL_P  = woba_from_counts(PA_L, BB_L_P, HBP_L_P, S1_L_P, S2_L_P, S3_L_P, HR_L_P)
wOBA_tot_P = woba_from_counts(PA,   BB_tot_P, HBP_tot_P, S1_tot_P, S2_tot_P, S3_tot_P, HR_tot_P)

wRAA_off_P = (wOBA_tot_P - LEAGUE_WOBA) / WOBA_SCALE * PA
wRAA_vR_P  = (wOBA_vR_P  - LEAGUE_WOBA) / WOBA_SCALE * PA_R
wRAA_vL_P  = (wOBA_vL_P  - LEAGUE_WOBA) / WOBA_SCALE * PA_L

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
out["wobavR_P"]   = wOBA_vR_P

out["K%_vsL"]     = K_vL
out["BB%_vsL"]    = BB_vL
out["HR%_vsL"]    = HR_vL
out["BABIP%_vsL"] = BABIP_vL
out["OBP_vsL"]    = OBP_vL
out["wobavL"]     = wOBA_vL   # <- for lineup tool
out["wobavL_P"]   = wOBA_vL_P

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
out["wOBA_P"]   = wOBA_tot_P
out["wRAA_off"] = wRAA_off
out["wRAA_off_P"] = wRAA_off_P
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
    rating_changes.to_excel(writer, sheet_name="RatingChanges", index=False)
    growth_watch.to_excel(writer, sheet_name="GrowthWatch", index=False)
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

    # ---------- RATING CHANGES SHEET ----------
    ws_ch = writer.sheets["RatingChanges"]
    ws_ch.freeze_panes(1, 0)

    nrows_ch, ncols_ch = rating_changes.shape
    if ncols_ch > 0:
        if nrows_ch > 0:
            table_range_ch = xl_range(0, 0, nrows_ch, ncols_ch - 1)
            ws_ch.add_table(table_range_ch, {
                "name": "RatingChangesTable",
                "header_row": True,
                "style": "TableStyleMedium9",
                "columns": [{"header": col} for col in rating_changes.columns]
            })
        else:
            # Header only; still allow filtering
            ws_ch.autofilter(0, 0, 0, ncols_ch - 1)

    # Helpful widths
    col_idx_ch = {name: i for i, name in enumerate(rating_changes.columns)}
    for name, width in [("ID", 7), ("Name_curr", 22), ("POS_curr", 6), ("ORG_curr", 6), ("PrevAsOf", 12), (DATE_COL, 12)]:
        if name in col_idx_ch:
            ws_ch.set_column(col_idx_ch[name], col_idx_ch[name], width)

    # Conditional formatting on delta columns
    if nrows_ch > 0:
        for cname in [c for c in rating_changes.columns if str(c).startswith("Δ")]:
            c = col_idx_ch[cname]
            data_range = xl_range(1, c, nrows_ch, c)  # skip header
            ws_ch.conditional_format(data_range, {"type": "3_color_scale"})

print(f"Wrote {OUT_FILE}")