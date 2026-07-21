import { chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { getElement } from "../dom.js";
import { CHART_COLORS } from "./chartTheme.js";

export function renderLineChart(targetId, title, payload, yTitle = "") {
  const target = getElement(targetId);
  const series = payload?.series || [];

  if (!series.length) {
    showChartEmpty(target, "No chart data available.");
    return;
  }

  const traces = [];

  if (payload.strike_price !== undefined && payload.strike_price !== null) {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: "Strike price",
      x: series[0]?.x || [],
      y: (series[0]?.x || []).map(() => payload.strike_price),
      line: { dash: "dash", color: CHART_COLORS.green, width: 2 },
    });
  }

  traces.push(
    ...series.map((item) => ({
      type: "scatter",
      mode: "lines",
      name: item.label,
      x: item.x,
      y: item.y,
      line: { color: CHART_COLORS.blue, width: 2.5 },
    })),
  );

  const plotly = getPlotly(target);
  if (!plotly) return;

  const layout = chartLayout(title, yTitle);
  layout.legend.traceorder = "reversed";

  plotly.react(target, traces, layout);
}
