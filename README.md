# Perfekt Projections — TGS Baseball Projection System

A player valuation and draft-ranking system for **Out of the Park Baseball 26** (OOTP).
Exports data from in-game Excel sheets, runs it through Future Value (FV) and
Draft FV models, and displays everything in a local web app you open in your browser.

Originally built for my own league; this guide explains how to set it up for yours.

---

## What you get

- **Hitters / Pitchers page** — every player in your league scored on FV (20-80 scale) and Draft FV
- **Draft Board** — draft-eligible players only, filters as you make picks
- **Market Value page** — trade/roster valuation in dollars
- **Roster Optimizer** — lineup / bullpen / rotation suggestions
- **Team Standings / Dev Analysis** — league overview and prospect tuning
- **Multi-league support** — run it for as many save files as you want, side by side

See [TGS Valuation Systems Explained.txt](TGS%20Valuation%20Systems%20Explained.txt)
for how FV and Draft FV are calculated.

---

## Requirements

Install these once:

1. **Python 3.10+** — https://www.python.org/downloads/
   - During install, **check the box "Add Python to PATH"**
2. **Node.js 18+** — https://nodejs.org/ (LTS version is fine)
3. **OOTP 26** — obviously
4. **GitHub Desktop** (optional, but easy) — https://desktop.github.com/

After installing Python, open a Command Prompt and run:

```
pip install openpyxl
```

That's the only Python package needed.

---

## One-time setup

### 1. Get the code

**With GitHub Desktop (easiest):**
- File → Clone Repository → URL tab
- Paste: `https://github.com/perfektoa/perfektprojections`
- Pick where to put it (default is fine) and click **Clone**

**Or with a terminal:**
```
git clone https://github.com/perfektoa/perfektprojections.git
```

### 2. Install webapp dependencies

Open the folder in File Explorer. Go into `tgs-viz/`. In the address bar, type `cmd` and press Enter — that opens a Command Prompt in that folder. Then run:

```
npm install
```

Wait for it to finish (~1-2 minutes first time).

### 3. Set up your league data

Decide what you want to call your league (e.g. `MYLEAGUE`). Create a folder next to `tgs-viz/` named:

```
The Sheets MYLEAGUE
```

The script auto-discovers any folder starting with `The Sheets `. You can have multiple leagues at once.

Inside that folder, drop in these Excel files (exported from OOTP — see "Where the xlsx files come from" below):

| File | Required? | What it's for |
|---|---|---|
| `The Sheet Hitters.xlsx` | **Required** | Main hitters list |
| `The Sheet Pitchers.xlsx` | **Required** | Main pitchers list |
| `The Sheet Hitters - Draft.xlsx` | Optional | Draft board hitters |
| `The Sheet Pitchers - Draft.xlsx` | Optional | Draft board pitchers |
| `The Sheet Hitters - FA.xlsx` | Optional | Free agent hitters |
| `The Sheet Pitchers - FA.xlsx` | Optional | Free agent pitchers |

Each file needs a sheet named `Hitters` or `Pitchers` with the standard column layout
(ID, Name, Age, WAA columns, wOBA, potential columns, Prone, WE, INT, etc.).

See my `The Sheets TGS/` folder in the repo for a working example.

### 4. Run the data extractor

Double-click **`Update Data.bat`**. It will:
- Find all `The Sheets *` folders
- Read the xlsx files
- Write JSON files to `tgs-viz/public/data/<LEAGUE_ID>/`
- Update `leagues.json` so the webapp knows what's available

You'll see a window showing progress. Takes 10-60 seconds depending on league size.

### 5. Launch the webapp

Double-click **`Launch TGS.bat`**. It will:
- Start the Vite dev server on port 3000
- Open your browser to `http://localhost:3000`

Switch between leagues with the dropdown in the top nav.

Leave the window open while you use the app. Closing it stops the server.

---

## Daily usage

Once set up, the loop is:

1. Play your OOTP season
2. Re-export the xlsx files into your `The Sheets <LEAGUE>` folder (overwrite the old ones)
3. Double-click `Update Data.bat`
4. Double-click `Launch TGS.bat` (if not already running) and refresh your browser

---

## Where the xlsx files come from

The Excel files are expected to be outputs of the "25 Regressions" workflow —
in-game ratings run through regression formulas that produce WAA (Wins Above Average)
projections per player. The key columns the app reads:

- **IDs & identity:** `ID`, `Name`, `Age`, `POS`, `ORG`, `Level`
- **Current WAA:** `WAA wtd`, `Max WAA wtd`, `Max WAA vR`, `WAA wtd RP`
- **Potential WAA:** `MAX WAA P`, `WAP`, `WAP RP` (only for age ~16-23)
- **Hitting metric:** `wOBA wtd`
- **Traits:** `Prone` (durability), `WE` (work ethic), `INT` (intelligence)
- **Draft-only:** `Player List` sheet with `Manual='DRAFT'` flag, `Drafted` sheet with StatsPlus paste

If you don't have a 25 Regressions workbook of your own, the simplest path is to
copy my `The Sheets TGS/25 Regressions.xlsx` and adapt it to your league's data.

---

## How the pipeline works

```
  OOTP ——export——>  The Sheets LEAGUE/*.xlsx
                            |
                    python extract_data.py
                            |
                            v
             tgs-viz/public/data/LEAGUE/*.json
                            |
                      React webapp
                            |
                            v
                    http://localhost:3000
```

`extract_data.py` — reads xlsx, filters draft-eligible players, writes JSON
`tgs-viz/src/lib/futureValue.js` — FV calculation (S-curve, risk, aging)
`tgs-viz/src/lib/draftFV.js` — Draft FV calculation (age percentile + ceiling)
`tgs-viz/src/pages/` — each page in the webapp

FV and Draft FV parameters are tunable — see the Dev Analysis page in the app,
or edit the constants at the top of the two .js files.

---

## Troubleshooting

**"python is not recognized" when running Update Data.bat**
You didn't check "Add Python to PATH" during install. Reinstall Python and check the box, or add it to PATH manually.

**"npm is not recognized" when running Launch TGS.bat**
Node.js isn't installed, or you need to restart your Command Prompt after installing it.

**"No 'The Sheets *' folders found!"**
Your league folder isn't named correctly — it has to start with `The Sheets ` (with a space), and it needs to be in the repo root (next to the `tgs-viz` folder).

**Webapp opens but shows no data / says "Failed to load"**
You haven't run `Update Data.bat` yet, or it errored out. Check the `leagues.json` file in `tgs-viz/public/data/` — it should list your league.

**Port 3000 already in use**
Something else is running on that port. Edit `Launch TGS.bat` and change `--port 3000` to `--port 3001`.

**Browser opens to a blank page**
Check the Command Prompt window — if there's a red error, it'll usually tell you what's wrong. Most common cause: mismatched column names in your xlsx. Compare your column headers against the ones listed above.

---

## Folder layout

```
perfektprojections/
├── README.md                          <- you are here
├── TGS Valuation Systems Explained.txt <- how FV and Draft FV work
├── Launch TGS.bat                     <- starts the webapp
├── Update Data.bat                    <- regenerates data from xlsx
├── The Sheets TGS/                    <- example league (my data)
│   ├── 25 Regressions.xlsx
│   ├── 25 Metadata.xlsx
│   ├── The Sheet Hitters.xlsx
│   ├── The Sheet Pitchers.xlsx
│   └── ...
├── The Sheets BLM/                    <- another example league
│   └── ...
└── tgs-viz/
    ├── extract_data.py                <- xlsx -> JSON pipeline
    ├── package.json                   <- webapp dependencies
    ├── src/                           <- React source
    │   ├── lib/futureValue.js         <- FV logic
    │   ├── lib/draftFV.js             <- Draft FV logic
    │   └── pages/                     <- webapp pages
    └── public/data/                   <- generated JSON (gitignored after first run)
        ├── leagues.json
        ├── TGS/
        └── BLM/
```

---

## Credit

Built on top of OOTP 26's in-game rating system and the excellent "25 Regressions"
community workflow for converting raw ratings to WAA projections.
