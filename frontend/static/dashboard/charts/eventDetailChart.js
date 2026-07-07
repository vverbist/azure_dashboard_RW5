import { getElement } from "../dom.js";
import { chartLayout, getPlotly, showChartEmpty } from "./layout.js";

const CHART_METRIC_BY_KEY = {
  "negative-imbalance-revenue-events": "Total imbalance revenue",
  "positive-imbalance-revenue-events": "Total imbalance revenue",
  "negative-epex-revenue-events": "EPEX revenue",
};

export function renderEventDetailChart(targetId, key, rows) {
  const target = getElement(targetId);

  if (!rows || !rows.length) {
    showChartEmpty(target, "No 15-minute rows in this window.");
    return;
  }

  const metric = CHART_METRIC_BY_KEY[key] || "Total revenue";
  const x = rows.map((row) => row.Timestamp);
  const y = rows.map((row) => row[metric]);

  const plotly = getPlotly(target);
  if (!plotly) return;

  const layout = chartLayout(metric, "EUR");
  layout.margin = { l: 56, r: 16, t: 40, b: 40 };
  layout.showlegend = false;
  layout.height = 220;

  plotly.react(
    target,
    [
      {
        type: "bar",
        x,
        y,
        marker: { color: y.map((value) => (value < 0 ? "#c0392b" : "#1f8a5f")) },
      },
    ],
    layout,
    { displayModeBar: false, responsive: true },
  );
}
