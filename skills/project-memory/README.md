# project-memory — память проекта (для человека)

Кодификация ручной схемы «папка Claude/ в объекте»: bootstrap одной
командой + rot-курирование статуса + хуки дисциплины журнала.
Мультидевайс — Я.Диск: относительные пути, свежесть по mtime, без git;
откат — из `_backup_<дата>/`.

## Быстрый старт

```powershell
python "$HOME\.claude\skills\project-memory\tools\bootstrap.py" "Мой объект" --target "<корень проекта>"
```

Получите:

```
<проект>/CLAUDE.md            # указатель-страховка
<проект>/Claude/CLAUDE.md     # правила папки, порядок сессии
<проект>/Claude/README.md     # навигатор
<проект>/Claude/ЖУРНАЛ СЕССИЙ.md
<проект>/Claude/STATUS.md
```

Повторный запуск ничего не затирает (`=` в отчёте); перезапись одного
файла — `--force STATUS.md` (для CLAUDE.md указывать путь: `./CLAUDE.md`
или `Claude/CLAUDE.md`).

## Курирование протухшего статуса

```powershell
python "$HOME\.claude\skills\project-memory\tools\curate_rot.py" propose --project "<корень>"
# → Claude/.curate/<stamp>/REPORT.md — читать глазами
python "$HOME\.claude\skills\project-memory\tools\curate_rot.py" apply <stamp> --accept p1,p3 --project "<корень>"
# бэкап в Claude/_backup_<дата>/ делается сам; откат — скопировать назад
```

Скрипт только ПРЕДЛАГАЕТ (все правки — после вашего/Claude review);
пустой evidence отбрасывается; авто-apply нет; вне `Claude/` не пишет.

## Установка хуков (один раз, settings.shared.json)

⚠ В ЛИЧНЫЙ `~/.claude/settings.json` хуки ставить БЕСПОЛЕЗНО: ключ `hooks` —
strictly-shared, `merge-shared-settings.ps1` перезаписывает его из
`settings.shared.json` при каждом старте сессии (проверено 2026-07-06).

Единственное рабочее место — `~/.claude/settings.shared.json` (уезжает всем
ПК команды через auto-pull; вне папок с `Claude/ЖУРНАЛ СЕССИЙ.md` хуки —
молчаливый no-op). С 2026-07-07 блок УЖЕ добавлен в shared решением владельца —
ничего ставить не нужно. Сниппет ниже — справочно (структура записей;
блоки `SessionStart` в конфиге обычно уже есть — ДОБАВЛЯТЬ hooks внутрь
существующих матчеров, не дублировать):

```json
"SessionStart": [
  { "matcher": "startup", "hooks": [
    { "type": "command",
      "command": "& \"$HOME\\.claude\\skills\\project-memory\\tools\\hooks\\session_start.ps1\"",
      "shell": "powershell", "timeout": 10 } ] },
  { "matcher": "resume", "hooks": [
    { "type": "command",
      "command": "& \"$HOME\\.claude\\skills\\project-memory\\tools\\hooks\\session_start.ps1\"",
      "shell": "powershell", "timeout": 10 } ] }
],
"Stop": [
  { "matcher": "*", "hooks": [
    { "type": "command",
      "command": "& \"$HOME\\.claude\\skills\\project-memory\\tools\\hooks\\session_end.ps1\"",
      "shell": "powershell", "timeout": 20 } ] }
]
```

Поведение:
- вне папок с `Claude/ЖУРНАЛ СЕССИЙ.md` оба хука — молчаливый no-op;
- SessionStart печатает верхние 2 записи журнала в контекст сессии;
- Stop напоминает «допиши журнал» максимум ОДИН раз за сессию и только
  если файлы проекта менялись, а журнал — нет;
- состояние сессий — `~/.claude/.local-state/project-memory/` (локально,
  НЕ в Я.Диске; маркеры старше 7 дней чистятся сами).

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
