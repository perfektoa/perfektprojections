"""
Offline-league ingest — EXPERIMENTAL.

Builds public/data/<LEAGUE>/{hitters.json, pitchers.json, metadata.json} for a
league that is NOT hosted on StatsPlus, from a single OOTP ratings-export file
(CSV/TSV/HTML table — the "export to file" of a player-list view containing
EVERY player in the universe, hitters and pitchers together).

  python tgs-viz/ingest/offline_league.py MYLEAGUE --ratings-csv path.csv [--ootp-version 26] [--name "My League"] [--write]

Without --write it produces SIDE files (hitters_engine.json / pitchers_engine.json)
so you can inspect before going live. With --write it writes the real
hitters.json / pitchers.json (timestamped .bak first), emits metadata.json, and
adds/updates the league's entry in public/data/leagues.json so the webapp's
league selector picks it up.

Engine calibration: the projection engine's constants (Data Points / Filters /
Ballparks) are lifted read-only from an existing league's projection sheets via
the same scan_consts mechanism the online pipeline uses. --ootp-version picks
which calibration to borrow: 26 -> "The Sheets TGS", 27 -> "The Sheets BLM".
Your offline league must use the SAME player-ratings scale those sheets were
calibrated on (the StatsPlus-style 20-80 numeric scale); no rescaling is done.

STATUS: EXPERIMENTAL — no real offline OOTP export sample has been tested yet.
The COLUMN_MAP below is a best-guess translation of OOTP-export headers to the
engine's field names; headers already using the engine/sheet names pass through
unchanged. If your export's headers differ, extend COLUMN_MAP. Validation is
strict: missing required columns are listed exactly and the script exits
non-zero with instructions for the OOTP export view.

What an offline league CANNOT have (these come only from StatsPlus):
  Price / SalarySchedule / ContractYrs (Market Value), OnDL / DLDays (injury),
  DFA / OnWaivers / MLBSvcYrs, live draft-pool removal. The webapp degrades
  gracefully: those columns render "-" and the Market Value / Draft / FA tabs
  are hidden via the leagues.json feature flags this script writes.

Known caveats:
  * Lev values are normalized by LEV_NORMALIZE (best-guess); unknown level
    strings pass through — such players won't slot into the Org Builder ladder
    (INT/WL/R-/R+/A-/A+/AA/AAA/MLB) but nothing errors.
  * metadata.json borrows the calibration league's "matchups" block (platoon
    vR share) since an offline league has no measured value; the optimizer
    would otherwise fall back to its internal ~0.74 anyway.
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TGS_VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(TGS_VIZ)
sys.path.insert(0, HERE)      # ingest/ratings.py (export reader + engine runner)
sys.path.insert(0, TGS_VIZ)   # extract_data.py (leagues.json manifest helpers)

import ratings as R  # noqa: E402
import extract_data as X  # noqa: E402  (manifest helpers: build_manifest_entry, upsert_manifest)

DATA_DIR = os.path.join(TGS_VIZ, "public", "data")

# Which existing league's projection sheets supply the engine constants for a
# given OOTP version (via ratings.run_hitters/run_pitchers -> scan_consts).
CALIBRATION_BY_VERSION = {"26": "TGS", "27": "BLM"}

# ─── COLUMN_MAP: OOTP-export header -> engine/sheet field name ───────────────
# Only headers that DIFFER from the engine's names need an entry; anything not
# listed here passes through unchanged (so an export already using the sheet's
# Player List names — ID..R5 — needs no mapping at all). Matching is exact
# first, then case-insensitive. Best-guess for OOTP 26 list-view exports;
# extend as real samples surface.
COLUMN_MAP = {
    # bio / roster
    "Position": "POS", "Pos": "POS",
    "Bats": "B", "Throws": "T",
    "Height": "HT", "Hgt": "HT",
    "Organization": "ORG", "Org": "ORG",
    "Level": "Lev", "Lvl": "Lev", "League Level": "Lev",
    "OVR": "Ovr", "Overall": "Ovr", "POT": "Pot", "Potential": "Pot",
    # hitter ratings by split (the sheet's "BA" = the BABIP rating)
    "BABIP vR": "BA vR", "BABIP vL": "BA vL", "BABIP P": "HT P", "BABIP Pot": "HT P",
    "GAP Pot": "GAP P", "POW Pot": "POW P", "EYE Pot": "EYE P",
    "Ks vR": "K vR", "Ks vL": "K vL", "K's vR": "K vR", "K's vL": "K vL",
    "AVK vR": "K vR", "AVK vL": "K vL", "Ks P": "K P", "AVK P": "K P",
    # running / stealing
    "SPD": "SPE", "Speed": "SPE",
    "STL": "STE", "Steal": "STE", "SR Rating": "SR", "Stealing Rate": "SR",
    "BR": "RUN", "Baserunning": "RUN",
    # fielding
    "DP": "TDP", "Turn DP": "TDP",
    "C ABIL": "C ABI", "C BLK": "C ABI", "CBL": "C ABI",
    # pitcher ratings by split (OOTP "CTL" = control -> sheet "CON";
    # movement sub-ratings: pHR -> HRR, pBABIP -> PBABIP)
    "CTL vR": "CON vR", "CTL vL": "CON vL", "CTL P": "CON P", "CTL Pot": "CON P",
    "pHR vR": "HRR vR", "pHR vL": "HRR vL", "pHR P": "HRR P",
    "HRA vR": "HRR vR", "HRA vL": "HRR vL", "HRA P": "HRR P",
    "pBABIP vR": "PBABIP vR", "pBABIP vL": "PBABIP vL", "pBABIP P": "PBABIP P",
    "STU Pot": "STU P",
    "STA": "STM", "Stamina": "STM", "HOLD": "HLD", "Hold": "HLD",
}

# Individual pitch grades, current + potential (needed to derive the engine's
# Pitches / SP Pitch / SP P Pitch counts — same names the sheet uses).
PITCH_COLS_CUR = ["FB", "CH", "CB", "SL", "SI", "SP", "CT", "FO", "CC", "SC", "KC", "KN"]
PITCH_COLS_POT = [c + "P" for c in PITCH_COLS_CUR]

# ─── required / recommended columns (validated AFTER header mapping) ─────────
# ORG and Lev are required because most webapp pages group by ORG and filter by
# Lev (Org Builder, Standings, Market Value) — blank pages without them.
REQUIRED_COMMON = ["ID", "Name", "POS", "Age", "B", "T", "ORG", "Lev"]
REQUIRED_HITTER = [
    "BA vR", "GAP vR", "POW vR", "EYE vR", "K vR",
    "BA vL", "GAP vL", "POW vL", "EYE vL", "K vL",
    "SPE", "SR", "STE", "RUN",
    "IF RNG", "IF ERR", "IF ARM", "TDP",
    "OF RNG", "OF ERR", "OF ARM",
    "C ABI", "C FRM", "C ARM",
    "HT",  # feeds HT Sort (height in cm); "HT Sort" itself also accepted
]
REQUIRED_PITCHER = [
    "STU vR", "HRR vR", "PBABIP vR", "CON vR",
    "STU vL", "HRR vL", "PBABIP vL", "CON vL",
    "STM", "HLD",
] + PITCH_COLS_CUR + PITCH_COLS_POT
# Missing these only degrades (no potential/FV blocks, no durability signal).
RECOMMENDED = ["EYE P", "POW P", "K P", "HT P", "GAP P",
               "STU P", "HRR P", "PBABIP P", "CON P",
               "SB%", "Ovr", "Pot", "Prone"]

# OOTP level label -> the Lev strings the app's level ladder knows
# (best-guess; unknown labels pass through untouched).
LEV_NORMALIZE = {
    "MAJ": "MLB", "ML": "MLB",
    "A": "A-",           # this ecosystem's tier below A+ is written "A-"
    "R": "R+", "RK": "R+", "Rk": "R+",
    "INTL": "INT", "Int'l": "INT",
}

PITCHER_POS = {"P", "SP", "RP", "CL"}


def _canonical_names():
    """Every engine/sheet field name we know about (for case-insensitive fixup)."""
    names = set(REQUIRED_COMMON) | set(REQUIRED_HITTER) | set(REQUIRED_PITCHER) | set(RECOMMENDED)
    names |= {"HT Sort", "HT"}
    return names


def map_headers(records):
    """Rename export headers to engine names: exact COLUMN_MAP match, then
    case-insensitive COLUMN_MAP match, then case-insensitive canonical-name
    fixup; unknown headers pass through unchanged."""
    lower_map = {k.lower(): v for k, v in COLUMN_MAP.items()}
    lower_canon = {n.lower(): n for n in _canonical_names()}

    def map_one(h):
        if h in COLUMN_MAP:
            return COLUMN_MAP[h]
        if h.lower() in lower_map:
            return lower_map[h.lower()]
        if h.lower() in lower_canon:
            return lower_canon[h.lower()]
        return h

    return [{map_one(k): v for k, v in r.items()} for r in records]


def _aliases_for(field):
    """Accepted export headers for an engine field (for error messages)."""
    alts = sorted({k for k, v in COLUMN_MAP.items() if v == field})
    return [field] + alts


def validate_columns(headers, have_hitters, have_pitchers):
    """Strict column check. Returns (missing_required, missing_recommended)."""
    have = set(headers)

    def missing_from(cols):
        out = []
        for c in cols:
            if c == "HT" and ("HT" in have or "HT Sort" in have):
                continue
            if c not in have:
                out.append(c)
        return out

    missing = missing_from(REQUIRED_COMMON)
    if have_hitters:
        missing += missing_from(REQUIRED_HITTER)
    if have_pitchers:
        missing += missing_from(REQUIRED_PITCHER)
    return missing, missing_from(RECOMMENDED)


def check_rating_scale(records):
    """Warn if ratings look like the wrong scale (engine expects the
    StatsPlus-style numeric scale the calibration sheets were built on)."""
    for col in ("BA vR", "STU vR"):
        vals = [R.H.num(r.get(col)) for r in records[:500]]
        vals = [v for v in vals if isinstance(v, float)]
        if vals and max(vals) <= 20:
            print(f"WARNING: '{col}' tops out at {max(vals):g} — this looks like a "
                  f"1-10/2-8 ratings scale. The engine is calibrated on the 20-80 "
                  f"style numeric scale; projections will be nonsense. Switch your "
                  f"OOTP ratings scale (or rescale the export) and re-run.")
            return False
    return True


def write_json(records, path, overwrite):
    """refresh.py semantics: side file unless --write; timestamped .bak first."""
    target = path if overwrite else path.replace(".json", "_engine.json")
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    return target


def build_metadata(league_id, source, calib_league, hrecs, precs):
    """Minimal metadata.json. The webapp only consumes metadata.matchups
    ["OVR vR"] (roster-optimizer platoon share) and tolerates null metadata
    entirely; the rest is documentation. The matchups block is borrowed from
    the calibration league (same sheets the engine constants come from)."""
    meta = {
        "extracted_at": datetime.now().isoformat(),
        "league": league_id,
        "source": source,
        "generator": "ingest/offline_league.py (EXPERIMENTAL)",
        "engine_calibration": calib_league,
        "datasets": {},
    }
    for key, data in (("hitters", hrecs), ("pitchers", precs)):
        if data:
            meta["datasets"][key] = {"count": len(data), "columns": list(data[0].keys())}
    try:
        with open(os.path.join(DATA_DIR, calib_league, "metadata.json"), encoding="utf-8") as f:
            calib_meta = json.load(f)
        if calib_meta.get("matchups"):
            meta["matchups"] = calib_meta["matchups"]
            meta["matchups_note"] = f"borrowed from {calib_league} calibration"
    except (OSError, ValueError):
        pass
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="offline_league.py",
        description="EXPERIMENTAL: build webapp data for an offline (non-StatsPlus) "
                    "league from an OOTP ratings export.",
        epilog="Example: python tgs-viz/ingest/offline_league.py MYLEAGUE "
               "--ratings-csv export.csv --ootp-version 26 --write",
    )
    ap.add_argument("league", help="League id — becomes public/data/<LEAGUE>/ and the "
                                   "selector entry (letters/digits/_/- only)")
    ap.add_argument("--ratings-csv", required=True, metavar="PATH",
                    help="OOTP player-list export (CSV/TSV/HTML) covering ALL players")
    ap.add_argument("--ootp-version", default="26", choices=sorted(CALIBRATION_BY_VERSION),
                    help="OOTP version — picks the engine calibration sheets "
                         "(26->TGS, 27->BLM). Default: 26")
    ap.add_argument("--name", default=None, help="Display name for the league selector "
                                                 "(default: the league id)")
    ap.add_argument("--write", action="store_true",
                    help="Write the real hitters.json/pitchers.json (+metadata.json) and "
                         "register the league in leagues.json. Without this, side "
                         "*_engine.json files are written for inspection.")
    args = ap.parse_args(argv)

    league_id = args.league.strip()
    if not league_id or not all(c.isalnum() or c in "_-" for c in league_id):
        print(f"ERROR: league id {league_id!r} must be letters/digits/underscore/hyphen "
              f"(it becomes a folder and URL path).")
        return 2

    # Never let the offline path clobber a sheet-driven league (TGS/BLM/...).
    if args.write and os.path.isdir(os.path.join(REPO, f"The Sheets {league_id}")):
        print(f"ERROR: '{league_id}' is a sheet-driven league (folder 'The Sheets "
              f"{league_id}' exists). Its data is owned by extract_data.py / "
              f"refresh.py — refusing to --write over it.")
        return 2

    calib_league = CALIBRATION_BY_VERSION[args.ootp_version]
    calib_sheet = os.path.join(REPO, f"The Sheets {calib_league}", "The Sheet Hitters.xlsx")
    if not os.path.exists(calib_sheet):
        print(f"ERROR: calibration sheets for OOTP {args.ootp_version} not found "
              f"(expected {calib_sheet}). The engine borrows its constants from them.")
        return 2

    if not os.path.exists(args.ratings_csv):
        print(f"ERROR: ratings export not found: {args.ratings_csv}")
        return 2

    # ── read + map ──
    records = R.read_export(args.ratings_csv)
    if not records:
        print(f"ERROR: no rows parsed from {args.ratings_csv} (empty file or "
              f"unrecognized format — expected a CSV/TSV/HTML table with headers).")
        return 2
    records = map_headers(records)
    headers = list(records[0].keys())
    print(f"read {len(records)} rows, {len(headers)} columns from {args.ratings_csv}")

    def is_pit(r):
        return str(r.get("POS", "")).strip().upper() in PITCHER_POS

    hit_rows = [r for r in records if not is_pit(r)]
    pit_rows = [r for r in records if is_pit(r)]

    # ── strict validation ──
    missing, missing_rec = validate_columns(headers, bool(hit_rows), bool(pit_rows))
    if missing:
        print("\nMISSING REQUIRED COLUMNS — cannot continue.")
        print("Add these to your OOTP export view (accepted header spellings shown):")
        for field in missing:
            print(f"  {field:12} <- any of: {', '.join(_aliases_for(field))}")
        print("\nYour OOTP player-list view must include: player ID, name, position, "
              "age, bats/throws, organization, level, height, the per-split batting "
              "ratings (BABIP/GAP/POW/EYE/K vs L and vs R), running/stealing, all "
              "fielding ratings, the per-split pitching ratings (STU/pHR/pBABIP/CTL "
              "vs L and vs R), stamina, hold, and every individual pitch rating "
              "(current + potential). Then re-export and re-run.")
        return 2
    if missing_rec:
        print(f"note: recommended columns absent (features degrade, nothing breaks): "
              f"{', '.join(missing_rec)}")

    check_rating_scale(records)

    # ── normalize Lev labels toward the app's level ladder ──
    changed = 0
    for r in records:
        lev = str(r.get("Lev") or "").strip()
        if lev in LEV_NORMALIZE:
            r["Lev"] = LEV_NORMALIZE[lev]
            changed += 1
    if changed:
        print(f"normalized Lev labels on {changed} rows ({LEV_NORMALIZE})")

    # ── run the engine (constants lifted read-only from the calibration sheets) ──
    print(f"engine calibration: OOTP {args.ootp_version} -> The Sheets {calib_league}")
    hrecs = R.run_hitters(hit_rows, calib_league)
    precs = R.run_pitchers(pit_rows, calib_league)
    print(f"hitters : {len(hit_rows)} rows -> {len(hrecs)} computed "
          f"({len(hit_rows) - len(hrecs)} skipped on missing/bad ratings)")
    print(f"pitchers: {len(pit_rows)} rows -> {len(precs)} computed "
          f"({len(pit_rows) - len(precs)} skipped on missing/bad ratings)")
    if not hrecs and not precs:
        print("ERROR: engine produced 0 players — the ratings columns mapped, but "
              "their values didn't parse. Check the export's number formatting.")
        return 1

    # ── write ──
    out_dir = os.path.join(DATA_DIR, league_id)
    os.makedirs(out_dir, exist_ok=True)
    if hrecs:
        t = write_json(hrecs, os.path.join(out_dir, "hitters.json"), args.write)
        print(f"hitters : {len(hrecs)} -> {os.path.relpath(t, REPO)}")
    if precs:
        t = write_json(precs, os.path.join(out_dir, "pitchers.json"), args.write)
        print(f"pitchers: {len(precs)} -> {os.path.relpath(t, REPO)}")

    if not args.write:
        print("done. (side files — inspect them, then re-run with --write to go live)")
        return 0

    # metadata.json (only the matchups block matters to the app; see docstring)
    meta = build_metadata(league_id, os.path.abspath(args.ratings_csv), calib_league, hrecs, precs)
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"metadata.json written ({os.path.relpath(out_dir, REPO)})")

    # register in leagues.json — features derived from what's actually on disk
    # (an offline league: draft/fa/contracts all end up false, so the webapp
    # hides those tabs for it)
    entry = X.build_manifest_entry(league_id, name=args.name or league_id)
    X.upsert_manifest(os.path.join(DATA_DIR, "leagues.json"), [entry])
    feats = ", ".join(k for k, v in entry["features"].items() if v) or "none"
    print(f"leagues.json updated: {league_id} datasets=[{', '.join(entry['datasets'])}] "
          f"features=[{feats}]")
    print("done — the league now appears in the webapp's league selector.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
