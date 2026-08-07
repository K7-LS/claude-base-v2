---
created: 2026-06-04
updated: 2026-06-04
status: active
owner: <владелец базы>
tags: [reference, autocad, autocad-mcp, кириллица, lisp, com, file_ipc]
related:
  - [[2026-05-21_acad-com-cookbook]]
  - [[reference_autocad_pdf_overlay_mcp]]
  - [[reference_acad_ov_dwg_recreation]]
  - [[anti-patterns]]
---

# autocad-mcp: кириллица (вход/выход) + открытие документа

Загружать по триггерам: «autocad-mcp кириллица», «русские слои/блоки AutoCAD», «execute_lisp
кириллица», «drawing open не работает», «не тот активный документ AutoCAD».

Общий урок для ЛЮБЫХ задач через autocad-mcp (backend `file_ipc`, живой AutoCAD по COM),
не только квартир. Дополняет [[2026-05-21_acad-com-cookbook]] и [[reference_autocad_pdf_overlay_mcp]].

## Кириллица — АСИММЕТРИЯ вход/выход

- **ВХОД (запись) — писать кириллицу ПРЯМО в коде LISP** (доходит как Unicode):
  `(vla-InsertBlock ms pt "Воздуховод" 1 1 1 0)`, `(vla-put-Layer ref "!Приток")`,
  имена dyn-свойств кириллицей — работают.
  ❌ **НЕ реконструировать через `(chr N)` по cp1251:** «В» = Unicode 1042, не 194;
  `(chr 194)` = `Â` → InsertBlock ищет внешний `.dwg` → «Ошибка файлера».
- **ВЫХОД (чтение) — русские имена приходят в cp1251** (в JSON выглядят как `Ïð…`).
  Длинные списки (слои/блоки/листы): LISP пишет дамп в файл, читать PowerShell в cp1251:
  ```lisp
  (setq f (open "C:/temp/dump.txt" "w")) (write-line имя f) ... (close f)
  ```
  ```powershell
  $enc=[Text.Encoding]::GetEncoding(1251); [IO.File]::ReadAllText("C:\temp\dump.txt",$enc)
  ```

## `drawing open` (MCP) ВРЁТ — открывать через COM

- MCP-команда `drawing open` возвращает «opened», но **активный документ НЕ меняется**
  (ни кириллица, ни ASCII путь). 
- ✅ Открывать через COM:
  ```lisp
  (vla-Open (vla-get-Documents (vlax-get-acad-object)) "C:\\temp\\x.dwg")
  ```
  затем **отдельным вызовом** (переключение применяется ПОСЛЕ выхода из LISP):
  `(vla-put-ActiveDocument (vlax-get-acad-object) tgt)`.
  Проверять `(getvar "DWGNAME")`.
- **Рабочий путь — ASCII** (`C:\temp\*.dwg`); кириллицу в путях обходить, в финале копировать
  в проектную папку PowerShell-ом.

## Связанные общие грабли autocad-mcp (см. соседние reference)

- backend выбирается при старте → `system status`/`system init` (file_ipc).
- `execute_lisp` не возвращает stdout — писать в файл, читать (cp1251).
- модальный диалог вешает IPC (таймаут) → `AppActivate($pid)`+`SendKeys("{ESC}")`.
- печать в PDF — `vla-PlotToFile` (MCP `plot_pdf`/COM PlotToFile часто дают пустой PDF;
  для превью — `PNGOUT` зоны).

## Источник

feedback `2026-06-04_autocad-pdf-to-dwg` (R-090226727A), локальный `reference_autocad_mcp_cyrillic`.
