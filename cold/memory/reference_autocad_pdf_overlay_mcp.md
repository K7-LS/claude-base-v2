---
created: 2026-06-03
updated: 2026-06-03
status: active
owner: <владелец базы>
tags: [reference, pdf, autocad, autocad-mcp, разметка, pdfimport]
related:
  - [[reference_autocad_pdf_svg_markup]]
  - [[2026-05-21_acad-com-cookbook]]
  - [[reference_inkscape_pdf_editing]]
  - [[anti-patterns]]
---

# Правка наложения на AutoCAD-PDF через autocad-mcp (живой AutoCAD / PDFIMPORT)

Загружать по триггерам: «перерисовать наложение на чертеже-PDF **с возвратом в
DWG**», «PDFIMPORT», «autocad-mcp правка чертежа», когда на выходе нужен DWG (а не
только PDF). Если DWG не нужен — легче через [[reference_autocad_pdf_svg_markup]].

## Контекст

Тот же класс задачи, что [[reference_autocad_pdf_svg_markup]] (наложение схемы
СС/ЭО поверх чертежа, пришедшего только в PDF), но через **живой AutoCAD** —
даёт DWG на выходе. **2026-06-03**: сделаны 2 варианта (DWG+PDF), векторное
качество подложки сохранено, pipeline воспроизводим.

## Главные технические уроки

1. **Backend autocad-mcp выбирается при СТАРТЕ сервера.** Если AutoCAD запущен
   ПОЗЖЕ Claude Code — `system status` даёт `backend=ezdxf` (файловый: НЕ умеет
   PDFIMPORT, `can_plot_pdf:false`, нет `execute_lisp`). Лечится `system init`
   → `backend=file_ipc` (живой AutoCAD по COM, все capabilities `true`).
   **Всегда проверять backend и при ezdxf делать init.**
2. **`execute_lisp` возвращает значение ПОСЛЕДНЕГО выражения** (строкой) в
   `payload`; `(princ)` НЕ возвращается → последним делать нужную строку
   (`strcat`). `include_screenshot:true` отдаёт огромный base64 и картинкой, и
   текстом — жжёт контекст, избегать; верификация через counts + `vla-PlotToFile`
   + рендер pdf-mcp. (См. также [[2026-05-21_acad-com-cookbook]] — stdout в
   file_ipc не возвращается, писать в файл, читать `Get-Content -Encoding default`,
   AutoLISP пишет CP1251.)
3. **PDFIMPORT разрушает «толстое» наложение.** Толстые штрихи тесселлируются в
   тысячи мелких SOLID/HATCH на слое `PDF_Сплошная заливка`; цвет уходит в ByLayer
   на нейтральный `PDF_Геометрия`. Искать «жирную красную линию» по цвету/толщине
   ПОСЛЕ импорта бесполезно. **Вывод: наложение не редактировать в импорте, а
   строить заново.**
4. **Рабочий приём — ГИБРИД:** идентификация наложения в исходном PDF через
   PyMuPDF `get_drawings` (в page-space сигнатура «цвет+толщина» работает идеально:
   25 лучей, 19 кружков, 4 квадрата); геометрию переносим в AutoCAD и строим чистый
   слой заново. Прямую байт-правку потока PyMuPDF НЕ делать (вложенные cm/повороты,
   мастер-масштаб 0.12, унаследованные толщины).
5. **Трансформ page→model при PDFIMPORT (scale 1, ins 0,0):** равномерный,
   `model_x = k·page_x`, `model_y = k·(H − page_y)` (Y-flip!), `k ≈ extents_x /
   page_width_pt`. Калибровать по extents/underlay, НЕ по «похожим» сущностям
   (камеры импортируются как не-красные фрагменты → поиск красного даёт промахи).
   Реперные метки уникальным цветом не годятся, если этот цвет есть в подложке.
6. **Печать в PDF: только `vla-PlotToFile`** —
   `(vla-PlotToFile (vla-get-Plot doc) path "DWG To PDF.pc3")` при
   `BACKGROUNDPLOT=0`; печатает текущий вид → `ZOOM E`/`ZOOM W` задаёт область.
   **MCP `drawing plot_pdf` молча НЕ создаёт файл** (возвращает ok+путь, файла нет).
   **`EXPORTPDF` открывает МОДАЛЬНЫЙ диалог даже при `FILEDIA=0` → IPC виснет
   (Timeout)**; восстановление — PowerShell `WScript.Shell.AppActivate($acadPid)` +
   `SendKeys("{ESC}")`.
7. **`-INSERT` применяет коэффициент единиц** (наблюдали ~1/25: «5» → scale 0.2)
   → масштаб блока задавать через `entmod` групп 41/42/43, не аргументом -INSERT.
8. **PDF-плот из AutoCAD НЕ передаёт полупрозрачность.** Solid-заливка зоны →
   непрозрачный блин; hatch `ANSI31` в «единицах PDF» сливается в сплошняк.
   Надёжно читается **контур** (closed LWPOLYLINE) сектора. Нужна закраска —
   включать настоящую прозрачность печати в плоттере.
9. **Блоки — через `entmake`** (BLOCK→entities `(62 . 0)` ByBlock→ENDBLK).
   Разворот камеры = угол биссектрисы её лучей (atan2 после Y-flip в model-space),
   вставлять как rotation. Сектор = угловой диапазон крайних лучей + дальняя дуга;
   радиус ОБЯЗАТЕЛЬНО капить (длинные лучи оригинала → конусы вылезают за участок).

## Чек-лист

1. AutoCAD запущен → `system init` (добиться `file_ipc`).
2. PDF в ASCII-путь (кириллица/скобки ломают cmdline); `FILEDIA=0`.
3. PyMuPDF: геометрия наложения в page-space (цвет+толщина) → JSON.
4. `-PDFATTACH` + `-PDFIMPORT` (опц., для калибровки extents) → k и Y-flip.
5. `entmake` блоков; новый слой; рисовать заново по трансформу. Масштаб — `entmod`.
6. `ZOOM E` → `vla-PlotToFile ... "DWG To PDF.pc3"`; верификация рендером pdf-mcp.
7. НЕ использовать EXPORTPDF (модальный) и MCP `plot_pdf` (не пишет файл).

## Косяки базы для фикса (backlog)

- MCP `drawing plot_pdf` возвращает ok+путь, но файл не создаёт — починить или
  задокументировать в autocad-mcp.
- Прозрачность/штриховка зон при печати DWG→PDF — нужен рецепт настройки плоттера.

## Источник

feedback `2026-06-03_autocad-mcp-pdf-overlay-edit` от R-090226727A (по явной просьбе
пользователя — наработку в базу как развитие работы через AutoCAD).
