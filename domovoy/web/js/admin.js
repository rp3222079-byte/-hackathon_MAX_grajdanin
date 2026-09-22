// Панель управляющей компании: список обращений и смена статусов.
import { api, ApiError, STATUS_LABELS, formatDateTime } from "./api.js";

const loginForm = document.querySelector("#login-form");
const panel = document.querySelector("#panel");
const tbody = document.querySelector("#appeals-body");
const statusFilter = document.querySelector("#status-filter");
const loginNotice = document.querySelector("#login-notice");

let adminToken = sessionStorage.getItem("domovoy_admin_token") || "";

function authHeaders() {
  return { "X-Admin-Token": adminToken };
}

function statusCell(appeal) {
  const cell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "status";
  badge.dataset.status = appeal.status;
  badge.textContent = STATUS_LABELS[appeal.status] || appeal.status;
  cell.append(badge);
  return cell;
}

function actionCell(appeal) {
  const cell = document.createElement("td");
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Статус обращения ${appeal.number}`);

  ["new", "sent", "in_progress", "resolved"].forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = STATUS_LABELS[value];
    option.selected = appeal.status === value;
    select.append(option);
  });

  select.addEventListener("change", async () => {
    try {
      await api(`/api/appeals/${appeal.id}/status`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify({ status: select.value }),
      });
      await loadAppeals();
    } catch (error) {
      console.error(error);
      alert("Статус не сохранился. Проверьте токен и попробуйте ещё раз.");
    }
  });

  cell.append(select);
  return cell;
}

function row(appeal) {
  const tr = document.createElement("tr");

  const number = document.createElement("td");
  number.textContent = appeal.number;

  const created = document.createElement("td");
  created.textContent = formatDateTime(appeal.created_at);

  const address = document.createElement("td");
  address.textContent = appeal.address_text;

  const category = document.createElement("td");
  category.textContent = appeal.category;

  const message = document.createElement("td");
  message.textContent = appeal.message;

  const company = document.createElement("td");
  company.textContent = appeal.company ? appeal.company.name : "не определена";

  tr.append(number, created, address, category, message, company, statusCell(appeal), actionCell(appeal));
  return tr;
}

async function loadAppeals() {
  const query = statusFilter.value ? `?status_filter=${statusFilter.value}` : "";
  const appeals = await api(`/api/appeals${query}`, { headers: authHeaders() });

  tbody.textContent = "";
  if (!appeals.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.textContent = "Обращений пока нет.";
    tr.append(td);
    tbody.append(tr);
    return;
  }
  appeals.forEach((appeal) => tbody.append(row(appeal)));
}

async function signIn(token) {
  adminToken = token;
  try {
    await loadAppeals();
    sessionStorage.setItem("domovoy_admin_token", token);
    loginForm.hidden = true;
    panel.hidden = false;
  } catch (error) {
    adminToken = "";
    sessionStorage.removeItem("domovoy_admin_token");
    loginNotice.hidden = false;
    loginNotice.dataset.state = "error";
    loginNotice.textContent =
      error instanceof ApiError && error.status === 401
        ? "Токен не подошёл. Это значение ADMIN_TOKEN из файла .env."
        : "Сервер не ответил. Проверьте, запущен ли uvicorn.";
  }
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  signIn(loginForm.token.value.trim());
});

statusFilter.addEventListener("change", () => {
  loadAppeals().catch((error) => console.error(error));
});

if (adminToken) signIn(adminToken);
