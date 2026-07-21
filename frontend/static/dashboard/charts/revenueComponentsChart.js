import { getElement } from "../dom.js";
import { applyInspectionRange, chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { CHART_COLORS } from "./chartTheme.js";
import { SERIES_LABELS } from "./seriesLabels.js";

const POSITIVE_IMBALANCE_LABEL = "Positive imbalance revenue";
const NEGATIVE_IMBALANCE_LABEL = "Negative imbalance revenue";

export function renderRevenueComponentsChart(payload, targetId, options = {}) {
  const target = getElement(targetId);
  const series = payload?.series || [];
  const epexSeries = series.find(
    (item) => item.label === SERIES_LABELS.revenue.epex,
  );
  const imbalanceSeries = series.find(
    (item) => item.label === SERIES_LABELS.revenue.imbalance,
  );
  const totalSeries = series.find(
    (item) => item.label === SERIES_LABELS.revenue.total,
  );

  if (!epexSeries && !imbalanceSeries && !totalSeries) {
    showChartEmpty(target, "No revenue component data available.");
    return;
  }

  const traces = [];

  if (totalSeries) {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: totalSeries.label,
      x: totalSeries.x,
      y: totalSeries.y,
      line: {
        color: CHART_COLORS.blue,
        width: 2.5,
      },
      zorder: 10,
    });
  }

  if (epexSeries) {
    traces.push({
      type: "bar",
      name: epexSeries.label,
      x: epexSeries.x,
      y: epexSeries.y,
      marker: { color: CHART_COLORS.blueLight },
    });
  }

  if (imbalanceSeries) {
    const positiveValues = valuesBySign(imbalanceSeries.y, (value) => value > 0);
    const negativeValues = valuesBySign(imbalanceSeries.y, (value) => value < 0);

    if (positiveValues.some(Number.isFinite)) {
      traces.push({
        type: "bar",
        name: POSITIVE_IMBALANCE_LABEL,
        x: imbalanceSeries.x,
        y: positiveValues,
        marker: { color: CHART_COLORS.green },
      });
    }

    if (negativeValues.some(Number.isFinite)) {
      traces.push({
        type: "bar",
        name: NEGATIVE_IMBALANCE_LABEL,
        x: imbalanceSeries.x,
        y: negativeValues,
        marker: { color: CHART_COLORS.red },
      });
    }
  }

  const unit = epexSeries?.unit || imbalanceSeries?.unit || totalSeries?.unit || "EUR";
  const layout = applyInspectionRange(
    chartLayout(payload.group || "Revenue components", unit),
    options.inspectionWindow,
  );
  layout.barmode = "relative";
  layout.legend.traceorder = "normal";
  layout.yaxis.zerolinecolor = CHART_COLORS.zeroLine;
  layout.yaxis.zerolinewidth = 1.25;

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}

function valuesBySign(values, predicate) {
  return (values || []).map((value) => {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) && predicate(numericValue)
      ? numericValue
      : null;
  });
}
