import { chartLayout, getPlotly, showChartEmpty } from "../charts/layout.js";
import { renderDownloads } from "./downloads.js";
import { renderTable, renderTableError } from "./tables.js";
import { getElement } from "../dom.js";

export function renderMonthly(monthly) {
  renderTable("monthly-table", monthly?.monthly_kpi_table || []);
  renderMonthlyCharts(monthly);
  renderDownloads("monthly-downloads", [
    { label: "KPI overview", path: "/api/downloads/monthly-kpi-overview" },
    { label: "Numeric export", path: "/api/downloads/monthly-numeric" },
  ]);
}

export function renderMonthlyCharts(monthly) {
  const rows = monthly?.chart_data?.rows || [];
  const preferred = [
    "Total revenue EUR",
    "Delivered volume MWh",
    "Capture price EUR/MWh",
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

    plotly.react(
      target,
      [
        {
          type: "bar",
          name: metric,
          x: rows.map((row) => row.Month),
          y: rows.map((row) => row[metric]),
          marker: { color: index === 2 ? "#95C800" : "#1673E6" },
        },
      ],
      chartLayout(
        metric.replace(" EUR", "").replace(" MWh", ""),
        metric.includes("EUR/MWh")
          ? "EUR/MWh"
          : metric.includes("EUR")
            ? "EUR"
            : "MWh",
      ),
    );
  });
}

export function renderMonthlyError(message) {
  renderTableError("monthly-table", message);
  renderDownloads("monthly-downloads", []);
  [1, 2, 3].forEach((index) => {
    showChartEmpty(`monthly-chart-${index}`, message);
  });
}
