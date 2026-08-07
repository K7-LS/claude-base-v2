---
name: web-access-r-jina-fallback
description: при непробитии страницы веб-доступом — повторить через префикс r.jina.ai
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c61090fe-8cfb-4a69-be16-358b0a7f015c
---

Основной веб-доступ — Exa (`web_search_exa` / `web_fetch_exa`) и `WebFetch`. Если страница
не пробивается (JS-рендер, пустой/мусорный markdown, пейвол публичного техконтента) —
**повторить через префикс** `https://r.jina.ai/<URL>` (Jina Reader → чистый markdown,
native PDF). Веб-поиск markdown'ом — `https://s.jina.ai/?q=<query>`. Бесплатно: 20 rpm без
ключа, 500 rpm + 10M токенов с free-ключом (`JINA_API_KEY`, опционально).

**Why:** WebFetch/Exa проваливаются на части сайтов; r.jina.ai вытягивает чистый текст там,
где они пасуют. Пользователь (08.06.2026) подтвердил это как апгрейд основного поисковика,
а не отдельный инструмент.

**How to apply:** при неудачном fetch/Exa — не сдаваться, а retry с префиксом `r.jina.ai/`;
дальше по цепочке усиления веб-доступа — `firecrawl` (массовый scrape) и `playwright` (рендеренные
JS-страницы). См. secret-tools (per-machine, не shared).
