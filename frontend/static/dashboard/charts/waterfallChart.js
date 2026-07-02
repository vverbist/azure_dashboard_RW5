import { chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { getElement } from "../dom.js";

export function renderWaterfall(targetId, title, components) {
  const target = getElement(targetId);

  if (!components || !components.length) {
    showChartEmpty(target, "No bridge data available.");
    return;
  }

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(
    target,
    [
      {
        type: "waterfall",
        measure: components.map((row) => row.measure),
        x: components.map((row) => row.label),
        y: components.map((row) => row.value),
        text: components.map((row) => row.text),
        textposition: "outside",
        connector: { line: { width: 1 } },
        increasing: { marker: { color: "#95C800" } },
        decreasing: { marker: { color: "#EF4444" } },
        totals: { marker: { color: "#1673E6" } },
      },
    ],
    chartLayout(title, "EUR"),
  );
}
