import { getElement } from "../dom.js";
import { applyInspectionRange, chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { SERIES_LABELS } from "./seriesLabels.js";

const PRICE_LABELS_TO_SHOW = [
  SERIES_LABELS.prices.epex,
  SERIES_LABELS.prices.longImbalance,
  SERIES_LABELS.prices.shortImbalance,
];

const PRICE_LINE_STYLES = {
  [SERIES_LABELS.prices.epex]: { color: "#1f77b4", dash: "solid" },
  [SERIES_LABELS.prices.longImbalance]: { color: "#fab170", dash: "solid" },
  [SERIES_LABELS.prices.shortImbalance]: { color: "#ff7f0e", dash: "solid" },
};

export function renderPricesChart(payload, targetId, options = {}) {
  const target = getElement(targetId);
  const includedSeries = (payload?.series || []).filter((series) =>
    PRICE_LABELS_TO_SHOW.includes(cleanLabel(series.label)),
  );

  if (!includedSeries.length) {
    showChartEmpty(target, "No price series available.");
    return;
  }

  const traces = includedSeries.map((series) => {
    const label = cleanLabel(series.label);

    return {
      type: "scatter",
      mode: "lines",
      name: label,
      x: series.x,
      y: series.y,
      line: {
        width: 2,
        color: PRICE_LINE_STYLES[label]?.color,
        dash: PRICE_LINE_STYLES[label]?.dash,
      },
    };
  });

  const unit = includedSeries?.[0]?.unit || "EUR/MWh";
  const layout = applyInspectionRange(
    chartLayout(payload.group || "Prices", unit),
    options.inspectionWindow,
  );
  layout.yaxis.zeroline = true;

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}

function cleanLabel(label) {
  return String(label || "").trim();
}
