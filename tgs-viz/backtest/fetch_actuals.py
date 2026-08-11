"""
Bank a season's ACTUAL stats from the public StatsPlus per-player stats APIs.

Pulls batting + pitching + fielding for one season and writes them as CSVs with
the exact server headers, preserving the raw split/stint rows (split_id 1=overall,
2=vsL, 3=vsR, 21=playoffs; stint rows have stint>0) — downstream aggregates.

Run this at each season end, before the new season starts. No OOTP needed —
these endpoints are public (no auth).

Usage:
  python tgs-viz/backtest/fetch_actuals.py --league TGS [--slug tgs] [--year 2044] [--levels mlb|all] --write

  --league   folder name under backtest/actuals/ (TGS, BLM)
  --slug     StatsPlus slug (default: lowercased league)
  --year     season to bank (default: current in-game year via /date)
  --levels   mlb = top-level MLB only (level 1 in /lgdata; excludes NPB/foreign);
             all = every league id in /lgdata  (default: mlb)
  --write    actually write (otherwise dry run: fetch + print counts only)

Output: tgs-viz/backtest/actuals/<LEAGUE>/<year>/{batting,pitching,fielding}.csv
Idempotent: re-running overwrites, after saving a timestamped .bak of the old file.
"""
import argparse, csv, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ingest"))
import statsplus as sp  # noqa: E402


def season_complete(game_date, year):
    """Is `year`'s REGULAR SEASON complete as of the in-game date?
    MLB-style calendar heuristic: a later year, or Oct 1+ of the same year
    (playoffs may still be running — regular-season stats are final)."""
    gy, gm = int(game_date[:4]), int(game_date[5:7])
    return gy > year or (gy == year and gm >= 10)


def discover_lids(base, levels):
    """League ids to pull, from /lgdata. 'mlb' = level 1 (the true top-level MLB;
    excludes foreign primaries like TGS's JPBO which sits at level 8)."""
    leagues = sp.fetch_lgdata(base)
    if levels == "all":
        lids = [lg["league_id"] for lg in leagues]
    else:
        lids = [lg["league_id"] for lg in leagues if lg.get("level") == 1]
    if not lids:
        raise SystemExit(f"no league ids found in {base}/lgdata/ for levels={levels}")
    names = {lg["league_id"]: lg.get("abbr") or lg.get("name") for lg in leagues}
    print(f"  leagues ({levels}): " + ", ".join(f"{i}={names.get(i, '?')}" for i in lids))
    return lids


def write_rows(path, rows):
    """Write dict rows back out with the exact server header (key order of row 1)."""
    if os.path.exists(path):
        bak = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(path, bak)
        print(f"  (old file saved as {os.path.basename(bak)})")
    with open(path, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Bank a season's actual stats from StatsPlus")
    ap.add_argument("--league", required=True, help="TGS or BLM (folder name)")
    ap.add_argument("--slug", default=None, help="StatsPlus slug (default: lowercased --league)")
    ap.add_argument("--year", type=int, default=None, help="season year (default: current in-game year)")
    ap.add_argument("--levels", choices=("mlb", "all"), default="mlb")
    ap.add_argument("--allow-partial", action="store_true",
                    help="override the completed-seasons-only rule (analysis previews only)")
    ap.add_argument("--write", action="store_true", help="write CSVs (otherwise dry run)")
    a = ap.parse_args()

    league = a.league.upper()
    base = sp.normalize_base(a.slug or league.lower())
    game_date = sp.fetch_date(base)
    year = a.year or int(game_date[:4])
    complete = season_complete(game_date, year)
    print(f"[{league}] {base}  in-game date {game_date}  banking season {year}")
    if not complete and not a.allow_partial:
        # HARD RULE (user-set): the actuals folders hold COMPLETED seasons only.
        # Mid-season data never lands here — metadata and backtest scoring both
        # require full seasons, and a partial on disk is a trap waiting to be read.
        print(f"  SKIPPED: {year} is still in progress as of {game_date}.")
        print(f"  Re-run at season end (the stats stay fetchable — nothing is lost by waiting).")
        return
    lids = discover_lids(base, a.levels)

    out_dir = os.path.join(HERE, "actuals", league, str(year))
    pulls = [("batting", sp.fetch_batting), ("pitching", sp.fetch_pitching), ("fielding", sp.fetch_fielding)]
    for name, fn in pulls:
        rows = fn(base, year=year, lids=lids)  # no split filter: keep ALL split/stint rows
        players = {r.get("player_id") for r in rows}
        print(f"  {name:<9}: {len(rows):>6} rows   {len(players):>5} distinct players")
        if not rows:
            print(f"  WARNING: {name} came back empty (HTTP 204?) — nothing to write")
            continue
        if a.write:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{name}.csv")
            write_rows(path, rows)
            print(f"  wrote {path}")
    if a.write:
        # Completeness marker: anything scoring/recalibrating from this folder MUST
        # check this first — a mid-season bank is a preview, not the season.
        meta = {
            "league": league, "year": year, "in_game_date": game_date,
            "season_complete": complete,
            "banked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        print(f"  meta.json: season_complete={complete}")
    else:
        print("  (dry run — pass --write to save)")


if __name__ == "__main__":
    main()
