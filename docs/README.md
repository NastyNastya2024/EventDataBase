# GitHub Pages

Сборка:

```bash
python3 scripts/build_pages_site.py
```

Деплой: **Settings → Pages → Build and deployment → Source: GitHub Actions**.

После push в `main` workflow `.github/workflows/pages.yml` публикует `_site/`
(`index.html`, `styles.css`, `app.js`, `contacts.json`).

Fallback: **Deploy from branch `main`, folder `/docs`**.
