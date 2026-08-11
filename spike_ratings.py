"""
Quick check: can we pull your StatsPlus player RATINGS, and what columns come
back? (Once this works, `refresh.py --statsplus` makes the whole refresh
hands-off.)

StatsPlus authenticates with your **browser cookies** (sessionid + csrftoken),
and ratings is an async job (start -> poll). Your secret stays on your machine —
this reads it from an environment variable and only sends it to statsplus.net.
Paste me the "COLUMNS:" line it prints (not the cookie).

HOW TO GET THE COOKIE (one time):
  1. In your browser, log into  https://statsplus.net/tgs/  (linked to your team).
  2. F12 -> Application (or Storage) -> Cookies -> https://statsplus.net
  3. Copy the VALUES of  sessionid  and  csrftoken.

HOW TO RUN (PowerShell, from the project folder):
  $env:STATSPLUS_COOKIE="sessionid=<paste>;csrftoken=<paste>"; python spike_ratings.py tgs
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tgs-viz", "ingest"))
import statsplus as S

slug = sys.argv[1] if len(sys.argv) > 1 else "tgs"
cookie = os.environ.get("STATSPLUS_COOKIE", "").strip()
token = os.environ.get("STATSPLUS_TOKEN", "").strip()

# rating-ish fields we hope to see (exact names may differ — eyeball COLUMNS)
WANT = ["BABIP", "GAP", "POW", "EYE", "STU", "CON", "HRR", "OVR", "POT", "BA vR", "STU vR"]


def main():
    if not (cookie or token):
        print("Set STATSPLUS_COOKIE first — see the instructions at the top of this file.")
        return
    rows, method = S.fetch_ratings(slug, cookie=cookie, token=token)
    if not rows:
        print("\nCouldn't get ratings (see messages above). If you're sure you're logged in,")
        print("double-check the cookie includes BOTH sessionid and csrftoken.")
        return
    cols = list(rows[0].keys())
    print(f"\nSUCCESS via {method} — {len(rows)} players, {len(cols)} columns.")
    print("COLUMNS:", cols)
    present = [w for w in WANT if w in cols]
    print("rating-ish fields found:", present or "NONE (names differ — eyeball COLUMNS above)")
    print("\n-> Paste the COLUMNS line to me and I'll wire the fully-automatic refresh.")


if __name__ == "__main__":
    main()
