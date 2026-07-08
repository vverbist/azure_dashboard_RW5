import { getElement } from "../dom.js";
import { debugLog } from "../logger.js";
import { getStateValue } from "../state.js";
import { showChartEmpty } from "./layout.js";
import { renderDefaultTimeseriesChart } from "./defaultTimeseriesChart.js";
import { renderPricesChart } from "./pricesChart.js";
import { renderRevenueComponentsChart } from "./revenueComponentsChart.js";
import { renderVolumesChart } from "./volumesChart.js";

export const TIMESERIES_GROUPS = ["Volumes", "Revenue components", "Prices"];

// Guards against the relayout we trigger on the other charts (to mirror a
// zoom/pan) re-triggering this same propagation and looping forever.
let syncingZoom = false;

function rangeFromRelayoutEvent(eventData) {
  if (
    eventData["xaxis.range[0]"] !== undefined &&
    eventData["xaxis.range[1]"] !== undefined
  ) {
    return [eventData["xaxis.range[0]"], eventData["xaxis.range[1]"]];
  }
  if (eventData["xaxis.range"]) {
    return eventData["xaxis.range"];
  }
  if (eventData["xaxis.autorange"]) {
    return "auto";
  }
  return null;
}

function bindZoomSync(chartIds) {
  const plotly = window.Plotly;
  if (!plotly) return;

  chartIds.forEach((sourceId) => {
    const sourceEl = document.getElementById(sourceId);
    if (!sourceEl || typeof sourceEl.on !== "function") return;

    sourceEl.on("plotly_relayout", (eventData) => {
      if (syncingZoom || !getStateValue("syncChartZoom")) return;

      const range = rangeFromRelayoutEvent(eventData);
      if (!range) return;

      syncingZoom = true;
      const updates = chartIds
        .filter((id) => id !== sourceId)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((el) =>
          range === "auto"
            ? plotly.relayout(el, { "xaxis.autorange": true })
            : plotly.relayout(el, { "xaxis.range": range }),
        );

      Promise.all(updates).finally(() => {
        syncingZoom = false;
      });
    });
  });
}

export function renderTimeseriesChart(payload, targetId, options = {}) {
  const group = String(payload?.group || "").trim();

  debugLog("Routing timeseries chart", {
    targetId,
    group,
    labels: (payload?.series || []).map((series) => series.label),
  });

  if (group === "Volumes") {
    renderVolumesChart(payload, targetId, options);
    return;
  }

  if (group === "Revenue components") {
    renderRevenueComponentsChart(payload, targetId, options);
    return;
  }

  if (group === "Prices") {
    renderPricesChart(payload, targetId, options);
    return;
  }

  renderDefaultTimeseriesChart(payload, targetId, options);
}

export function renderAllTimeseries(results, options = {}) {
  const target = getElement("timeseries-plots");
  const items = results || [];

  if (!items.length) {
    showChartEmpty(target, "No time-series charts available.");
    return;
  }

  target.innerHTML = items
    .map(
      (_, index) =>
        `<div class="chart-frame large" id="timeseries-chart-${index}"></div>`,
    )
    .join("");

  const chartIds = items.map((_, index) => `timeseries-chart-${index}`);

  items.forEach((item, index) => {
    const targetId = chartIds[index];

    if (item.status === "rejected") {
      showChartEmpty(
        targetId,
        `Could not load ${item.group || "time-series"} chart.`,
      );
      console.warn("Timeseries chart failed", item.group, item.reason);
      return;
    }

    renderTimeseriesChart(item.value || item, targetId, options);
  });

  bindZoomSync(chartIds);
}
