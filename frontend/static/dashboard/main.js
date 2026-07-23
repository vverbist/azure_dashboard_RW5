import { apiGet, isAbortError, loadDatasets } from "./api.js";
import {
  applyQuickPeriod,
  bindControlEvents,
  bindZoomSyncToggle,
  currentState,
  populateDatasetOptions,
  readControls,
  setupTabs,
  switchTab,
  updateDateBounds,
  updateQuickPeriodMonths,
  updateTimestampOptions,
} from "./controls.js";
import { bindElements, clearError, getElement, setStatus, showError } from "./dom.js";
import { escapeHtml } from "./formatters.js";
import { updateState } from "./state.js";
import { renderAssumptionStrip } from "./renderers/assumptions.js";
import {
  renderDataAvailability,
  renderScadaDataAvailability,
  renderSelectedPeriodScope,
} from "./renderers/context.js";
import { renderCompleteness } from "./renderers/completeness.js";
import { renderDownloads } from "./renderers/downloads.js";
import { renderKpis, renderNarrative } from "./renderers/kpis.js";
import { renderMonthly, renderMonthlyError } from "./renderers/monthly.js";
import {
  renderAnomalies,
  renderAnomaliesError,
} from "./renderers/anomalies.js";
import { renderTable, renderTableError } from "./renderers/tables.js";
import {
  renderScadaEnvelope,
  renderScadaEnvelopeError,
} from "./renderers/scada.js";
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
let lastTimeseriesResults = [];
let lastScadaEnvelope = null;

const EVENT_WINDOW_PADDING_HOURS = 2;

function renderSynchronizedTimeseries(results, options = {}) {
  const additionalCharts = lastScadaEnvelope?.available
    ? [{ id: "scada-envelope-chart", payload: lastScadaEnvelope }]
    : [];
  renderAllTimeseries(results, { ...options, additionalCharts });
}

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
    scada: apiGet("/api/scada", {}, { signal }),
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
    results.scada,
  ].filter((result) => result?.status === "rejected").length;
  const timeseriesFailures = (results.timeseries || []).filter(
    (result) => result.status === "rejected",
  ).length;

  return coreFailures + timeseriesFailures;
}

function renderSummary(summary) {
  renderDataAvailability(summary.context?.data_available_through);
  renderCompleteness(summary.context?.completeness);
  renderSelectedPeriodScope(summary.context);
  renderAssumptionStrip(currentState(), summary.commercial_basis);
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

function paddedLocalIso(value, paddingHours) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  date.setHours(date.getHours() + paddingHours);

  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-") + `T${[
    String(date.getHours()).padStart(2, "0"),
    String(date.getMinutes()).padStart(2, "0"),
    String(date.getSeconds()).padStart(2, "0"),
  ].join(":")}`;
}

function renderInspectionStrip() {
  const target = getElement("inspection-strip");
  const inspection = currentState().activeInspection;

  if (!inspection) {
    target.hidden = true;
    target.innerHTML = "";
    return;
  }

  target.hidden = false;
  target.innerHTML = `
    <strong>Inspecting ${escapeHtml(inspection.type || "anomaly event")}</strong>
    <span>${escapeHtml(inspection.start)} to ${escapeHtml(inspection.end)}</span>
    <button class="clear-inspection-button" type="button">Clear zoom</button>
  `;
  target.querySelector(".clear-inspection-button")?.addEventListener("click", () => {
    updateState({ activeInspection: null });
    renderInspectionStrip();
    renderSynchronizedTimeseries(lastTimeseriesResults, {
      timestampColumn: currentState().timestamp_col,
    });
  });
}

function inspectAnomalyEvent(event) {
  const { start, end, type } = event.detail || {};
  const zoomStart = paddedLocalIso(start, -EVENT_WINDOW_PADDING_HOURS);
  const zoomEnd = paddedLocalIso(end, EVENT_WINDOW_PADDING_HOURS);

  if (!zoomStart || !zoomEnd) return;

  updateState({
    activeInspection: { start, end, type, zoomStart, zoomEnd },
  });
  switchTab("selected-period");
  setStatus(`Inspecting ${type || "anomaly event"}`);
  renderInspectionStrip();
  renderSynchronizedTimeseries(lastTimeseriesResults, {
    timestampColumn: currentState().timestamp_col,
    inspectionWindow: currentState().activeInspection,
  });

  getElement("timeseries-plots").scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

export async function refreshDashboard() {
  const refresh = beginRefresh();

  clearError();
  setStatus("Loading");
  renderDataAvailability(null, "Loading...");
  renderScadaDataAvailability(null, "Loading...");
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
      const periodChanged = updateQuickPeriodMonths(results.monthly.value);
      if (periodChanged) {
        await refreshDashboard();
        return;
      }
      renderMonthly(results.monthly.value);
    } else {
      renderMonthlyError(
        resultMessage("Could not load monthly overview", results.monthly),
      );
    }

    renderSummary(summary);
    renderRevenueBridge(results.revenueBridge);
    renderStrikeExposure(results.strike);
    if (results.scada.status === "fulfilled") {
      lastScadaEnvelope = results.scada.value.selected_period;
      renderScadaDataAvailability(results.scada.value.data_available_through);
      renderScadaEnvelope(lastScadaEnvelope);
    } else {
      lastScadaEnvelope = null;
      renderScadaDataAvailability(null);
      renderScadaEnvelopeError(
        resultMessage("Could not load SCADA production envelope", results.scada),
      );
    }

    if (results.anomalies.status === "fulfilled") {
      renderAnomalies(results.anomalies.value);
    } else {
      renderAnomaliesError(
        resultMessage("Could not load anomaly tables", results.anomalies),
      );
    }

    lastTimeseriesResults = results.timeseries;
    renderInspectionStrip();
    renderSynchronizedTimeseries(results.timeseries, {
      timestampColumn: currentState().timestamp_col,
      inspectionWindow: currentState().activeInspection,
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
  bindZoomSyncToggle();
  document.addEventListener("inspect-anomaly-event", inspectAnomalyEvent);
  bindControlEvents({ onRefresh: refreshDashboard });

  try {
    setStatus("Loading datasets");
    const datasetPayload = await loadDatasets();
    populateDatasetOptions(datasetPayload);

    try {
      // Establish the real date bounds before the first full refresh so the
      // "Last full month" default doesn't trigger a second full data load.
      const monthly = await apiGet("/api/monthly", {});
      updateQuickPeriodMonths(monthly);
    } catch (_) {
      // Ignore; refreshDashboard() below will surface a monthly-specific
      // error and fall back to unfiltered bounds.
    }

    await refreshDashboard();
  } catch (error) {
    setStatus("Error");
    showError(error.message || String(error));
  }
}

init();
