"""Fit a demand model to OOTP league data so the pricing app uses real elasticity."""
import numpy as np

# MLB teams only (Japanese NPB teams excluded per user instruction)
# Columns: team, market_size, fan_loyalty, ticket_price, attendance
rows = [
    ("NYY", "Astronomical", "Good",      39.5399, 2907909),
    ("PHI", "Huge",         "Good",      41.0000, 2027488),
    ("BAL", "Very Big",     "Very Good", 35.3421, 2252938),
    ("CIN", "Very Big",     "Above Avg", 27.5000, 1957341),
    ("MIN", "Very Big",     "Above Avg", 29.4974, 3167948),
    ("TOR", "Very Big",     "Above Avg", 37.2581, 1938487),
    ("CHC", "Very Big",     "Great",     37.0756, 2967339),
    ("SEA", "Very Big",     "Good",      30.1252, 1926322),
    ("KCM", "Very Big",     "Very Good", 36.8216, 2461326),
    ("BOS", "Big",          "Good",      32.4703, 2120877),
    ("CWS", "Big",          "Good",      36.3618, 2128257),
    ("KCR", "Big",          "Good",      32.4999, 2173614),
    ("OAK", "Big",          "Very Good", 45.2352, 3549068),
    ("TEX", "Big",          "Very Good", 37.4877, 3482515),
    ("DET", "Big",          "Above Avg", 38.6273, 1749088),
    ("TB",  "Big",          "Good",      33.5055, 1788507),
    ("CLE", "Big",          "Very Good", 36.0000, 2863402),
    ("ARI", "Big",          "Good",      34.2563, 3059151),
    ("NYM", "Big",          "Good",      34.8931, 3577526),
    ("ANA", "Big",          "Good",      39.2508, 3070983),
    ("FLA", "Big",          "Average",   30.0000, 2359336),
    ("COL", "Big",          "Good",      43.1413, 1806811),
    ("MIL", "Big",          "Good",      35.0000, 2214024),
    ("STL", "Big",          "Good",      39.6798, 3102804),
    ("PIT", "Big",          "Good",      43.5764, 2473821),
    ("SD",  "Big",          "Good",      35.0636, 1755932),
    ("SF",  "Big",          "Average",   29.3605, 1825921),
    ("WAS", "Big",          "Very Good", 41.0349, 2986509),
    ("LAD", "Big",          "Great",     35.7500, 2763052),
    ("HOU", "Big",          "Extreme",   55.0000, 2828021),
    ("MON", "Big",          "Good",      42.5000, 2977325),
    ("ATL", "Above Avg",    "Good",      30.2171, 1805987),
]

market_score = {"Above Avg": 5, "Big": 6, "Very Big": 7, "Huge": 8, "Astronomical": 10}
loyalty_score = {"Average": 3, "Above Avg": 5, "Good": 6, "Very Good": 7, "Great": 8, "Extreme": 10}

teams  = [r[0] for r in rows]
market = np.array([market_score[r[1]] for r in rows], dtype=float)
loyal  = np.array([loyalty_score[r[2]] for r in rows], dtype=float)
price  = np.array([r[3] for r in rows], dtype=float)
att    = np.array([r[4] for r in rows], dtype=float)

# Log-log demand: ln(att) = b0 + b_m*market + b_l*loyalty + b_p*ln(price)
# b_p is the price elasticity of demand (constant-elasticity form)
y = np.log(att)
X = np.column_stack([np.ones_like(price), market, loyal, np.log(price)])

# Drop likely capacity-constrained teams for the price-elasticity fit so their
# censored attendance doesn't flatten the curve. Assume ~81 games * 44k = 3.56M cap.
cap_mask = att < 3_400_000
Xc = X[cap_mask]
yc = y[cap_mask]
print(f"Fitting on {cap_mask.sum()} of {len(rows)} teams (dropped capacity-hit outliers)")
print("Dropped:", [teams[i] for i in range(len(rows)) if not cap_mask[i]])

beta, *_ = np.linalg.lstsq(Xc, yc, rcond=None)
b0, b_m, b_l, b_p = beta
print(f"\nCoefficients:")
print(f"  intercept     = {b0:.4f}")
print(f"  market score  = {b_m:.4f}   (+1 market tier -> +{(np.exp(b_m)-1)*100:.1f}% att)")
print(f"  loyalty score = {b_l:.4f}   (+1 loyalty tier -> +{(np.exp(b_l)-1)*100:.1f}% att)")
print(f"  ln(price)     = {b_p:.4f}   (price elasticity)")

# R^2 on the filtered sample
yhat = Xc @ beta
ss_res = ((yc - yhat) ** 2).sum()
ss_tot = ((yc - yc.mean()) ** 2).sum()
print(f"  R^2           = {1 - ss_res/ss_tot:.3f}")

# Optimal price under constant elasticity (no capacity cap):
# revenue = p * att, att = A * p^b_p  =>  rev = A * p^(1+b_p)
# If b_p < -1, revenue rises as price falls (no interior max w/o capacity).
# If -1 < b_p < 0, revenue rises as price rises (corner solution, raise until demand collapses).
# In practice OOTP has a realistic upper price wall — so we combine the log-log fit with
# a capacity ceiling and show the tradeoff in the app.
print(f"\nElasticity interpretation: every 10% price increase -> {b_p*10:.1f}% attendance change")

# Quick sanity: predict each team's attendance at their actual price
att_pred = np.exp(X @ beta)
capacity_hint = 81 * 44000  # placeholder 44k avg cap
att_pred_capped = np.minimum(att_pred, capacity_hint)
print("\nTeam           actual      predicted   diff%")
for i, t in enumerate(teams):
    diff = (att_pred[i] - att[i]) / att[i] * 100
    print(f"  {t:5s}  {att[i]:>10,.0f}  {att_pred[i]:>10,.0f}  {diff:+6.1f}%")
