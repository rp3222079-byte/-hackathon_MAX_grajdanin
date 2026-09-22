// Общий слой доступа к REST API и форматирование.
const API_BASE = window.DOMOVOY_API_BASE || "";

export const UTILITY_LABELS = {
  water_cold: "Холодная вода",
  water_hot: "Горячая вода",
  electricity: "Электричество",
  heating: "Отопление",
  gas: "Газ",
};

export const STATUS_LABELS = {
  new: "создано",
  sent: "отправлено в УК",
  in_progress: "в работе",
  resolved: "решено",
  failed: "не отправлено",
};

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Ошибка ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  if (!response.ok) {
    let detail = "";
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function formatDateTime(value) {
  if (!value) return "время не указано";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "время не указано";
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getDate()} ${MONTHS[date.getMonth()]}, ${hours}:${minutes}`;
}

export function formatPeriod(startsAt, endsAt) {
  const start = formatDateTime(startsAt);
  if (!endsAt) return `С ${start}, срок не объявлен`;
  return `С ${start} до ${formatDateTime(endsAt)}`;
}
