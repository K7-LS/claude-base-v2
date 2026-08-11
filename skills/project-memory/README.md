# project-memory — единое ядро проекта (для человека)

Кодификация переносимой схемы единого ядра: bootstrap одной
командой + rot-курирование статуса + progressive SessionStart-контекст.
Мультидевайс — Я.Диск: относительные пути, свежесть по mtime, без git;
откат — из `_backup_<дата>/`.

## Быстрый старт

```powershell
python "$HOME\.claude\skills\project-memory\tools\bootstrap.py" "Мой объект" --target "<корень проекта>"
```

Если ядра нет, получите:

```
<проект>/CLAUDE.md            # указатель-страховка
<проект>/AGENTS.md             # указатель для Codex и других клиентов
<проект>/Claude/CLAUDE.md     # правила переносимой памяти
<проект>/Claude/README.md     # навигатор
<проект>/Claude/ЖУРНАЛ СЕССИЙ.md
<проект>/Claude/STATUS.md
```

Повторный запуск ничего не затирает (`=` в отчёте); перезапись одного
файла — `--force STATUS.md` (для CLAUDE.md указывать путь: `./CLAUDE.md`
или `Claude/CLAUDE.md`).

Если до запуска уже существует валидное `Codex/`, оно становится общим ядром:
`Claude/` рядом не создаётся. Аналогично Codex переиспользует существующее
`Claude/`. Два несогласованных ядра дают `CORE_CONFLICT` до любых записей.

## Курирование протухшего статуса

```powershell
python "$HOME\.claude\skills\project-memory\tools\curate_rot.py" propose --project "<корень>"
# → <ядро>/.curate/<stamp>/REPORT.md — читать глазами
python "$HOME\.claude\skills\project-memory\tools\curate_rot.py" apply <stamp> --accept p1,p3 --project "<корень>"
# бэкап в <ядро>/_backup_<дата>/ делается сам; откат — скопировать назад
```

Скрипт только ПРЕДЛАГАЕТ (все правки — после вашего/Claude review);
пустой evidence отбрасывается; авто-apply нет; вне `Claude/` не пишет.

## Runtime behavior

Employee runtime не устанавливает project-memory hooks: native project
`CLAUDE.md` остаётся bootstrap-точкой. Опциональный `session_start.ps1`
может быть добавлен только управляемым релизом конфигурации после решения
владельца; сам скилл settings не патчит. Stop-hook не устанавливается.

Поведение:
- вне папок с `Claude/ЖУРНАЛ СЕССИЙ.md` hook — молчаливый no-op;
- опциональный SessionStart печатает верхние 2 записи журнала в контекст
  и сохраняет cwd-project cache для v2;
- Stop-hook не устанавливается: решение об обновлении STATUS/журнала
  принимается по материальному изменению переносимого состояния;
- старый `session_end.ps1` сохранён как silent compatibility no-op и не
  блокирует завершение;
- cwd-project cache — `~/.claude/.local-state/project-memory/` (локально,
  НЕ в Я.Диске; записи старше 7 дней чистятся сами).

## Тесты

```powershell
python -m pytest "$HOME\.claude\skills\project-memory\tests" -v
```

Переносимые (tmp, синтетика, без привязки к машине); `test_hooks.py` —
Windows-only smoke (PowerShell 5.1).

## v2 — установка хуков доставки/гейта (по решению владельца)

Хуки Этапа 1 (доставка ядра + блокирующий гейт, см. SKILL.md §v2) реализованы
и протестированы, но включаются ОСОЗНАННО (гейт даёт `exit 2`). Через скилл
`update-config`, в СУЩЕСТВУЮЩИЕ блоки (не дублируя матчеры):

- **UserPromptSubmit** += `& "$HOME\.claude\skills\project-memory\tools\hooks\project_context.ps1"`
- **PreToolUse** (ОТДЕЛЬНЫЙ матчер, НЕ в блок `screenshot|zoom`) += `& "$HOME\.claude\skills\project-memory\tools\hooks\project_gate.ps1"`
- **PostToolUse** — регистрация чтения уже в `scripts/log-tool-usage.ps1` (подключён).

Без этой правки доставка ① и гейт ② инертны (эффекта в живой сессии нет).

## Точка расширения

`templates/profiles/` — пусто в v1. Профиль (напр. `id-tom`) = свой набор
шаблонов поверх ядра; первым добавит блок ПТО. `--profile` в bootstrap
уже зарезервирован.
