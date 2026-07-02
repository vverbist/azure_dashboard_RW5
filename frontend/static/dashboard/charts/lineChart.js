import { chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { getElement } from "../dom.js";

export function renderLineChart(targetId, title, payload, yTitle = "") {
  const target = getElement(targetId);
  const series = payload?.series || [];

  if (!series.length) {
    showChartEmpty(target, "No chart data available.");
    return;
  }

  const traces = series.map((item) => ({
    type: "scatter",
    mode: "lines",
    name: item.label,
    x: item.x,
    y: item.y,
    line: { width: 2 },
  }));

  if (payload.strike_price !== undefined && payload.strike_price !== null) {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: "Strike price",
      x: traces[0]?.x || [],
      y: (traces[0]?.x || []).map(() => payload.strike_price),
      line: { dash: "dash", color: "#F59E0B", width: 2 },
    });
  }

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, chartLayout(title, yTitle));
}
