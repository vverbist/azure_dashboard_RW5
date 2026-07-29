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

let plotConfigured = false;

export function getPlotly(targetOrId) {
  const target =
    typeof targetOrId === "string" ? getElement(targetOrId) : targetOrId;

  if (!window.Plotly) {
    showChartEmpty(target, "Charting library is unavailable.");
    return null;
  }

  // Centralized default config for every chart: resize with the window, no vendor logo.
  if (!plotConfigured) {
    window.Plotly.setPlotConfig({ responsive: true, displaylogo: false });
    plotConfigured = true;
  }

  return window.Plotly;
}

// Resize every Plotly chart inside a container (call after a hidden tab becomes visible;
// Plotly cannot size a display:none element, so charts drawn while hidden need this).
export function resizeChartsIn(container) {
  if (!window.Plotly?.Plots?.resize || !container) return;
  container
    .querySelectorAll(".js-plotly-plot")
    .forEach((element) => window.Plotly.Plots.resize(element));
}
