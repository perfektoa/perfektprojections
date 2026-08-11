"""
currency_fit.py — fit the hitter<->pitcher CURRENCY + wins-bookkeeping constants
(audit D2, D6, D9) from each league's 260-season clone archive, and emit
calib/<LEAGUE>/currency.json — the opt-in `currency` layer consumed by
engine/hitters.py + engine/pitchers.py via ratings.live_currency().

NOTHING here writes to any workbook. Everything that ships is FITTED or
MEASURED (user hard requirement — no invented constants):

SHIPPED (wired into the engine / the JS win models):
  * ra9_exponent (D2, per role): wOBA-against -> RA/9 exponent, fitted log-log
    (BF-weighted) on archive pitcher-seasons with the AS-BUILT workbook wOBA
    construction. Gate: octile calibration table act/pred flat under the fit
    (tilted ~0.97 -> 1.04 under the sheet's hardcoded ^2).
  * rpw / H30 override (D9, one per league): wins-per-run-diff regression on
    clone-mean team-seasons. The two OLS directions (W|RD and RD|W) bracket the
    truth; the shipped value is their geometric mean (mid-range spec).
  * luck_sd_wins (D9): the sim's own season-to-season win spread for FIXED
    talent — variance across archive years of each team's clone-mean wins,
    scaled back by the clone count (Var_years(mean_c W) ~= sigma^2_luck/nclone).
  * sp_workload / rp_workload (D9): mean innings actually thrown by each
    team-season's top-5 starters / top-8 relievers vs the model's 5x800 BF and
    8x300 BF statics. The optimizer scales the rostered aggregates by these so
    staff WAA is priced at innings the sim actually hands out.
  * rp_shrink (D6, --rp-backtest): calibration slope of ACTUAL RP RA/9 on the
    CURRENT engine's projected RP RA/9 over the banked 2044 TGS season
    (backtest/actuals joined to the ratings snapshot), + the residual spread
    that widens the Monte Carlo. TGS-fitted, applied to both leagues (BLM has
    no banked actuals yet) — see the note stored in the JSON.

REPORT-ONLY (fitted, then REFUSED by its own gate — deliberately NOT wired):
  * run_values (D2's hitter half): per-event run values from the team-clone-year
    regression of (actual runs - UBR) on event counts. The audit hypothesized
    the as-built hitter run values were ~17% hot (OFF slope 0.855); the
    reproduction shows the as-built OFF already regresses at slope ~0.979
    (both leagues, archive frame; 1.052 +/- 0.04 live-2044 frame) — inside the
    1.00 +/- 0.03 gate — while substituting the fitted values into the wOBA
    construction moves the slope AWAY from 1 (0.944 TGS / 0.962 BLM). The
    construction (runs_minus = total/unproductive-outs) is self-calibrating at
    the team level, so the fitted per-event values de-calibrate it. Full fit +
    both gate slopes are stored under "run_values_report" for the record.

Usage:
  python tgs-viz/engine/currency_fit.py                 # fit + write both leagues
  python tgs-viz/engine/currency_fit.py --league TGS    # one league
  python tgs-viz/engine/currency_fit.py --rp-backtest   # also (re)fit D6 RP shrink
  python tgs-viz/engine/currency_fit.py --dry-run       # print, write nothing
"""
import csv, json, math, os, sys, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CAL = os.path.join(HERE, "calib")
EXT = os.path.join(HERE, "extracted")

# The BLM archive pools a partial 2027 season (audit B11) — drop it everywhere.
DROP_YEARS = {"BLM": {"2027.0", "2027"}}
# ARCHIVE (clone-lab) frame ONLY: the lab archives play ~154 games (archive W+L
# means 154.2/153.5) and this constant just rounds the archive's mean W+L to an
# integer clone count in fit_wins(); the RPW/luck regressions then use G measured
# from the archive itself. The REAL leagues play 162 (measured: TGS banked 2044
# actuals, BLM statsplus 2026 season — all teams W+L=162). Live game counts live
# in src/lib/rosterOptimizer.js LEAGUE_GAMES; do NOT use this constant for them.
GAMES = 154.0


def rows_of(league, fname):
    drop = DROP_YEARS.get(league, set())
    with open(os.path.join(CAL, league, fname), newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["split_id"] not in ("1.0", "1") or row["year"] in drop:
                continue
            yield row


def dollarde(ip):
    return int(ip) + (ip - int(ip)) * 10.0 / 3.0


def lstsq(X, y):
    """Plain OLS via normal equations (no numpy dependency guarantees needed —
    numpy is available in this environment, use it)."""
    import numpy as np
    b, *_ = np.linalg.lstsq(np.asarray(X, float), np.asarray(y, float), rcond=None)
    return b


# ---------------------------------------------------------------- run values (D2 report)

def fit_run_values(league):
    """Team-clone-year regression: (runs - UBR) on event counts. UBR is removed
    from the target because OFF credits it separately (OFF = wRAA + UBRAA + wSB),
    so the wOBA weights must not re-earn baserunning runs. SB/CS enter as
    controls; their own coefficients are NOT shippable from this data (team
    level: confounded — TGS CS comes out +0.39 +/- 0.09, wrong-signed; player
    level identifies only the runner's own scoring channel, missing the
    inning-death cost). Returns the fit + the OFF-slope gates."""
    import numpy as np
    L = defaultdict(float)
    TY = defaultdict(lambda: defaultdict(float))
    for row in rows_of(league, "Batting.csv"):
        g = lambda c: float(row[c] or 0)
        t = TY[(row["year"], row["team_id"])]
        for c in ("r", "ab", "h", "d", "t", "hr", "bb", "ibb", "hp", "sb", "cs",
                  "gdp", "sh", "sf", "ubr"):
            v = g(c); L[c] += v; t[c] += v
    L1B = L["h"] - L["d"] - L["t"] - L["hr"]

    rowsB = []
    for t in TY.values():
        s1 = t["h"] - t["d"] - t["t"] - t["hr"]
        ubb = t["bb"] - t["ibb"] + t["hp"]
        outs = t["ab"] - t["h"] + t["sf"] + t["sh"] + t["gdp"]
        rowsB.append([t["r"] - t["ubr"], ubb, s1, t["d"], t["t"], t["hr"], t["sb"], t["cs"], outs])
    M = np.array(rowsB)
    b = lstsq(M[:, 1:], M[:, 0])
    rng = np.random.default_rng(11)
    bs = [lstsq(M[i][:, 1:], M[i][:, 0]) for i in (rng.integers(0, len(M), len(M)) for _ in range(200))]
    se = np.std(bs, axis=0)
    names = ["uBB", "1B", "2B", "3B", "HR", "SB", "CS", "out"]
    fitted = {n: round(float(v), 4) for n, v in zip(names, b)}
    fitted_se = {n: round(float(v), 4) for n, v in zip(names, se)}

    # ---- OFF-slope gate, as-built vs fitted-substituted ----
    outsL = L["ab"] - L["h"] + L["sf"] + L["sh"] + L["gdp"] + L["cs"]
    rpo = L["r"] / outsL
    rv_old = {"BB": 0.14 + rpo}
    rv_old["HBP"] = rv_old["BB"] + 0.025; rv_old["1B"] = rv_old["BB"] + 0.155
    rv_old["2B"] = rv_old["1B"] + 0.3; rv_old["3B"] = rv_old["2B"] + 0.27
    rv_old["HR"] = 1.4; rv_old["SB"] = 0.2; rv_old["CS"] = -((2 * rpo) + 0.075)
    rv_new = dict(rv_old)
    rv_new.update(BB=float(b[0]), HBP=float(b[0]) + 0.025, **{"1B": float(b[1]),
                  "2B": float(b[2]), "3B": float(b[3]), "HR": float(b[4])})

    def off_slope(rv):
        total = ((L["bb"] - L["ibb"]) * rv["BB"] + rv["HBP"] * L["hp"] + rv["1B"] * L1B
                 + rv["2B"] * L["d"] + rv["3B"] * L["t"] + rv["HR"] * L["hr"]
                 + rv["SB"] * L["sb"] + rv["CS"] * L["cs"])
        pro = L1B + L["d"] + L["t"] + L["hr"] + L["bb"] + L["hp"] - L["ibb"]
        unpro = L["ab"] - (L1B + L["d"] + L["t"] + L["hr"]) + L["sf"]
        rminus = total / unpro
        scale = 1.0 / (total / pro + rminus)
        w = {k: (rv[k] + rminus) * scale for k in ("BB", "HBP", "1B", "2B", "3B", "HR")}
        lgw = ((L["bb"] - L["ibb"]) * w["BB"] + L["hp"] * w["HBP"] + L1B * w["1B"]
               + L["d"] * w["2B"] + L["t"] * w["3B"] + L["hr"] * w["HR"]) \
            / (L["ab"] + L["bb"] + L["hp"] - L["ibb"] + L["sf"])
        lgwsb = max((L["sb"] * rv["SB"] + L["cs"] * rv["CS"]) / (L["bb"] + L["hp"] + L1B - L["ibb"]), 0.0)
        ubr_rate = L["ubr"] / ((L1B + L["bb"] + L["hp"]) * 3 + L["d"] * 2 + L["t"] - L["cs"] * 3 - L["sb"])
        offs, runs = [], []
        for t in TY.values():
            s1 = t["h"] - t["d"] - t["t"] - t["hr"]
            num = ((t["bb"] - t["ibb"]) * w["BB"] + t["hp"] * w["HBP"] + s1 * w["1B"]
                   + t["d"] * w["2B"] + t["t"] * w["3B"] + t["hr"] * w["HR"])
            den = t["ab"] + t["bb"] + t["hp"] - t["ibb"] + t["sf"]
            wraa = (num / den - lgw) / scale * den
            ubraa = t["ubr"] - ubr_rate * ((s1 + t["bb"] + t["hp"]) * 3 + t["d"] * 2 + t["t"] - t["sb"] - t["cs"] * 3)
            wsb = (t["sb"] * rv["SB"] + t["cs"] * rv["CS"]) - lgwsb * (s1 + t["bb"] + t["hp"] - t["ibb"])
            offs.append(wraa + ubraa + wsb); runs.append(t["r"])
        sl = np.polyfit(np.array(offs), np.array(runs), 1)[0]
        r2 = np.corrcoef(offs, runs)[0, 1] ** 2
        return round(float(sl), 3), round(float(r2), 3)

    slope_old = off_slope(rv_old)
    slope_new = off_slope(rv_new)
    return dict(
        method="team-clone-year OLS of (R - UBR) on [uBB+HBP, 1B, 2B, 3B, HR, SB, CS, outs]; n=%d" % len(M),
        fitted=fitted, fitted_se=fitted_se,
        gate_off_slope_asbuilt=dict(slope=slope_old[0], r2=slope_old[1]),
        gate_off_slope_fitted_substituted=dict(slope=slope_new[0], r2=slope_new[1]),
        decision=("NOT WIRED: as-built OFF already inside the 1.00+/-0.03 gate; substituting the "
                  "fitted per-event values de-calibrates it (the wOBA construction's "
                  "runs_minus=total/unpro is self-calibrating at team level). SB/CS additionally "
                  "blocked-on-data (team level confounded, player level misses inning-death)."),
    )


# ---------------------------------------------------------------- pitcher side (D2 exponents)

def fit_exponents(league):
    """Per-role wOBA-against -> RA/9 exponent, archive pitcher-seasons, with the
    AS-BUILT workbook wOBA construction rebuilt in-frame per role (the engine's
    live weights are the same construction over live totals, so the fitted
    exponent transports as a shape parameter — the wOBA ratio is scale-free)."""
    import numpy as np
    P = defaultdict(lambda: defaultdict(float))
    for row in rows_of(league, "Pitching.csv"):
        g = lambda c: float(row[c] or 0)
        p = P[(row["player_id"], row["year"], row["team_id"])]
        for c in ("r", "ab", "ha", "da", "ta", "hra", "bb", "iw", "hp", "sb", "cs",
                  "sf", "sh", "bf", "gs", "g"):
            p[c] += g(c)
        p["ipr"] += dollarde(g("ip"))

    def block_weights(rows_blk):
        B = defaultdict(float)
        for p in rows_blk:
            for c in ("r", "ab", "ha", "da", "ta", "hra", "bb", "iw", "hp", "sb", "cs", "sf", "sh"):
                B[c] += p[c]
            B["ipr"] += p["ipr"]
        s1 = B["ha"] - B["da"] - B["ta"] - B["hra"]
        outs = B["ab"] - B["ha"] + B["cs"] + B["sh"] + B["sf"]
        rpo = B["r"] / outs
        rv = {"BB": 0.14 + rpo}
        rv["HBP"] = rv["BB"] + 0.025; rv["1B"] = rv["BB"] + 0.155
        rv["2B"] = rv["1B"] + 0.3; rv["3B"] = rv["2B"] + 0.27
        rv["HR"] = 1.4; rv["SB"] = 0.2; rv["CS"] = -((2 * rpo) + 0.075)
        total = ((B["bb"] - B["iw"]) * rv["BB"] + rv["HBP"] * B["hp"] + rv["1B"] * s1
                 + rv["2B"] * B["da"] + rv["3B"] * B["ta"] + rv["HR"] * B["hra"]
                 + rv["SB"] * B["sb"] + rv["CS"] * B["cs"])
        pro = s1 + B["da"] + B["ta"] + B["hra"] + B["bb"] + B["hp"] - B["iw"]
        unpro = B["ab"] - (s1 + B["da"] + B["ta"] + B["hra"]) + B["sf"]
        rminus = total / unpro
        scale = 1.0 / (total / pro + rminus)
        w = {k: (rv[k] + rminus) * scale for k in ("BB", "HBP", "1B", "2B", "3B", "HR")}
        w["SB"] = rv["SB"] * scale; w["CS"] = rv["CS"] * scale
        return B, w

    def pwoba(p, w):
        s1 = p["ha"] - p["da"] - p["ta"] - p["hra"]
        num = ((p["bb"] - p["iw"]) * w["BB"] + p["hp"] * w["HBP"] + s1 * w["1B"]
               + p["da"] * w["2B"] + p["ta"] * w["3B"] + p["hra"] * w["HR"]
               + p["sb"] * w["SB"] + p["cs"] * w["CS"])
        den = p["ab"] + p["bb"] - p["iw"] + p["hp"] + p["sf"]
        return num / den if den > 0 else None

    out = {}
    for role in ("SP", "RP"):
        blk = [p for p in P.values() if (p["gs"] > 0) == (role == "SP")]
        B, w = block_weights(blk)
        lgw = pwoba(B, w); lgra9 = B["r"] / B["ipr"] * 9
        xs, ys, wts = [], [], []
        minbf = 200 if role == "SP" else 80
        for p in blk:
            if p["bf"] < minbf or p["ipr"] <= 0 or p["r"] <= 0:
                continue
            wo = pwoba(p, w)
            if not wo or wo <= 0:
                continue
            xs.append(math.log(wo / lgw))
            ys.append(math.log(p["r"] / p["ipr"] * 9 / lgra9))
            wts.append(p["bf"])
        import numpy as np
        xs, ys, wts = np.array(xs), np.array(ys), np.array(wts)
        e = float((wts * xs * ys).sum() / (wts * xs * xs).sum())
        rng = np.random.default_rng(7)
        bs = []
        for _ in range(200):
            i = rng.integers(0, len(xs), len(xs))
            bs.append(float((wts[i] * xs[i] * ys[i]).sum() / (wts[i] * xs[i] * xs[i]).sum()))
        octs = np.array_split(np.argsort(xs), 8)
        tab = lambda ee: [round(float(np.exp(ys[o]).mean() / (np.exp(xs[o]) ** ee).mean()), 3) for o in octs]
        out[role] = dict(exponent=round(e, 3), se=round(float(np.std(bs)), 3), n=int(len(xs)),
                         min_bf=minbf, octile_act_over_pred_fit=tab(e), octile_act_over_pred_e2=tab(2.0))
    return out


# ---------------------------------------------------------------- wins bookkeeping (D9)

def fit_wins(league):
    """RPW (both OLS directions + GM), luck floor, top-5-SP / top-8-RP workload
    factors, clone count and games/season — all from the archive."""
    import numpy as np
    dpw = json.load(open(os.path.join(EXT, f"{league}_pitchers_datapoints.json"), encoding="utf-8"))
    H33, H34 = float(dpw["H33"]), float(dpw["H34"])   # modeled IP per SP / RP slot

    P = defaultdict(lambda: defaultdict(float))
    TP = defaultdict(lambda: defaultdict(float))
    RS = defaultdict(float)
    for row in rows_of(league, "Pitching.csv"):
        g = lambda c: float(row[c] or 0)
        p = P[(row["player_id"], row["year"], row["team_id"])]
        p["gs"] += g("gs"); p["ipr"] += dollarde(g("ip"))
        t = TP[(row["year"], row["team_id"])]
        t["r"] += g("r"); t["w"] += g("w"); t["l"] += g("l")
    for row in rows_of(league, "Batting.csv"):
        RS[(row["year"], row["team_id"])] += float(row["r"] or 0)

    ks = sorted(TP)
    wl = [[TP[k]["w"], TP[k]["l"]] for k in ks]
    import numpy as np
    wl = np.array(wl)
    nclone = round(float(wl.sum(axis=1).mean()) / GAMES)
    G = float((wl.sum(axis=1) / nclone).mean())
    W = wl[:, 0] / nclone
    RD = np.array([(RS[k] - TP[k]["r"]) / nclone for k in ks])
    dW = W - G / 2
    bA = float(np.polyfit(RD, dW, 1)[0])
    bB = float(np.polyfit(dW, RD, 1)[0])
    rpwA, rpwB = 1 / bA, bB
    rpwGM = math.sqrt(rpwA * rpwB)

    teams = sorted({k[1] for k in ks}); yrs = sorted({k[0] for k in ks})
    v = [np.var([TP[(y, tm)]["w"] / nclone for y in yrs if (y, tm) in TP], ddof=1)
         for tm in teams if sum((y, tm) in TP for y in yrs) >= 5]
    luck_sd = math.sqrt(float(np.mean(v)) * nclone)

    staff = defaultdict(list)
    for (pid, y, tm), p in P.items():
        staff[(y, tm)].append(p)
    sp5, rp8 = [], []
    for arr in staff.values():
        sps = sorted((p["ipr"] for p in arr if p["gs"] > 0), reverse=True)
        rps = sorted((p["ipr"] for p in arr if p["gs"] == 0), reverse=True)
        sp5.append(sum(sps[:5]) / nclone)
        rp8.append(sum(rps[:8]) / nclone)
    sp_wl = float(np.mean(sp5)) / (5 * H33)
    rp_wl = float(np.mean(rp8)) / (8 * H34)
    return dict(nclone=nclone, games=round(G, 1),
                rpw=dict(A_W_on_RD=round(rpwA, 3), B_RD_on_W=round(rpwB, 3), GM=round(rpwGM, 3)),
                luck_sd_wins=round(luck_sd, 2),
                sp_workload=round(sp_wl, 3), rp_workload=round(rp_wl, 3),
                sp_top5_ip=round(float(np.mean(sp5)), 1), rp_top8_ip=round(float(np.mean(rp8)), 1),
                model_ip=dict(sp=round(5 * H33, 1), rp=round(8 * H34, 1)))


# ---------------------------------------------------------------- D6 RP shrink (backtest)

def fit_rp_shrink():
    """TGS-only (the only league with banked actuals): re-project the 2044-10-08
    ratings snapshot with the CURRENT engine (S-curves + this currency layer),
    join to the banked 2044 actuals, and fit the RP calibration slope
    (actual RA/9 on projected RA/9, through the IP-weighted centroid) plus the
    residual spread that widens the Monte Carlo. The residual is split into the
    sim's own sampling noise (runs-allowed treated as a count process — Poisson
    variance measured from the observed counts) and projection/talent error."""
    import numpy as np
    sys.path.insert(0, os.path.join(REPO, "tgs-viz", "ingest"))
    import ratings as R
    import statsplus as S

    snap_dir = os.path.join(REPO, "tgs-viz", "backtest", "snapshots", "TGS", "2044-10-08")
    raw = json.load(open(os.path.join(snap_dir, "statsplus_tgs.json"), encoding="utf-8"))
    raw = S.drop_foreign(raw, league="TGS")
    trows = S.translate_rows(raw)
    is_pit = lambda r: str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
    currency = R.live_currency("TGS")
    precs = R.run_pitchers([r for r in trows if is_pit(r)], "TGS",
                           scurves=R.live_scurves("TGS"), currency=currency)
    proj = {str(r.get("ID")): r for r in precs}

    A = defaultdict(lambda: defaultdict(float))
    with open(os.path.join(REPO, "tgs-viz", "backtest", "actuals", "TGS", "2044", "pitching.csv"),
              newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["split_id"] not in ("1", "1.0") or row["level_id"] not in ("1", "1.0"):
                continue
            g = lambda c: float(row[c] or 0)
            a = A[str(int(float(row["player_id"])))]
            a["r"] += g("r"); a["gs"] += g("gs"); a["g"] += g("g"); a["bf"] += g("bf")
            a["ipr"] += dollarde(g("ip"))

    xs, ys, wts = [], [], []
    for pid, a in A.items():
        p = proj.get(pid)
        if not p:
            continue
        # RP outcomes only: pitched in relief (majority of games not started), >= 20 IP
        if a["ipr"] < 20 or a["gs"] > 0.5 * a["g"]:
            continue
        pr = p.get("RA/9 wtd RP")
        if pr is None:
            continue
        xs.append(float(pr)); ys.append(a["r"] / a["ipr"] * 9); wts.append(a["ipr"])
    xs, ys, wts = np.array(xs), np.array(ys), np.array(wts)
    xb = (wts * xs).sum() / wts.sum(); yb = (wts * ys).sum() / wts.sum()
    slope = float((wts * (xs - xb) * (ys - yb)).sum() / (wts * (xs - xb) ** 2).sum())
    r = float(np.corrcoef(xs, ys)[0, 1])
    resid = ys - (yb + slope * (xs - xb))
    resid_sd = float(math.sqrt((wts * resid ** 2).sum() / wts.sum()))
    # sampling floor: runs allowed ~ count process; per-arm RA/9 sampling SD at the
    # mean joined workload = sqrt(mean runs)/IP*9, measured from the joined arms.
    mean_ip = float(wts.mean()); mean_r = float((ys * wts / 9).mean())
    samp_sd = math.sqrt(mean_r) / mean_ip * 9
    talent_sd = math.sqrt(max(resid_sd ** 2 - samp_sd ** 2, 0.0))
    return dict(
        fitted_on="TGS 2044 (snapshot 2044-10-08 re-projected with the CURRENT engine; actuals join)",
        note=("Applied to BOTH leagues: BLM has no banked actuals yet — refit when its first "
              "season lands (fetch_actuals + this tool's --rp-backtest)."),
        n=int(len(xs)), slope=round(slope, 3), r=round(r, 3),
        proj_mean_ra9=round(float(xb), 3), act_mean_ra9=round(float(yb), 3),
        resid_sd_ra9=round(resid_sd, 3), sampling_sd_ra9=round(samp_sd, 3),
        talent_resid_sd_ra9=round(talent_sd, 3), mean_ip=round(mean_ip, 1))


# ---------------------------------------------------------------- assembly

def build(league, rp_shrink=None):
    print(f"=== {league} ===")
    rv = fit_run_values(league)
    print("  run values (REPORT-ONLY):", rv["fitted"])
    print("    OFF-slope gate: as-built", rv["gate_off_slope_asbuilt"],
          "| fitted-substituted", rv["gate_off_slope_fitted_substituted"])
    ex = fit_exponents(league)
    for role in ("SP", "RP"):
        print(f"  {role} exponent {ex[role]['exponent']} +/- {ex[role]['se']} (n={ex[role]['n']})")
        print(f"    octiles fit: {ex[role]['octile_act_over_pred_fit']}")
        print(f"    octiles ^2 : {ex[role]['octile_act_over_pred_e2']}")
    wins = fit_wins(league)
    print(f"  RPW {wins['rpw']}  luckSD {wins['luck_sd_wins']}  "
          f"workload SP {wins['sp_workload']} RP {wins['rp_workload']}")
    rpw = wins["rpw"]["GM"]
    cur = {
        "league": league,
        "fitted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": "engine/currency_fit.py over calib/%s clone archive (%d clones x %s seasons)"
                  % (league, wins["nclone"], "2016-2025" if league == "TGS" else "2016-2026"),
        # ---- wired into the engine ----
        "ra9_exponent": {"SP": ex["SP"]["exponent"], "RP": ex["RP"]["exponent"]},
        "pitcher_cells": {"H30": rpw},
        "hitter_cells": {"H30": rpw},
        # ---- wired into the JS win models (via src/lib/leagueCalib.js) ----
        "rpw": rpw,
        "games": GAMES,
        "luck_sd_wins": wins["luck_sd_wins"],
        "sp_workload": wins["sp_workload"],
        "rp_workload": wins["rp_workload"],
        # ---- provenance / reports ----
        "rpw_specs": wins["rpw"],
        "workload_detail": {k: wins[k] for k in ("sp_top5_ip", "rp_top8_ip", "model_ip", "nclone")},
        "exponent_report": ex,
        "run_values_report": rv,
    }
    if rp_shrink:
        cur["rp_shrink"] = rp_shrink
    return cur


def main():
    leagues = ["TGS", "BLM"]
    if "--league" in sys.argv:
        leagues = [sys.argv[sys.argv.index("--league") + 1]]
    dry = "--dry-run" in sys.argv
    cur_by_lg = {}
    for lg in leagues:
        cur_by_lg[lg] = build(lg)
    if not dry:
        for lg, cur in cur_by_lg.items():
            # keep an existing rp_shrink block if we aren't refitting it now
            path = os.path.join(CAL, lg, "currency.json")
            if os.path.exists(path):
                old = json.load(open(path, encoding="utf-8"))
                if "rp_shrink" in old and "rp_shrink" not in cur:
                    cur["rp_shrink"] = old["rp_shrink"]
            json.dump(cur, open(path, "w", encoding="utf-8"), indent=1)
            print(f"wrote calib/{lg}/currency.json")
    if "--rp-backtest" in sys.argv:
        # needs currency.json in place (projections use the live layer) — run after writing
        shr = fit_rp_shrink()
        print("  D6 RP shrink:", {k: shr[k] for k in ("n", "slope", "r", "resid_sd_ra9",
                                                      "sampling_sd_ra9", "talent_resid_sd_ra9")})
        if not dry:
            for lg in ("TGS", "BLM"):
                path = os.path.join(CAL, lg, "currency.json")
                if os.path.exists(path):
                    cur = json.load(open(path, encoding="utf-8"))
                    cur["rp_shrink"] = shr
                    json.dump(cur, open(path, "w", encoding="utf-8"), indent=1)
                    print(f"updated rp_shrink in calib/{lg}/currency.json")


if __name__ == "__main__":
    main()
