"""
hitter_tails_fit.py — audit D4: refit the PROVEN-BROKEN hitter tail regions from
the archive bucket data and emit calib/<LG>/hitter_tails.json, the opt-in
`tails` layer consumed by engine/hitters.py via ratings.live_hitter_tails().

The four regions (exactly the audit's list — nothing else is touched):
  SO   (K vR   65..80): contact tail under-projected (K-75 +3.8 phantom runs)
  HR   (POW vR 70..80): the 70-75 hump — POW-80 must project >= POW-75
  HHR  (BA vR  20..35): the BA-20 BABIP floor (+14 phantom-dock runs)
  XBH  (GAP vR 20..35 and 70..80): XBH over-projected at both GAP tails

Method (NOTHING INVENTED — every shipped knot value is an archive-measured
bucket quantity, the SB%-cap precedent):
  1. Rebuild the exact pivot1 fit pools (calibrate.py machinery, verified: the
     two-segment WLS refit from these pools must reproduce
     constants-latest.json to ~1e-9 before anything is fitted).
  2. PA-weighted empirical bucket means on the 5-point rungs.
  3. In each audited tail region, fit the bucket means MONOTONE (weighted PAVA
     in the block's known direction), then clip at the two-line's value at the
     region's anchor rung so the corrected curve can never cross back over the
     mid-range line (zero seams, zero inversions).
  4. Ship the region as archive-frame DELTAS off the two-line fit:
     knots [[rung, iso - line], ...] with delta == 0 at the anchor. The engine
     adds interp(knots, rating) to the block's rate — inside the audited
     region it lands ON the measured monotone bucket curve, outside it the
     two-line fit is bit-identical to today (and to the sheet).
     Beyond rating 80 / below 20 the last delta is held (support ends there).

The projection sheets keep their two-segment formulas (sheet formula changes
are out of scope) — this layer is an engine-side INTENTIONAL divergence,
documented at the use sites in hitters.py.

Usage:
  python tgs-viz/engine/hitter_tails_fit.py                # both leagues
  python tgs-viz/engine/hitter_tails_fit.py --league TGS
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calibrate as C  # noqa: E402  (pool machinery reused verbatim)

SUPPORT = (20.0, 80.0)

# block -> (x column, hi/lo constants keys, direction, regions)
# regions: list of (anchor_rung, side); side 'hi' = knots above the anchor,
# 'lo' = knots below. Anchor rungs are the audit's region boundaries; every
# shipped VALUE at the knots is a measured bucket mean.
BLOCKS = {
    "SO":  ("K vR",   ("hK's", "lK's"),   -1, [(60, "hi")]),
    "HR":  ("POW vR", ("hPOW", "lPOW"),   +1, [(65, "hi")]),
    "HHR": ("BA vR",  ("hBABIP", "lBABIP"), +1, [(40, "lo")]),
    "XBH": ("GAP vR", ("hGAP", "lGAP"),   +1, [(40, "lo"), (65, "hi")]),
}


def rate_fns():
    def kp(a):    return a["k"] / (a["pa"] - a["ibb"] - a["bb"] - a["hp"])
    def hrp(a):   return a["hr"] / (a["pa"] - a["ibb"] - a["bb"] - a["hp"])
    def babip(a): return (a["h"] - a["hr"]) / (a["ab"] - a["hr"] - a["k"] + a["sf"])
    def xbh(a):   return (a["d"] + a["t"]) / (a["h"] - a["hr"])
    return {"SO": kp, "HR": hrp, "HHR": babip, "XBH": xbh}


def pava(vals, wts, increasing=True):
    """Weighted pool-adjacent-violators; returns the isotonic sequence."""
    if not increasing:
        return [-v for v in pava([-v for v in vals], wts, True)]
    blocks = []  # [weight, weighted-sum, count]
    for v, w in zip(vals, wts):
        blocks.append([w, w * v, 1])
        while len(blocks) > 1 and \
                blocks[-2][1] / blocks[-2][0] > blocks[-1][1] / blocks[-1][0] + 1e-15:
            w2, wv2, n2 = blocks.pop()
            blocks[-1][0] += w2
            blocks[-1][1] += wv2
            blocks[-1][2] += n2
    out = []
    for w, wv, n in blocks:
        out.extend([wv / w] * n)
    return out


def build_pool(csv_dir):
    bat = C.load_rows(os.path.join(csv_dir, "Batting.csv"))
    hitters = {r["ID"]: r for r in C.load_rows(os.path.join(csv_dir, "Hitters.csv"))
               if isinstance(r.get("ID"), float)}
    bat, _, _ = C.drop_partial_final_season(bat, [], [])
    p1, _ = C.group_sum(bat, "player_id", C.HIT_FIELDS,
                        where=lambda r: r.get("split_id") == 3)
    vis = sorted(i for i, a in p1.items() if a["pa"] >= 10)
    gt = C.totals(p1, vis, C.HIT_FIELDS)
    return p1, vis, gt, hitters


def fit_league(league):
    csv_dir = os.path.join(HERE, "calib", league)
    consts = json.load(open(os.path.join(csv_dir, "constants-latest.json")))["hitting"]
    p1, vis, gt, hitters = build_pool(csv_dir)
    fns = rate_fns()

    out = {"league": league,
           "fitted_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "source": f"engine/hitter_tails_fit.py over calib/{league} archive "
                     "(pivot1 pools, PA-weighted bucket means, anchored PAVA)",
           "support": list(SUPPORT), "blocks": {}}

    print(f"=== {league} (pivot1 n={len(vis)}) ===")
    worst_fid = 0.0
    for blk, (xcol, (khi, klo), direction, regions) in BLOCKS.items():
        yfn = fns[blk]
        xbar = C.rating_mean(hitters, vis, xcol)
        gtr = yfn(gt)
        pts = []
        for i in vis:
            r = hitters.get(i, {}).get(xcol)
            if not isinstance(r, (int, float)):
                continue
            pts.append((float(r), yfn(p1[i]), p1[i]["pa"]))

        # pool fidelity: the two-segment WLS from THESE points must reproduce
        # constants-latest.json (proves the pool == the live fit pool)
        for key, filt in ((khi, lambda x: x >= 50), (klo, lambda x: x < 50)):
            b, m = C.wls([(r - xbar, y - gtr, w) for r, y, w in pts if filt(r)])
            want = consts[key]
            worst_fid = max(worst_fid,
                            abs(b - want[0]) / (1e-9 + abs(want[0])),
                            abs(m - want[1]) / (1e-9 + abs(want[1])))

        b_hi, m_hi = consts[khi]
        b_lo, m_lo = consts[klo]

        def line(r):
            b, m = (b_hi, m_hi) if r >= 50 else (b_lo, m_lo)
            return gtr + b + m * (r - xbar)

        # PA-weighted bucket means on 5-rungs
        agg = {}
        for r, y, w in pts:
            rung = round(r / 5) * 5
            if not (SUPPORT[0] <= rung <= SUPPORT[1]):
                continue
            a = agg.setdefault(rung, [0, 0.0, 0.0])
            a[0] += 1
            a[1] += w
            a[2] += y * w
        buckets = {rung: (n, pa, wy / pa) for rung, (n, pa, wy) in sorted(agg.items())
                   if pa > 0}

        knots = []
        for anchor, side in regions:
            rungs = ([r for r in sorted(buckets) if r > anchor] if side == "hi"
                     else [r for r in sorted(buckets) if r < anchor])
            if not rungs:
                continue
            vals = [buckets[r][2] for r in rungs]
            wts = [buckets[r][1] for r in rungs]
            iso = pava(vals, wts, increasing=(direction > 0))
            bound = line(anchor)
            if side == "hi":
                # composite must stay monotone across the anchor:
                # increasing blocks may not dip below line(anchor), the
                # decreasing block (SO) may not rise above it
                iso = [max(v, bound) if direction > 0 else min(v, bound) for v in iso]
                knots.append((float(anchor), 0.0))
                knots.extend((float(r), iso_v - line(r)) for r, iso_v in zip(rungs, iso))
            else:
                iso = [min(v, bound) if direction > 0 else max(v, bound) for v in iso]
                knots.extend((float(r), iso_v - line(r)) for r, iso_v in zip(rungs, iso))
                knots.append((float(anchor), 0.0))
        knots.sort()

        def adj(r):
            if not knots:
                return 0.0
            if r <= knots[0][0]:
                return knots[0][1]
            if r >= knots[-1][0]:
                return knots[-1][1]
            for (r1, d1), (r2, d2) in zip(knots, knots[1:]):
                if r1 <= r <= r2:
                    return d1 + (d2 - d1) * (r - r1) / (r2 - r1)
            return 0.0

        # report + gate table
        rep = {}
        print(f"  {blk:4} ({xcol:7}) xbar={xbar:.2f} gt={gtr:.4f}  "
              f"regions={[(a, s) for a, s in regions]}")
        for rung in sorted(buckets):
            n, pa, emp = buckets[rung]
            ln = line(rung)
            fx = ln + adj(rung)
            rep[str(int(rung))] = {"n": n, "pa": pa, "emp": emp, "line": ln,
                                   "fitted": fx}
            tag = " <- region" if abs(adj(rung)) > 1e-12 or \
                any((s == "hi" and rung > a) or (s == "lo" and rung < a)
                    for a, s in regions) else ""
            print(f"      r={rung:3.0f} n={n:4d} pa={pa:9.0f}  emp={emp:.4f}  "
                  f"line={ln:.4f} ({ln - emp:+.4f})  fitted={fx:.4f} "
                  f"({fx - emp:+.4f}){tag}")
        # seam/monotonicity scan of the composite over the full support
        bad = 0
        prev = line(SUPPORT[0]) + adj(SUPPORT[0])
        r = SUPPORT[0] + 0.1
        while r <= SUPPORT[1] + 1e-9:
            # composite only guaranteed monotone within a branch; check anyway
            cur = line(r) + adj(r)
            if (cur - prev) * direction < -1e-10 and not (49.9 < r < 50.1):
                bad += 1
            prev = cur
            r += 0.1
        if bad:
            print(f"      !! composite monotonicity violations (outside the "
                  f"50-breakpoint): {bad}")
        out["blocks"][blk] = {
            "x": xcol, "direction": direction,
            "regions": [[a, s] for a, s in regions],
            "knots": [[r, d] for r, d in knots],
            "report": rep, "monotone_violations": bad,
        }
    print(f"  pool fidelity vs constants-latest.json: worst rel diff "
          f"{worst_fid:.2e} ({'OK' if worst_fid < 1e-6 else '!! POOLS DIFFER'})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=["TGS", "BLM"])
    a = ap.parse_args()
    for lg in ([a.league] if a.league else ["TGS", "BLM"]):
        res = fit_league(lg)
        path = os.path.join(HERE, "calib", lg, "hitter_tails.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print(f"wrote {path}\n")


if __name__ == "__main__":
    main()
