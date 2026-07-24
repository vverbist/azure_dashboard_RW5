export const CONTROL_IDS = [
  "dataset",
  "timestamp_col",
  "quick_period",
  "start_date",
  "end_date",
  "resampling_rule",
  "greenchoice_afslag_percentage",
  "greenchoice_afslag_floor",
  "gvo_value",
  "strike_price",
  "row_count",
];

const REQUIRED_ELEMENT_IDS = [
  ...CONTROL_IDS,
  "controls",
  "status",
  "data-available-through",
  "scada-data-available-through",
  "completeness-strip",
  "user-badge",
  "error-banner",
  "selected-period-scope",
  "assumption-strip",
  "inspection-strip",
  "kpis",
  "narrative",
  "commercial-table",
  "summary-downloads",
  "monthly-table",
  "monthly-partial-note",
  "monthly-downloads",
  "monthly-chart-1",
  "monthly-chart-2",
  "monthly-chart-3",
  "scada-monthly-downloads",
  "scada-monthly-table",
  "scada-monthly-chart",
  "revenue-bridge-chart",
  "strike-chart",
  "strike-table",
  "scada-coverage-note",
  "scada-envelope-chart",
  "scada-period-table",
  "sync-chart-zoom",
  "autoscale-y-on-zoom",
  "timeseries-plots",
  "anomaly-event-tables",
  "anomaly-tables",
  "anomaly-downloads",
  "quality-table",
  "assumptions-table",
  "recognized-table",
];

const elements = {};

export function requireElement(id) {
  const element = document.getElementById(id);

  if (!element) {
    throw new Error(`Required dashboard element #${id} was not found.`);
  }

  return element;
}

export function bindElements() {
  REQUIRED_ELEMENT_IDS.forEach((id) => {
    elements[id] = requireElement(id);
  });

  return elements;
}

export function getElement(id) {
  if (!elements[id] || !document.body.contains(elements[id])) {
    elements[id] = requireElement(id);
  }

  return elements[id];
}

export function setStatus(text) {
  getElement("status").textContent = text;
}

export function showError(message) {
  const error = getElement("error-banner");
  error.textContent = message;
  error.hidden = false;
}

export function clearError() {
  getElement("error-banner").hidden = true;
}
