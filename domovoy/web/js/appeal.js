// Страница обращения в управляющую компанию.
import { api, ApiError } from "./api.js";

const form = document.querySelector("#appeal-form");
const notice = document.querySelector("#notice");
const companyHint = document.querySelector("#company-hint");

function showNotice(state, text) {
  notice.hidden = false;
  notice.dataset.state = state;
  notice.textContent = text;
  notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function lookupCompany() {
  const street = form.street.value.trim();
  const house = form.house.value.trim();
  if (!street || !house) {
    companyHint.textContent = "";
    return;
  }
  try {
    const params = new URLSearchParams({ street, house });
    const company = await api(`/api/companies/by-address?${params}`);
    companyHint.textContent = `Обращение уйдёт в ${company.name} (${company.email}).`;
  } catch (error) {
    companyHint.textContent =
      error instanceof ApiError && error.status === 404
        ? "Для этого дома управляющая компания не найдена. Проверьте адрес."
        : "";
  }
}

async function uploadPhoto(file) {
  const data = new FormData();
  data.append("file", file);
  const response = await fetch("/api/appeals/photo", { method: "POST", body: data });
  if (!response.ok) throw new ApiError(response.status, "Фото не загрузилось");
  const result = await response.json();
  return result.photo_path;
}

form.street.addEventListener("blur", lookupCompany);
form.house.addEventListener("blur", lookupCompany);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  notice.hidden = true;

  try {
    let photoPath = null;
    const file = form.photo.files[0];
    if (file) {
      try {
        photoPath = await uploadPhoto(file);
      } catch (error) {
        console.error(error);
        showNotice("error", "Фото не загрузилось, отправляем обращение без него.");
      }
    }

    const appeal = await api("/api/appeals", {
      method: "POST",
      body: JSON.stringify({
        category: form.category.value,
        message: form.message.value.trim(),
        city: form.city.value.trim(),
        street: form.street.value.trim(),
        house: form.house.value.trim(),
        flat: form.flat.value.trim() || null,
        contact: form.contact.value.trim() || null,
        photo_path: photoPath,
        source: "web",
      }),
    });

    if (appeal.status === "failed") {
      showNotice(
        "error",
        `Обращение ${appeal.number} сохранено, но управляющая компания для адреса не найдена. Проверьте адрес или напишите нам.`,
      );
    } else {
      const company = appeal.company ? appeal.company.name : "управляющую компанию";
      showNotice("ok", `Обращение ${appeal.number} отправлено в ${company}. Сохраните номер.`);
      form.reset();
      companyHint.textContent = "";
    }
  } catch (error) {
    const message =
      error instanceof ApiError && error.status === 422
        ? "Проверьте поля: нужны улица, дом и текст обращения."
        : "Не получилось отправить. Попробуйте ещё раз через минуту.";
    showNotice("error", message);
    console.error(error);
  } finally {
    submit.disabled = false;
  }
});
