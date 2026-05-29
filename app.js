import {
  PAGE_SIZE,
  esc,
  linkify,
  fetchContacts,
  isMatch,
  filterByContactKind,
  orgKey,
  loadWorkSet,
  renderWorkCheckbox,
  bindWorkCheckboxes,
  kindLabel,
  formatContactValue,
} from "./shared.js";

let all = [];
let filtered = [];
let workSet = loadWorkSet();

let renderLimit = PAGE_SIZE;

const $ = (id) => document.getElementById(id);
const rowsEl = $("rows");
const statusEl = $("status");
const pageStatusEl = $("pageStatus");
const loadMoreBtn = $("loadMore");
const prevPageBtn = $("prevPage");
const nextPageBtn = $("nextPage");
const pageNumsEl = $("pageNums");
const qEl = $("q");
const contactFilterEl = $("contactFilter");
const orgTypeToggleEl = $("orgTypeToggle");
const orgTypePanelEl = $("orgTypePanel");
const orgTypeSearchEl = $("orgTypeSearch");
const orgTypeOptionsEl = $("orgTypeOptions");
const orgTypeSelectAllEl = $("orgTypeSelectAll");
const orgTypeClearEl = $("orgTypeClear");
const orgTypeMultiEl = $("orgTypeMulti");

/** @type {Set<string>} пустой = все типы */
let selectedOrgTypes = new Set();
let contactFilter = "all";
let allOrgTypes = [];

let pageIndex = 0;
let pagesShown = 1;

function applyFilters({ resetLimit = true } = {}) {
  const q = (qEl.value || "").trim();
  filtered = filterByContactKind(all, contactFilter)
    .filter((r) => {
      if (selectedOrgTypes.size === 0) return true;
      return selectedOrgTypes.has(r.orgType || "N/A");
    })
    .filter((r) => isMatch(r, q));

  if (resetLimit) {
    renderLimit = PAGE_SIZE;
    pageIndex = 0;
    pagesShown = 1;
  }
  render();
}

function render() {
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const curPage = Math.min(pageIndex, totalPages - 1);
  const start = curPage * PAGE_SIZE;
  const shown = Math.min(total, start + pagesShown * PAGE_SIZE);

  statusEl.textContent = `Найдено: ${total.toLocaleString("ru-RU")} — показано: ${shown.toLocaleString("ru-RU")}`;
  pageStatusEl.textContent = `Страница: ${(curPage + 1).toLocaleString("ru-RU")} / ${totalPages.toLocaleString("ru-RU")}`;

  loadMoreBtn.hidden = shown >= total;
  prevPageBtn.disabled = curPage <= 0;
  nextPageBtn.disabled = curPage >= totalPages - 1;
  rowsEl.innerHTML = "";

  const slice = filtered.slice(start, shown);
  const html = slice
    .map((r) => {
      const key = orgKey(r.org);
      const inWork = workSet.has(key);
      const valueCell = formatContactValue(r);
      const siteCell = linkify(r.site);
      return `<tr${inWork ? ' class="in-work"' : ""}>
        <td class="col-work">${renderWorkCheckbox(key, workSet)}</td>
        <td>${esc(r.org)}</td>
        <td>${esc(r.orgType || "N/A")}</td>
        <td class="col-site hide-sm">${siteCell}</td>
        <td class="col-kind"><span class="mono">${esc(kindLabel(r.kind))}</span></td>
        <td>${valueCell}</td>
      </tr>`;
    })
    .join("");
  rowsEl.innerHTML = html;
  bindWorkCheckboxes(rowsEl, workSet);

  renderPageNums(totalPages, curPage);
}

function renderPageNums(totalPages, curPage) {
  const maxButtons = 7;
  let start = Math.max(0, curPage - Math.floor(maxButtons / 2));
  let end = Math.min(totalPages - 1, start + maxButtons - 1);
  start = Math.max(0, end - (maxButtons - 1));

  pageNumsEl.innerHTML = "";
  for (let i = start; i <= end; i++) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "pageNum" + (i === curPage ? " is-on" : "");
    b.textContent = String(i + 1);
    b.addEventListener("click", () => {
      pageIndex = i;
      pagesShown = 1;
      renderLimit = PAGE_SIZE;
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    pageNumsEl.appendChild(b);
  }
}

async function main() {
  statusEl.textContent = "Загрузка…";
  const data = await fetchContacts();
  all = data.filter((r) => !r.isEventAgency);
  workSet = loadWorkSet();

  allOrgTypes = Array.from(new Set(all.map((r) => r.orgType || "N/A"))).sort((a, b) =>
    a.localeCompare(b, "ru", { sensitivity: "base" })
  );
  buildOrgTypeOptions(allOrgTypes);

  filtered = all;
  applyFilters();
}

function updateOrgTypeToggleLabel() {
  const n = selectedOrgTypes.size;
  if (n === 0) {
    orgTypeToggleEl.textContent = "Все типы";
    return;
  }
  if (n === 1) {
    orgTypeToggleEl.textContent = [...selectedOrgTypes][0];
    return;
  }
  orgTypeToggleEl.textContent = `Выбрано типов: ${n}`;
}

function buildOrgTypeOptions(types) {
  const q = (orgTypeSearchEl.value || "").trim().toLowerCase();
  orgTypeOptionsEl.innerHTML = "";
  const visible = q ? types.filter((t) => t.toLowerCase().includes(q)) : types;

  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "orgTypeEmpty";
    empty.textContent = "Ничего не найдено";
    orgTypeOptionsEl.appendChild(empty);
    return;
  }

  for (const t of visible) {
    const label = document.createElement("label");
    label.className = "orgTypeOption";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = t;
    cb.checked = selectedOrgTypes.has(t);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedOrgTypes.add(t);
      else selectedOrgTypes.delete(t);
      updateOrgTypeToggleLabel();
      applyFilters({ resetLimit: true });
    });
    label.appendChild(cb);
    label.append(" ", t);
    orgTypeOptionsEl.appendChild(label);
  }
}

function setOrgTypePanelOpen(open) {
  orgTypePanelEl.hidden = !open;
  orgTypeToggleEl.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) orgTypeSearchEl.focus();
}

qEl.addEventListener("input", () => applyFilters({ resetLimit: true }));
contactFilterEl.addEventListener("change", () => {
  contactFilter = contactFilterEl.value;
  applyFilters({ resetLimit: true });
});
orgTypeToggleEl.addEventListener("click", () => {
  setOrgTypePanelOpen(orgTypePanelEl.hidden);
});

orgTypeSearchEl.addEventListener("input", () => {
  buildOrgTypeOptions(allOrgTypes);
});

orgTypeSelectAllEl.addEventListener("click", () => {
  const q = (orgTypeSearchEl.value || "").trim().toLowerCase();
  const visible = q ? allOrgTypes.filter((t) => t.toLowerCase().includes(q)) : allOrgTypes;
  for (const t of visible) selectedOrgTypes.add(t);
  buildOrgTypeOptions(allOrgTypes);
  updateOrgTypeToggleLabel();
  applyFilters({ resetLimit: true });
});

orgTypeClearEl.addEventListener("click", () => {
  selectedOrgTypes.clear();
  buildOrgTypeOptions(allOrgTypes);
  updateOrgTypeToggleLabel();
  applyFilters({ resetLimit: true });
});

document.addEventListener("click", (e) => {
  if (!orgTypeMultiEl.contains(e.target)) setOrgTypePanelOpen(false);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !orgTypePanelEl.hidden) {
    setOrgTypePanelOpen(false);
    orgTypeToggleEl.focus();
  }
});

loadMoreBtn.addEventListener("click", () => {
  pagesShown += 1;
  render();
});
prevPageBtn.addEventListener("click", () => {
  pageIndex = Math.max(0, pageIndex - 1);
  pagesShown = 1;
  renderLimit = PAGE_SIZE;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
});
nextPageBtn.addEventListener("click", () => {
  pageIndex = pageIndex + 1;
  pagesShown = 1;
  renderLimit = PAGE_SIZE;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

main().catch((e) => {
  statusEl.textContent = `Ошибка загрузки данных: ${e?.message || e}`;
});
