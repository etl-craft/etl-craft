// Administration and maintenance forms: send the filled fields as the same JSON the CLI sends and
// show the outcome; a created token is shown once. Empty fields are left out, so "change" keeps
// values. A button may preview (`data-dry-run`, or `data-method="get"` for a read), ask for
// confirmation first (`data-confirm`), and a form may show the returned document (`data-show-result`).
const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
const result = document.querySelector("#admin-result");

// A name such as `key.id` fills a nested object; checkboxes send booleans and `data-list`
// fields send their comma-separated entries.
function value(field) {
  if (field.type === "checkbox") return field.checked;
  if (field.type === "number") return Number(field.value);
  if (field.type === "datetime-local") return new Date(field.value).toISOString();
  if ("list" in field.dataset) return field.value.split(",").map((part) => part.trim()).filter(Boolean);
  return field.value;
}

function body(form) {
  const values = {};
  for (const field of form.querySelectorAll("input, select, textarea")) {
    if (!field.name || (field.type !== "checkbox" && field.value === "")) continue;
    const [outer, inner] = field.name.split(".");
    if (inner === undefined) values[outer] = value(field);
    else (values[outer] ??= {})[inner] = value(field);
  }
  return values;
}

function erasureResult(notice, returned) {
  if (returned.tables.length) {
    const scroll = document.createElement("div");
    scroll.className = "scroll";
    const table = document.createElement("table");
    table.className = "list";
    const head = table.createTHead().insertRow();
    for (const label of ["Table", "Identifier columns", returned.dry_run ? "Matching rows" : "Deleted rows"]) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      head.append(cell);
    }
    const body = table.createTBody();
    for (const found of returned.tables) {
      const row = body.insertRow();
      for (const value of [found.table, found.column, found.rows]) {
        const cell = row.insertCell();
        cell.className = "wrap";
        cell.textContent = String(value);
      }
    }
    scroll.append(table);
    notice.append(scroll);
  }
  for (const found of returned.unfollowed) {
    const boundary = document.createElement("p");
    boundary.textContent = `${found.table}: ${found.reason} ${found.remedy}`;
    notice.append(boundary);
  }
}

function show(kind, text, token, returned, changed = true) {
  const notice = document.createElement("section");
  notice.className = `notice ${kind}`;
  notice.setAttribute("role", kind === "error" ? "alert" : "status");
  const message = document.createElement("p");
  message.textContent = text;
  notice.append(message);
  if (token) {
    const value = document.createElement("code");
    value.id = "created-token";
    value.textContent = token;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.dataset.copy = "created-token";
    copy.textContent = "Copy token";
    notice.append(value, copy);
  }
  if (returned?.schema === "etl-craft/erasure/1") {
    erasureResult(notice, returned);
  } else if (returned !== undefined) {
    const detail = document.createElement("pre");
    detail.className = "result-document";
    detail.textContent = JSON.stringify(returned, null, 2);
    notice.append(detail);
  }
  if (changed && kind !== "error") {
    const reload = document.createElement("a");
    reload.href = location.pathname + location.search;
    reload.textContent = "Reload to see the change";
    notice.append(reload);
  }
  result.replaceChildren(notice);
  notice.scrollIntoView({ block: "nearest" });
}

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-api-form]");
  if (!form) return;
  event.preventDefault();
  const button = event.submitter || {};
  const url = button.dataset?.url || form.dataset.url;
  const erasure = "erasure" in form.dataset;
  const confirmation = erasure
    ? `${button.dataset?.confirm} ${form.elements.table.value}.${form.elements.column.value}?`
    : button.dataset?.confirm;
  if (button.dataset?.confirm && !window.confirm(confirmation)) return;
  const values = body(form);
  if (button.dataset && "dryRun" in button.dataset) values.dry_run = true;
  if (erasure && values.dry_run) delete form.dataset.previewed;
  if (button.dataset && "erasureLift" in button.dataset) values.lift = true;
  const read = button.dataset?.method === "get";
  const buttons = [...form.querySelectorAll("button:not([disabled])")];
  buttons.forEach((each) => { each.disabled = true; });
  try {
    const response = read
      ? await fetch(`${url}?${new URLSearchParams(values)}`, { headers: { Accept: "application/json" } })
      : await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify(values),
      });
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) {
      show("error", answer.detail || answer.message || `Request refused (HTTP ${response.status}).`);
      return;
    }
    const shown = "showResult" in form.dataset ? answer : undefined;
    const text = read ? "Read only: nothing changed." : values.dry_run ? "Preview only: nothing changed." : "Request recorded.";
    show("done", text, answer.token, shown, !read && !values.dry_run);
    if (erasure && values.dry_run) form.dataset.previewed = "yes";
    if (!answer.token && !read && !values.dry_run) {
      form.reset();
      delete form.dataset.previewed;
    }
  } finally {
    buttons.forEach((each) => { each.disabled = false; });
    if (erasure) form.querySelector("[data-erasure-apply]").disabled = !form.dataset.previewed;
  }
});


document.addEventListener("input", (event) => {
  const form = event.target.closest("[data-erasure]");
  if (!form) return;
  delete form.dataset.previewed;
  form.querySelector("[data-erasure-apply]").disabled = true;
});
