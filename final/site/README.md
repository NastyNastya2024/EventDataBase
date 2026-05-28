## Мини‑сайт контактов (final/site)

### Сборка данных

```bash
python3 scripts/build_contacts_site_json.py
```

Скрипт читает `final/final_contacts_with_type.md` и генерирует `final/site/contacts.json`.

### Запуск локально

```bash
cd final/site
python3 -m http.server 8000
```

Открой `http://localhost:8000`.

