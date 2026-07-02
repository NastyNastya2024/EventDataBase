# GitHub Pages

Сборка:

```bash
python3 scripts/build_pages_site.py
```

## Деплой

**Settings → Pages → Build and deployment → Source: GitHub Actions**

После push в `main` workflow `.github/workflows/pages.yml` собирает `docs/` и публикует сайт.

Если Actions не работает — fallback:

**Source: Deploy from a branch → `main` → `/docs`**

Тогда публикуется папка `docs/` из репозитория (без workflow).

## Обучение (видео)

Страница: `training.html`  
Видео: `videos/training/*.mp4` (только mp4, .mov не деплоится)
