// Client-side mirror of pipeline/analytics/risk_engine.py sizing conventions.
// Fixed-fractional risk parity with portfolio heat cap; kept in sync with the
// pipeline defaults so the terminal shows the same book the pipeline logs.

export interface SizingSignal {
  ticker: string;
  signalType: string;
  entryReference: number | null;
  stopLoss: number | null;
  conviction?: string | null;
}

export interface SizedPosition {
  ticker: string;
  signalType: string;
  entryReference: number;
  stopLoss: number;
  stopDistancePct: number;
  shares: number;
  positionValuePkr: number;
  riskPkr: number;
  riskPctOfEquity: number;
  conviction: string | null;
  clampedByMaxPosition: boolean;
}

export interface SizingBook {
  positions: SizedPosition[];
  rejected: { ticker: string | null; reason: string }[];
  totals: {
    positions: number;
    deployedValuePkr: number;
    deployedPctOfEquity: number;
    totalRiskPkr: number;
    portfolioHeatPct: number;
    avgStopDistancePct: number;
  };
}

const ACTIONABLE_SIGNAL_TYPES = new Set([
  "ACCUMULATION",
  "STEALTH_ACCUMULATION",
  "INSTITUTIONAL_TARGET",
  "MOMENTUM_BREAKOUT",
  "INSIDER_BUYING",
  "LEVERAGE_FLUSH_BOTTOM",
  "VALUE_YIELD",
  "HIGH_YIELD",
]);

const CONVICTION_RANK: Record<string, number> = {
  HIGH: 3,
  ELEVATED: 2,
  NOTABLE_VOLUME_SPIKE: 2,
  MODERATE: 1,
};

export const RISK_DEFAULTS = {
  riskPerTradePct: 1.0,
  maxPortfolioHeatPct: 6.0,
  maxPositionPct: 20.0,
  maxPositions: 8,
  minStopDistancePct: 1.5,
  maxGrossExposurePct: 100.0,
  minPositionValuePkr: 25000,
};

export function sizeBook(
  signals: SizingSignal[],
  equityPkr: number,
  params: {
    riskPerTradePct: number;
    maxPortfolioHeatPct: number;
    maxPositionPct: number;
    maxPositions: number;
    minStopDistancePct: number;
    maxGrossExposurePct: number;
    minPositionValuePkr: number;
  } = RISK_DEFAULTS
): SizingBook {
  const rejected: { ticker: string | null; reason: string }[] = [];
  if (!(equityPkr > 0)) {
    return {
      positions: [],
      rejected,
      totals: {
        positions: 0,
        deployedValuePkr: 0,
        deployedPctOfEquity: 0,
        totalRiskPkr: 0,
        portfolioHeatPct: 0,
        avgStopDistancePct: 0,
      },
    };
  }

  const riskBudgetPkr = equityPkr * (params.riskPerTradePct / 100);
  const heatCapPkr = equityPkr * (params.maxPortfolioHeatPct / 100);
  const maxValuePkr = equityPkr * (params.maxPositionPct / 100);
  const grossCapPkr = equityPkr * (params.maxGrossExposurePct / 100);

  const candidates: (SizingSignal & {
    _stopDistance: number;
    _conv: number;
    _entry: number;
  })[] = [];
  for (const signal of signals) {
    if (!ACTIONABLE_SIGNAL_TYPES.has(signal.signalType)) {
      rejected.push({ ticker: signal.ticker, reason: "NON_ACTIONABLE_TYPE" });
      continue;
    }
    const entry = signal.entryReference;
    const stop = signal.stopLoss;
    if (entry == null || entry <= 0 || stop == null) {
      rejected.push({ ticker: signal.ticker, reason: "NO_ENTRY" });
      continue;
    }
    const stopDistance = (entry - stop) / entry;
    if (stopDistance <= 0) {
      rejected.push({ ticker: signal.ticker, reason: "NOT_LONG_BIAS" });
      continue;
    }
    if (stopDistance * 100 < params.minStopDistancePct) {
      rejected.push({ ticker: signal.ticker, reason: "STOP_TOO_TIGHT" });
      continue;
    }
    candidates.push({
      ...signal,
      _stopDistance: stopDistance,
      _conv: CONVICTION_RANK[signal.conviction ?? ""] ?? 0,
      _entry: entry,
    });
  }

  candidates.sort(
    (a, b) => b._conv - a._conv || a._stopDistance - b._stopDistance
  );

  const positions: SizedPosition[] = [];
  let totalRisk = 0;
  let deployedValue = 0;
  const seenTickers = new Set<string>();

  for (const candidate of candidates) {
    if (positions.length >= params.maxPositions) {
      rejected.push({ ticker: candidate.ticker, reason: "MAX_POSITIONS" });
      continue;
    }
    // One position per underlying across all timeframes/signals.
    const tickerKey = candidate.ticker.toUpperCase().trim();
    if (seenTickers.has(tickerKey)) {
      rejected.push({ ticker: candidate.ticker, reason: "DUPLICATE_TICKER" });
      continue;
    }
    const entry = candidate._entry;
    const stopDistance = candidate._stopDistance;

    let positionValue = riskBudgetPkr / stopDistance;
    const clamped = positionValue > maxValuePkr;
    if (clamped) positionValue = maxValuePkr;

    let tradeRisk = positionValue * stopDistance;
    const remainingHeat = heatCapPkr - totalRisk;
    if (tradeRisk > remainingHeat + 1e-9) {
      if (remainingHeat <= 1e-9) {
        rejected.push({ ticker: candidate.ticker, reason: "HEAT_CAP" });
        continue;
      }
      positionValue = remainingHeat / stopDistance;
      tradeRisk = remainingHeat;
    }

    // Gross-exposure guardrail: trim to the remaining cash budget.
    const remainingGross = grossCapPkr - deployedValue;
    if (positionValue > remainingGross) {
      if (remainingGross <= 1e-9) {
        rejected.push({ ticker: candidate.ticker, reason: "GROSS_EXPOSURE_CAP" });
        continue;
      }
      positionValue = remainingGross;
      tradeRisk = positionValue * stopDistance;
    }

    const shares = Math.floor(positionValue / entry);
    if (shares <= 0 || shares * entry < params.minPositionValuePkr) {
      rejected.push({ ticker: candidate.ticker, reason: "BELOW_MIN_SIZE" });
      continue;
    }

    seenTickers.add(tickerKey);

    deployedValue += shares * entry;
    totalRisk += tradeRisk;
    positions.push({
      ticker: candidate.ticker,
      signalType: candidate.signalType,
      entryReference: entry,
      stopLoss: candidate.stopLoss as number,
      stopDistancePct: Math.round(stopDistance * 10000) / 100,
      shares,
      positionValuePkr: Math.round(shares * entry),
      riskPkr: Math.round(tradeRisk),
      riskPctOfEquity:
        Math.round((tradeRisk / equityPkr) * 100000) / 1000,
      conviction: candidate.conviction ?? null,
      clampedByMaxPosition: clamped,
    });
  }

  return {
    positions,
    rejected,
    totals: {
      positions: positions.length,
      deployedValuePkr: Math.round(deployedValue),
      deployedPctOfEquity:
        Math.round((deployedValue / equityPkr) * 10000) / 100,
      totalRiskPkr: Math.round(totalRisk),
      portfolioHeatPct:
        Math.round((totalRisk / equityPkr) * 100000) / 1000,
      avgStopDistancePct:
        positions.length === 0
          ? 0
          : Math.round(
              (positions.reduce((a, p) => a + p.stopDistancePct, 0) /
                positions.length) *
                100
            ) / 100,
    },
  };
}
