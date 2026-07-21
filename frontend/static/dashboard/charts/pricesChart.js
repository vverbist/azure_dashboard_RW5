import { getElement } from "../dom.js";
import { applyInspectionRange, chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { CHART_COLORS } from "./chartTheme.js";
import { SERIES_LABELS } from "./seriesLabels.js";

const PRICE_LABELS_TO_SHOW = [
  SERIES_LABELS.prices.epex,
  SERIES_LABELS.prices.longImbalance,
  SERIES_LABELS.prices.shortImbalance,
];

const REGELTOESTAND_LABEL = "Regeltoestand 2";

const PRICE_LINE_STYLES = {
  [SERIES_LABELS.prices.epex]: {
    color: CHART_COLORS.blue,
    dash: "solid",
  },
  [SERIES_LABELS.prices.longImbalance]: {
    color: CHART_COLORS.green,
    dash: "dashdot",
  },
  [SERIES_LABELS.prices.shortImbalance]: {
    color: CHART_COLORS.green,
    dash: "solid",
  },
};

const PRICE_DRAW_ORDER = [
  SERIES_LABELS.prices.shortImbalance,
  SERIES_LABELS.prices.longImbalance,
  SERIES_LABELS.prices.epex,
];

export function renderPricesChart(payload, targetId, options = {}) {
  const target = getElement(targetId);
  const includedSeries = (payload?.series || []).filter((series) =>
    PRICE_LABELS_TO_SHOW.includes(cleanLabel(series.label)),
  );

  if (!includedSeries.length) {
    showChartEmpty(target, "No price series available.");
    return;
  }

  const seriesByLabel = new Map(
    includedSeries.map((series) => [cleanLabel(series.label), series]),
  );
  const traces = [];
  const longImbalance = seriesByLabel.get(SERIES_LABELS.prices.longImbalance);
  const shortImbalance = seriesByLabel.get(SERIES_LABELS.prices.shortImbalance);

  if (longImbalance && shortImbalance) {
    traces.push(
      {
        type: "scatter",
        mode: "lines",
        x: longImbalance.x,
        y: longImbalance.y,
        line: { width: 0, color: CHART_COLORS.green },
        hoverinfo: "skip",
        showlegend: false,
      },
      {
        type: "scatter",
        mode: "lines",
        name: REGELTOESTAND_LABEL,
        x: shortImbalance.x,
        y: shortImbalance.y,
        line: { width: 0, color: CHART_COLORS.green , dash:  "dashdot" },
        fill: "tonexty",
        fillcolor: CHART_COLORS.greenFill,
        hoverinfo: "skip",
      },
    );
  }

  PRICE_DRAW_ORDER.forEach((label) => {
    const series = seriesByLabel.get(label);
    if (!series) return;

    const style = PRICE_LINE_STYLES[label];
    traces.push({
      type: "scatter",
      mode: "lines",
      name: label,
      x: series.x,
      y: series.y,
      line: {
        width: 2,
        color: style?.color,
        dash: style?.dash,
      },
    });
  });

  const unit = includedSeries?.[0]?.unit || "EUR/MWh";
  const layout = applyInspectionRange(
    chartLayout(payload.group || "Prices", unit),
    options.inspectionWindow,
  );
  layout.yaxis.zeroline = true;
  layout.legend.traceorder = "reversed";

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}

function cleanLabel(label) {
  return String(label || "").trim();
}
