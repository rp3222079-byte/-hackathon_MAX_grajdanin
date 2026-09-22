// Главная страница: проверка адреса и лента отключений.
import { api, ApiError, UTILITY_LABELS, formatPeriod } from "./api.js";

const form = document.querySelector("#check-form");
const verdict = document.querySelector("#verdict");
const list = document.querySelector("#timeline");
const filters = document.querySelector("#filters");

let currentFilter = "all";
let allOutages = [];

function outageElement(outage) {
  const item = document.createElement("li");
  item.className = "outage";
  item.dataset.utility = outage.utility;
  item.dataset.emergency = String(!outage.is_planned);

  const top = document.createElement("div");
  top.className = "outage-top";

  const utility = document.createElement("span");
  utility.className = "outage-utility";
  utility.textContent = UTILITY_LABELS[outage.utility] || outage.utility;

  const kind = document.createElement("span");
  kind.className = "outage-kind";
  kind.textContent = outage.is_planned ? "плановое отключение" : "аварийное отключение";

  top.append(utility, kind);

  const when = document.createElement("p");
  when.className = "outage-when";
  when.textContent = formatPeriod(outage.starts_at, outage.ends_at);

  const where = document.createElement("p");
  where.className = "outage-where";
  where.textContent = outage.raw_addresses;

  item.append(top, when, where);

  if (outage.reason) {
    const why = document.createElement("p");
    why.className = "outage-why";
    why.textContent = outage.reason;
    item.append(why);
  }
  return item;
}

function renderList(outages) {
  list.textContent = "";
  if (!outages.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.innerHTML = "<strong>Отключений нет</strong>По выбранному фильтру ничего не запланировано.";
    list.append(empty);
    return;
  }
  outages.forEach((outage) => list.append(outageElement(outage)));
}

function applyFilter() {
  if (currentFilter === "all") return renderList(allOutages);
  if (currentFilter === "water") {
    return renderList(allOutages.filter((item) => item.utility.startsWith("water")));
  }
  return renderList(allOutages.filter((item) => item.utility === currentFilter));
}

async function loadOutages() {
  try {
    allOutages = await api("/api/outages?active_only=true&limit=200");
    applyFilter();
  } catch (error) {
    list.textContent = "";
    const failure = document.createElement("li");
    failure.className = "empty";
    failure.innerHTML =
      "<strong>Список не загрузился</strong>Проверьте, запущен ли сервер: uvicorn app.main:app";
    list.append(failure);
    console.error(error);
  }
}

function showVerdict(state, title, text) {
  verdict.hidden = false;
  verdict.dataset.state = state;
  verdict.classList.remove("reveal");
  void verdict.offsetWidth; // перезапускает анимацию
  verdict.classList.add("reveal");
  verdict.querySelector("h2").textContent = title;
  verdict.querySelector("p").textContent = text;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const street = form.street.value.trim();
  const house = form.house.value.trim();
  if (!street || !house) return;

  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;

  try {
    const params = new URLSearchParams({ street, house });
    const found = await api(`/api/outages/check?${params}`);

    if (!found.length) {
      showVerdict("clear", "Отключений по этому адресу нет", `${street}, д. ${house}`);
    } else {
      const names = found.map((item) => UTILITY_LABELS[item.utility] || item.utility);
      showVerdict(
        "hit",
        `Запланировано отключений: ${found.length}`,
        `${street}, д. ${house} — ${[...new Set(names)].join(", ")}. Подробности в списке ниже.`,
      );
      allOutages = found;
      currentFilter = "all";
      filters.querySelectorAll(".chip").forEach((chip) => {
        chip.setAttribute("aria-pressed", String(chip.dataset.filter === "all"));
      });
      applyFilter();
    }
  } catch (error) {
    const message =
      error instanceof ApiError && error.status === 422
        ? "Не разобрали адрес. Напишите улицу и дом так, как в квитанции."
        : "Сервер не ответил. Попробуйте ещё раз.";
    showVerdict("error", "Проверка не прошла", message);
    console.error(error);
  } finally {
    submit.disabled = false;
  }
});

filters.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  currentFilter = chip.dataset.filter;
  filters.querySelectorAll(".chip").forEach((item) => {
    item.setAttribute("aria-pressed", String(item === chip));
  });
  applyFilter();
});

loadOutages();
