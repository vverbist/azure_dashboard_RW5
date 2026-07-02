import { urlFor } from "../api.js";
import { getElement } from "../dom.js";
import { escapeHtml, safeDomId } from "../formatters.js";
import { renderDownloads } from "./downloads.js";
import { renderEmptyState, renderTable } from "./tables.js";

function anomalyTableId(key, index) {
  return `anomaly-${safeDomId(key)}-${index}`;
}

export function renderAnomalies(payload) {
  const tables = payload?.tables || {};
  const entries = Object.entries(tables);
  const target = getElement("anomaly-tables");

  if (!entries.length) {
    renderEmptyState(target, "No anomaly tables available.");
    renderDownloads("anomaly-downloads", []);
    return;
  }

  target.innerHTML = entries
    .map(([key, table], index) => {
      const tableId = anomalyTableId(key, index);

      return `
      <section class="content-section">
        <div class="section-header">
          <h3>${escapeHtml(table.label || key)}</h3>
          <a class="download-link" href="${escapeHtml(urlFor(`/api/downloads/anomalies/${key}`).toString())}">Download</a>
        </div>
        <p>${escapeHtml(table.description || "")}</p>
        <div id="${escapeHtml(tableId)}"></div>
      </section>
    `;
    })
    .join("");

  entries.forEach(([key, table], index) => {
    renderTable(anomalyTableId(key, index), table.rows || []);
  });

  renderDownloads("anomaly-downloads", [
    { label: "All anomaly tables", path: "/api/downloads/anomalies/all" },
  ]);
}

export function renderAnomaliesError(message) {
  renderEmptyState("anomaly-tables", message);
  renderDownloads("anomaly-downloads", []);
}
