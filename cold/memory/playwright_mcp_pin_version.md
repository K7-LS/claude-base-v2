---
name: playwright-mcp-pin-version
description: "playwright MCP «открывает Chrome на about:blank, ничего не происходит» — причина @latest авто-апдейт + докачка браузера через корп-прокси зависает; чинится пином версии"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 92f397ec-45cc-4ccd-8456-d2f42782715e
---

Симптом (несколько сотрудников): при активации playwright Chrome открывается, «делает попытки», но остаётся about:blank; раньше реально искал. Перемежающийся — то работает, то нет.

Корень: регистрация была `npx -y @playwright/mcp@latest`. `@latest` авто-обновляется; на смене версии Playwright докачивает свежую сборку браузера (`ms-playwright/mcp-chrome-<hash>`) через npm/CDN, а корп-прокси режет CONNECT → докачка зависает → сервер стартует, Chrome открывается пустой (about:blank), навигация не идёт. В сессии без pending-апдейта (версия уже в кэше) — работает. Отсюда «то ищет, то about:blank». Проверено 2026-06-22: на v0.0.76 navigate на example.com и Google-поиск грузятся нормально → база не сломана, виноват авто-апдейт.

Вторая причина (на конкретных сайтах): антибот (Cloudflare/DDoS-Guard) отдаёт пустую/«Just a moment» — выглядит как about:blank. Приём: скрин → ждать 5-6с → повторить navigate ([[feedback_web_direct_access]]).

**Why:** `@latest` в npx = недетерминированная версия → сюрприз-докачка браузера за корп-прокси = тихий about:blank.

**How to apply:**
- Версия playwright ЗАКРЕПЛЕНА в `mcp-manifest.json`: `@playwright/mcp@0.0.76` (2026-06-22, был latest на тот день). Обновлять вручную на хабе, проверив навигацию.
- Раздача: `/sync-base` шаг 4 «version-drift» перерегистрирует `@latest`→пин (setup-extras сверяет по ИМЕНИ и сам не чинит). Консьюмеру: один раз `/sync-base` + restart Claude Code.
- Быстрая диагностика «жив ли playwright»: navigate на example.com — грузится? Да → проблема в конкретном сайте (антибот) или была pending-докачка; нет → смотреть docks/прокси.
