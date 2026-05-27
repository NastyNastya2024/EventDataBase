#!/usr/bin/env python3
"""
Поиск в Google: первая ссылка из органической выдачи.

Рекомендуемый способ — Serper (https://serper.dev), это JSON-API с результатами Google.
Прямой scrape google.com часто блокируется (капча / enablejs).

Переменные окружения:
  SERPER_API_KEY — ключ Serper (backend=serper)
  GOOGLE_API_KEY + GOOGLE_CSE_ID — Google Custom Search JSON API (backend=cse)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

_SKIP_HOSTS = frozenset(
    {
        "google.com",
        "www.google.com",
        "accounts.google.com",
        "support.google.com",
        "policies.google.com",
        "maps.google.com",
        "webcache.googleusercontent.com",
        "translate.google.com",
    }
)

_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.casefold()
    except Exception:
        return ""


def is_kontur_focus_url(url: str) -> bool:
    u = url.casefold().strip()
    if not u:
        return False
    return "focus.kontur.ru" in u or (
        "kontur.ru" in u and ("/site/" in u or "populyarnye-kompanii" in u)
    )


def _is_skippable(url: str) -> bool:
    host = _host(url)
    if not host:
        return True
    if is_kontur_focus_url(url):
        return True
    if host in _SKIP_HOSTS:
        return True
    if host.endswith(".google.com") or host.endswith(".google.ru"):
        return True
    if host.endswith("rusprofile.ru") or host.endswith("2gis.ru") or host.endswith("zoon.ru"):
        return True
    if host in {"vk.com", "www.vk.com", "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com"}:
        return True
    return False


def _pick_first(urls: list[str]) -> str:
    for u in urls:
        u = u.strip()
        if u and not _is_skippable(u):
            return u
    return ""


def google_first_url(
    query: str,
    *,
    backend: str = "auto",
    serper_api_key: str = "",
    google_api_key: str = "",
    google_cse_id: str = "",
    timeout: float = 25.0,
) -> str:
    """
    Возвращает URL первого подходящего результата или ''.
    backend: auto | serper | cse | scrape
    """
    backend = backend.casefold()
    if backend == "auto":
        serper_api_key = serper_api_key or os.environ.get("SERPER_API_KEY", "")
        google_api_key = google_api_key or os.environ.get("GOOGLE_API_KEY", "")
        google_cse_id = google_cse_id or os.environ.get("GOOGLE_CSE_ID", "")
        if serper_api_key:
            backend = "serper"
        elif google_api_key and google_cse_id:
            backend = "cse"
        else:
            backend = "scrape"

    if backend == "serper":
        key = serper_api_key or os.environ.get("SERPER_API_KEY", "")
        if not key:
            raise ValueError("Serper: задайте SERPER_API_KEY или --serper-api-key")
        return _serper_first(query, key, timeout=timeout)
    if backend == "cse":
        key = google_api_key or os.environ.get("GOOGLE_API_KEY", "")
        cx = google_cse_id or os.environ.get("GOOGLE_CSE_ID", "")
        if not key or not cx:
            raise ValueError("CSE: задайте GOOGLE_API_KEY и GOOGLE_CSE_ID")
        return _cse_first(query, key, cx, timeout=timeout)
    if backend == "scrape":
        return _scrape_first(query, timeout=timeout)
    raise ValueError(f"Неизвестный backend: {backend}")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: float = 25.0,
) -> dict:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def _serper_first(query: str, api_key: str, *, timeout: float) -> str:
    payload = json.dumps({"q": query, "gl": "ru", "hl": "ru", "num": 10}).encode("utf-8")
    data = _http_json(
        "https://google.serper.dev/search",
        method="POST",
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        body=payload,
        timeout=timeout,
    )
    urls: list[str] = []
    for item in data.get("organic") or []:
        link = (item or {}).get("link") or ""
        if link:
            urls.append(link)
    return _pick_first(urls)


def _cse_first(query: str, api_key: str, cse_id: str, *, timeout: float) -> str:
    params = urllib.parse.urlencode(
        {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": "10",
            "hl": "ru",
            "gl": "ru",
        }
    )
    data = _http_json(
        f"https://www.googleapis.com/customsearch/v1?{params}",
        timeout=timeout,
    )
    urls = [(item or {}).get("link", "") for item in (data.get("items") or [])]
    return _pick_first(urls)


def _scrape_first(query: str, *, timeout: float) -> str:
    """
    Прямой запрос к google.com/search. Может вернуть '' при блокировке бота.
    """
    params = urllib.parse.urlencode({"q": query, "num": "10", "hl": "ru", "gl": "ru"})
    url = f"https://www.google.com/search?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _CHROME_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return ""
        raise

    if "enablejs" in html or "unusual traffic" in html.casefold():
        return ""

    urls: list[str] = []

    # Классический редирект /url?q=
    for m in re.finditer(r"/url\?q=(https?[^&\"'>]+)", html):
        urls.append(urllib.parse.unquote(m.group(1)))

    # data-lpage и похожие атрибуты
    for m in re.finditer(r'data-lpage="(https?://[^"]+)"', html):
        urls.append(m.group(1))

    # div.yuRUbf (старая вёрстка) — через regex, без bs4
    for m in re.finditer(
        r'<div[^>]*class="[^"]*yuRUbf[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"',
        html,
        re.I,
    ):
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("/url?q="):
            href = urllib.parse.unquote(href.split("/url?q=", 1)[1].split("&", 1)[0])
        if href.startswith("http"):
            urls.append(href)

    # Мобильная вёрстка ezO2md
    for m in re.finditer(r'class="[^"]*ezO2md[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"', html, re.S | re.I):
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("/url?q="):
            href = urllib.parse.unquote(href.split("/url?q=", 1)[1].split("&", 1)[0])
        if href.startswith("http"):
            urls.append(href)

    return _pick_first(urls)


def build_query(name: str, suffix: str = "") -> str:
    name = name.strip()
    suffix = suffix.strip()
    if suffix and suffix not in name:
        return f"{name} {suffix}"
    return name
