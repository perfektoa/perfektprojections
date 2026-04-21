# TGS Ranking Systems — How They Work

There are 4 ranking systems. Each one takes the same player data and turns it into a 20-80 grade, but they each care about different things.

---

## 1. FV (Future Value)

**What it does:** Predicts how much total WAA a player will produce over the rest of his career.

**How it works, step by step:**

1. Look at the player's current WAA (how good he is right now)
2. Look at his potential WAA (how good the game says he could become)
3. The difference between those two is the "gap" — how much room he has to grow
4. Use an S-curve based on age to figure out how much of that gap he'll actually close. A 16-year-old has barely started developing. A 22-year-old is almost done. By 25, development is finished.
5. Apply a risk discount (80-95%) because not every prospect reaches their potential
6. Now you have an expected peak WAA. Project that forward year by year, applying an aging decline (players get worse after 25, and fall off a cliff around 30)
7. Add up all those future years of WAA. That total is the raw FV number.
8. Convert that total to a 20-80 grade

**What this means in practice:**
- A young player with high potential gets a decent score because he has many productive years ahead
- An older player needs to be good RIGHT NOW because he doesn't have many years left
- Two players with the same peak ability get different FV scores if one is younger (more years of production)

**Example:** A 19-year-old with -7 current WAA and +3 potential WAA has a big gap (10 WAA). FV projects him developing along the S-curve, reaching close to +3 by age 25, then declining. It adds up all those future years to get a total.

---

## 2. G5 (Peak FV)

**What it does:** Predicts how good a player will be at his absolute best — his peak season. Does not care about how many years he plays.

**How it works, step by step:**

1. Look at current WAA and potential WAA, same as FV
2. Calculate the gap (potential minus current)
3. "Gap factor" — based on age, how much credit does he get for that gap? Ages 16-22 get almost full credit. By age 27, gap credit drops to zero (you are what you are).
4. "Risk factor" — a small multiplier (0.82 to 0.90) that slightly discounts the gap. Almost everyone gets roughly the same risk factor — it barely differentiates. This is on purpose: the system doesn't want to punish young players for being underdeveloped.
5. Multiply: `current WAA + (gap x gap factor x risk factor)` = expected peak WAA
6. Convert that single WAA number to a 20-80 grade

**What this means in practice:**
- Only cares about how good you'll be at your best, not how long you'll be good
- A 19-year-old with +5 potential and a 26-year-old with +5 current get similar grades
- Players 27+ just get their current WAA as their grade (no more development expected)
- Ignores injuries, work ethic, career length — pure ability ceiling

**Example:** That same 19-year-old with -7 current and +3 potential: gap = 10. At age 19, gap factor is ~0.90 (almost full credit). Risk factor is ~0.83. So expected peak = -7 + (10 x 0.90 x 0.83) = -7 + 7.47 = +0.47 WAA. That converts to about a 40-45 grade.

---

## 3. Draft FV

**What it does:** Grades a player for draft purposes by asking two questions: how good is he compared to other players his age, and how high is his ceiling?

**How it works, step by step:**

1. **Age percentile (25% of the grade):** Take the player's current performance (wOBA for hitters, WAA for pitchers) and rank it against ALL players in the league who are the same age. If he's better than 80% of other 18-year-olds, his age percentile is 80.
2. **Ceiling score (75% of the grade):** Take his potential WAA (MAX WAA P for hitters, WAP for pitchers) and scale it from 0-100. A potential WAA of -3 or worse = 0. A potential of +3 (hitters) or +1.5 (pitchers) or better = 100.
3. Combine: `(age percentile x 0.25) + (ceiling score x 0.75)` = raw score
4. **Durability modifier:** Multiply by a penalty based on injury proneness:
   - Wrecked = 0 (completely undraftable, grade forced to 20)
   - Fragile = 0.75 (25% penalty)
   - Normal = 0.95 (small 5% penalty)
   - Durable or Iron Man = 1.0 (no penalty)
5. **Work ethic modifier:** If WE is "H" (high), multiply by 1.05 (5% bonus). Otherwise no change.
6. Convert the final raw score (0-100) to a 20-80 grade

**What this means in practice:**
- Heavily ceiling-focused (75%) because in a draft you're betting on upside
- The age percentile part rewards players who are already performing well for their age
- Wrecked players are automatically undraftable regardless of talent
- High work ethic gives a small bump
- High INT is flagged but doesn't change the number

**Example:** An 18-year-old hitter with wOBA of .280 ranks at the 60th percentile among 18-year-olds. His MAX WAA P is +2.0, which scales to about 83 on the ceiling score. Raw = (60 x 0.25) + (83 x 0.75) = 15 + 62.25 = 77.25. He's Normal durability (x 0.95) and High WE (x 1.05) = 77.25 x 0.95 x 1.05 = 77.1. That converts to about a 55 grade.

---

## 4. Hybrid FV

**What it does:** Takes the grades from FV, G5, and Draft FV and averages them together with weights that change based on age.

**How it works, step by step:**

1. Take the player's FV grade, G5 grade, and Draft FV grade (all on 20-80 scale)
2. Convert each to 0-100 (so a grade of 20 = 0, grade of 50 = 50, grade of 80 = 100)
3. Pick weights based on age:
   - **Age 20 or younger:** FV gets 25%, G5 gets 30%, Draft FV gets 45%
   - **Age 21-24:** Weights gradually shift from the young mix to the old mix
   - **Age 25 or older:** FV gets 55%, G5 gets 30%, Draft FV gets 15%
4. Weighted average: `(FV weight x FV score) + (G5 weight x G5 score) + (Draft weight x Draft score)`
5. Convert that back to a 20-80 grade

**What this means in practice:**
- For young players, Draft FV matters most (because comparing to age peers and ceiling are the best info you have)
- For older players, FV matters most (because career projection is reliable when you know what a player is)
- G5 always stays at 30% regardless of age
- It's just a blend — no new analysis, just combining the other three

---

## The Actual Differences, Simply

| | FV | G5 | Draft FV | Hybrid |
|---|---|---|---|---|
| **Cares about career length?** | Yes — more years = higher score | No | No | Partially (through FV) |
| **Cares about peak ability?** | Somewhat | Yes — this is the whole point | Yes (75% ceiling) | Partially (through G5) |
| **Cares about age?** | Yes — younger = more years | Yes — younger = more gap credit | Yes — compares to same-age players | Yes — changes the weights |
| **Cares about injuries?** | No | No | Yes — Wrecked/Fragile penalty | Partially (through Draft FV) |
| **Cares about work ethic?** | No | No | Yes — High WE = +5% | Partially (through Draft FV) |
| **What makes it go up?** | High potential + young age + many years left | High potential + young age | High ceiling + good for your age + healthy | All three being high |
| **What makes it go down?** | Old age, low potential, short career | Already at peak with low WAA | Low ceiling, bad for age, injured | All three being low |

---

## Glossary

- **WAA** = Wins Above Average. How many wins a player adds compared to an average player. 0 = average. Positive = good. Negative = bad.
- **Current WAA** = How good the player is right now (from the "wtd" columns in the sheets)
- **Potential WAA** = How good the game says the player could become (from the "P" columns)
- **Gap** = Potential WAA minus Current WAA. A 19-year-old with -7 current and +3 potential has a gap of 10.
- **20-80 scale** = Scouting grade scale. 40 = average. 50 = above average. 60 = very good. 70 = elite. 80 = best in the game.
- **Age percentile** = How a player ranks against others his same age. 90th percentile means he's better than 90% of players his age.
- **Ceiling** = The best a player could possibly become (his potential WAA)
- **S-curve** = The shape of player development. Slow early, fast in the middle, levels off near maturity (age 25).
- **G5** = Just the name of the peak projection model. Not an abbreviation for anything specific.
