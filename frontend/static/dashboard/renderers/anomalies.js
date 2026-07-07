import { apiGet, urlFor } from "../api.js";
import { getElement } from "../dom.js";
import { escapeHtml, safeDomId } from "../formatters.js";
import { showChartEmpty } from "../charts/layout.js";
import { renderEventDetailChart } from "../charts/eventDetailChart.js";
import { renderDownloads } from "./downloads.js";
import { renderEmptyState, renderTable, renderTableError } from "./tables.js";

const SEVERITY_BAR_WIDTH = {
  Critical: 100,
  High: 66,
  Medium: 33,
  Review: 15,
};

// Only the parameters that actually matter for each event type - e.g. imbalance
// prices for imbalance events, not EPEX prices, and vice versa.
const EVENT_TYPE_COLUMNS = {
  "negative-imbalance-revenue-events": [
    { key: "Net imbalance", label: "Net imbalance" },
    { key: "Imbalance price", label: "Imbalance price" },
  ],
  "positive-imbalance-revenue-events": [
    { key: "Net imbalance", label: "Net imbalance" },
    { key: "Imbalance price", label: "Imbalance price" },
  ],
  "negative-epex-revenue-events": [
    { key: "Nominated volume", label: "Nominated volume" },
    { key: "Avg EPEX price", label: "Avg EPEX price" },
  ],
};

// Row objects keyed by "<eventKey>-<eventStart>" so the Details panel can read
// the already-fetched summary fields (Impact, explanation, ...) without a
// second round trip - only the raw 15-min rows are fetched on demand.
const eventRowRegistry = new Map();

function anomalyTableId(key, index) {
  return `anomaly-${safeDomId(key)}-${index}`;
}

function anomalyEventTableId(key, index) {
  return `anomaly-event-${safeDomId(key)}-${index}`;
}

function eventActions(row, key, label) {
  if (!row?._event_start || !row?._event_end) return "";

  const rowId = `${key}-${row._event_start}`;
  eventRowRegistry.set(rowId, { row, key });

  return `
    <div class="event-actions">
      <button
        class="inspect-event-button"
        type="button"
        data-event-key="${escapeHtml(key)}"
        data-event-start="${escapeHtml(row._event_start)}"
        data-event-end="${escapeHtml(row._event_end)}"
        data-event-type="${escapeHtml(row["Event type"] || label || key)}"
      >
        Inspect &rarr;
      </button>
      <button class="details-event-button" type="button" data-row-id="${escapeHtml(rowId)}">
        Details
      </button>
    </div>
  `;
}

function impactCell(row) {
  const value = row._impact_value;
  const severity = row.Severity || "Review";
  const width = SEVERITY_BAR_WIDTH[severity] ?? 15;
  const direction =
    typeof value === "number"
      ? value < 0
        ? "impact-negative"
        : "impact-positive"
      : "impact-neutral";

  return `
    <div class="impact-cell ${direction}">
      <span class="impact-value">${escapeHtml(row["Impact"] ?? "-")}</span>
      <span class="impact-bar" style="width:${width}%"></span>
    </div>
  `;
}

function eventTableColumns(key, label) {
  return [
    {
      key: "actions",
      label: "Actions",
      sticky: true,
      render: (row) => eventActions(row, key, label),
    },
    { key: "Start", label: "Start" },
    { key: "Duration", label: "Duration" },
    { key: "Periods", label: "Periods" },
    { key: "Impact", label: "Impact", render: impactCell },
    ...(EVENT_TYPE_COLUMNS[key] || []),
  ];
}

function kpiChip(label, value) {
  if (value === undefined || value === null || value === "") return "";
  return `
    <div class="assumption-chip">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `;
}

async function toggleEventDetail(button) {
  const row = button.closest("tr");
  const next = row.nextElementSibling;

  if (next && next.classList.contains("event-detail-row")) {
    next.remove();
    button.textContent = "Details";
    return;
  }

  const entry = eventRowRegistry.get(button.dataset.rowId);
  if (!entry) return;

  const { row: eventRow, key } = entry;
  const columnCount = row.closest("table").querySelectorAll("thead th").length;
  const panelId = `event-detail-${safeDomId(button.dataset.rowId)}`;
  const chartId = `${panelId}-chart`;
  const tableId = `${panelId}-rows`;

  row.insertAdjacentHTML(
    "afterend",
    `
      <tr class="event-detail-row">
        <td colspan="${columnCount}">
          <div class="event-detail-panel">
            <div class="event-detail-kpis">
              ${kpiChip("Impact", eventRow["Impact"])}
              ${kpiChip("Duration", eventRow["Duration"])}
              ${kpiChip("Periods", eventRow["Periods"])}
              ${(EVENT_TYPE_COLUMNS[key] || [])
                .map((col) => kpiChip(col.label, eventRow[col.key]))
                .join("")}
            </div>
            <p class="event-detail-explanation">${escapeHtml(eventRow["What happened?"] || "")}</p>
            <p class="event-detail-suggestion"><strong>Suggested check:</strong> ${escapeHtml(eventRow["Suggested check"] || "")}</p>
            <div class="event-detail-chart" id="${chartId}"></div>
            <div id="${tableId}"></div>
          </div>
        </td>
      </tr>
    `,
  );
  button.textContent = "Hide";

  try {
    const data = await apiGet("/api/anomalies/event-rows", {
      start: eventRow._event_start,
      end: eventRow._event_end,
    });
    renderEventDetailChart(chartId, key, data.rows || []);
    renderTable(tableId, data.rows || []);
  } catch (error) {
    showChartEmpty(chartId, "Could not load the 15-minute rows for this event.");
    renderTableError(tableId, error.message || String(error));
  }
}

function bindEventActions(target) {
  target.querySelectorAll(".inspect-event-button").forEach((button) => {
    button.addEventListener("click", () => {
      target.dispatchEvent(
        new CustomEvent("inspect-anomaly-event", {
          bubbles: true,
          detail: {
            key: button.dataset.eventKey,
            start: button.dataset.eventStart,
            end: button.dataset.eventEnd,
            type: button.dataset.eventType,
          },
        }),
      );
    });
  });

  target.querySelectorAll(".details-event-button").forEach((button) => {
    button.addEventListener("click", () => toggleEventDetail(button));
  });
}

function renderTableGroup(targetId, entries, tableIdFor, emptyMessage, options = {}) {
  const target = getElement(targetId);

  if (!entries.length) {
    renderEmptyState(target, emptyMessage);
    return;
  }

  target.innerHTML = entries
    .map(([key, table], index) => {
      const tableId = tableIdFor(key, index);

      return `
      <section class="content-section anomaly-section">
        <div class="section-header">
          <h3>${escapeHtml(table.label || key)}</h3>
          ${targetId === "anomaly-tables" ? `<a class="download-link" href="${escapeHtml(urlFor(`/api/downloads/anomalies/${key}`).toString())}">Download</a>` : ""}
        </div>
        <p class="table-description">${escapeHtml(table.description || "")}</p>
        <div id="${escapeHtml(tableId)}"></div>
      </section>
    `;
    })
    .join("");

  entries.forEach(([key, table], index) => {
    const isEventTable = options.kind === "events";
    renderTable(tableIdFor(key, index), table.rows || [], {
      columns: isEventTable
        ? eventTableColumns(key, table.label || key)
        : undefined,
    });
  });

  if (options.kind === "events") bindEventActions(target);
}

export function renderAnomalies(payload) {
  const tables = payload?.tables || {};
  const eventTables = payload?.event_tables || {};
  const periodEntries = Object.entries(tables);
  const eventEntries = Object.entries(eventTables);

  eventRowRegistry.clear();

  if (!periodEntries.length && !eventEntries.length) {
    renderEmptyState("anomaly-event-tables", "No anomaly events available.");
    renderEmptyState("anomaly-tables", "No anomaly tables available.");
    renderDownloads("anomaly-downloads", []);
    return;
  }

  renderTableGroup(
    "anomaly-event-tables",
    eventEntries,
    anomalyEventTableId,
    "No anomaly events available for the selected period.",
    { kind: "events" },
  );
  renderTableGroup(
    "anomaly-tables",
    periodEntries,
    anomalyTableId,
    "No period-level anomaly rows available.",
  );

  renderDownloads("anomaly-downloads", [
    { label: "All anomaly tables", path: "/api/downloads/anomalies/all" },
  ]);
}

export function renderAnomaliesError(message) {
  renderEmptyState("anomaly-event-tables", message);
  renderEmptyState("anomaly-tables", message);
  renderDownloads("anomaly-downloads", []);
}
