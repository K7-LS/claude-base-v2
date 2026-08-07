---
name: reference_harvested_tools_2026
description: "Реестр внешних инструментов, оценённых harvest'ом (вердикт/tier/риск) — чтобы НЕ переоценивать заново; смотрели ли уже X и почему такой вердикт"
metadata:
  node_type: memory
  type: reference
---

# Оценённые внешние инструменты (harvest) — реестр «чтобы не забыть»

> Загружать по триггерам: «смотрели ли инструмент X», «оценивали ли Y», «что там по <название>»,
> «уже отклоняли?», перед оценкой нового инструмента (проверить — вдруг уже смотрели).
> Полный журнал (47 кандидатов, все поля) — `Трекер_реворк_базы.xlsx` в папке программы
> «Заведомо проигранный бой (или нет)». Здесь — быстрый machine-readable recall.
> Связано: [[project-base-rework]], [[external-tools-audit]] (39 кандидатов до 2026-07-01).

## Партия 2026-07-01 (список владельца перед сном, параллельный fan-out 8 sonnet-субагентов)

Метрики — из GitHub API (не README). Метод: каждый инструмент изучен субагентом (README+API/сайт).

| Инструмент | URL | Вердикт | Tier | Риск | Суть (почему) |
|---|---|---|---|---|---|
| **MinerU** | github.com/opendatalab/MinerU | **Добавить** | **A** | Средний | PDF/скан/офис→MD/JSON; PP-OCRv6+VLM, кириллица; кросс-страничные таблицы, layout, формулы→LaTeX. **Сильнее нашего стека (markitdown/pdf-mcp/image-text-replace) на структурных инженерных PDF и сканах ИД** (спеки СО, АОСР, журналы). 72601★. GPU 8GB для топ-качества. Нет MCP-обёртки — написать. ТЕСТИРОВАТЬ на русских ГОСТ-штампах vs pdf-mcp |
| **council-of-high-intelligence** | github.com/0xNyk/council-of-high-intelligence | **Интегрировать** (идею) | B | Средний | `/council` дебаты 18 персон, 3 раунда + dissent quota против ложного консенсуса. = «Claude Council» из YouTube-кейса (идея LLM-council Карпаты), **лечит подхалимаж → наша тема п.5 CLAUDE.md**. Взять ПРОТОКОЛ как локальный скилл `decision-council` (5 персон, не 18), БЕЗ install.sh (перезапишет наши агенты). 2333★ MIT. full-mode ~50k токенов |
| **OmniRoute** | github.com/diegosouzapw/OmniRoute | **Добавить** (пилот) | B | Средний | self-hosted LLM-роутер (:20128), 236 провайдеров (50+ free), автофаллбэк, компрессия RTK 60-95%, 87 MCP. «Бесконечные токены» = агрегация free-tier ~1.6B/мес (гипербола, квоты нестабильны). **Черновиковый слой** (OCR/парсинг УПД), НЕ для финала/приватного (данные к внешним провайдерам — не для ФИО/шифров). 8483★ MIT. Ось делегирования #4 |
| Loopy | github.com/Forward-Future/loopy | Отклонить\* | C | Низкий | Библиотека агентских feedback-LOOPS (observe→act→verify→record). **ВАЖНО: заявка «порядок в скиллах/дубли SKILL.md» ИСКАЖЕНА** — про loops, НЕ аудит наших скиллов. Нашу боль (дубли/мёртвые скиллы, health-check ~50) не решает → свой Python(embedding)+graphify. Условно полезна библиотека готовых loops. 2209★, репо 19 дней |
| memanto | github.com/moorcheh-ai/memanto | Отклонить (переоценить) | C | Высокий | Агент памяти, 13 типов записей, retrieval без вект.БД. Добавляет АВТОМАТИЗМ (лечит «0 вызовов graphify»). НО **облако = контекст с шифрами/ФИО/объектами на чужие серверы = НАРУШЕНИЕ обезличивания**; обезличивание не встроено; сырость (3 мес, 177 issues); вендор-замок. Локаль Docker переоценить через 6-12 мес. 1502★ MIT |
| OpenHuman | github.com/tinyhumansai/OpenHuman | Отклонить | C | Средний | Десктоп AI-ассистент (Tauri/Rust), SQLite+Obsidian память, Super Context, OAuth 100+ сервисов. **Конкурент Claude Code, не дополнение**; дублирует CLAUDE.md+memory+graphify → конфликт слоёв. Приватность (объекты/шифры) через облако стартапа. 34005★ GPL-3.0 |
| Claude Science / AI Workbench | anthropic.com/news/claude-science-ai-workbench | Отклонить | D | Высокий | Научный workbench Anthropic (геномика/химия), Python/R+HPC, агент-рецензент. **Блокеры: РФ нет в supported countries + Windows не поддерживается + биология-домен**. Переносимая идея: воспроизводимые расчёты (код+окружение+история) для designer. Beta 30.06.2026 |
| Torlink | github.com/baairon/torlink | Отклонить | D | Высокий | Консольный torrent-клиент (источники — пиратские трекеры). **Пиратство (легальность) + безопасность (npx без pin, автосидирование) + мимо домена**. Репо создано 25.06.2026 (5 дней, аномальный рост = красный флаг). 1661★ |

**Связанный кейс (не инструмент):** YouTube shorts/jwxOkMu_8p8 (Артемий Миллер, 08.06.2026) — «Claude Council»,
про подхалимаж Claude → живая иллюстрация правила п.5 CLAUDE.md «Партнёр, а не подхалим». Связан с council выше.

**Итог партии:** реальный лидер — MinerU (A, практичный). council — ценная идея (decision-council скилл).
OmniRoute — осторожный пилот. Приоритеты владельца (Loopy/memanto «важнейшие») скорректированы фактом:
Loopy — заявка искажена, memanto — приватность-блокер. 5 из 8 отклонены с обоснованием.

Детали каждого — `session-reports/2026-07-01_harvest-8-tools/_оценки_накопитель.md`.

## Фаза 1b (2026-07-01): забытое из harvested/ + backlog → +17 в трекер (47→64)

Прочёсаны 26 harvested-папок (138 заметок) + 5 backlog. Добавлены забытые-НЕ-отвергнутые:
- **harvested (14):** open-webui, markitdown-ocr, litellm-agent-platform, ollama-admin, claude-mem, docling, OCRmyPDF, camelot, jztan-pdf-mcp, redact_mcp, terrastruct-d2, mingrammer/diagrams, acad-api-skill, netbox-topology.
- **backlog (3):** cross-model-review (РФ-модель), promptfoo, tools/-миграция.
- **ДОЛГ ИСПОЛНЕНИЯ (ключевое):** docling/OCRmyPDF/camelot решены «используем» (15.05), НЕ установлены (pip global пусто, siblings pdfplumber/pymupdf стоят) → база теряет РЕШЕНИЯ, не инструменты (доказано фактом).
- **Дубли-переоткрытия:** MinerU 2× (16.05 entera-analog + 01.07); claude-mem≈memanto (авто-память).
- **Отсеяно как решённое-НЕТ (НЕ забытьё):** marker/surya (GPL «не интегрируем»), rsp2k (непроверенность). teammate-tmux архивирован (поглощён Workflow).
Детали — `0_СТАТУС_программы.md` + session-report `2026-07-01_faza1b-zabytoe`.
