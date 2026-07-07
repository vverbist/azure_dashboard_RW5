import { getElement } from "../dom.js";
import { debugLog } from "../logger.js";
import { showChartEmpty } from "./layout.js";
import { renderDefaultTimeseriesChart } from "./defaultTimeseriesChart.js";
import { renderPricesChart } from "./pricesChart.js";
import { renderRevenueComponentsChart } from "./revenueComponentsChart.js";
import { renderVolumesChart } from "./volumesChart.js";

export const TIMESERIES_GROUPS = ["Volumes", "Revenue components", "Prices"];

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

  items.forEach((item, index) => {
    const targetId = `timeseries-chart-${index}`;

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
}
