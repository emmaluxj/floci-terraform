const rows = document.querySelector("#contact-rows");
const emptyState = document.querySelector("#empty-state");
const dialog = document.querySelector("#contact-dialog");
const form = document.querySelector("#contact-form");
const search = document.querySelector("#search");
const formError = document.querySelector("#form-error");
const toast = document.querySelector("#toast");
let contacts = [];
let editingId = null;
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function formatDate(value) {
  if (!value) return "JUST NOW";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function render() {
  const term = search.value.trim().toLowerCase();
  const filtered = contacts.filter((contact) => [contact.name, contact.email, contact.company].join(" ").toLowerCase().includes(term));
  rows.replaceChildren();
  for (const contact of filtered) {
    const row = document.createElement("tr");
    const person = document.createElement("div");
    person.className = "person-cell";
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.textContent = initials(contact.name);
    const name = document.createElement("span");
    name.textContent = contact.name;
    person.append(avatar, name);
    const nameCell = row.insertCell();
    nameCell.append(person);
    for (const value of [contact.email, contact.company || "—", formatDate(contact.updated_at)]) {
      const cell = row.insertCell();
      cell.textContent = value;
    }
    const actionCell = row.insertCell();
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const edit = document.createElement("button");
    edit.className = "row-action";
    edit.type = "button";
    edit.textContent = "Edit";
    edit.setAttribute("aria-label", `Edit ${contact.name}`);
    edit.addEventListener("click", () => openEditor(contact));
    const remove = document.createElement("button");
    remove.className = "row-action delete";
    remove.type = "button";
    remove.textContent = "Delete";
    remove.setAttribute("aria-label", `Delete ${contact.name}`);
    remove.addEventListener("click", () => deleteContact(contact));
    actions.append(edit, remove);
    actionCell.append(actions);
    rows.append(row);
  }
  document.querySelector("#contact-count").textContent = contacts.length.toLocaleString();
  emptyState.hidden = filtered.length > 0;
  rows.closest("table").hidden = filtered.length === 0;
  if (contacts.length > 0 && filtered.length === 0) {
    emptyState.querySelector("h3").textContent = "No matches found";
    emptyState.querySelector("p").textContent = "Try a different name, email, or organization.";
    document.querySelector("#empty-add").hidden = true;
  } else {
    emptyState.querySelector("h3").textContent = "No contacts here yet";
    emptyState.querySelector("p").textContent = "Add someone to start your directory.";
    document.querySelector("#empty-add").hidden = false;
  }
}

async function loadContacts() {
  try {
    contacts = await api("/api/contacts");
    render();
  } catch (error) {
    showToast(error.message);
  }
}

function openEditor(contact = null) {
  editingId = contact?.contact_id || null;
  form.reset();
  formError.hidden = true;
  document.querySelector("#dialog-title").textContent = editingId ? "Edit contact" : "Add a contact";
  document.querySelector("#save-contact").textContent = editingId ? "Save changes" : "Save contact";
  if (contact) {
    form.elements.name.value = contact.name;
    form.elements.email.value = contact.email;
    form.elements.company.value = contact.company || "";
  }
  dialog.showModal();
  form.elements.name.focus();
}

async function deleteContact(contact) {
  if (!window.confirm(`Remove ${contact.name} from your directory?`)) return;
  try {
    await api(`/api/contacts/${encodeURIComponent(contact.contact_id)}`, { method: "DELETE" });
    showToast("Contact removed. The audit event is on its way.");
    await loadContacts();
  } catch (error) {
    showToast(error.message);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  const values = Object.fromEntries(new FormData(form));
  const saveButton = document.querySelector("#save-contact");
  saveButton.disabled = true;
  try {
    await api(editingId ? `/api/contacts/${encodeURIComponent(editingId)}` : "/api/contacts", {
      method: editingId ? "PUT" : "POST",
      body: JSON.stringify(values),
    });
    dialog.close();
    showToast(editingId ? "Contact updated." : "Contact added.");
    await loadContacts();
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
});

document.querySelector("#add-contact").addEventListener("click", () => openEditor());
document.querySelector("#empty-add").addEventListener("click", () => openEditor());
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#cancel-dialog").addEventListener("click", () => dialog.close());
search.addEventListener("input", render);
loadContacts();
