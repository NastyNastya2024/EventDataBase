## Мини‑сайт контактов (final/site)

### Сборка данных

```bash
python3 scripts/build_contacts_site_json.py
```

Скрипт читает `final/final_contacts_with_type.md` и генерирует `final/site/contacts.json`.

### Публикация (GitHub Pages)

```bash
python3 scripts/build_pages_site.py
```

Копирует `index.html`, `styles.css`, `app.js`, `contacts.json` и `.nojekyll` в **корень** репозитория (Pages: branch `main`, folder `/`).

### Запуск локально

```bash
python3 scripts/build_pages_site.py
python3 -m http.server 8000
```

Открой `http://localhost:8000` из корня проекта.

