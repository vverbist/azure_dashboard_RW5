import { CONTROL_IDS, getElement } from "./dom.js";
import { escapeHtml, asDateInput, timestampLabel } from "./formatters.js";
import {
  getState,
  getStateValue,
  setStateValue,
  updateState,
} from "./state.js";
import { parseNumberInput } from "./validation.js";

const NUMERIC_CONTROLS = {
  greenchoice_afslag_percentage: {},
  greenchoice_afslag_floor: {},
  gvo_value: {},
  strike_price: {},
  row_count: { integer: true },
};

function readControlValue(id) {
  const element = getElement(id);

  if (NUMERIC_CONTROLS[id]) {
    return parseNumberInput(
      element.value,
      getStateValue(id),
      NUMERIC_CONTROLS[id],
    );
  }

  return element.value;
}

export function readControls() {
  const nextValues = {};

  CONTROL_IDS.forEach((id) => {
    nextValues[id] = readControlValue(id);
  });

  return updateState(nextValues);
}

export function writeControl(id, value) {
  setStateValue(id, value);

  const element = getElement(id);
  if (element) element.value = value ?? "";
}

function setDateLimits(bounds) {
  if (!bounds) return;

  ["start_date", "end_date"].forEach((id) => {
    const element = getElement(id);
    element.min = bounds.start;
    element.max = bounds.end;
  });
}

export function updateDateBounds(summary) {
  const period = summary?.context?.period || "";
  const matches = period.match(/(\d{4}-\d{2}-\d{2}).*to\s+(\d{4}-\d{2}-\d{2})/);

  if (!matches) return;

  const dataBounds = { start: matches[1], end: matches[2] };
  const state = updateState({ dataBounds });
  setDateLimits(state.fullBounds || dataBounds);
}

export function applyQuickPeriod() {
  const state = readControls();

  if (state.quick_period === "All data") {
    writeControl("start_date", "");
    writeControl("end_date", "");
    return;
  }

  if (state.quick_period === "Last full month" && state.fullBounds?.end) {
    const max = new Date(`${state.fullBounds.end}T00:00:00`);
    const firstOfCurrent = new Date(max.getFullYear(), max.getMonth(), 1);
    const lastFullEnd = new Date(
      firstOfCurrent.getTime() - 24 * 60 * 60 * 1000,
    );
    const lastFullStart = new Date(
      lastFullEnd.getFullYear(),
      lastFullEnd.getMonth(),
      1,
    );

    writeControl("start_date", asDateInput(lastFullStart));
    writeControl("end_date", asDateInput(lastFullEnd));
    return;
  }

  if (state.quick_period.startsWith("month:")) {
    const selected = state.monthPeriods.find(
      (month) => month.value === state.quick_period,
    );

    if (selected) {
      writeControl("start_date", selected.start);
      writeControl("end_date", selected.end);
    }
  }
}

export function updateQuickPeriodMonths(monthly) {
  const rows = monthly?.chart_data?.rows || [];
  const months = rows
    .map((row) => row.Month)
    .filter((month) => /^\d{4}-\d{2}$/.test(month))
    .map((month) => {
      const [year, monthNumber] = month.split("-").map(Number);
      const start = `${month}-01`;
      const endDate = new Date(year, monthNumber, 0);
      const end = asDateInput(endDate);
      const label = new Intl.DateTimeFormat("en", {
        month: "long",
        year: "numeric",
      }).format(new Date(year, monthNumber - 1, 1));

      return { value: `month:${month}`, label, start, end };
    });

  const patch = { monthPeriods: months };

  if (months.length) {
    patch.fullBounds = {
      start: months[0].start,
      end: months[months.length - 1].end,
    };
  }

  const state = updateState(patch);

  if (state.fullBounds) {
    setDateLimits(state.fullBounds);
  }

  const quickPeriod = getElement("quick_period");
  const current = quickPeriod.value;
  const fixed = [
    { value: "All data", label: "All data" },
    { value: "Last full month", label: "Last full month" },
    ...months,
    { value: "Custom range", label: "Custom range" },
  ];

  quickPeriod.innerHTML = fixed
    .map(
      (item) =>
        `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`,
    )
    .join("");
  quickPeriod.value = fixed.some((item) => item.value === current)
    ? current
    : "Last full month";
  setStateValue("quick_period", quickPeriod.value);

  const before = getState();
  if (
    quickPeriod.value === "Last full month" ||
    quickPeriod.value.startsWith("month:")
  ) {
    applyQuickPeriod();
  }
  const after = getState();
  return before.start_date !== after.start_date || before.end_date !== after.end_date;
}

export function updateTimestampOptions(options) {
  if (!options.length) return;

  const timestampControl = getElement("timestamp_col");
  const current = timestampControl.value;
  const ams = options.includes("timestamp_Ams") ? ["timestamp_Ams"] : [];
  const utc = ["timestamp_UTC", "timestamp_utc", "timestamp"].find((option) =>
    options.includes(option),
  );
  const timezoneOptions = [...ams, ...(utc ? [utc] : [])];
  const usableOptions = timezoneOptions.length ? timezoneOptions : options;

  timestampControl.innerHTML = usableOptions
    .map(
      (option) =>
        `<option value="${escapeHtml(option)}">${escapeHtml(timestampLabel(option))}</option>`,
    )
    .join("");
  timestampControl.value = usableOptions.includes(current)
    ? current
    : usableOptions[0];
  setStateValue("timestamp_col", timestampControl.value);
}

export function populateDatasetOptions(data) {
  const datasets = data.datasets || [];
  const datasetControl = getElement("dataset");

  datasetControl.innerHTML = datasets
    .map(
      (name) =>
        `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`,
    )
    .join("");
  datasetControl.value = data.default_dataset || datasets[0] || "";
  setStateValue("dataset", datasetControl.value);
}

export function setupTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      switchTab(button.dataset.tab);
    });
  });
}

export function switchTab(tabId) {
  const button = document.querySelector(`.tab-button[data-tab="${tabId}"]`);
  const panel = getElement(tabId);

  document
    .querySelectorAll(".tab-button")
    .forEach((item) => item.classList.remove("active"));
  document
    .querySelectorAll(".tab-panel")
    .forEach((item) => item.classList.remove("active"));

  if (button) button.classList.add("active");
  panel.classList.add("active");
}

export function bindControlEvents({ onRefresh }) {
  getElement("controls").addEventListener("submit", (event) => {
    event.preventDefault();
    onRefresh();
  });

  getElement("quick_period").addEventListener("change", () => {
    applyQuickPeriod();
    onRefresh();
  });

  getElement("timestamp_col").addEventListener("change", onRefresh);

  getElement("start_date").addEventListener("change", () => {
    writeControl("quick_period", "Custom range");
  });

  getElement("end_date").addEventListener("change", () => {
    writeControl("quick_period", "Custom range");
  });

  getElement("dataset").addEventListener("change", () => {
    updateState({
      dataBounds: null,
      fullBounds: null,
      monthPeriods: [],
    });
    writeControl("quick_period", "Last full month");
    writeControl("start_date", "");
    writeControl("end_date", "");
    onRefresh();
  });
}

export function bindZoomSyncToggle() {
  const syncToggle = getElement("sync-chart-zoom");
  const autoScaleToggle = getElement("autoscale-y-on-zoom");
  setStateValue("syncChartZoom", syncToggle.checked);
  setStateValue("autoScaleYOnZoom", autoScaleToggle.checked);

  syncToggle.addEventListener("change", () => {
    setStateValue("syncChartZoom", syncToggle.checked);
  });

  autoScaleToggle.addEventListener("change", () => {
    setStateValue("autoScaleYOnZoom", autoScaleToggle.checked);
  });
}

export function currentState() {
  return getState();
}
