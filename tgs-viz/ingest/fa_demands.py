"""
fa_demands.py — free agent demands -> public/data/<LG>/fa_demands.json

StatsPlus has no free agent demands. The in-game Free Agents screen does: export it
from OOTP (Transactions > Free Agents, all free agents, a view with the DEM and Sign
columns) and it lands in the save's import_export folder as FNAME below.

This writes only what StatsPlus lacks, joined on ID by the app:
    DEM     the asking salary per year as OOTP shows it ("$12.5m", "$850k", "-")
    Demand  the same in dollars (null for "-": no set demand)
    Sign    signability (Very Easy / Easy / ...)

No projection is recomputed here (the same rule as iafa.py): the FA pages compare
Demand with the Fair AAV the app already computes for the row.

    python ingest/fa_demands.py [--league TGS] [--csv <path>] [--write]

Without --write it reports what it would do. A missing export is not an error: the
FA pages then show no demands.
"""
import os
import re
import sys
import csv
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402

FNAME = "mlb_transactions_free_agents_-_all_free_agents_fa_screen.csv"
DEFAULT_CSV = {
    lg: os.path.join(ST.ootp_save_dir(lg), "import_export", FNAME)
    for lg, e in ST.leagues(include_disabled=True).items()
    if e.get("type") == "statsplus" and ST.ootp_save_dir(lg)
}
KEEP = ("ID", "Name", "POS", "Age", "DEM", "Sign")
# Demands move as free agency goes on, so an old export is flagged sooner than the IAFA one.
STALE_DAYS = 3


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def demand_dollars(dem):
    """'$12.5m' -> 12500000, '$850k' -> 850000, '-' or blank -> None."""
    m = re.match(r"^\s*\$\s*([\d.]+)\s*([mk])\s*$", str(dem or ""), re.I)
    if not m:
        return None
    return round(float(m.group(1)) * (1e6 if m.group(2).lower() == "m" else 1e3))


def load_demands(path):
    """Read the export. Returns [] when the file is absent."""
    if not path or not os.path.exists(path):
        return []
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days > STALE_DAYS:
        print(f"  WARNING: export is {age_days:.0f} days old. Demands change during free agency; "
              f"export it again from OOTP.")
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        pid = str(r.get("ID") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not pid or not name:
            continue
        rec = {k: (str(r.get(k) or "").strip() or None) for k in KEEP}
        rec["Demand"] = demand_dollars(rec["DEM"])
        out.append(rec)
    return out


def main():
    league = _arg("--league", "TGS")
    write = "--write" in sys.argv
    path = _arg("--csv") or DEFAULT_CSV.get(league)
    pool = load_demands(path)
    if not pool:
        print(f"FA demands {league}: no export found at {path or '(none configured)'}. Nothing to do.")
        return 0

    ids = {p["ID"] for p in pool}
    priced = sum(1 for p in pool if p["Demand"] is not None)
    data_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    matched = 0
    for fn in ("hitters.json", "pitchers.json"):
        fp = os.path.join(data_dir, fn)
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as fh:
                rows = json.load(fh)
            matched += sum(1 for r in rows if str(r.get("ID") or "").strip() in ids)
    print(f"FA demands {league}: {len(pool)} free agents in the export ({priced} with a set demand), "
          f"{matched} matched in the app data")
    if matched < len(pool):
        print(f"  {len(pool) - matched} not in the app data (players outside the ratings pull keep no demand).")

    out_path = os.path.join(data_dir, "fa_demands.json")
    if not write:
        print(f"  (dry run) would write {out_path}. Pass --write.")
        return 0
    os.makedirs(data_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(pool, fh, ensure_ascii=False)
    print(f"  wrote {os.path.relpath(out_path, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
