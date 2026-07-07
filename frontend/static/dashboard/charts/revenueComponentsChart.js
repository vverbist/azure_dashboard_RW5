import { getElement } from "../dom.js";
import { applyInspectionRange, chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { SERIES_LABELS } from "./seriesLabels.js";

export function renderRevenueComponentsChart(payload, targetId, options = {}) {
  const target = getElement(targetId);
  const componentLabels = [
    SERIES_LABELS.revenue.epex,
    SERIES_LABELS.revenue.imbalance,
  ];
  const componentSeries = (payload?.series || []).filter((series) =>
    componentLabels.includes(series.label),
  );
  const totalSeries = (payload?.series || []).find(
    (series) => series.label === SERIES_LABELS.revenue.total,
  );

  if (!componentSeries.length && !totalSeries) {
    showChartEmpty(target, "No revenue component data available.");
    return;
  }

  const traces = componentSeries.map((series) => ({
    type: "bar",
    name: series.label,
    x: series.x,
    y: series.y,
  }));

  if (totalSeries) {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: totalSeries.label,
      x: totalSeries.x,
      y: totalSeries.y,
      line: {
        width: 2,
      },
    });
  }

  const unit = componentSeries?.[0]?.unit || totalSeries?.unit || "EUR";
  const layout = applyInspectionRange(
    chartLayout(payload.group || "Revenue components", unit),
    options.inspectionWindow,
  );
  layout.barmode = "relative";

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}
