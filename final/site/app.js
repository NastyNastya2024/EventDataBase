let all = [];
let filtered = [];

const PAGE_SIZE = 200;
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
const orgTypeEl = $("orgType");

let orgType = "all";
let contactFilter = "all";

let pageIndex = 0;
let pagesShown = 1; // "Показать больше" increments this

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function isMatch(row, q) {
  if (!q) return true;
  const t = q.toLowerCase();
  return (
    row.org.toLowerCase().includes(t) ||
    (row.orgType || "").toLowerCase().includes(t) ||
    (row.site || "").toLowerCase().includes(t) ||
    (row.value || "").toLowerCase().includes(t)
  );
}

function applyFilters({ resetLimit = true } = {}) {
  const q = (qEl.value || "").trim();
  filtered = all
    .filter((r) => {
      if (contactFilter === "all") return true;
      if (contactFilter === "phone") return r.kind === "phone";
      if (contactFilter === "email") return r.kind === "email";
      if (contactFilter === "social") return r.kind === "social";
      if (contactFilter.startsWith("social:")) {
        const p = contactFilter.slice("social:".length);
        return r.kind === "social" && r.socialPlatform === p;
      }
      return true;
    })
    .filter((r) => (orgType === "all" ? true : (r.orgType || "N/A") === orgType))
    .filter((r) => isMatch(r, q));

  if (resetLimit) {
    renderLimit = PAGE_SIZE;
    pageIndex = 0;
    pagesShown = 1;
  }
  render();
}

function linkify(url) {
  if (!url) return "";
  const u = String(url);
  const safe = esc(u);
  if (u.startsWith("http://") || u.startsWith("https://")) {
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`;
  }
  return safe;
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
      const kindLabel = r.kind === "phone" ? "phone" : r.kind === "email" ? "email" : "social";
      const valueCell = r.kind === "social" ? linkify(r.value) : esc(r.value);
      const siteCell = linkify(r.site);
      return `<tr>
        <td>${esc(r.org)}</td>
        <td>${esc(r.orgType || "N/A")}</td>
        <td class="hide-sm">${siteCell}</td>
        <td><span class="mono">${esc(kindLabel)}</span></td>
        <td>${valueCell}</td>
      </tr>`;
    })
    .join("");
  rowsEl.innerHTML = html;

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
  const res = await fetch("./contacts.json", { cache: "no-store" });
  all = await res.json();

  // normalize fields to avoid runtime checks
  all = all.map((r) => ({
    org: r.org || "",
    orgType: r.orgType || "N/A",
    site: r.site || "",
    kind: r.kind || "",
    value: r.value || "",
    socialPlatform: r.socialPlatform || "",
  }));

  // build dropdown options
  const types = Array.from(new Set(all.map((r) => r.orgType || "N/A"))).sort((a, b) =>
    a.localeCompare(b, "ru", { sensitivity: "base" })
  );
  for (const t of types) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    orgTypeEl.appendChild(opt);
  }

  filtered = all;
  applyFilters();
}

qEl.addEventListener("input", () => applyFilters({ resetLimit: true }));
contactFilterEl.addEventListener("change", () => {
  contactFilter = contactFilterEl.value;
  applyFilters({ resetLimit: true });
});
orgTypeEl.addEventListener("change", () => {
  orgType = orgTypeEl.value;
  applyFilters({ resetLimit: true });
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

// chips removed; keep table controls minimal

main().catch((e) => {
  statusEl.textContent = `Ошибка загрузки данных: ${e?.message || e}`;
});

