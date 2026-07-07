import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

export function chartLayout(title, yTitle) {
  return {
    title: { text: title, x: 0.02, xanchor: "left" },
    paper_bgcolor: "rgba(255,255,255,0)",
    plot_bgcolor: "#FFFFFF",
    font: { color: "#002B5C", family: "Montserrat, sans-serif" },
    margin: { l: 72, r: 34, t: 72, b: 92 },
    hovermode: "x unified",
    legend: { orientation: "h", y: -0.24 },
    yaxis: { title: yTitle, gridcolor: "#E8EEF6", zeroline: true },
    xaxis: { showgrid: false },
  };
}

export function applyInspectionRange(layout, inspectionWindow) {
  if (!inspectionWindow?.zoomStart || !inspectionWindow?.zoomEnd) return layout;

  layout.xaxis = {
    ...(layout.xaxis || {}),
    range: [inspectionWindow.zoomStart, inspectionWindow.zoomEnd],
  };
  return layout;
}

export function showChartEmpty(targetOrId, message) {
  const target =
    typeof targetOrId === "string" ? getElement(targetOrId) : targetOrId;
  target.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

export function getPlotly(targetOrId) {
  const target =
    typeof targetOrId === "string" ? getElement(targetOrId) : targetOrId;

  if (!window.Plotly) {
    showChartEmpty(target, "Charting library is unavailable.");
    return null;
  }

  return window.Plotly;
}
