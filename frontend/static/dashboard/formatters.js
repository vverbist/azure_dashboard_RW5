export function formatCell(value) {
  if (value === null || value === undefined) return "-";

  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }

  return String(value);
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function asDateInput(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function timestampLabel(column) {
  if (column === "timestamp_Ams") return "Amsterdam time";
  if (["timestamp_UTC", "timestamp_utc", "timestamp"].includes(column))
    return "UTC";
  return column;
}

export function timestampColumnToTimeZone(column) {
  if (["timestamp_UTC", "timestamp_utc", "timestamp"].includes(column)) {
    return "UTC";
  }

  return "Europe/Amsterdam";
}

export function timestampToSelectedLocalString(timestamp, timestampColumn) {
  const date = new Date(timestamp);
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: timestampColumnToTimeZone(timestampColumn),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const values = Object.fromEntries(
    parts
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );

  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second}`;
}

export function safeDomId(value) {
  const safe = String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return safe || "item";
}
