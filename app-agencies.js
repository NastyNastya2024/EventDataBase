import {
  AGENCIES_PAGE_SIZE,
  esc,
  linkify,
  fetchContacts,
  filterByContactKind,
  groupByOrg,
  orgKey,
  loadWorkSet,
  renderWorkCheckbox,
  bindWorkCheckboxes,
  kindLabel,
  formatContactValue,
} from "./shared.js";

let agencyRows = [];
let filtered = [];
let workSet = loadWorkSet();

const PAGE_SIZE = AGENCIES_PAGE_SIZE;

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

let contactFilter = "all";
let pageIndex = 0;
let pagesShown = 1;

function groupMatches(g, q) {
  if (!q) return true;
  const t = q.toLowerCase();
  if (g.org.toLowerCase().includes(t)) return true;
  if ((g.orgType || "").toLowerCase().includes(t)) return true;
  if ((g.site || "").toLowerCase().includes(t)) return true;
  return g.contacts.some((c) => (c.value || "").toLowerCase().includes(t));
}

function applyFilters({ resetLimit = true } = {}) {
  const q = (qEl.value || "").trim();
  const rows = filterByContactKind(agencyRows, contactFilter);
  filtered = groupByOrg(rows).filter((g) => groupMatches(g, q));

  if (resetLimit) {
    pageIndex = 0;
    pagesShown = 1;
  }
  render();
}

function renderContactsStack(contacts) {
  return contacts
    .map((c) => {
      return `<div class="contact-line">
        <span class="mono contact-kind">${esc(kindLabel(c.kind))}</span>
        <span class="contact-value">${formatContactValue(c)}</span>
      </div>`;
    })
    .join("");
}

function render() {
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const curPage = Math.min(pageIndex, totalPages - 1);
  const start = curPage * PAGE_SIZE;
  const shown = Math.min(total, start + pagesShown * PAGE_SIZE);
  const contactCount = filtered.reduce((n, g) => n + g.contacts.length, 0);

  statusEl.textContent = `Организаций: ${total.toLocaleString("ru-RU")} — контактов: ${contactCount.toLocaleString("ru-RU")} — показано: ${shown.toLocaleString("ru-RU")}`;
  pageStatusEl.textContent = `Страница: ${(curPage + 1).toLocaleString("ru-RU")} / ${totalPages.toLocaleString("ru-RU")}`;

  loadMoreBtn.hidden = shown >= total;
  prevPageBtn.disabled = curPage <= 0;
  nextPageBtn.disabled = curPage >= totalPages - 1;
  rowsEl.innerHTML = "";

  const slice = filtered.slice(start, shown);
  const html = slice
    .map((g) => {
      const key = orgKey(g.org);
      const inWork = workSet.has(key);
      const siteCell = linkify(g.site);
      return `<tr${inWork ? ' class="in-work"' : ""}>
        <td class="col-work">${renderWorkCheckbox(key, workSet)}</td>
        <td>${esc(g.org)}</td>
        <td>${esc(g.orgType || "N/A")}</td>
        <td class="col-site hide-sm">${siteCell}</td>
        <td class="contacts-cell"><div class="contacts-stack">${renderContactsStack(g.contacts)}</div></td>
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
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    pageNumsEl.appendChild(b);
  }
}

async function main() {
  statusEl.textContent = "Загрузка…";
  const data = await fetchContacts();
  agencyRows = data.filter((r) => r.isEventAgency);
  workSet = loadWorkSet();
  filtered = groupByOrg(agencyRows);
  applyFilters();
}

qEl.addEventListener("input", () => applyFilters({ resetLimit: true }));
contactFilterEl.addEventListener("change", () => {
  contactFilter = contactFilterEl.value;
  applyFilters({ resetLimit: true });
});

loadMoreBtn.addEventListener("click", () => {
  pagesShown += 1;
  render();
});
prevPageBtn.addEventListener("click", () => {
  pageIndex = Math.max(0, pageIndex - 1);
  pagesShown = 1;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
});
nextPageBtn.addEventListener("click", () => {
  pageIndex = pageIndex + 1;
  pagesShown = 1;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

main().catch((e) => {
  statusEl.textContent = `Ошибка загрузки данных: ${e?.message || e}`;
});
