/** @typedef {{ org: string, orgType: string, site: string, kind: string, value: string, socialPlatform: string, isEventAgency?: boolean }} ContactRow */

const WORK_STORAGE_KEY = "eventDatabaseOrgsInWork";

export const PAGE_SIZE = 200;
export const AGENCIES_PAGE_SIZE = 80;

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

export function linkify(url) {
  if (!url) return "";
  const u = String(url);
  const safe = esc(u);
  if (u.startsWith("http://") || u.startsWith("https://")) {
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`;
  }
  return safe;
}

export function orgKey(org) {
  return org || "";
}

/** @deprecated use orgKey */
export function contactKey(row) {
  return orgKey(row.org);
}

export function loadWorkSet() {
  try {
    const raw = localStorage.getItem(WORK_STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

export function saveWorkSet(set) {
  localStorage.setItem(WORK_STORAGE_KEY, JSON.stringify([...set]));
}

export function toggleWork(key, on) {
  const set = loadWorkSet();
  if (on) set.add(key);
  else set.delete(key);
  saveWorkSet(set);
  return set;
}

export function kindLabel(kind) {
  if (kind === "phone") return "phone";
  if (kind === "email") return "email";
  if (kind === "social") return "social";
  if (kind === "address") return "address";
  return kind || "other";
}

export function formatContactValue(row) {
  if (row.kind === "social") return linkify(row.value);
  return esc(row.value);
}

export async function fetchContacts() {
  const res = await fetch(`./contacts.json?_=${Date.now()}`, { cache: "no-store" });
  const data = await res.json();
  return data.map((r) => ({
    org: r.org || "",
    orgType: r.orgType || "N/A",
    site: r.site || "",
    kind: r.kind || "",
    value: r.value || "",
    socialPlatform: r.socialPlatform || "",
    isEventAgency: Boolean(r.isEventAgency),
  }));
}

export function isMatch(row, q) {
  if (!q) return true;
  const t = q.toLowerCase();
  return (
    row.org.toLowerCase().includes(t) ||
    (row.orgType || "").toLowerCase().includes(t) ||
    (row.site || "").toLowerCase().includes(t) ||
    (row.value || "").toLowerCase().includes(t)
  );
}

export function filterByContactKind(rows, contactFilter) {
  if (contactFilter === "all") return rows;
  if (contactFilter === "phone") return rows.filter((r) => r.kind === "phone");
  if (contactFilter === "email") return rows.filter((r) => r.kind === "email");
  if (contactFilter === "social") return rows.filter((r) => r.kind === "social");
  if (contactFilter.startsWith("social:")) {
    const p = contactFilter.slice("social:".length);
    return rows.filter((r) => r.kind === "social" && r.socialPlatform === p);
  }
  return rows;
}

/** @param {ContactRow[]} rows */
export function groupByOrg(rows) {
  /** @type {Map<string, { org: string, orgType: string, site: string, contacts: ContactRow[] }>} */
  const map = new Map();
  for (const r of rows) {
    let g = map.get(r.org);
    if (!g) {
      g = { org: r.org, orgType: r.orgType, site: r.site, contacts: [] };
      map.set(r.org, g);
    }
    g.contacts.push(r);
    if (!g.site && r.site) g.site = r.site;
  }
  return [...map.values()].sort((a, b) => a.org.localeCompare(b.org, "ru", { sensitivity: "base" }));
}

export function renderWorkCheckbox(key, workSet) {
  const checked = workSet.has(key) ? " checked" : "";
  return `<input type="checkbox" class="work-check" data-key="${esc(key)}" title="Взяли в работу"${checked} aria-label="Взяли в работу" />`;
}

export function bindWorkCheckboxes(container, workSet, onChange) {
  container.querySelectorAll(".work-check").forEach((el) => {
    el.addEventListener("change", () => {
      const key = el.getAttribute("data-key");
      if (!key) return;
      toggleWork(key, el.checked);
      container.querySelectorAll(".work-check").forEach((cb) => {
        if (cb.getAttribute("data-key") === key) cb.checked = el.checked;
      });
      container.querySelectorAll("tr").forEach((tr) => {
        const cb = tr.querySelector(".work-check");
        if (cb?.getAttribute("data-key") === key) tr.classList.toggle("in-work", el.checked);
      });
      onChange?.();
    });
  });
}
