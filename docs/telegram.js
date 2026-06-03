const TOPICS = [
  { id: "event", label: "Ивент", match: /event|ивент|мероприят/i },
  { id: "contractors", label: "Подрядчики", match: /подряд|поиск|вместе|area|hunter|bigfinger/i },
  { id: "moscow", label: "Москва", match: /москв|msk|москвич/i },
  { id: "venue", label: "Площадки", match: /площад|loft|ищу площад/i },
  { id: "network", label: "Нетворкинг", match: /нетворк|network/i },
  { id: "music", label: "Артисты", match: /замен|кавер|танц|групп/i },
  { id: "other", label: "Другое", match: /.*/ },
];

const KIND_LABELS = {
  addlist: "Папка чатов",
  channel: "Канал",
  chat: "Чат",
  invite: "Приглашение",
  bot: "Бот",
};

let channels = [];
let activeTopic = "all";

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

function detectTopics(channel) {
  const text = `${channel.name} ${channel.username || ""}`;
  const topics = TOPICS.filter((t) => t.id !== "other" && t.match.test(text)).map((t) => t.id);
  if (!topics.length) topics.push("other");
  return topics;
}

function enrich(channel) {
  return { ...channel, topics: detectTopics(channel) };
}

function topicLabel(id) {
  return TOPICS.find((t) => t.id === id)?.label || id;
}

function renderChips() {
  const container = $("topic-filters");
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "chip active";
  allBtn.dataset.topic = "all";
  allBtn.textContent = "Все темы";
  container.appendChild(allBtn);

  for (const t of TOPICS.filter((x) => x.id !== "other")) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.dataset.topic = t.id;
    btn.textContent = t.label;
    container.appendChild(btn);
  }

  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    activeTopic = btn.dataset.topic;
    container.querySelectorAll(".chip").forEach((b) => {
      b.classList.toggle("active", b.dataset.topic === activeTopic);
    });
    update();
  });
}

function filterList() {
  const q = ($("search").value || "").trim().toLowerCase();
  return channels.filter((ch) => {
    const hay = `${ch.name} ${ch.username || ""} ${ch.url}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (activeTopic !== "all" && !ch.topics.includes(activeTopic)) return false;
    return true;
  });
}

function joinLabel(ch) {
  if (ch.kind === "addlist") return "Открыть папку";
  if (ch.kind === "invite") return "Вступить в чат";
  if (ch.kind === "bot") return "Открыть бота";
  return "Перейти в чат";
}

function renderGrid(list) {
  const grid = $("grid");
  $("count").textContent = String(list.length);

  if (!list.length) {
    grid.innerHTML = `
      <div class="empty">
        <h3>Ничего не найдено</h3>
        <p>Попробуйте изменить запрос или сбросить фильтры</p>
      </div>`;
    return;
  }

  grid.innerHTML = list
    .map((ch) => {
      const tags = [
        `<span class="tag">${esc(KIND_LABELS[ch.kind] || ch.kind || "Чат")}</span>`,
        ...ch.topics.slice(0, 3).map((t) => `<span class="tag">${esc(topicLabel(t))}</span>`),
      ].join("");

      const userLine = ch.username
        ? `<div class="card-user">@${esc(ch.username)}</div>`
        : `<div class="card-user">${esc(ch.url.replace(/^https?:\/\//, ""))}</div>`;

      return `
        <article class="card">
          <div class="card-num">#${ch.id}</div>
          <h2 class="card-title">${esc(ch.name)}</h2>
          <div class="card-tags">${tags}</div>
          ${userLine}
          <a class="btn-join" href="${esc(ch.url)}" target="_blank" rel="noopener noreferrer">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/></svg>
            ${esc(joinLabel(ch))}
          </a>
        </article>`;
    })
    .join("");
}

function update() {
  renderGrid(filterList());
}

async function init() {
  renderChips();
  $("search").addEventListener("input", update);

  try {
    const res = await fetch("./data/event_telegram_channels.json");
    if (!res.ok) throw new Error("JSON not found");
    channels = (await res.json()).map(enrich);
  } catch (e) {
    $("grid").innerHTML = `<div class="empty"><h3>Ошибка загрузки</h3><p>${esc(e?.message || e)}</p></div>`;
    return;
  }

  $("total").textContent = `Всего: ${channels.length}`;
  $("grid").classList.remove("loading");
  update();
}

init();
