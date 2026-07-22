import { getElement } from "../dom.js";
import { debugLog } from "../logger.js";
import { getStateValue } from "../state.js";
import { showChartEmpty } from "./layout.js";
import { renderDefaultTimeseriesChart } from "./defaultTimeseriesChart.js";
import { renderPricesChart } from "./pricesChart.js";
import { renderRevenueComponentsChart } from "./revenueComponentsChart.js";
import { SERIES_LABELS } from "./seriesLabels.js";
import { renderVolumesChart } from "./volumesChart.js";

export const TIMESERIES_GROUPS = ["Volumes", "Revenue components", "Prices"];

const AUTOSCALE_PADDING_RATIO = 0.08;
const ZOOM_SYNC_DEBOUNCE_MS = 80;
const AUTOSCALE_LABELS_BY_GROUP = {
  Volumes: new Set([
    SERIES_LABELS.volumes.delivered,
    SERIES_LABELS.volumes.nominated,
  ]),
  "Revenue components": new Set([
    SERIES_LABELS.revenue.total,
    SERIES_LABELS.revenue.epex,
    SERIES_LABELS.revenue.imbalance,
  ]),
  Prices: new Set([
    SERIES_LABELS.prices.epex,
    SERIES_LABELS.prices.longImbalance,
    SERIES_LABELS.prices.shortImbalance,
  ]),
};

// Guards against the relayout we trigger on the other charts (to mirror a
// zoom/pan) re-triggering this same propagation and looping forever.
let syncingZoom = false;
let zoomSyncTimer = null;

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

function timestampValue(value) {
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function visibleYRange(payload, range) {
  if (!payload || range === "auto") return null;

  const rangeStart = timestampValue(range[0]);
  const rangeEnd = timestampValue(range[1]);
  if (rangeStart === null || rangeEnd === null) return null;

  const minimumTime = Math.min(rangeStart, rangeEnd);
  const maximumTime = Math.max(rangeStart, rangeEnd);
  const group = String(payload.group || "").trim();
  const allowedLabels = AUTOSCALE_LABELS_BY_GROUP[group];
  const values = [];

  (payload.series || []).forEach((series) => {
    if (allowedLabels && !allowedLabels.has(series.label)) return;

    (series.x || []).forEach((xValue, index) => {
      const timestamp = timestampValue(xValue);
      const yValue = Number(series.y?.[index]);

      if (
        timestamp !== null &&
        timestamp >= minimumTime &&
        timestamp <= maximumTime &&
        Number.isFinite(yValue)
      ) {
        values.push(yValue);
      }
    });
  });

  if (!values.length) return null;

  const includeZero = group === "Volumes" || group === "Revenue components";
  let minimum = Infinity;
  let maximum = -Infinity;

  values.forEach((value) => {
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
  });

  if (includeZero) {
    minimum = Math.min(minimum, 0);
    maximum = Math.max(maximum, 0);
  }

  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * AUTOSCALE_PADDING_RATIO, 1);
    return includeZero && minimum === 0
      ? [0, padding]
      : [minimum - padding, maximum + padding];
  }

  const padding = (maximum - minimum) * AUTOSCALE_PADDING_RATIO;
  return [
    includeZero && minimum === 0 ? 0 : minimum - padding,
    includeZero && maximum === 0 ? 0 : maximum + padding,
  ];
}

function relayoutUpdate({
  chartId,
  sourceId,
  range,
  payload,
  syncX,
  autoScaleY,
}) {
  const update = {};

  if (syncX && chartId !== sourceId) {
    if (range === "auto") {
      update["xaxis.autorange"] = true;
    } else {
      update["xaxis.range"] = range;
    }
  }

  if (autoScaleY) {
    if (range === "auto") {
      update["yaxis.autorange"] = true;
    } else {
      const rangeY = visibleYRange(payload, range);
      if (rangeY) update["yaxis.range"] = rangeY;
    }
  }

  return update;
}

function bindZoomSync(chartIds, chartPayloads) {
  const plotly = window.Plotly;
  if (!plotly) return;

  chartIds.forEach((sourceId) => {
    const sourceEl = document.getElementById(sourceId);
    if (!sourceEl || typeof sourceEl.on !== "function") return;

    sourceEl.on("plotly_relayout", (eventData) => {
      if (syncingZoom) return;

      const range = rangeFromRelayoutEvent(eventData);
      if (!range) return;

      const syncX = getStateValue("syncChartZoom");
      const autoScaleY = getStateValue("autoScaleYOnZoom");
      if (!syncX) return;

      if (zoomSyncTimer) clearTimeout(zoomSyncTimer);
      zoomSyncTimer = setTimeout(() => {
        zoomSyncTimer = null;
        syncingZoom = true;
        let updates;

        try {
          updates = chartIds
            .filter((chartId) => chartId !== sourceId)
            .map((chartId) => {
              const element = document.getElementById(chartId);
              if (!element) return null;

              const update = relayoutUpdate({
                chartId,
                sourceId,
                range,
                payload: chartPayloads.get(chartId),
                syncX,
                autoScaleY,
              });
              if (!Object.keys(update).length) return null;

              return plotly.relayout(element, update);
            })
            .filter(Boolean);
        } catch (error) {
          syncingZoom = false;
          console.warn("Chart zoom sync failed", error);
          return;
        }

        if (!updates.length) {
          syncingZoom = false;
          return;
        }

        Promise.all(updates)
          .catch((error) => console.warn("Chart zoom sync failed", error))
          .finally(() => {
            syncingZoom = false;
          });
      }, ZOOM_SYNC_DEBOUNCE_MS);
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

  if (zoomSyncTimer) {
    clearTimeout(zoomSyncTimer);
    zoomSyncTimer = null;
  }

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
  const chartPayloads = new Map();

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

    const payload = item.value || item;
    chartPayloads.set(targetId, payload);
    renderTimeseriesChart(payload, targetId, options);
  });

  bindZoomSync([...chartPayloads.keys()], chartPayloads);
}
