import { urlFor } from "../api.js";
import { getElement } from "../dom.js";
import { escapeHtml, safeDomId } from "../formatters.js";
import { renderDownloads } from "./downloads.js";
import { renderEmptyState, renderTable } from "./tables.js";

function anomalyTableId(key, index) {
  return `anomaly-${safeDomId(key)}-${index}`;
}

function anomalyEventTableId(key, index) {
  return `anomaly-event-${safeDomId(key)}-${index}`;
}

function renderTableGroup(targetId, entries, tableIdFor, emptyMessage) {
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
    renderTable(tableIdFor(key, index), table.rows || []);
  });
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
