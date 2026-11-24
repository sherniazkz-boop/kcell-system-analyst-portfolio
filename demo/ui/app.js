const applicationsPath = "/api/applications";
const sampleId = "00000000-0000-4000-8000-000000000001";
const statusLabels = {
  RECEIVED: "Принята",
  IN_REVIEW: "На рассмотрении",
  CONNECTED: "Подключена",
};
const serviceLabels = Object.fromEntries(
  Array.from(document.querySelectorAll("#service-type option[value]:not([value=''])"))
    .map((option) => [option.value, option.textContent]),
);

const createForm = document.querySelector("#create-form");
const lookupForm = document.querySelector("#lookup-form");
const idField = document.querySelector("#application-id");
const createResult = document.querySelector("#create-result");
const lookupResult = document.querySelector("#lookup-result");
const fields = {
  applicant_alias: [document.querySelector("#applicant-alias"), document.querySelector("#alias-error")],
  service_type: [document.querySelector("#service-type"), document.querySelector("#service-error")],
};

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error.message);
    error.fields = data.error.fields;
    throw error;
  }
  return data;
}

function showError(target, message) {
  target.dataset.kind = "error";
  target.textContent = message;
  target.hidden = false;
}

function showApplication(target, application, title) {
  const heading = document.createElement("strong");
  heading.textContent = title;
  const number = document.createElement("code");
  number.textContent = application.id;
  const details = document.createElement("p");
  details.textContent = `${serviceLabels[application.service_type]} · ${statusLabels[application.status]}`;
  target.replaceChildren(heading, number, details);
  target.dataset.kind = "success";
  target.hidden = false;
}

function setFieldError(name, message) {
  const [field, feedback] = fields[name];
  feedback.textContent = message;
  feedback.hidden = !message;
  if (message) {
    field.setAttribute("aria-invalid", "true");
  } else {
    field.removeAttribute("aria-invalid");
  }
}

for (const [name, [field]] of Object.entries(fields)) {
  field.addEventListener("input", () => setFieldError(name, ""));
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = createForm.querySelector("button[type='submit']");
  button.disabled = true;
  createResult.hidden = true;
  for (const name of Object.keys(fields)) {
    setFieldError(name, "");
  }
  try {
    const application = await request(applicationsPath, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(createForm))),
    });
    idField.value = application.id;
    lookupResult.hidden = true;
    createForm.reset();
    showApplication(createResult, application, "Заявка создана");
  } catch (error) {
    if (error.fields) {
      for (const [name, message] of Object.entries(error.fields)) {
        setFieldError(name, message);
      }
      fields[Object.keys(error.fields)[0]][0].focus();
    }
    showError(createResult, error instanceof TypeError ? "Сервер недоступен. Повторите попытку." : error.message);
  } finally {
    button.disabled = false;
  }
});

idField.addEventListener("input", () => {
  lookupResult.hidden = true;
});

document.querySelector("#sample-button").addEventListener("click", () => {
  idField.value = sampleId;
  lookupResult.hidden = true;
  idField.focus();
});

lookupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = idField.value.trim();
  if (!id) {
    showError(lookupResult, "Введите номер заявки.");
    idField.focus();
    return;
  }
  const button = lookupForm.querySelector("button[type='submit']");
  button.disabled = true;
  lookupResult.hidden = true;
  try {
    const application = await request(`${applicationsPath}/${encodeURIComponent(id)}`);
    if (idField.value.trim() === id) {
      showApplication(lookupResult, application, "Текущий статус");
    }
  } catch (error) {
    if (idField.value.trim() === id) {
      showError(lookupResult, error instanceof TypeError ? "Сервер недоступен. Повторите попытку." : error.message);
    }
  } finally {
    button.disabled = false;
  }
});
