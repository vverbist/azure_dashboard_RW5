import { apiGet, isAbortError, loadDatasets } from "./api.js";
import {
  applyQuickPeriod,
  bindControlEvents,
  currentState,
  populateDatasetOptions,
  readControls,
  setupTabs,
  updateDateBounds,
  updateQuickPeriodMonths,
  updateTimestampOptions,
} from "./controls.js";
import { bindElements, clearError, setStatus, showError } from "./dom.js";
import { renderAssumptionStrip } from "./renderers/assumptions.js";
import {
  renderContext,
  renderSelectedPeriodScope,
} from "./renderers/context.js";
import { renderDownloads } from "./renderers/downloads.js";
import { renderKpis, renderNarrative } from "./renderers/kpis.js";
import { renderMonthly, renderMonthlyError } from "./renderers/monthly.js";
import {
  renderAnomalies,
  renderAnomaliesError,
} from "./renderers/anomalies.js";
import { renderTable, renderTableError } from "./renderers/tables.js";
import { showChartEmpty } from "./charts/layout.js";
import { renderLineChart } from "./charts/lineChart.js";
import {
  renderAllTimeseries,
  TIMESERIES_GROUPS,
} from "./charts/timeseriesRouter.js";
import { renderWaterfall } from "./charts/waterfallChart.js";

let initialized = false;
let refreshToken = 0;
let activeRefreshController = null;

function beginRefresh() {
  if (activeRefreshController) {
    activeRefreshController.abort();
  }

  activeRefreshController = new AbortController();
  refreshToken += 1;

  return {
    token: refreshToken,
    signal: activeRefreshController.signal,
  };
}

function isCurrentRefresh(token) {
  return token === refreshToken;
}

async function settleRecord(record) {
  const entries = Object.entries(record);
  const settled = await Promise.allSettled(
    entries.map(([, promise]) => promise),
  );

  return Object.fromEntries(
    entries.map(([key], index) => [key, settled[index]]),
  );
}

async function loadDashboardData(signal) {
  const coreRequests = {
    summary: apiGet("/api/summary", {}, { signal }),
    monthly: apiGet("/api/monthly", {}, { signal }),
    revenueBridge: apiGet("/api/revenue-bridge", {}, { signal }),
    strike: apiGet("/api/strike-exposure", {}, { signal }),
    anomalies: apiGet("/api/anomalies", {}, { signal }),
    quality: apiGet("/api/data-quality", {}, { signal }),
  };
  const timeseriesRequests = TIMESERIES_GROUPS.map((group) =>
    apiGet("/api/timeseries", { chart_group: group }, { signal }),
  );
  const [core, timeseriesSettled] = await Promise.all([
    settleRecord(coreRequests),
    Promise.allSettled(timeseriesRequests),
  ]);

  return {
    ...core,
    timeseries: timeseriesSettled.map((result, index) => ({
      group: TIMESERIES_GROUPS[index],
      ...result,
    })),
  };
}

function resultValue(result) {
  return result.status === "fulfilled" ? result.value : null;
}

function resultMessage(prefix, result) {
  const reason = result?.reason?.message || result?.reason || "";
  return reason ? `${prefix}: ${reason}` : prefix;
}

function countOptionalFailures(results) {
  const coreFailures = [
    results.monthly,
    results.revenueBridge,
    results.strike,
    results.anomalies,
    results.quality,
  ].filter((result) => result?.status === "rejected").length;
  const timeseriesFailures = (results.timeseries || []).filter(
    (result) => result.status === "rejected",
  ).length;

  return coreFailures + timeseriesFailures;
}

function renderSummary(summary) {
  renderSelectedPeriodScope(summary.context);
  renderAssumptionStrip(currentState());
  renderContext(summary.context);
  renderKpis(summary.headline_kpis);
  renderNarrative(summary.executive_narrative);
  renderTable(
    "commercial-table",
    summary.commercial_breakdown?.formatted || [],
  );
  renderDownloads("summary-downloads", [
    { label: "Filtered data", path: "/api/downloads/filtered-data" },
    { label: "Summary table", path: "/api/downloads/summary-table" },
    { label: "Variance table", path: "/api/downloads/variance-table" },
  ]);
}

function renderRevenueBridge(result) {
  if (result.status === "fulfilled") {
    renderWaterfall(
      "revenue-bridge-chart",
      "Revenue bridge",
      result.value.components,
    );
    return;
  }

  showChartEmpty(
    "revenue-bridge-chart",
    resultMessage("Could not load revenue bridge", result),
  );
}

function renderStrikeExposure(result) {
  if (result.status === "fulfilled") {
    renderLineChart(
      "strike-chart",
      "EPEX price versus strike price",
      result.value,
      "EUR/MWh",
    );
    renderTable("strike-table", result.value.summary || []);
    return;
  }

  showChartEmpty(
    "strike-chart",
    resultMessage("Could not load strike-price exposure", result),
  );
  renderTableError(
    "strike-table",
    resultMessage("Could not load strike-price table", result),
  );
}

function renderQuality(result) {
  if (result.status === "fulfilled") {
    const quality = result.value;
    renderTable("quality-table", quality.data_quality_checks || []);
    renderTable("assumptions-table", quality.selected_assumptions || []);
    renderTable("recognized-table", quality.recognized_columns || []);
    updateTimestampOptions(quality.timestamp_columns || []);
    return;
  }

  renderTableError(
    "quality-table",
    resultMessage("Could not load data quality checks", result),
  );
  renderTableError(
    "assumptions-table",
    resultMessage("Could not load selected assumptions", result),
  );
  renderTableError(
    "recognized-table",
    resultMessage("Could not load recognized columns", result),
  );
}

export async function refreshDashboard() {
  const refresh = beginRefresh();

  clearError();
  setStatus("Loading");
  applyQuickPeriod();
  readControls();

  try {
    const results = await loadDashboardData(refresh.signal);

    if (!isCurrentRefresh(refresh.token)) return;

    if (results.summary.status === "rejected") {
      throw results.summary.reason;
    }

    const summary = resultValue(results.summary);
    updateDateBounds(summary);

    if (results.monthly.status === "fulfilled") {
      updateQuickPeriodMonths(results.monthly.value);
      renderMonthly(results.monthly.value);
    } else {
      renderMonthlyError(
        resultMessage("Could not load monthly overview", results.monthly),
      );
    }

    renderSummary(summary);
    renderRevenueBridge(results.revenueBridge);
    renderStrikeExposure(results.strike);

    if (results.anomalies.status === "fulfilled") {
      renderAnomalies(results.anomalies.value);
    } else {
      renderAnomaliesError(
        resultMessage("Could not load anomaly tables", results.anomalies),
      );
    }

    renderAllTimeseries(results.timeseries, {
      timestampColumn: currentState().timestamp_col,
    });
    renderQuality(results.quality);

    const optionalFailures = countOptionalFailures(results);
    setStatus(
      optionalFailures
        ? `Loaded ${summary.dataset} with warnings`
        : `Loaded ${summary.dataset}`,
    );
  } catch (error) {
    if (isAbortError(error) || !isCurrentRefresh(refresh.token)) return;

    setStatus("Error");
    showError(error.message || String(error));
  }
}

export async function init() {
  if (initialized) return;
  initialized = true;

  bindElements();
  setupTabs();
  bindControlEvents({ onRefresh: refreshDashboard });

  try {
    setStatus("Loading datasets");
    const datasetPayload = await loadDatasets();
    populateDatasetOptions(datasetPayload);
    await refreshDashboard();
  } catch (error) {
    setStatus("Error");
    showError(error.message || String(error));
  }
}

init();
