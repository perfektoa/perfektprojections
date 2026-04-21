/**
 * Column definitions for the data tables.
 * Based on actual extracted column names from the TGS sheets.
 */
import { formatMoney } from './marketValue';

// WAA columns for hitters (used by roster optimizer)
export const HITTER_WAA_COLUMNS = [
  'C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd',
  'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd',
  'DH WAA wtd', 'Max WAA wtd',
  'C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR',
  'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR',
  'DH WAA vR', 'Max WAA vR',
  'C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL',
  'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL',
  'DH WAA vL', 'Max WAA vL',
  'C WAA P', '1B WAA P', '2B WAA P', '3B WAA P',
  'SS WAA P', 'LF WAA P', 'CF WAA P', 'RF WAA P',
  'DH WAA P', 'MAX WAA P',
];

// WAA columns for pitchers
export const PITCHER_WAA_COLUMNS = [
  'WAA vR', 'WAA vL', 'WAA wtd', 'WAR wtd',
  'WAA vR RP', 'WAA vL RP', 'WAA wtd RP',
  'WAP', 'WAP RP',
];

export const HITTER_COLUMN_GROUPS = {
  info: {
    label: 'Player Info',
    columns: ['Name', 'POS', 'ORG', 'Lev', 'Age', 'B', 'T'],
  },
  value: {
    label: 'Value',
    columns: ['Rank', 'Max WAA wtd', 'Max WAA vR', 'Max WAA vL', 'MAX WAA P', '_fvScale', '_futureValue'],
  },
  ratingsVR: {
    label: 'Ratings vs R',
    columns: ['BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR'],
  },
  ratingsVL: {
    label: 'Ratings vs L',
    columns: ['BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL'],
  },
  potential: {
    label: 'Potential',
    columns: ['HT P', 'GAP P', 'POW P', 'EYE P', 'K P'],
  },
  offense: {
    label: 'Offense',
    columns: ['wOBA vR', 'wOBA vL', 'wOBA wtd', 'OBP vR', 'OBP vL', 'OBP wtd', 'BatR wtd'],
  },
  baserunning: {
    label: 'Baserunning',
    columns: ['SPE', 'STE', 'RUN', 'SB%', 'BSR wtd', 'wSB wtd', 'UBR wtd'],
  },
  defense: {
    label: 'Position Eligibility',
    columns: ['C Eligible', '1B Eligible', '2B Eligible', '3B Eligible', 'SS Eligible', 'LF Eligible', 'CF Eligible', 'RF Eligible'],
  },
  fieldingSkills: {
    label: 'Fielding Skills',
    columns: ['C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM'],
  },
  posWAA: {
    label: 'Position WAA',
    columns: ['C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd', 'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd', 'DH WAA wtd'],
  },
  posWAA_vR: {
    label: 'WAA vs RHP',
    columns: ['C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR', 'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR', 'DH WAA vR'],
  },
  posWAA_vL: {
    label: 'WAA vs LHP',
    columns: ['C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL', 'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL', 'DH WAA vL'],
  },
  posWAA_P: {
    label: 'WAA Potential',
    columns: ['C WAA P', '1B WAA P', '2B WAA P', '3B WAA P', 'SS WAA P', 'LF WAA P', 'CF WAA P', 'RF WAA P', 'DH WAA P'],
  },
  defRuns: {
    label: 'Defensive Runs',
    columns: ['C RunsP', '1B RunsP', '2B RunsP', '3B RunsP', 'SS RunsP', 'LF RunsP', 'CF RunsP', 'RF RunsP'],
  },
  contract: {
    label: 'Contract',
    columns: ['Price', 'MLY', 'Eligible', 'ON40', 'WAIV', 'R5'],
  },
  futureValue: {
    label: 'Future Value',
    columns: ['_fvScale', '_futureValue', '_currentWAA', '_potentialWAA', '_peakWAA', '_pctToPeak', '_yearsTilPeak'],
  },
  personality: {
    label: 'Personality',
    columns: ['LEA', 'LOY', 'AD', 'WE', 'INT'],
  },
  draftValue: {
    label: 'Draft FV',
    columns: ['_draftFV', '_draftRawFV', '_agePercentile', '_draftCeiling', '_durability', '_highINT'],
  },
  g5Value: {
    label: 'G5 Peak FV',
    columns: ['_g5FV', '_g5Raw', '_g5DevPct', '_g5GapFactor', '_g5RiskFactor'],
  },
  hybridValue: {
    label: 'Hybrid FV',
    columns: ['_hybridFV', '_hybridRaw', '_hybridWFV', '_hybridWG5', '_hybridWDraft'],
  },
  marketCurrent: {
    label: '$ Current',
    columns: ['Price', '_perWAA', '_annualValue', '_offerFloor', '_offerMid', '_offerCeiling', '_surplus'],
  },
  marketFuture: {
    label: '$ Future',
    columns: ['_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh', '_marketValue'],
  },
};

export const PITCHER_COLUMN_GROUPS = {
  info: {
    label: 'Player Info',
    columns: ['Name', 'POS', 'ORG', 'Lev', 'Age', 'T'],
  },
  value: {
    label: 'Value (SP)',
    columns: ['Rank', 'WAA wtd', 'WAA vR', 'WAA vL', 'WAR wtd', '_fvScale', '_futureValue'],
  },
  valueRP: {
    label: 'Value (RP)',
    columns: ['Rank RP', 'WAA wtd RP', 'WAA vR RP', 'WAA vL RP'],
  },
  ratingsVR: {
    label: 'Ratings vs R',
    columns: ['STU vR', 'HRR vR', 'PBABIP vR', 'CON vR'],
  },
  ratingsVL: {
    label: 'Ratings vs L',
    columns: ['STU vL', 'HRR vL', 'PBABIP vL', 'CON vL'],
  },
  ratingsPot: {
    label: 'Potential',
    columns: ['STU P', 'HRR P', 'PBABIP P', 'CON P'],
  },
  performance: {
    label: 'SP Performance',
    columns: ['wOBA vR', 'wOBA vL', 'wOBA wtd', 'RA/9 vR', 'RA/9 vL', 'RA/9 wtd'],
  },
  performanceRP: {
    label: 'RP Performance',
    columns: ['wOBA vR RP', 'wOBA vL RP', 'wOBA wtd RP', 'RA/9 vR RP', 'RA/9 vL RP', 'RA/9 wtd RP'],
  },
  arsenal: {
    label: 'Pitch Arsenal',
    columns: ['Pitches', 'SP Pitch', 'SP P Pitch', 'STM', 'HLD'],
  },
  potential_value: {
    label: 'WAA Potential',
    columns: ['WAP', 'WAP RP'],
  },
  contract: {
    label: 'Contract',
    columns: ['Price', 'Type', 'Eligible', 'ON40', 'WAIV', 'R5'],
  },
  futureValue: {
    label: 'Future Value',
    columns: ['_fvScale', '_futureValue', '_currentWAA', '_potentialWAA', '_peakWAA', '_pctToPeak', '_yearsTilPeak'],
  },
  draftValue: {
    label: 'Draft FV',
    columns: ['_draftFV', '_draftRawFV', '_agePercentile', '_draftCeiling', '_durability', '_highINT'],
  },
  g5Value: {
    label: 'G5 Peak FV',
    columns: ['_g5FV', '_g5Raw', '_g5DevPct', '_g5GapFactor', '_g5RiskFactor'],
  },
  hybridValue: {
    label: 'Hybrid FV',
    columns: ['_hybridFV', '_hybridRaw', '_hybridWFV', '_hybridWG5', '_hybridWDraft'],
  },
  marketCurrent: {
    label: '$ Current',
    columns: ['Price', '_perWAA', '_marketRole', '_annualValue', '_offerFloor', '_offerMid', '_offerCeiling', '_surplus'],
  },
  marketFuture: {
    label: '$ Future',
    columns: ['_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh', '_marketValue'],
  },
};

// Column formatting helpers
export function formatCellValue(value, columnName) {
  if (value === null || value === undefined || value === '') return '-';

  const num = parseFloat(value);

  const intCols = ['Age', 'Rank', 'Rank vR', 'Rank vL', 'Rank P', 'Rank RP',
    '_fvScale', '_draftFV', '_g5FV', '_hybridFV', '_pctToPeak', '_yearsTilPeak',
    '_hybridWFV', '_hybridWG5', '_hybridWDraft',
    'SPE', 'STE', 'RUN', 'STM', 'HLD',
    'BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL',
    'BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR',
    'HT P', 'GAP P', 'POW P', 'EYE P', 'K P',
    'STU P', 'HRR P', 'PBABIP P', 'CON P',
    'STU vR', 'HRR vR', 'PBABIP vR', 'CON vR',
    'STU vL', 'HRR vL', 'PBABIP vL', 'CON vL',
    'C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM',
  ];

  if (intCols.includes(columnName) && !isNaN(num)) {
    return Math.round(num);
  }

  // WAA/WAR/Runs columns - 1 decimal
  const isWaaCols = columnName.includes('WAA') || columnName.includes('WAR') || columnName.includes('WAP') ||
    columnName.includes('BatR') || columnName.includes('BSR') || columnName.includes('UBR') ||
    columnName.includes('wSB') || columnName.includes('RunsP') || columnName.includes('PMAA') ||
    columnName.includes('EAA') || columnName.includes('DPAA') || columnName.includes('ARMAA') ||
    columnName.includes('FRMAA') || columnName.includes('ArmR') ||
    columnName === '_futureValue' || columnName === '_peakWAA' ||
    columnName === '_currentWAA' || columnName === '_potentialWAA' ||
    columnName === '_draftRawFV' || columnName === '_draftCeiling' || columnName === '_ceilingScore' ||
    columnName === '_g5Raw' || columnName === '_hybridRaw';

  if (isWaaCols && !isNaN(num)) {
    return num.toFixed(1);
  }

  // wOBA / OBP - 3 decimals
  if ((columnName.includes('wOBA') || columnName.includes('OBP')) && !isNaN(num)) {
    return num.toFixed(3);
  }

  // RA/9 - 2 decimals
  if (columnName.includes('RA/9') && !isNaN(num)) {
    return num.toFixed(2);
  }

  if (columnName === 'SB%' && !isNaN(num)) {
    return (num * 100).toFixed(0) + '%';
  }

  if (columnName === '_pctToPeak' && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if (columnName === '_agePercentile' && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if (columnName === '_g5DevPct' && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if ((columnName === '_g5GapFactor' || columnName === '_g5RiskFactor') && !isNaN(num)) {
    return num.toFixed(3);
  }

  if ((columnName === '_hybridWFV' || columnName === '_hybridWG5' || columnName === '_hybridWDraft') && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if (columnName === '_highINT') {
    return value === true ? 'Y' : '-';
  }

  if (columnName === '_wrecked') {
    return value === true ? 'WRECKED' : '-';
  }

  if (columnName === '_weBoost') {
    return value === true ? '+5%' : '-';
  }

  // Money columns — format as $12.5M / $750K
  const moneyCols = ['Price', '_perWAA', '_marketValue', '_offerFloor', '_offerMid', '_offerCeiling', '_annualValue', '_surplus',
    '_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh'];
  if (moneyCols.includes(columnName) && !isNaN(num)) {
    return formatMoney(num);
  }

  // Role column
  if (columnName === '_marketRole') {
    return value || '-';
  }

  return value;
}

export function getCellColorClass(value, columnName) {
  // String-based color coding (non-numeric)
  if (columnName === '_durability') {
    const durMap = {
      'Wrecked': 'text-red-400 font-bold',
      'Fragile': 'text-orange-400',
      'Normal': 'text-gray-300',
      'Durable': 'text-green-400',
      'Iron Man': 'text-cyan-400 font-semibold',
    };
    return durMap[value] || '';
  }
  if (columnName === '_highINT') {
    return value === true ? 'text-green-400 font-semibold' : 'text-slate-600';
  }
  if (columnName === '_wrecked') {
    return value === true ? 'text-red-400 font-bold' : '';
  }

  const num = parseFloat(value);
  if (isNaN(num)) return '';

  const ratingLikeCols = [
    'BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL',
    'BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR',
    'HT P', 'GAP P', 'POW P', 'EYE P', 'K P',
    'STU P', 'HRR P', 'PBABIP P', 'CON P',
    'STU vR', 'HRR vR', 'PBABIP vR', 'CON vR',
    'STU vL', 'HRR vL', 'PBABIP vL', 'CON vL',
    '_fvScale', '_draftFV', '_g5FV', '_hybridFV',
    'C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM',
    'SPE', 'STE', 'STM', 'HLD',
  ];

  if (ratingLikeCols.includes(columnName)) {
    if (num >= 75) return 'text-purple-400 font-bold';
    if (num >= 65) return 'text-cyan-400 font-semibold';
    if (num >= 55) return 'text-green-400';
    if (num >= 45) return 'text-yellow-300';
    if (num >= 35) return 'text-orange-400';
    return 'text-red-400';
  }

  const isValueCol = columnName.includes('WAA') || columnName.includes('WAR') ||
    columnName.includes('WAP') || columnName === '_futureValue' || columnName === '_peakWAA' ||
    columnName === '_currentWAA' || columnName === '_potentialWAA' ||
    columnName === '_draftCeiling' || columnName === '_g5Raw';

  if (isValueCol) {
    if (num >= 5) return 'text-purple-400 font-bold';
    if (num >= 3) return 'text-cyan-400 font-semibold';
    if (num >= 1.5) return 'text-green-400';
    if (num >= 0) return 'text-gray-300';
    if (num >= -1) return 'text-orange-400';
    return 'text-red-400';
  }

  if (columnName.includes('RA/9')) {
    if (num <= 3.0) return 'text-purple-400 font-bold';
    if (num <= 3.5) return 'text-cyan-400 font-semibold';
    if (num <= 4.0) return 'text-green-400';
    if (num <= 4.5) return 'text-gray-300';
    if (num <= 5.5) return 'text-orange-400';
    return 'text-red-400';
  }

  if (columnName.includes('wOBA')) {
    if (num >= 0.400) return 'text-purple-400 font-bold';
    if (num >= 0.360) return 'text-cyan-400 font-semibold';
    if (num >= 0.320) return 'text-green-400';
    if (num >= 0.300) return 'text-gray-300';
    if (num >= 0.280) return 'text-orange-400';
    return 'text-red-400';
  }

  // Surplus: green = underpaid/good deal, red = overpaid
  if (columnName === '_surplus') {
    if (num > 10_000_000) return 'text-green-400 font-bold';
    if (num > 0) return 'text-green-400';
    if (num > -5_000_000) return 'text-orange-400';
    return 'text-red-400';
  }

  // Money columns — just use green for positive values
  const moneyColorCols = ['_marketValue', '_offerFloor', '_offerMid', '_offerCeiling', '_annualValue', '_perWAA',
    '_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh'];
  if (moneyColorCols.includes(columnName)) {
    if (num > 0) return 'text-green-400';
    return 'text-slate-500';
  }

  // Role column
  if (columnName === '_marketRole') {
    return value === 'SP' ? 'text-blue-400' : value === 'RP' ? 'text-yellow-300' : '';
  }

  if (columnName === '_agePercentile' || columnName === '_draftRawFV' || columnName === '_ceilingScore' ||
    columnName === '_g5DevPct' || columnName === '_hybridRaw') {
    if (num >= 90) return 'text-purple-400 font-bold';
    if (num >= 75) return 'text-cyan-400 font-semibold';
    if (num >= 50) return 'text-green-400';
    if (num >= 25) return 'text-yellow-300';
    if (num >= 10) return 'text-orange-400';
    return 'text-red-400';
  }

  return '';
}

export const COLUMN_LABELS = {
  '_fvScale': 'FV',
  '_futureValue': 'Future$',
  '_currentWAA': 'Curr WAA',
  '_potentialWAA': 'Pot WAA',
  '_peakWAA': 'Peak WAA',
  '_pctToPeak': '% to Peak',
  '_yearsTilPeak': 'Yrs to Peak',
  '_maxWAA': 'Max WAA',
  'Max WAA wtd': 'Best WAA',
  'Max WAA vR': 'Best vR',
  'Max WAA vL': 'Best vL',
  'MAX WAA P': 'Best P',
  'WAA wtd': 'SP WAA',
  'WAA wtd RP': 'RP WAA',
  'WAR wtd': 'SP WAR',
  '_draftFV': 'Draft FV',
  '_draftRawFV': 'Draft Raw',
  '_agePercentile': 'Age Pctl',
  '_draftCeiling': 'Ceiling',
  '_ceilingScore': 'Ceil Score',
  '_durability': 'Durability',
  '_highINT': 'High INT',
  '_wrecked': 'Wrecked',
  '_weBoost': 'WE+',
  '_g5FV': 'G5 FV',
  '_g5Raw': 'G5 Peak',
  '_g5DevPct': 'Dev Pctl',
  '_g5GapFactor': 'Gap Factor',
  '_g5RiskFactor': 'Risk Factor',
  '_hybridFV': 'Hybrid FV',
  '_hybridRaw': 'Hybrid Raw',
  '_hybridWFV': 'w(FV)',
  '_hybridWG5': 'w(G5)',
  '_hybridWDraft': 'w(Draft)',
  'C Eligible': 'C',
  '1B Eligible': '1B',
  '2B Eligible': '2B',
  '3B Eligible': '3B',
  'SS Eligible': 'SS',
  'LF Eligible': 'LF',
  'CF Eligible': 'CF',
  'RF Eligible': 'RF',
  // Market value labels
  '_perWAA': '$/WAA',
  '_marketValue': 'Career $',
  '_offerFloor': 'Offer Low',
  '_offerMid': 'Fair Value',
  '_offerCeiling': 'Offer High',
  '_annualValue': 'Curr AAV',
  '_surplus': 'Surplus',
  '_futureAAV': 'Peak AAV',
  '_futureOfferLow': 'Fut Low',
  '_futureOfferMid': 'Fut Mid',
  '_futureOfferHigh': 'Fut High',
  '_marketRole': 'Role $',
  '_bestWAA': 'Best WAA',
};
