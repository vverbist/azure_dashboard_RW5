import { urlFor } from "../api.js";
import { getElement } from "../dom.js";
import { escapeHtml, safeDomId } from "../formatters.js";
import { renderDownloads } from "./downloads.js";
import { renderEmptyState, renderTable } from "./tables.js";

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

function anomalyTableId(key, index) {
  return `anomaly-${safeDomId(key)}-${index}`;
}

function anomalyEventTableId(key, index) {
  return `anomaly-event-${safeDomId(key)}-${index}`;
}

function eventButton(row, key, label) {
  if (!row?._event_start || !row?._event_end) return "";

  return `
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
      key: "inspect",
      label: "Inspect",
      sticky: true,
      render: (row) => eventButton(row, key, label),
    },
    { key: "Start", label: "Start" },
    { key: "Duration", label: "Duration" },
    { key: "Periods", label: "Periods" },
    { key: "Impact", label: "Impact", render: impactCell },
    ...(EVENT_TYPE_COLUMNS[key] || []),
  ];
}

function bindInspectButtons(target) {
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

  if (options.kind === "events") bindInspectButtons(target);
}

export function renderAnomalies(payload) {
  const tables = payload?.tables || {};
  const eventTables = payload?.event_tables || {};
  const periodEntries = Object.entries(tables);
  const eventEntries = Object.entries(eventTables);

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
