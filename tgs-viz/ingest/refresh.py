"""
One-command refresh — the no-paste pipeline.

Point it at your two OOTP exports (the batters export and the pitchers export,
each = Player List columns ID..R5) and it runs the engine and writes the app's
JSON directly. No pasting into Excel, no Excel formulas. Your sheets are never
opened for this (constants were already lifted by the engine).

  python tgs-viz/ingest/refresh.py --league TGS --hitters hit.html --pitchers pit.html
      --> writes public/data/TGS/hitters_engine.json + pitchers_engine.json (safe side files)

  add --write to overwrite the real hitters.json / pitchers.json (a timestamped
  .bak is made first). The app then shows engine-generated data.

By default it writes SIDE files so you can diff/verify before switching over.
"""
import os, sys, json, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ratings as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def drift_check(league):
    """audit B4 guard: engine/extracted snapshots and calib/constants-latest.json must
    describe the same constants the live workbooks carry. A full calibrate ->
    sync_datapoints --calib -> extract cycle leaves all three in agreement; if one leg
    is re-run and another forgotten, the sentinel cells below diverge (that stale-extract
    drift is how BLM_pitchers ended up carrying TGS constants). Loud warning, non-fatal."""
    eng = os.path.join(REPO, "tgs-viz", "engine")
    paths = {
        "hit": os.path.join(eng, "extracted", f"{league}_hitters_datapoints.json"),
        "pit": os.path.join(eng, "extracted", f"{league}_pitchers_datapoints.json"),
        "cal": os.path.join(eng, "calib", league, "constants-latest.json"),
    }
    missing = [os.path.basename(p) for p in paths.values() if not os.path.exists(p)]
    if missing:
        print(f"  [drift-check {league}] skipped (missing: {', '.join(missing)})")
        return
    src = {k: json.load(open(paths[k], encoding="utf-8")) for k in ("hit", "pit")}
    cal = json.load(open(paths["cal"], encoding="utf-8"))
    # sentinel cell -> constants-latest key. Covers hitting, SBA (B1), UBR (B9),
    # fielding E% (B2/B5), SP lo-STU (the original B4 symptom), lBABIP (B7), RP STU.
    SENTINELS = [
        ("hit", "B3",  ("hitting", "hEYE", 0)),  ("hit", "C3",  ("hitting", "hEYE", 1)),
        ("hit", "B15", ("hitting", "hSBA", 0)),  ("hit", "C15", ("hitting", "hSBA", 1)),
        ("hit", "B19", ("hitting", "UBR", 0)),   ("hit", "C19", ("hitting", "UBR", 1)),
        ("hit", "K15", ("fielding", "2B E%", "intercept")), ("hit", "L15", ("fielding", "2B E%", "x")),
        ("hit", "K25", ("fielding", "SS E%", "intercept")), ("hit", "L25", ("fielding", "SS E%", "x")),
        ("pit", "B7",  ("pitching_sp", "hSTU", 0)), ("pit", "C7", ("pitching_sp", "hSTU", 1)),
        ("pit", "D7",  ("pitching_sp", "lSTU", 0)), ("pit", "E7", ("pitching_sp", "lSTU", 1)),
        ("pit", "D9",  ("pitching_sp", "lBABIP", 0)), ("pit", "E9", ("pitching_sp", "lBABIP", 1)),
        ("pit", "B18", ("pitching_rp", "hSTU", 0)), ("pit", "C18", ("pitching_rp", "hSTU", 1)),
    ]
    bad = checked = 0
    for which, cell, (sec, key, idx) in SENTINELS:
        try:
            got = float(src[which].get(cell))
        except (TypeError, ValueError):
            continue
        want = cal.get(sec, {}).get(key)
        if isinstance(want, dict):
            want = want.get(idx)
        elif isinstance(want, (list, tuple)):
            want = want[idx] if idx < len(want) else None
        if want is None:
            continue
        checked += 1
        # relative (6-sig-fig) tolerance - "1 + |want|" would make this an absolute test and
        # blind the guard to drift in the sub-1 constants, which is all of them
        if abs(got - float(want)) > 1e-6 * max(abs(got), abs(float(want))):
            bad += 1
            print(f"  !! DRIFT {league} {which}!{cell}: extracted {got:.10g} vs "
                  f"constants-latest {float(want):.10g}  [{sec}/{key}]")
    if bad:
        print(f"  !!!!!!!! {league}: {bad}/{checked} sentinel constants DIFFER between "
              f"engine/extracted and calib/constants-latest.json - projections may be "
              f"built on stale constants. Re-run calibrate -> sync_datapoints --calib -> "
              f"extract_sheet/extract_pitchers so all three agree.")
    else:
        print(f"  [drift-check {league}] OK - extracted matches constants-latest on {checked} sentinels")
    # audit D1 status note (league policy): TGS runs the fitted S-curves
    # (calib/TGS/scurves.json); BLM stays on the two-segment lines until its
    # season-end rebuild (ratings re-scouted mid-season after the metadata
    # anchors). See ratings.live_scurves() for the flip procedure.
    if league == "BLM":
        print("  [D1 note] BLM pitching still uses the TWO-SEGMENT curves - the "
              "S-curve flip is TGS-only until BLM's season-end recalibration.")
    # audit D2/D9 status note: the fitted currency layer (RA/9 exponents + RPW)
    # is league-policy LIVE for BOTH leagues (it is archive-fitted, not
    # anchor-dependent, so BLM's mid-season re-scout does not gate it).
    cpath = os.path.join(eng, "calib", league, "currency.json")
    if not os.path.exists(cpath):
        print(f"  !! [currency note] {league}: calib/{league}/currency.json missing - "
              "projections fall back to sheet constants (exp 2.0, tangent RPW). "
              "Run engine/currency_fit.py to restore the fitted D2/D9 layer.")
    # audit D4 + D3 layers (both leagues live — archive-fitted, not anchor-gated)
    for fn, tool, what in [("hitter_tails.json", "engine/hitter_tails_fit.py",
                            "D4 tail corrections (sheet two-line tails)"),
                           ("fielding_curves.json", "engine/fielding_curves_fit.py",
                            "D3 piecewise PM% (sheet linear fits)")]:
        if not os.path.exists(os.path.join(eng, "calib", league, fn)):
            print(f"  !! [{fn.split('.')[0]} note] {league}: calib/{league}/{fn} missing - "
                  f"hitters fall back to {what}. Run {tool}.")


def write_json(records, path, overwrite):
    target = path if overwrite else path.replace(".json", "_engine.json")
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    return target


def main():
    league = _arg("--league", "TGS")
    overwrite = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    drift_check(league)   # audit B4: warn loudly if constants snapshots disagree

    # --- fully-automatic mode: pull ratings from StatsPlus with your token ---
    if "--statsplus" in sys.argv:
        import statsplus as S
        slug = _arg("--slug") or {"TGS": "tgs"}.get(league, league.lower())
        raw_path = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
        if "--from-cache" in sys.argv:    # reprocess the saved raw pull — no auth, no re-fetch
            rows = json.load(open(raw_path, encoding="utf-8"))
            method = "cache"
        else:
            token = os.environ.get("STATSPLUS_TOKEN")
            cookie = os.environ.get("STATSPLUS_COOKIE")
            if not (token or cookie):
                print("Set your StatsPlus browser cookies first (PowerShell):")
                print('  $env:STATSPLUS_COOKIE="sessionid=<...>;csrftoken=<...>"; python tgs-viz\\ingest\\refresh.py --statsplus --league TGS')
                return
            rows, method = S.fetch_ratings(slug, cookie=cookie, token=token)
            if not rows:
                print(f"StatsPlus /ratings returned nothing usable for slug '{slug}' (tried several auth methods).")
                print("If the slug is wrong pass --slug <slug>; otherwise the token may not grant ratings access.")
                return
            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:   # save raw for validation / --from-cache reprocess
                json.dump(rows, f)
            # audit M2 (ratings-input governance): ALSO archive every successful
            # live pull immutably under .cache/history/ — snapshot-to-snapshot
            # scout churn moves projections ~3x model error, and smoothing
            # (ratings.smoothed_pull) needs the vintages. --from-cache
            # reprocessing deliberately does NOT re-archive (same vintage).
            hist_dir = os.path.join(HERE, ".cache", "history")
            os.makedirs(hist_dir, exist_ok=True)
            hist_path = os.path.join(
                hist_dir, f"statsplus_{slug}_" + time.strftime("%Y%m%d-%H%M") + ".json")
            shutil.copy2(raw_path, hist_path)
            print(f"  archived pull -> {os.path.relpath(hist_path, REPO)}")
            # ratings-history DB (informational only — projections never read it):
            # append this live pull to backtest/ratings_history.db so per-player
            # rating trends accumulate automatically. Additive; never fatal.
            try:
                import importlib.util
                _rdb = os.path.join(REPO, "tgs-viz", "backtest", "ratings_db.py")
                spec = importlib.util.spec_from_file_location("ratings_db", _rdb)
                rdb = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rdb)
                rdb.append_pull(league, rows, source="live",
                                files=[os.path.relpath(hist_path, REPO)])
                print("  ratings-history DB: appended pull -> tgs-viz/backtest/ratings_history.db")
                # The .db is gitignored (92 MB binary) and StatsPlus serves no
                # rating history, so a lost pull is unrecoverable. Mirror each
                # vintage to a small committed CSV as it arrives.
                _vb = os.path.join(REPO, "tgs-viz", "backtest", "vintage_backup.py")
                spec = importlib.util.spec_from_file_location("vintage_backup", _vb)
                vb = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(vb)
                vb.export()
            except Exception as e:
                print(f"  WARNING: ratings-history DB append failed "
                      f"({type(e).__name__}: {e}) — refresh continues unaffected")
        cols = list(rows[0].keys())
        print(f"StatsPlus: {len(rows)} ratings rows via {method} ({len(cols)} columns).")

        before = len(rows)
        rows = S.drop_foreign(rows, league=league)   # TGS: NPB/KBO; BLM: none
        print(f"  filtered out {before - len(rows)} foreign players; {len(rows)} remain")

        try:
            names = S.team_name_map(S.fetch_teams(S.normalize_base(slug)))
            S.enrich_org_lev(rows, names, league=league)   # readable ORG + Lev for the app/org-builder
        except Exception as e:
            print(f"  WARNING: couldn't fetch team names ({type(e).__name__}); ORG stays numeric")

        trows = S.translate_rows(rows)

        def is_pit(r):
            return str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
        currency = R.live_currency(league)   # audit D2/D9: fitted currency layer (both leagues)
        print(f"  currency layer: {'FITTED (D2 exponents + D9 RPW, calib/' + league + '/currency.json)' if currency else 'sheet constants (no currency.json)'}")
        tails = R.live_hitter_tails(league)      # audit D4: measured tail corrections (both leagues)
        fielding = R.live_fielding(league)       # audit D3: monotone piecewise PM% (both leagues)
        print(f"  hitter tails: {'FITTED (D4, calib/' + league + '/hitter_tails.json)' if tails else 'sheet two-line (no hitter_tails.json)'}")
        print(f"  fielding PM%: {'PIECEWISE (D3, calib/' + league + '/fielding_curves.json)' if fielding else 'sheet linear (no fielding_curves.json)'}")
        hrecs = R.run_hitters([r for r in trows if not is_pit(r)], league, currency=currency,
                              tails=tails, fielding=fielding)
        scurves = R.live_scurves(league)   # audit D1: fitted S-curves (TGS) / None (BLM)
        print(f"  pitching curves: {'fitted S-curves (D1, calib/' + league + '/scurves.json)' if scurves else 'two-segment lines'}")
        precs = R.run_pitchers([r for r in trows if is_pit(r)], league, scurves=scurves, currency=currency)
        if not hrecs and not precs:
            print("Mapping produced 0 players. Raw columns:")
            print(" ", cols)
            print("Paste that list to me (already saved the raw file) and I'll fix the mapping.")
            return

        # --- attach contracts (salary) + injury/service status ---
        # Public endpoints (no auth). Market Value needs Price; this also adds the
        # per-year salary schedule, current DL status, and MLB service time.
        try:
            base = S.normalize_base(slug)
            cmap, pmap = S.build_contract_injury_maps(S.fetch_contracts(base), S.fetch_players(base))
            n = S.attach_contract_injury(hrecs, cmap, pmap) + S.attach_contract_injury(precs, cmap, pmap)
            print(f"  attached contracts + injury status: {n} players now carry a salary (Price)")
        except Exception as e:
            print(f"  WARNING: couldn't attach contracts/injury ({type(e).__name__}: {e}); Market Value will be blank")

        # Validate the mapping: compare to the sheet's existing hitters.json (same players).
        try:
            cur = {str(x.get("ID")): x for x in json.load(open(os.path.join(out_dir, "hitters.json"), encoding="utf-8"))}
            n = ok = 0; worst = 0.0
            for r in hrecs:
                j = cur.get(str(r.get("ID")))
                if not j:
                    continue
                try:
                    d = abs(float(r.get("Max WAA wtd")) - float(j.get("Max WAA wtd")))
                except (TypeError, ValueError):
                    continue
                n += 1; worst = max(worst, d); ok += (d < 0.5)
            if n:
                verdict = "LOOKS RIGHT — safe to use." if ok > 0.9 * n else "MISMATCH — I'll use the saved raw file to fix the mapping/scale."
                print(f"  mapping check: {ok}/{n} hitters within 0.5 WAA of your sheet (worst {worst:.2f}) -> {verdict}")
        except Exception:
            pass

        if hrecs:
            t = write_json(hrecs, os.path.join(out_dir, "hitters.json"), overwrite)
            print(f"hitters: {len(hrecs)} -> {os.path.relpath(t, REPO)}")
        if precs:
            t = write_json(precs, os.path.join(out_dir, "pitchers.json"), overwrite)
            print(f"pitchers: {len(precs)} -> {os.path.relpath(t, REPO)}")
        print("done." + ("" if overwrite else "  (side files — add --write to go live)"))
        return

    hit_f, pit_f = _arg("--hitters"), _arg("--pitchers")
    if not hit_f and not pit_f:
        print(__doc__)
        return

    if hit_f:
        recs = R.run_hitters(R.read_export(hit_f), league, currency=R.live_currency(league),
                             tails=R.live_hitter_tails(league), fielding=R.live_fielding(league))
        t = write_json(recs, os.path.join(out_dir, "hitters.json"), overwrite)
        print(f"hitters: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    if pit_f:
        recs = R.run_pitchers(R.read_export(pit_f), league, scurves=R.live_scurves(league),
                              currency=R.live_currency(league))
        t = write_json(recs, os.path.join(out_dir, "pitchers.json"), overwrite)
        print(f"pitchers: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    print("done." + ("" if overwrite else "  (side files — add --write to make them live)"))


if __name__ == "__main__":
    main()
