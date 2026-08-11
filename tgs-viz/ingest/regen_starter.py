"""
One-off: recompute pitcher projections in the EXISTING app JSON with the current
engine (STARTER_MIN_STM now 35), preserving every joined field (ORG, Lev, Price,
contracts, injury). No StatsPlus pull — uses the rating fields already in the JSON.

  python tgs-viz/ingest/regen_starter.py TGS           # dry run (reports, writes nothing)
  python tgs-viz/ingest/regen_starter.py TGS --write   # overwrite pitchers.json (.bak first)
"""
import os, sys, json, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, ENGINE)
sys.path.insert(0, HERE)
import pitchers as P
import hitters as H
import ratings as R   # for the (fixed) derive_pitcher_counts
REPO = os.path.dirname(os.path.dirname(HERE))

league = next((a for a in sys.argv[1:] if not a.startswith("--")), "TGS")
write = "--write" in sys.argv
jpath = os.path.join(REPO, "tgs-viz", "public", "data", league, "pitchers.json")
ppath = os.path.join(REPO, f"The Sheets {league}", "The Sheet Pitchers.xlsx")

dp, filt, park = P.scan_consts(ppath)
records = json.load(open(jpath, encoding="utf-8"))

def numj(v):
    try: return float(v)
    except (TypeError, ValueError): return None

flipFT = flipTF = recomputed = unchanged_drift = 0
worst_drift = 0.0
new_starters = []
out = []
for rec in records:
    rec = dict(rec)
    rec["Pitches"], rec["SP Pitch"], rec["SP P Pitch"] = R.derive_pitcher_counts(rec)   # re-count from raw grades (fixed)
    p, ok = {}, True
    for col in P.RATING_COLS:
        v = rec.get(col)
        if col in P.META:
            p[col] = v
        else:
            nv = 20.0 if isinstance(v, str) and v.strip() == "-" else H.num(v)
            p[col] = nv
            if nv is None and col not in P.OPTIONAL:
                ok = False
    if not ok:
        out.append(rec); continue
    try:
        comp = P.compute(p, dp, filt, park)
    except Exception:
        out.append(rec); continue
    recomputed += 1
    oldStarter = rec.get("Starter") is True
    newStarter = comp.get("Starter") is True
    # drift check on a guy whose starter flag did NOT change: should be ~0
    if oldStarter == newStarter:
        for c in ("WAA wtd", "WAA wtd RP", "wOBA wtd"):
            a, b = numj(rec.get(c)), numj(comp.get(c))
            if a is not None and b is not None:
                d = abs(a - b)
                worst_drift = max(worst_drift, d)
                if d > 1e-6: unchanged_drift += 1
    if newStarter and not oldStarter:
        flipFT += 1
        if len(new_starters) < 10:
            new_starters.append(f"{rec.get('Name')} (STM {rec.get('STM')}, age {rec.get('Age')}, ORG {rec.get('ORG')}) new SP WAA {comp.get('WAA wtd')}")
    if oldStarter and not newStarter:
        flipTF += 1
    merged = dict(rec)
    merged.update({k: v for k, v in comp.items() if not str(k).startswith("_")})
    out.append(merged)

print(f"{league}: {len(records)} pitchers | recomputed {recomputed}")
print(f"  Starter FALSE->TRUE (newly starter): {flipFT}")
print(f"  Starter TRUE->FALSE (should be 0):   {flipTF}")
print(f"  unchanged-flag players with >1e-6 drift (should be 0): {unchanged_drift}  | worst drift {worst_drift:.2e}")
print("  sample newly-starter:")
for s in new_starters: print("    " + s)
z = next((r for r in out if "Ivan Z" in (r.get("Name") or "")), None)
if z: print(f"  Ivan Zak: Starter now {z.get('Starter')}, SP WAA wtd {z.get('WAA wtd')}, WAP {z.get('WAP')}")

if write:
    if unchanged_drift > 0:
        print("ABORT: unexpected drift on unchanged-flag players — not writing.")
        sys.exit(1)
    shutil.copy2(jpath, jpath + ".bak-starter35-" + time.strftime("%Y%m%d-%H%M%S"))
    json.dump(out, open(jpath, "w", encoding="utf-8"), ensure_ascii=False)
    print("  WROTE " + os.path.relpath(jpath, REPO) + " (.bak saved)")
else:
    print("  (dry run — pass --write to apply)")
