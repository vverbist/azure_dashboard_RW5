import { chartLayout, getPlotly, showChartEmpty } from "../charts/layout.js";
import { renderDownloads } from "./downloads.js";
import { renderTable, renderTableError } from "./tables.js";
import { getElement } from "../dom.js";
import { renderScadaMonthly, renderScadaMonthlyError } from "./scada.js";

const MONTHLY_GROUP_STARTS = new Set([
  "Delivered volume",
  "Greenchoice benchmark",
  "EPEX-only revenue",
  "Imbalance revenue",
  "Below-strike revenue",
  
]);

function monthlyRowClass(row) {
  const kpi = row?.KPI || "";
  const classes = ["monthly-kpi-row"];

  if (MONTHLY_GROUP_STARTS.has(kpi)) classes.push("monthly-group-start");
  if (kpi.includes("capture price")) classes.push("monthly-derived-row");

  return classes.join(" ");
}

function renderPartialNote(partialInfos, hasProjection) {
  const note = getElement("monthly-partial-note");

  if (!partialInfos.length) {
    note.hidden = true;
    note.textContent = "";
    return;
  }

  const parts = partialInfos.map(
    (info) =>
      `${info.label} covers ${info.days_covered} of ${info.days_in_month} days (through ${info.coverage_through})`,
  );
  const projectionNote = hasProjection
    ? " Charts show a projected full-month estimate (dotted, linear run-rate) for revenue and volume."
    : "";
  note.hidden = false;
  note.textContent = `Partial month — ${parts.join(
    "; ",
  )}. Not directly comparable with completed months.${projectionNote}`;
}

export function renderMonthly(monthly) {
  const coverage = monthly?.month_coverage || {};
  const partialLabels = new Set();
  const partialMonths = new Set();
  const partialInfos = [];
  Object.entries(coverage).forEach(([monthKey, info]) => {
    if (info?.is_partial) {
      partialLabels.add(info.label);
      partialMonths.add(monthKey);
      partialInfos.push(info);
    }
  });

  const rows = monthly?.monthly_kpi_table || [];
  const options = {
    tableClass: "monthly-kpi-table",
    rowClassName: monthlyRowClass,
  };
  if (rows.length && partialLabels.size) {
    options.columns = Object.keys(rows[0]).map((key) => ({
      key,
      label: partialLabels.has(key) ? `${key} (partial)` : key,
    }));
  }

  const projection = monthly?.projection || {};
  renderTable("monthly-table", rows, options);
  renderPartialNote(partialInfos, Object.keys(projection).length > 0);
  renderMonthlyCharts(monthly, partialMonths, projection);
  renderScadaMonthly(monthly?.scada);
  renderDownloads("monthly-downloads", [
    { label: "KPI overview", path: "/api/downloads/monthly-kpi-overview" },
    { label: "Numeric export", path: "/api/downloads/monthly-numeric" },
  ]);
}

export function renderMonthlyCharts(monthly, partialMonths = new Set(), projection = {}) {
  const rows = monthly?.chart_data?.rows || [];
  const preferred = [
    "Total revenue EUR",
    "Delivered volume MWh",
    "Total capture price EUR/MWh",
  ];
  const metrics = preferred.filter((metric) =>
    monthly?.chart_data?.metrics?.includes(metric),
  );
  const fallback = monthly?.chart_data?.metrics || [];
  const selected = [
    ...metrics,
    ...fallback.filter((metric) => !metrics.includes(metric)),
  ].slice(0, 3);

  [1, 2, 3].forEach((index) => {
    const metric = selected[index - 1];
    const target = getElement(`monthly-chart-${index}`);

    if (!metric) {
      showChartEmpty(target, "No monthly chart data available.");
      return;
    }

    const plotly = getPlotly(target);
    if (!plotly) return;

    const baseColor = index === 2 ? "#95C800" : "#1673E6";
    const partialColor = index === 2 ? "#cfe08a" : "#a7c7f2";
    const isPartial = (row) => partialMonths.has(row.Month);
    const xs = rows.map((row) => row.Month);

    const actualTrace = {
      type: "bar",
      name: metric,
      x: xs,
      y: rows.map((row) => row[metric]),
      marker: {
        color: rows.map((row) => (isPartial(row) ? partialColor : baseColor)),
        pattern: { shape: rows.map((row) => (isPartial(row) ? "/" : "")) },
      },
    };

    // Projected remainder (partial month, additive metrics only): actual * (factor - 1).
    const remainderY = rows.map((row) => {
      const proj = projection[row.Month];
      const actual = Number(row[metric]);
      if (proj && proj.metrics.includes(metric) && Number.isFinite(actual)) {
        return actual * (proj.factor - 1);
      }
      return null;
    });
    const hasProjection = remainderY.some((value) => value != null && value !== 0);

    const traces = [actualTrace];
    if (hasProjection) {
      traces.push({
        type: "bar",
        name: "Projected (run-rate)",
        x: xs,
        y: remainderY,
        marker: {
          color: "rgba(120,130,145,0.32)",
          pattern: { shape: remainderY.map((value) => (value != null ? "." : "")) },
        },
        hovertemplate: "Projected remainder: %{y:,.0f}<extra></extra>",
      });
    }

    const unit = metric.includes("EUR/MWh")
      ? "EUR/MWh"
      : metric.includes("EUR")
        ? "EUR"
        : "MWh";

    plotly.react(target, traces, {
      ...chartLayout(metric.replace(" EUR", "").replace(" MWh", ""), unit),
      barmode: "stack",
      showlegend: hasProjection,
    });
  });
}

export function renderMonthlyError(message) {
  renderTableError("monthly-table", message);
  renderDownloads("monthly-downloads", []);
  [1, 2, 3].forEach((index) => {
    showChartEmpty(`monthly-chart-${index}`, message);
  });
  renderScadaMonthlyError(message);
}
