/**
 * serviceTime.js — REMAINING TEAM CONTROL, from the player's own row.
 *
 * Before this module every surplus, career-total and fair-offer number in the
 * app assumed SIX years of control for everybody (futureValue's
 * DEFAULT_YEARS_OF_CONTROL). A 30-year-old with 5.1 service years has ONE
 * controlled season left and was priced as if he had six; a pre-arb regular was
 * priced as if his six years were the same six. controlWindow() replaces that
 * blanket assumption with the two things the shipped JSON actually knows:
 *
 *   SERVICE — MLBSvcDays (with MLBSvcYrs as the coarse fallback). Free agency
 *   at FA_SERVICE_YEARS service years, so the seasons still owed to the club
 *   are ceil(6 - service). ceil, not round: a player at 5.1 finishes the season
 *   in front of him and then leaves, which is one more controlled season.
 *   Every quantity here counts the season IN PROGRESS as controlled season 1,
 *   the same convention futureValue's window uses (year 0 = current age).
 *
 *   CONTRACT — a signed deal overrides service upward: an extension can carry a
 *   player past 6.000 and the club still controls him. Years remaining =
 *   SalarySchedule.length. That is MEASURED, not assumed: over every contracted
 *   row in both leagues (TGS n=1334, BLM n=1299) the schedule length equals
 *   ContractYrs - ContractYr + 1 exactly, zero mismatches — so the schedule is
 *   the remaining years, and ContractYrs/ContractYr are only the fallback for
 *   rows that carry the counters without a schedule.
 *
 * NOT AVAILABLE, so NOT modelled: option years, the 40-man clock, Rule 5
 * status, and the calendar season itself. The last one is why faYear and
 * arbStartYear are null unless a caller supplies `seasonYear` — no in-game year
 * ships in public/data/**, and inventing one to print "FA 2047" would be a made-
 * up number. yearsToFA / yearsToArb carry the same information honestly.
 *
 * The three service constants live here (marketValue.js re-exports them for its
 * existing importers) so that this module has no dependencies and cannot form a
 * cycle with the $ layer that consumes it.
 */

function toNum(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Days in one MLB service year. MEASURED, not assumed — see marketValue.js's
 * header (route A identity: mlb_service_years === floor(mlb_service_days / 172)
 * for every MLB-world player in both leagues, and for no other L in 120..210).
 * If a future world changes the setting this is the one place to re-measure.
 */
export const SVC_YEAR_DAYS = 172;
/** Service years to free agency / to arbitration (OOTP league rules). */
export const FA_SERVICE_YEARS = 6;
export const ARB_SERVICE_YEARS = 3;

/**
 * The service-year length actually in force. SVC_YEAR_DAYS is the MEASURED
 * value and is what ships; the override exists so the sensitivity of the fit
 * to that measurement stays re-runnable from the shipped code
 * (scripts/market_sensitivity.mjs), not so anyone can tune it.
 */
export function svcYearDays(opts) {
  const v = opts && toNum(opts.svcYearDays);
  return v && v > 0 ? v : SVC_YEAR_DAYS;
}

/** Remaining years on the signed deal, or null when the row carries no deal. */
function contractYearsRemaining(p) {
  const sched = Array.isArray(p.SalarySchedule)
    ? p.SalarySchedule.filter(Number.isFinite) : [];
  if (sched.length) return sched.length;
  const yrs = toNum(p.ContractYrs);
  const yr = toNum(p.ContractYr);
  if (yrs !== null && yr !== null && yrs >= yr) return yrs - yr + 1;
  return null;
}

/**
 * Remaining team control for one player row.
 *
 * @param {Object} player - player row (MLBSvcDays / MLBSvcYrs / SalarySchedule)
 * @param {Object} [opts] - { seasonYear } to resolve faYear/arbStartYear to
 *        calendar years; { svcYearDays } for the sensitivity harness only.
 * @returns {Object} {
 *   controlYears   seasons the club still controls, current season included
 *   faYear         calendar year of free agency, or null (no season year ships)
 *   arbStartYear   calendar year arbitration starts, or null
 *   serviceYears   MLB service in years (fractional when day data is present)
 *   isPreArb       service below ARB_SERVICE_YEARS
 *   source         'contract' | 'service' | 'default' — 'default' means the row
 *                  carried neither, so the old blanket 6 was used
 *   yearsToFA / yearsToArb   the same two clocks in seasons, always available
 *   contractYears  years left on the signed deal, or null
 *   serviceBasis   'days' | 'years' | null
 * }
 */
export function controlWindow(player, opts = {}) {
  const L = svcYearDays(opts);
  const seasonYear = opts && toNum(opts.seasonYear);

  const svcDays = player ? toNum(player.MLBSvcDays) : null;
  const svcYrs = player ? toNum(player.MLBSvcYrs) : null;
  const serviceYears = svcDays !== null ? svcDays / L : svcYrs;
  const serviceBasis = svcDays !== null ? 'days' : (svcYrs !== null ? 'years' : null);

  const contractYears = player ? contractYearsRemaining(player) : null;

  // Seasons still owed on each clock. The season in progress counts as one.
  const yearsToFA = serviceYears === null
    ? null : Math.ceil(Math.max(0, FA_SERVICE_YEARS - serviceYears));
  const yearsToArb = serviceYears === null
    ? null : Math.ceil(Math.max(0, ARB_SERVICE_YEARS - serviceYears));

  let controlYears, source;
  if (yearsToFA !== null) {
    // A signed deal can only EXTEND control past the service clock, never cut
    // it short: a club that trades for the last year of a deal still gets the
    // pre-FA seasons behind it.
    controlYears = Math.max(yearsToFA, contractYears ?? 0);
    source = (contractYears ?? 0) > yearsToFA ? 'contract' : 'service';
  } else if (contractYears !== null) {
    controlYears = contractYears;
    source = 'contract';
  } else {
    // No service and no contract on the row — keep the app's historical
    // assumption, but SAY so: 'default' is what makes the fallback visible.
    controlYears = FA_SERVICE_YEARS;
    source = 'default';
  }

  return {
    controlYears,
    faYear: seasonYear !== null ? seasonYear + controlYears : null,
    arbStartYear: (seasonYear !== null && yearsToArb !== null)
      ? seasonYear + yearsToArb : null,
    serviceYears,
    isPreArb: serviceYears !== null ? serviceYears < ARB_SERVICE_YEARS : null,
    source,
    yearsToFA,
    yearsToArb,
    contractYears,
    serviceBasis,
  };
}

/** One-line readout: "3 yrs (FA 2047)" / "1 yr (contract)" / "6 yrs (default)". */
export function formatControl(cw) {
  if (!cw) return '-';
  const unit = cw.controlYears === 1 ? 'yr' : 'yrs';
  const note = cw.faYear !== null ? `FA ${cw.faYear}`
    : cw.source === 'default' ? 'default — no service data'
    : cw.source;
  return `${cw.controlYears} ${unit} (${note})`;
}
