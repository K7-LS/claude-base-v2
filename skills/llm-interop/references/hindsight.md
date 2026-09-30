# Hindsight: выборочная память проекта

Используй этот маршрут только по прямому запросу владельца на Hindsight.
Hindsight хранит извлечённый опыт и подкладывает агентам подсказки; принятые
факты, решения, статус и ссылки на доказательства остаются в каноне проекта
(`Claude/` или `Codex/`). Подсказка памяти не доказывает актуальность
исходника: перед существенным выводом сверяй её с файлами проекта, при
расхождении прав канон.

## Граница данных

- Настройки подключения, включая токен API, хранятся только в профиле
  пользователя `~/.hindsight/coding-agent.json`. Не копируй их в Git, отчёты и
  release Claude Base.
- Сначала `optInOnly: true`; допускай только явно выбранные корни проектов.
  Для Codex и Claude одного проекта укажи одинаковый банк через
  `mapPathToBank` на каждом устройстве. Не назначай один банк всем проектам.
- Для первоначального включения задай `gitIngest: "none"`, `autoSeed: false`,
  `codebaseSurvey: false`, `autoInject: "recall"`, `autoUpdate: false` и не
  запускай `--import-conversations`. По умолчанию `autoSeed` и
  `codebaseSurvey` включены: в git-проекте с «холодным» банком, а затем после
  накопления новых коммитов (`surveyRefreshCommits`) плагин при старте сеанса
  сам запускает `claude -p` с выбранной им моделью, читает репозиторий и
  отправляет выводы на сервер памяти. `autoInject` по умолчанию `"reflect"` —
  синтез ответа LLM памяти; `"recall"` подставляет найденные записи без вызова
  LLM (локальные модели поиска при этом работают).
- Для `"recall"` задай `recallOptions.types: ["world", "experience",
  "observation"]`: без него поиск берёт только observations, а их создаёт
  консолидация банка; если её отключили ради лимита, подсказки будут пустыми.
- При `retainSessions: true` новые сессии проекта уходят на сервер Hindsight, а
  извлечение фактов расходует лимит модели, выбранной для памяти; прежде чем
  включить, согласуй границу проекта и доступ к серверу. Записи, которые агент
  делает сам через инструменты Hindsight, подчиняются той же границе.
- Не копируй на сервер учётные данные Claude и других клиентов, `auth.json`,
  архивы сессий или историю браузера. Вход провайдера для памяти выполняют в
  отдельном каталоге учётных данных через штатный интерактивный вход.

## Подключение Claude

- Текущий пакет — `@vectorize-io/hindsight-coding-agents`. Устанавливай
  `install claude-code` конкретной проверенной версии, а не `install all`.
  Режим `self-hosted` с адресом своего API указывай явно: по умолчанию пакет
  выбирает `serverMode: cloud`.
- `hindsight-api` по умолчанию слушает `0.0.0.0`; запускай его с
  `--host 127.0.0.1`, чтобы API был доступен только локально.
- Установщик добавляет три хука в `~/.claude/settings.json` (`SessionStart`,
  `UserPromptSubmit`, `Stop`), регистрирует пользовательский MCP `hindsight`
  в `~/.claude.json` и кладёт навык в
  `~/.claude/skills/hindsight-coding-agent`. Старый плагин Hindsight для
  Claude Code одновременно с ним не включай: хук `SessionStart` предупреждает о
  нём событием `legacy_plugin_active`.
- `~/.claude/settings.json` вне управляемой поверхности Claude Base (база
  кладёт только `base/runtime/settings.template.json`), а `~/.claude.json`
  входит в её `preserved_paths`. Поэтому `$sync-base` не переписывает хуки и
  MCP Hindsight, и переносить их, как у Codex, не нужно.
- Навык `hindsight-coding-agent` Foundation Claude видит как неизвестную
  запись. `$sync-base` получает `BLOCKED_USER_DECISION`, берёт неизвестные
  записи из `plan` и повторяет установку с `-LocalExceptionPath`; итог —
  `CANONICAL_WITH_LOCAL_EXCEPTIONS`. Так сохраняются все неизвестные записи, и
  при каждом обновлении они перепроверяются. После удаления Hindsight `doctor`
  завершается `FAILED_DOCTOR` с кодом `ACTIVE_DRIFT`, пока не пройдёт
  следующий `$sync-base`. Не обходи `doctor` правкой `active.json`.
- После подключения проверь: по одному Hindsight-хуку на каждое из трёх
  событий рядом с хуками пользователя (хук базы `check-release` стоит только на
  `SessionStart`); `claude mcp list` показывает `hindsight` подключённым (сам
  статус MCP работу API не доказывает); `/health` локального API отвечает 200.
- Пока банк «холодный» или в нём нет knowledge pages, первый запрос нового
  сеанса идёт без памяти (`reflect_deferred_new_bank` в журнале хука). При
  `autoSeed: false` страницы сами не появляются, поэтому так будет в каждом
  новом сеансе. На втором запросе хук подставляет память (при
  `autoInject: "recall"` — событие `inject_recall`); если подстановка упала с
  ошибкой, он повторит её на следующем запросе, всего до двух попыток. При
  пустом результате подсказки нет.

## Хранение и перенос

Локальный `hindsight-api` может работать со встроенным PostgreSQL (`pg0`).
Не выставляй API или PostgreSQL в сеть; на другом ПК память поднимают из
резервной копии. `hindsight-admin backup` сохраняет полный снимок, а
`restore` заменяет данные целевой базы: сначала инициализируй отдельную
тестовую базу, после восстановления выполни
`hindsight-admin repair-bank --all` для частичных векторных индексов и проверь
поиск записи. Не синхронизируй живую папку `pg0` как файловую базу. Архив
содержит разговоры и факты; место его внешнего хранения и защиту согласуй
отдельно. Не помещай auth и архивы в release базы.

## Приёмка

1. Неразрешённый проект не создаёт банк; вне выбранного проекта хуки ничего
   не подставляют и не отправляют сессию.
2. Codex и Claude в выбранном проекте видят одну запись в общем банке;
   другой проект её не видит. Канон проекта не переписывается автоматически.
3. После `$sync-base` три Hindsight-хука, MCP и хуки пользователя и базы на
   месте без дублей; `doctor` — `CANONICAL_WITH_LOCAL_EXCEPTIONS` с навыком
   Hindsight среди исключений.
4. Локальный API доступен только через `127.0.0.1`; запись, поиск и
   восстановление из резервной копии проходят. Правило этой базы: если сервер
   выносят в сеть, перед подключением нужны HTTPS и Bearer-аутентификация.
5. В живом сеансе Claude в выбранном проекте при `autoInject: "recall"`
   журнал хука показывает `reflect_deferred_new_bank` на первом запросе и
   `inject_recall` с `count > 0` на втором.

Если пункт не проверен, укажи `NOT_RUN` или `BLOCKED` именно для него,
не объявляй развёртывание завершённым.

Первоисточники:

- https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/coding-agents/README.md
- https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/developer/installation.md
- https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/developer/admin-cli.md
- https://github.com/vectorize-io/hindsight/blob/main/skills/hindsight-docs/references/developer/configuration.md
