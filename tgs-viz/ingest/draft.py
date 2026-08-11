"""
Build the Draft Board JSON from OOTP's draft-pool CSV + the cached StatsPlus pull.

StatsPlus doesn't expose draft ELIGIBILITY (its draft_year = year-drafted, /draft = past
results), so OOTP's draft-pool export is the authoritative "this year's class." But the
RATINGS for every prospect ARE in the StatsPlus ratings pull. So: the CSV supplies the IDs,
the cached pull supplies the ratings, the engine projects them — no manual ratings paste.

  python tgs-viz/ingest/draft.py --league TGS [--csv "<path>"] [--write]

DISPERSAL mode (--orgs): a commish-run draft that doesn't exist in the game at all —
teams are folding and their entire orgs go into the pool. Eligibility is just org
membership, which the pull DOES know, so no CSV is involved:

  python tgs-viz/ingest/draft.py --league TGS --orgs "Org A,Org B" [--exclude <txt>] [--write]

Pool = every player whose ORG matches (all levels, real Lev kept, contracts + injury
status attached). StatsPlus can't know this draft's picks either, so removal is manual:
--exclude (default: <repo>/dispersal_drafted.txt) lists one player ID or exact name per
line ('#' comments ok) — append as picks happen and re-run. A fresh ratings pull after
the commish processes moves also shrinks the pool naturally (players change org).

Reads `.cache/statsplus_<slug>.json` (left by refresh.py), so run a StatsPlus pull first.
Without --write it writes *_engine.json side files; with --write it overwrites the live
hitters_draft.json / pitchers_draft.json (timestamped .bak first).
"""
import os, sys, json, csv, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, HERE); sys.path.insert(0, ENGINE)
import statsplus as S
import ratings as R
REPO = os.path.dirname(os.path.dirname(HERE))


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


# OOTP draft-pool export(s), per league. Override with --csv (repeatable).
# TGS exports ONE combined file; BLM's screen exports hitters and pitchers
# SEPARATELY — both are read and merged, and the file a row came from decides
# whether it is projected as a hitter or a pitcher (more reliable than POS).
import glob as _glob
_OOTP27 = os.path.join(os.path.expanduser("~"), "Documents", "Out of the Park Developments",
                       "OOTP Baseball 27", "saved_games")
DEFAULT_CSV = {
    # Each league is a LIST OF GROUPS. The first group with a file present wins, so a
    # fresh combined export is never merged with a stale split pair (or vice versa).
    "TGS": [[r"C:\OOTP 26\data\saved_games\TheGrandestSalami.lg\import_export\major_league_baseball_draft_pool_-_draft_pool_default.csv"]],
    "BLM": [[os.path.join(_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_default.csv")],
            [os.path.join(_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_hitter_export.csv"),
             os.path.join(_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_pitcher_export.csv")]],
}


def _pick_group(groups):
    """First group containing at least one existing file (groups may be a flat list)."""
    if groups and isinstance(groups[0], str):
        groups = [groups]
    for g in groups or []:
        if any(p and os.path.exists(p) for p in g):
            return [p for p in g if p and os.path.exists(p)]
    return []


def _load_pool(paths):
    """Read one or more draft-pool CSVs. Returns {id: row}; rows from a file whose
    name says 'pitcher' are tagged _isPit=True, 'hitter' -> False, else None
    (fall back to POS). Later files never clobber earlier ids."""
    by_id, seen = {}, []
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        seen.append(path)
        low = os.path.basename(path).lower()
        tag = True if "pitcher" in low else (False if "hitter" in low else None)
        text = open(path, encoding="utf-8-sig", errors="replace").read()
        n = 0
        for r in csv.DictReader(text.splitlines()):
            pid = str(r.get("ID", "")).strip()
            if not pid or pid in by_id:
                continue
            r["_isPit"] = tag
            by_id[pid] = r
            n += 1
        age_d = (time.time() - os.path.getmtime(path)) / 86400.0
        print(f"  {os.path.basename(path)}: {n} players  (exported {age_d:.0f} days ago)")
        if age_d > 14:
            print(f"    ^ WARNING: that export is {age_d:.0f} days old - re-export the pool "
                  f"from OOTP's Amateur Draft screen if this is a NEW draft.")
    return by_id, seen
# CSV columns the pull lacks but the Draft Board uses (signing demand etc.). Kept verbatim.
CSV_EXTRA = ["DEM", "Sign", "SctAcc", "NAT", "Inf"]
PITCHER_POS = {"SP", "RP", "CL", "P"}


def main():
    league = _arg("--league", "TGS")
    slug = _arg("--slug") or {"TGS": "tgs"}.get(league, league.lower())
    # --csv may be repeated; otherwise use the league's default export path(s).
    cli_csv = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--csv" and i + 1 < len(sys.argv)]
    csv_paths = cli_csv or _pick_group(DEFAULT_CSV.get(league)) or []
    write = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)

    by_id, found = _load_pool(csv_paths)
    if not by_id:
        print(f"No draft-pool CSV found for {league}. Looked for:")
        for g in (DEFAULT_CSV.get(league) or []):
          for p in (g if isinstance(g, list) else [g]):
            print("   " + str(p))
        print("Export the pool from OOTP's Amateur Draft screen (Draft Pool report -> CSV),")
        print("or pass --csv <path> (repeat --csv for separate hitter/pitcher exports).")
        return
    print(f"{len(by_id)} draft-pool players from {len(found)} file(s)")

    # Drop already-drafted players — StatsPlus /draft is the LIVE pick list (matches the pool
    # by ID). This replaces the manual "paste the draft API into the Drafted tab" step, so the
    # board shrinks as the draft happens. As-current-as your last StatsPlus upload.
    try:
        picks = S.fetch_draft(S.normalize_base(slug))
        dids = {str(p.get("ID")) for p in picks}
        dnames = {(p.get("Player Name") or "").strip().lower() for p in picks}
        before = len(by_id)
        by_id = {i: r for i, r in by_id.items()
                 if i not in dids and (r.get("Name") or "").strip().lower() not in dnames}
        print(f"  removed {before - len(by_id)} already-drafted ({len(picks)} picks in StatsPlus); {len(by_id)} still on the board")
    except Exception as e:
        print(f"  WARNING: couldn't fetch draft results ({type(e).__name__}: {e}); board may still show drafted players")

    cache = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
    if not os.path.exists(cache):
        print(f"No cached StatsPlus pull at {cache} — run a StatsPlus refresh first.")
        return
    pull = json.load(open(cache, encoding="utf-8"))
    draft = [r for r in pull if str(r.get("ID")) in by_id]
    print(f"matched {len(draft)} of them in the StatsPlus ratings pull")

    trows = S.translate_rows(draft)
    def is_pit(r):
        """hitter/pitcher: the split-file tag if we have one, else the CSV's POS, else
        the ratings pull's own POS (the combined export carries only ID/Name/OVR/POT)."""
        cr = by_id.get(str(r.get("ID")), {})
        tag = cr.get("_isPit")
        if tag is not None:
            return tag
        pos = str(cr.get("POS") or r.get("POS") or "").upper()
        return pos in PITCHER_POS
    currency = R.live_currency(league)   # audit D2/D9: same fitted currency layer as refresh.py
    hrecs = R.run_hitters([r for r in trows if not is_pit(r)], league, currency=currency,
                          tails=R.live_hitter_tails(league),      # audit D4
                          fielding=R.live_fielding(league))       # audit D3
    # audit D1: same live curve model as refresh.py (S-curves TGS / two-line BLM)
    precs = R.run_pitchers([r for r in trows if is_pit(r)], league,
                           scurves=R.live_scurves(league), currency=currency)

    for rec in hrecs + precs:
        cr = by_id.get(str(rec.get("ID")))
        if cr:
            for f in CSV_EXTRA:
                if cr.get(f) not in (None, ""):
                    rec[f] = cr[f]
        rec["Lev"] = "DRAFT"
        rec.setdefault("ORG", cr.get("NAT", "") if cr else "")

    print(f"projected: {len(hrecs)} hitters, {len(precs)} pitchers")

    def out(records, name):
        target = os.path.join(out_dir, name if write else name.replace(".json", "_engine.json"))
        if write and os.path.exists(os.path.join(out_dir, name)):
            shutil.copy2(os.path.join(out_dir, name), os.path.join(out_dir, name) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        json.dump(records, open(target, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {name if write else os.path.basename(target)}: {len(records)}")

    out(hrecs, "hitters_draft.json")
    out(precs, "pitchers_draft.json")
    print("done." + ("" if write else "  (side files - add --write to go live)"))


def dispersal_main():
    """--orgs mode: pool = entire orgs (folding teams), from the cached pull only."""
    league = _arg("--league", "TGS")
    slug = _arg("--slug") or {"TGS": "tgs"}.get(league, league.lower())
    orgs = [o.strip() for o in (_arg("--orgs") or "").split(",") if o.strip()]
    excl_path = _arg("--exclude") or os.path.join(REPO, "dispersal_drafted.txt")
    write = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    if not orgs:
        print("--orgs needs a comma-separated list of org names (as shown in the app).")
        return

    cache = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
    if not os.path.exists(cache):
        print(f"No cached StatsPlus pull at {cache} — run a StatsPlus refresh first.")
        return
    rows = json.load(open(cache, encoding="utf-8"))
    rows = S.drop_foreign(rows, league=league)

    # Team names are required here (org matching is by name) — fail loudly, not numerically.
    base = S.normalize_base(slug)
    names = S.team_name_map(S.fetch_teams(base))
    S.enrich_org_lev(rows, names, league=league)

    orgset = {o.lower() for o in orgs}
    pool = [r for r in rows if str(r.get("ORG", "")).strip().lower() in orgset]
    from collections import Counter
    per = Counter(str(r.get("ORG")) for r in pool)
    for o in orgs:
        n = per.get(o, sum(v for k, v in per.items() if k.lower() == o.lower()))
        print(f"  {o}: {n} players" + ("  <-- 0 matched — check the spelling!" if not n else ""))
    print(f"dispersal pool: {len(pool)} players from {len(orgs)} orgs")

    # Manual drafted-list removal (this draft doesn't exist in StatsPlus either).
    if os.path.exists(excl_path):
        toks = {ln.strip().lower() for ln in open(excl_path, encoding="utf-8-sig")
                if ln.strip() and not ln.strip().startswith("#")}
        if toks:
            before = len(pool)
            pool = [r for r in pool
                    if str(r.get("ID", "")).strip().lower() not in toks
                    and str(r.get("Name", "")).strip().lower() not in toks]
            print(f"  removed {before - len(pool)} drafted (of {len(toks)} lines in {os.path.basename(excl_path)}); {len(pool)} on the board")

    trows = S.translate_rows(pool)
    is_pit = lambda r: str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
    currency = R.live_currency(league)   # audit D2/D9: same fitted currency layer as refresh.py
    hrecs = R.run_hitters([r for r in trows if not is_pit(r)], league, currency=currency,
                          tails=R.live_hitter_tails(league),      # audit D4
                          fielding=R.live_fielding(league))       # audit D3
    # audit D1: same live curve model as refresh.py (S-curves TGS / two-line BLM)
    precs = R.run_pitchers([r for r in trows if is_pit(r)], league,
                           scurves=R.live_scurves(league), currency=currency)
    print(f"projected: {len(hrecs)} hitters, {len(precs)} pitchers")

    # Salaries + DL status matter when you're inheriting real contracts.
    try:
        cmap, pmap = S.build_contract_injury_maps(S.fetch_contracts(base), S.fetch_players(base))
        n = S.attach_contract_injury(hrecs, cmap, pmap) + S.attach_contract_injury(precs, cmap, pmap)
        print(f"  attached contracts + injury status ({n} with a salary)")
    except Exception as e:
        print(f"  WARNING: couldn't attach contracts/injury ({type(e).__name__}: {e})")

    def out(records, name):
        target = os.path.join(out_dir, name if write else name.replace(".json", "_engine.json"))
        if write and os.path.exists(os.path.join(out_dir, name)):
            shutil.copy2(os.path.join(out_dir, name), os.path.join(out_dir, name) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        json.dump(records, open(target, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {name if write else os.path.basename(target)}: {len(records)}")

    out(hrecs, "hitters_draft.json")
    out(precs, "pitchers_draft.json")
    print("done." + ("" if write else "  (side files - add --write to go live)"))


if __name__ == "__main__":
    dispersal_main() if "--orgs" in sys.argv else main()
