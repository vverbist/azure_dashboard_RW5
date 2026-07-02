import { getElement } from "../dom.js";
import { chartLayout, getPlotly, showChartEmpty } from "./layout.js";

export function renderDefaultTimeseriesChart(payload, targetId) {
  const target = getElement(targetId);
  const series = payload?.series || [];

  if (!series.length) {
    showChartEmpty(target, "No time-series data available.");
    return;
  }

  const isRevenue = ["Revenue components", "Revenue deltas"].includes(
    payload.group,
  );
  const traces = series.map((item) => ({
    type: isRevenue ? "bar" : "scatter",
    mode: isRevenue ? undefined : "lines",
    name: item.label,
    x: item.x,
    y: item.y,
  }));
  const unit = series?.[0]?.unit || "";
  const layout = chartLayout(payload.group || "Time-series", unit);

  if (isRevenue) layout.barmode = "relative";

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}
