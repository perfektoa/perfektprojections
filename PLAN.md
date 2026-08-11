# TGS Projections — Plan: Data Automation + Organization Builder

> Draft v1. Items marked **⚠️ CONFIRM** are assumptions I need you to verify before we lock the design.
> Two goals, in priority order:
> 1. **Kill the manual copy-paste** into the Excel sheets (automate data ingestion).
> 2. **Build an Organization Builder** — place players at the right minor-league level (by age + ability) and balance/flag each org's rosters, for all teams, with league switching like today.
>
> Hard constraint from you: **do NOT change how projections are computed.** The Sheet formulas stay the source of truth. Everything here either *feeds* the Sheet or *consumes* the JSON the Sheet already produces.

---

## How the data flows today (confirmed)

```
OOTP / StatsPlus  --(manual copy-paste)-->  "The Sheet" .xlsx input tabs
                                                  |  (Excel formulas: WAA, wOBA, RA/9, ...)
                                                  v
                                            Hitters / Pitchers computed tabs
                                                  |  extract_data.py (openpyxl, data_only)
                                                  v
                              tgs-viz/public/data/<LEAGUE>/*.json
                                                  |  React app (Vite)
                                                  v
                                            Hitters / Pitchers / Draft / Market / Optimizer / Standings
```

**The manual step we're eliminating** is the first arrow. Each workbook (`The Sheet Hitters.xlsx`, `The Sheet Pitchers.xlsx`, plus `- Draft` / `- FA` variants, per league folder) has dedicated **input tabs** that are pasted by hand:

| Tab | What gets pasted | Source (verified against the live StatsPlus API) |
|---|---|---|
| `Player List` | All players + bio + scouting ratings (OVR, POT, BABIP, GAP, POW, EYE, STU, CON, fielding, personality…) | **Ratings require a StatsPlus login** (`/ratings` returns "requires user to be logged in"). So either an authenticated StatsPlus pull **or** an OOTP CSV export — **⚠️ CONFIRM which you use today.** Bio/service/roster fields are public via `/players`. |
| `Drafted` | Draft results CSV (`"ID","Round","Pick In Round",...`) | ✅ **`/draft` endpoint is live and public** — this *is* the "Draft API from S+". Automatable now. |
| `Trade Block` | Trade-block list | StatsPlus ("Paste Trade Block from S+") — likely needs login like ratings; low priority. |
| `Ballparks` / `Team List` | Park factors / team list | `/teams/` is public (347 teams w/ parent links). Park factors change rarely. |

**Your actual current workflow (confirmed):** ratings come from **OOTP itself**, not StatsPlus. You use **different saved views + shortlists** per sheet, use OOTP's **"export to file" (opens a browser window)**, and **copy-paste** into each `Player List`. Which ratings you export depends on the league's scouting setup — **TGS has no scouts → export OSA ratings; a league with a scout → export the scouted ratings.**

`25 Metadata.xlsx` / `25 Regressions.xlsx` hold league-level calibration (wOBA weights, regression coefficients). You refresh these **at season end** with the latest ratings + stats so the sheet recomputes the **league environment**. Lower frequency than the player refresh, but also an automation target (Part A, phase A5).

---

## Part A — Automate data ingestion (kill the copy-paste)

### The approach
A standalone Python "refresher" that does what your hands do today, end to end:

```
1. FETCH   pull current data from the source (StatsPlus HTTP API and/or OOTP export folder)
2. MAP     reshape it into the exact column layout each Player List / Drafted tab expects
3. INJECT  write it into the workbook input tabs *with Excel open* so formulas recalc
4. EXTRACT run the existing extract_data.py  ->  JSON
5. (opt)   refresh the running app
```

Steps 4–5 already exist (`extract_data.py`, `Update Data.bat`). The new work is steps 1–3.

### Why "with Excel open" matters (key technical point)
`extract_data.py` reads **cached formula values** (`data_only=True`). If we write into the input tabs with a pure-Python writer (openpyxl), the `Hitters`/`Pitchers` formulas will **not recalculate** — the JSON would come out stale/blank. So step 3 must force a recalculation:

- **Recommended: `xlwings`** — drives the real Excel app (you're on Windows with Excel). It opens the workbook hidden, sets values only in the input tab, triggers a full recalc, saves, closes. Safest round-trip for big, formula-heavy, pivot-containing workbooks (won't corrupt charts/formatting the way a full openpyxl rewrite can).
- Fallbacks: LibreOffice headless recalc (riskier on a complex sheet), or "inject + you click each workbook open once" (semi-automated).

### Reusing ootp-dashboard's proven fetch code (MIT-licensed)
Its `model/src/statsplus.py` + `salary_report.py` are **self-contained stdlib** (`urllib`, `csv`) with no projection-code dependencies — liftable as-is. Confirmed endpoints (base = `https://statsplus.net/<league>/api`):

| Endpoint | Returns |
|---|---|
| `/date` | current in-game date → use as a cache key (only re-fetch when the league sims forward) |
| `/players` | player roster rows, service time, draft attributes |
| `/contract`, `/contractextension` | contracts / salaries |
| `/teams/` | every team in the OOTP world |
| `…/reports/news/html/teams/team_<id>_player_salary_report.html` | per-team salary HTML (scraped) |

**NPB Japan exclusion** (your standing rule): `/teams/` returns the whole world (incl. NPB). ootp-dashboard scopes to your league by filtering against the team list in `ballparks.csv`. We reuse that filter so Japan never pollutes TGS/BLM comparisons.

### What the live-API spike proved (TGS, in-game date 2044-02-15)
Tested `statsplus.net/tgs/api/*` directly — it's live and **unauthenticated** for these:

| Endpoint | Status | Feeds |
|---|---|---|
| `/date` | ✅ public | cache key (`2044-02-15`) |
| `/players` (40,953 rows, 45 cols) | ✅ public | bio, age, level, pos, service time, roster/DL/waiver status, draft attrs — **but NO ratings** |
| `/contract` (16,920 rows, 40 cols) | ✅ public | salaries, options, no-trade, bonuses |
| `/teams/` (347 rows) | ✅ public | team hierarchy w/ `Parent Team ID` (affiliate→MLB), NPB filter |
| `/draft` (121 rows) | ✅ public | **the "Draft API from S+"** — draft results for the `Drafted` tab |
| `/ratings` | 🔒 **login required** | scouting ratings (OVR/POT/BABIP/GAP/POW/EYE/STU/CON…) |

So **almost everything is automatable today with zero auth.** The *only* gated piece is **ratings** (the heart of `Player List`), which today you pull from OOTP via "export to file" + copy-paste. Two ways to automate it:

- **Option A — authenticated StatsPlus `/ratings` (preferred if it works):** replicate your logged-in `/ratings` request using a **session cookie** (copied from a browser logged into `statsplus.net/<league>` and linked to your team — no password stored). Two big wins: (1) **fully hands-off** — no OOTP interaction at all; (2) it serves **the logged-in team's ratings view**, so it returns **OSA for TGS and scouted ratings for BLM automatically** — exactly your per-league requirement, no config. Cost: sessions expire, so we refresh the cookie occasionally. **Next step: test `/ratings` with a real cookie to confirm its columns match `Player List`.**
- **Option B — OOTP CSV export auto-ingest (reliable fallback):** switch your OOTP "export to file (browser)" to **"Write Report to CSV"** (writes to disk). Your existing views/shortlists still define the columns (OSA or scouted, per league). One export click per view, then we auto-discover → map → inject → recalc → extract. No cookies; one click remains instead of the paste. (This is the ootp-dashboard approach — they even ship saved-view files so the export columns line up.)

Recommendation: **try Option A first** (test `/ratings`); if its columns don't cover everything the sheet needs, fall back to Option B. Either way the *pasting* disappears.

### Draft-pool / `Drafted` automation — ✅ solved
`/draft` is the StatsPlus "Draft API" the sheet wants pasted. It's public and returns the exact CSV shape (`ID, Round, Pick In Round, Overall, Player Name, Team`). We fetch it and inject straight into the `Drafted` tab — no more draft pasting.

### Phasing (Part A)
- **A0 — Public-API spike — ✅ DONE:** TGS API is live and unauthenticated for `/date`, `/players`, `/contract`, `/teams/`, `/draft`; only `/ratings` needs login. (See table above.)
- **A0.5 — Ratings spike (next):** test `/ratings` with a real session cookie. Resolves Option A vs B and confirms the ratings columns map to `Player List`. (Needs you to grab a cookie — I'll walk you through it.)
- **A1 — Fetch layer:** port `statsplus.py`/`salary_report.py` into a `tgs-viz/ingest/` module; per-league `league.json` (`statsplusUrl`, `team`, team list for the NPB filter). Use `/teams/` `Parent Team ID` to map affiliates → MLB parent.
- **A2 — Mapper:** map fetched fields → each `Player List` / `Drafted` column layout (one mapping per workbook type; OSA vs scouted handled by the source).
- **A3 — Injector:** `xlwings` writer that injects + recalcs + saves each workbook.
- **A4 — Orchestrator:** one command (`Refresh Data.bat`) = fetch → inject → `extract_data.py` → done; in-game-date cache so re-runs are cheap.
- **A5 — Seasonal metadata (lower priority):** pull season ratings + league stats and write the `25 Metadata` tabs so the league environment recomputes — automating the season-end refresh.

---

## Part B — Organization Builder

Goal: for **any** org (league-switchable like today), build the best set of affiliate rosters across the ladder (MLB-26 → AAA → AA → A+ → A → R), **placing each player at the level he should play** — challenged but not buried — then **balance** each roster and **flag** surpluses/holes.

This is a **new consumer of the existing JSON** — it does not touch the projection method. Neither project does this today; it's the net-new feature.

### What we already have in the data (no new pipeline needed)
Every player record already carries: `ORG`, `Lev` (full `R-/R+/A-/A+/AA/AAA/MLB` ladder + `INT`/`WL`), `Age`, `POS`, per-position WAA (current + potential) and split (vR/vL), position-eligibility booleans, `Prone`, work ethic, and the four computable value grades (FutureValue / DraftFV / G5 / Hybrid). That's enough to build everything below.

### B1 — Ability→Level model ("can he compete here, and is he wasting his time?")
We don't have native per-level stat projections — we have each player's **MLB-equivalent** talent (best-position WAA for hitters; best of SP/RP WAA for pitchers). So calibrate empirically:
- For each level, build the **league-wide distribution of incumbents' ability** (you have ~500 MLB / ~550 AAA hitters, etc. — big samples), **excluding NPB Japan**.
- That gives each level a competitive band. Then per player:
  - **Too high (overmatched):** ability below the level's ~20th pct → he'll get buried.
  - **Too low (wasting development):** ability above the level's ~80th pct → promote.
  - **Right level:** the highest level where he's still ≥ competitive.
- Honest caveat: this maps MLB-equivalent talent to levels via incumbent distributions — a calibrated inference, not a native per-level stat line. It's the right method given the data (and how scouts reason).

### B2 — Age-for-level overlay
- **Prospect vs filler tag:** young + good = push aggressively; old + mediocre = org depth/filler.
- **Age band per level** (R ~17–19 … AAA ~24–26): "old for level" = yellow (limited ceiling); "young for level" = green (advanced). Reuses the development curve already in `futureValue.js`.

### B3 — Affiliate roster construction (top-down cascade)
- MLB-26 = the existing `rosterOptimizer.js` output.
- Fill AAA→R in turn: take the best *available* players (not used above) who fit the level's band and round out positional/role needs, respecting per-level capacities (~2 C, full IF/OF + utility, ~5 SP, ~6–7 RP — configurable).
- Reuse the constraint-assignment pattern from `optimalPositionAssignment` (already in the repo) for the per-team lineup fit.
- Leftover good-but-blocked players → "promote or trade" list; unfilled slots → "need a C at AA" list.

### B4 — Balance & gap flags (per affiliate AND org-wide)
Extends ootp-dashboard's `depth.js`/`crunch.js` ideas to the **full pyramid** (theirs is 40-man only):
- Pitching shortfalls (<5 SP, thin RP, no LHP), catching depth in the low minors, a glut of 1B/DH-only bats, an affiliate that's all filler/no prospects.
- Org-wide: a position with no above-replacement prospect at any level = **future hole**; deep everywhere = **surplus / trade chip**.

### Borrowed foundation: positional-strength engine
Port the idea behind ootp-dashboard's `strength.js` — score every team at every position in two lenses (**Now** = current WAR; **Farm** = MiLB-only upside), slot-weighted, z-scored, league-ranked, with below-replacement depth counting negative. It's the substrate the gap flags and "org need" all stand on, and it's the biggest thing TGS lacks today. Field names differ (their JSON is nested; ours is flat), so it's port-the-logic / remap-the-fields, not copy-paste.

### UI (new page in tgs-viz)
- `/organization` page: org selector (all teams) + league switcher (reuses existing pattern).
- Pyramid view: MLB → AAA → AA → A+ → A → R, each as a built roster card with lineup/rotation/bullpen and a balance scorecard.
- Per-player chips: suggested level, promote/hold/demote, prospect-vs-filler, too-high/too-low flags.
- Org needs panel: holes, surpluses, future holes, trade chips.

### Phasing (Part B)
- **B0:** positional-strength + per-level aggregation engine (foundation) → a read-only "org strength" view.
- **B1:** ability→level + age-for-level scoring → per-player fit chips.
- **B2:** affiliate roster builder (cascade).
- **B3:** balance/gap flags + org-needs panel.
- **B4:** polish, all-teams comparison, trade-chip surfacing.

---

## Best parts of ootp-dashboard worth borrowing (summary)

| Borrow | From | Use here |
|---|---|---|
| StatsPlus HTTP fetch (no auth) | `statsplus.py`, `salary_report.py` | Part A — kill the paste |
| Team-list filter to exclude NPB | ballparks team set | Part A + B — clean comparisons |
| In-game-date fetch cache | `fetch_game_date` + cache | Part A — cheap re-runs |
| Positional-strength engine (Now/Farm, z-scores) | `strength.js` | Part B — foundation |
| Roster balance / gap flags + smart suggestions | `depth.js`, `crunch.js` | Part B4 |
| Aging/decline curve for future needs | `decline.js` | Part B — future holes |
| (Later, optional) Super-Two / option / Rule 5 modeling | `rosterPlanning/`, `contract_projection.py` | future roster-rules layer |

We are **not** borrowing their projection engine (WAR re-implementation, metadata calibration) — your Sheet stays the source of truth.

---

## Open questions to finalize  ⚠️
1. **Ratings — answered:** today you pull from OOTP views/shortlists (OSA for TGS, scouted for a scout league) via "export to file" + paste. **Decision left:** Option A (authed StatsPlus `/ratings`) vs Option B (OOTP CSV export) — resolved by the **A0.5 ratings spike**.
2. **BLM slug:** BLM is confirmed on StatsPlus — need its URL slug (`statsplus.net/<slug>/`) to wire it in.
3. **Excel for recalc:** confirm Excel is installed (for the `xlwings` injector). Almost certainly yes.
4. **Sequencing:** recommend Part A (automation) first, then Part B (Organization Builder). Confirm or flip.

## Suggested sequencing
1. **A0 spike** (resolves Q1/Q2 in an afternoon).
2. **Part A** automation (immediate daily relief, and it makes B faster to iterate on since data refreshes are one command).
3. **Part B** Organization Builder (B0 foundation → builder → flags).
