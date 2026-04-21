"""
Regression analysis for OOTP ticket pricing — like a player-projection model but for teams.

Fits two regressions:
  1. Price ~ team attributes  (what do teams like mine charge?)
  2. Revenue ~ price + price^2 + attributes  (what price maximizes predicted revenue?)

Then applies both to CHC to generate a recommendation.
"""
import numpy as np

# 32 MLB teams, this season (partial)
# (team, market_tier, loyalty_tier, price, avg_att_per_game, fan_interest)
rows = [
    ("OAK", 6,  8, 49.69, 32554, 100),
    ("NYM", 6,  6, 33.00, 40975, 100),
    ("STL", 6,  6, 42.00, 33057,  99),
    ("TEX", 6,  7, 38.25, 40936,  93),
    ("NYY", 10, 6, 39.54, 35952,  91),
    ("MIN", 7,  5, 32.50, 42770,  88),
    ("WAS", 6,  7, 41.75, 40788,  88),
    ("CHC", 7,  8, 37.00, 36789,  87),
    ("HOU", 6, 10, 55.00, 28508,  87),
    ("MON", 6,  7, 42.50, 28302,  87),
    ("PIT", 6,  6, 41.42, 29650,  85),
    ("ARI", 6,  6, 37.11, 38195,  84),
    ("CLE", 6,  7, 36.00, 34033,  81),
    ("ANA", 6,  5, 41.00, 34238,  80),
    ("PHI", 8,  6, 41.00, 26876,  80),
    ("KCM", 7,  7, 41.00, 34076,  79),
    ("LAD", 6,  8, 34.20, 38306,  79),
    ("BAL", 7,  7, 35.55, 31760,  75),
    ("COL", 6,  6, 40.00, 25654,  73),
    ("DET", 6,  5, 37.00, 27101,  72),
    ("BOS", 6,  6, 37.00, 25318,  69),
    ("TOR", 7,  5, 38.50, 24894,  68),
    ("SF",  6,  2, 29.36, 31321,  68),
    ("MIL", 6,  6, 35.00, 28753,  68),
    ("CWS", 6,  6, 36.36, 28524,  66),
    ("ATL", 5,  5, 35.00, 27046,  61),
    ("SEA", 7,  6, 30.13, 25119,  61),
    ("CIN", 7,  5, 27.50, 27564,  59),
    ("SD",  6,  5, 35.06, 24216,  58),
    ("KCR", 6,  6, 32.50, 27089,  56),
    ("TB",  6,  5, 30.00, 21840,  52),
    ("FLA", 6,  3, 30.00, 22218,  52),
]

games = 81
teams = [r[0] for r in rows]
market = np.array([r[1] for r in rows], dtype=float)
loyal  = np.array([r[2] for r in rows], dtype=float)
price  = np.array([r[3] for r in rows], dtype=float)
att    = np.array([r[4] for r in rows], dtype=float)
fi     = np.array([r[5] for r in rows], dtype=float)
revenue = price * att * games  # annualized

# ======================================================================
# Regression 1: What PRICE do teams with these attributes charge?
#   price = b0 + b1*FI + b2*market + b3*loyalty
# ======================================================================
X1 = np.column_stack([np.ones(len(rows)), fi, market, loyal])
y1 = price
coef1, *_ = np.linalg.lstsq(X1, y1, rcond=None)
pred_price = X1 @ coef1
resid1 = y1 - pred_price
r2_1 = 1 - (resid1 @ resid1) / ((y1 - y1.mean()) @ (y1 - y1.mean()))

print("=" * 72)
print("REGRESSION 1: PRICE ~ Fan Interest + Market + Loyalty")
print("=" * 72)
print(f"  Intercept       = {coef1[0]:7.3f}")
print(f"  Fan Interest    = {coef1[1]:7.4f}  (+10 FI   -> +${coef1[1]*10:.2f} price)")
print(f"  Market tier     = {coef1[2]:7.3f}  (+1 tier  -> +${coef1[2]:.2f} price)")
print(f"  Loyalty tier    = {coef1[3]:7.3f}  (+1 tier  -> +${coef1[3]:.2f} price)")
print(f"  R^2             = {r2_1:.3f}")
print()
print("  Predicted 'normal' price for each team vs actual:")
print(f"  {'Team':5s} {'FI':>3} {'M':>2} {'L':>2} {'Actual':>8} {'Predicted':>10} {'Diff':>8}")
for i, t in enumerate(teams):
    diff = price[i] - pred_price[i]
    tag = "  "
    if t == "CHC": tag = "<<"
    print(f"  {t:5s} {fi[i]:3.0f} {market[i]:2.0f} {loyal[i]:2.0f} ${price[i]:7.2f} ${pred_price[i]:9.2f} ${diff:+7.2f} {tag}")

# ======================================================================
# Regression 2: What price MAXIMIZES revenue?
#   revenue = b0 + b1*price + b2*price^2 + b3*FI + b4*market + b5*loyalty
#   d(revenue)/d(price) = b1 + 2*b2*price = 0
#   optimal_price = -b1 / (2*b2)   if b2 < 0
# ======================================================================
X2 = np.column_stack([np.ones(len(rows)), price, price**2, fi, market, loyal])
y2 = revenue
coef2, *_ = np.linalg.lstsq(X2, y2, rcond=None)
pred_rev = X2 @ coef2
resid2 = y2 - pred_rev
r2_2 = 1 - (resid2 @ resid2) / ((y2 - y2.mean()) @ (y2 - y2.mean()))

print()
print("=" * 72)
print("REGRESSION 2: REVENUE ~ price + price^2 + FI + market + loyalty")
print("=" * 72)
print(f"  Intercept       = {coef2[0]:>14,.0f}")
print(f"  Price           = {coef2[1]:>14,.0f}")
print(f"  Price^2         = {coef2[2]:>14,.0f}")
print(f"  Fan Interest    = {coef2[3]:>14,.0f}  (+10 FI   -> +${coef2[3]*10/1e6:.1f}M rev)")
print(f"  Market tier     = {coef2[4]:>14,.0f}  (+1 tier  -> +${coef2[4]/1e6:.1f}M rev)")
print(f"  Loyalty tier    = {coef2[5]:>14,.0f}  (+1 tier  -> +${coef2[5]/1e6:.1f}M rev)")
print(f"  R^2             = {r2_2:.3f}")

# Optimal price (holds for any team — controls shift the intercept, not the slope)
if coef2[2] < 0:
    opt_global = -coef2[1] / (2 * coef2[2])
    print(f"\n  Revenue-maximizing price (any team): ${opt_global:.2f}")
else:
    opt_global = None
    print(f"\n  Price^2 coefficient is positive — revenue still increasing at observed prices.")
    print(f"  No interior max in observed range.")

# ======================================================================
# CHC-specific output
# ======================================================================
CHC_FI, CHC_M, CHC_L = 87, 7, 8
CHC_PRICE = 37.0
CHC_ATT = 36789

print()
print("=" * 72)
print("CHC RECOMMENDATION")
print("=" * 72)

chc_normal_price = coef1[0] + coef1[1]*CHC_FI + coef1[2]*CHC_M + coef1[3]*CHC_L
print(f"\n  Reg 1: Normal price for your attributes = ${chc_normal_price:.2f}")
print(f"         Your actual price                 = ${CHC_PRICE:.2f}")
under = chc_normal_price - CHC_PRICE
print(f"         You're {'under' if under > 0 else 'over'}priced by ${abs(under):.2f}")

if opt_global is not None:
    chc_rev_at_current = coef2[0] + coef2[1]*CHC_PRICE + coef2[2]*CHC_PRICE**2 + coef2[3]*CHC_FI + coef2[4]*CHC_M + coef2[5]*CHC_L
    chc_rev_at_opt = coef2[0] + coef2[1]*opt_global + coef2[2]*opt_global**2 + coef2[3]*CHC_FI + coef2[4]*CHC_M + coef2[5]*CHC_L
    print(f"\n  Reg 2: Revenue-max price               = ${opt_global:.2f}")
    print(f"         Predicted rev at current $37       = ${chc_rev_at_current/1e6:.1f}M")
    print(f"         Predicted rev at optimum           = ${chc_rev_at_opt/1e6:.1f}M")
    print(f"         Upside                              = ${(chc_rev_at_opt-chc_rev_at_current)/1e6:.1f}M")

# Sweep prices and show revenue curve for CHC
print("\n  Predicted revenue at various prices (for CHC):")
print(f"  {'Price':>7}  {'Revenue':>10}  {'vs current':>12}")
cur_rev = CHC_PRICE * CHC_ATT * games
for p in [30, 33, 35, 37, 39, 41, 43, 45, 47, 50, 55]:
    predicted = coef2[0] + coef2[1]*p + coef2[2]*p**2 + coef2[3]*CHC_FI + coef2[4]*CHC_M + coef2[5]*CHC_L
    diff = (predicted - cur_rev) / cur_rev * 100
    marker = "  <<<" if abs(p - CHC_PRICE) < 0.5 else ""
    best_marker = "  *** BEST ***" if opt_global and abs(p - opt_global) < 1.5 else ""
    print(f"  ${p:>5.0f}  ${predicted/1e6:8.1f}M  {diff:+10.1f}%{marker}{best_marker}")
