export function parseNumberInput(value, fallback = "", options = {}) {
  const raw = String(value ?? "").trim();

  if (raw === "") return "";

  const parsed = options.integer ? Number.parseInt(raw, 10) : Number(raw);

  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return parsed;
}
