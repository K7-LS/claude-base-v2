# Claude Desktop на Windows = MSIX в WindowsApps (НЕ «урезанная Store-версия») + провал verifiable-first

> Загружать по триггерам: «странная версия Claude Desktop», «в этой версии многого нет vs другой ПК»,
> «WindowsApps — урезанная Store-сборка», «переустановить/удалить Claude Desktop», «Claude Desktop
> застрял / не обновляется / обновление не доезжает», «где данные Claude Desktop / claude_desktop_config.json»,
> «установщик Claude — App unavailable in region». Анти-паттерн (verifiable-first) + reference про окружение.
> Дополняет [[feedback_web_direct_access]].

## Что произошло
Пользователь: «странная версия Claude Desktop, многого нет vs ноутбук». Я решил, что версия в
`C:\Program Files\WindowsApps\Claude_…` — это «урезанная Microsoft Store сборка», а есть «полная
standalone», и погнал на необратимое: удаление + переустановку.

**Диагноз оказался неверным.** Официальный установщик Anthropic (`ClaudeSetup.exe`,
CompanyName = Anthropic PBC) ставит ИМЕННО в WindowsApps (формат MSIX). «Версия в WindowsApps» =
и есть нормальная официальная установка Claude Desktop для Windows. Двух разных сборок
(Store vs standalone) не существует. Переустановка вернула ту же версию.

## Why (корень)
Принял допущение («WindowsApps = урезанная Store») за факт и не проверил тип дистрибуции ДО
необратимого действия. Это прямое нарушение verifiable-first (Karpathy #5): локально проверяемый
факт (что за установщик, куда ставит — `Get-AppxPackage`, `VersionInfo` exe) надо было установить
ПЕРЕД тем, как заставлять пользователя удалять рабочее приложение.

## How to apply
1. **Не гнать необратимое** (удаление приложения/данных) на непроверенном допущении о дистрибуции.
   Сначала: `Get-AppxPackage *Name*`, `(Get-Item setup.exe).VersionInfo` (CompanyName/Description),
   куда ставит — потом выводы.
2. **Факт про окружение:** Claude Desktop для Windows распространяется как **MSIX** и живёт в
   `C:\Program Files\WindowsApps\Claude_…`; данные — в
   `AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\` (sandbox), там же
   `claude_desktop_config.json` для MCP. Это НЕ урезанная Store-версия.
3. **«Застрявший» Claude Desktop** (обновление не доезжает, перезапуск/«проверить обновления» не
   помогают) лечится **чистой переустановкой** той же версии (`Remove-AppxPackage` +
   `ClaudeSetup.exe` заново) — форсирует актуальное состояние.
4. **Грабли загрузки установщика:** `claude.ai/api/desktop/win32/x64/setup/latest/redirect`
   гео-блокирован для **RU и AE (Дубай)** → «App unavailable in region». Качать с **US/EU** egress +
   браузерный User-Agent + GET (HEAD даёт 405). Squirrel-stub при уже установленном Claude просто
   открывает существующий — для переустановки сперва удалить старый.

## Связь
Эпизод внутри сессии «виджет-мост MCP-app» (apps-surface рендерится в Desktop Chat, не в Claude Code).
Доступность аккаунта по региону — отдельный симптом (белый экран, `accountId=null`), решается
проверкой права на аккаунт, а не транспортом; гео/прокси при загрузке файлов — [[feedback_web_direct_access]].
