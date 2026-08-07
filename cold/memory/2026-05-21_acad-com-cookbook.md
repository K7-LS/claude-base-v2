# AutoCAD COM cookbook — работа с DXF и ACAD_TABLE через pywin32

**Дата:** 2026-05-21
**Контекст:** session-report 2026-05-21_acad-mcp-hovs-tables (заметка не заведена), тестирование AutoCAD MCP на проекте «Современная Москва К-12». Заполнение двух таблиц ХОВС через COM (где ezdxf не справился).

## TL;DR

**Правильный путь — autocad-mcp File IPC backend через AutoLISP-плагин** (см. секцию «File IPC backend» внизу — добавлено 2026-05-23). Этот документ описывает **обход через прямой `win32com.client`** — он работает и полезен, но это workaround. Когда mcp_dispatch.lsp загружен в AutoCAD через Startup Suite — autocad-mcp сам переключается на File IPC, и большинство ниже описанных хаков уже не нужны.

**Для редактирования ACAD_TABLE — НЕ через `ezdxf`.** `ezdxf` редактирует MTEXT в render-cache блоке, AutoCAD затирает изменения при regen из state. Через COM `AcadTable.SetText(row, col, text)` — state-level правка, сохраняется навсегда.

---

## Установка

```powershell
py -3 -m pip install --user pywin32
```

После установки AutoCAD должен быть запущен (Dispatch цепляется к существующему instance).

## Базовый скелет

```python
import win32com.client
import pythoncom
import time

def retry(fn, attempts=30, delay=0.3):
    """RPC_E_CALL_REJECTED очень частый на LMS Tech сборке. Retry с pump."""
    for i in range(attempts):
        try:
            return fn()
        except pythoncom.com_error:
            if i == attempts - 1:
                raise
            time.sleep(delay)
            pythoncom.PumpWaitingMessages()

acad = win32com.client.Dispatch("AutoCAD.Application")
acad.Visible = True
doc = retry(lambda: acad.Documents.Open(path, False))  # ReadOnly=False
time.sleep(2)  # let AutoCAD finish loading — без этого Item() падает

ms = retry(lambda: doc.ModelSpace)
```

## Поиск таблиц в ModelSpace

`ent.ObjectName` не работает в dynamic dispatch. **Duck-typing** по `.Rows`/`.Columns`:

```python
tables = []
for ent in ms:  # iterator — стабильнее чем Item(i) loop
    try:
        r = retry(lambda: ent.Rows)
        c = retry(lambda: ent.Columns)
        if isinstance(r, int) and isinstance(c, int):
            tables.append(ent)
    except Exception:
        pass
```

## Чтение и запись ячеек

```python
t = tables[0]
text = t.GetText(row, col)        # читает с MText-форматом
t.SetText(row, col, "новый текст") # пишет — state-level
```

**Сохрани MText-форматирование** при `SetText`, иначе текст потеряет шрифт (`\fGOST Common|...;`):

```python
import re
PAT_FMT = re.compile(r"^(\{(?:\\[A-Za-z][^;]*;)+)(.*?)(\})\s*$", re.DOTALL)

def wrap_with_format(orig, new_text):
    if not orig:
        return new_text
    m = PAT_FMT.match(orig)
    if m:
        return m.group(1) + new_text + m.group(3)
    return new_text

def set_cell(table, row, col, new_text):
    orig = retry(lambda: table.GetText(row, col))
    wrapped = wrap_with_format(orig, new_text)
    retry(lambda: table.SetText(row, col, wrapped))
```

## Merge / Unmerge cells

```python
# Merged sub-header → обычные cells (для замены layout)
table.UnmergeCells(7, 7, 0, table.Columns - 1)

# Обычная data row → merged sub-header
table.MergeCells(8, 8, 0, table.Columns - 1)
```

**ВАЖНО**: после `UnmergeCells` бывший sub-header сохраняет свой стиль (italic, центрированный). Нужно скопировать `CellStyle` от соседней data row, иначе текст пойдёт курсивом:

```python
ref_style = retry(lambda: t.GetCellStyle(9, 0))           # data row
ref_text_style = retry(lambda: t.GetCellTextStyle(9, 0))  # 'GOST Common'
ref_align = retry(lambda: t.GetCellAlignment(9, 0))       # 5 = MiddleCenter
ref_height = retry(lambda: t.GetCellTextHeight(9, 0))     # 2.4

for ci in range(t.Columns):
    retry(lambda: t.SetCellStyle(7, ci, ref_style))
    retry(lambda: t.SetCellTextStyle(7, ci, ref_text_style))
    retry(lambda: t.SetCellAlignment(7, ci, ref_align))
    retry(lambda: t.SetCellTextHeight(7, ci, ref_height))
```

## Изменение количества строк

```python
table.DeleteRows(start_row, num_rows)
table.InsertRows(row_index, height, num_rows)
```

## Сохранение в DXF

```python
doc.SaveAs(out_path, 65)  # 65 = acR2018_dxf
doc.Close(False)          # don't save changes (уже сохранили в SaveAs)
```

**Константы `AcSaveAsType`** (часто путаются):

| Код | Формат |
|---|---|
| 25 | acR2004_dxf |
| 37 | acR2007_dxf |
| 49 | acR2010_dxf |
| 61 | acR2013_dxf |
| **64** | acR2018_**dwg** (НЕ DXF!) |
| **65** | acR2018_**dxf** |

Если в имени `.dxf` а тип `64` — AutoCAD сохранит как DWG и **припишет `.dwg`** к имени → получится `файл.dxf.dwg`. Расширение определяется типом, не именем.

## DST locked при SaveAs

Если `doc.SaveAs(path)` где `path` уже открыт где-то ещё (Notepad / другой AutoCAD instance / explorer preview), AutoCAD выкинет `pywintypes.com_error: Ошибка при сохранении документа`. Решения:
- Сохранять в новый файл и переименовывать
- Или попросить пользователя закрыть все открытые копии DST перед запуском

## Anti-patterns (что не работает)

**ezdxf для редактирования ACAD_TABLE** — не работает. ezdxf видит таблицу как entity с `n_rows=262113, n_cols=0, cells=[]` (мусор). Реальные данные в attached extension dictionary (TABLECONTENT object), который ezdxf не парсит. Можно отредактировать MTEXT в render-блоке `*T<id>`, но AutoCAD при regen перетрёт.

**ezdxf видит «3 ACAD_TABLE» там где одна** — extension dictionary entries ошибочно парсятся как отдельные entities. COM показывает реальную картину.

**`acad.Documents.Item(i)`** в цикле — нестабильно на LMS Tech. Используй iterator `for ent in ms`.

**`ent.ObjectName`** в dynamic dispatch — AttributeError. Используй duck-typing.

**Без `time.sleep(2)` после `Documents.Open`** — последующие COM вызовы падают на RPC_E_CALL_REJECTED.

## File IPC backend — правильный путь (добавлено 2026-05-23)

После сессии 21-23.05 выяснилось что **autocad-mcp имеет нативный File IPC backend**, который работает с DWG напрямую через AutoLISP-плагин в AutoCAD. Это устраняет необходимость в прямом `win32com.client` (всё, что описано выше).

### Настройка (one-time per machine)

1. Открыть AutoCAD (любой DWG)
2. В командной строке: `APPLOAD` → Enter
3. В диалоге **Load/Unload Applications**:
   - Browse → выбрать `~/.claude/mcp-servers/autocad-mcp/lisp-code/mcp_dispatch.lsp` → **Load**
   - То же для `attribute_tools.lsp`
4. **Startup Suite** (нижняя секция диалога) → **Contents…** → **Add…** → выбрать оба .lsp файла → **Close**

После этого AutoCAD будет автоматически загружать оба плагина при каждом запуске. autocad-mcp с `AUTOCAD_MCP_BACKEND=auto` сам обнаружит активный File IPC канал и переключится с ezdxf на file_ipc.

### Что меняется

| | До (только ezdxf) | После (file_ipc) |
|---|---|---|
| Формат файлов | Только DXF | **DWG напрямую** |
| ACAD_TABLE state-edit | Сломан (regen затирает) | Работает через AutoLISP |
| `execute_lisp` | Запрещён | **Произвольный AutoLISP** |
| Screenshot | matplotlib | **PrintWindow** (Win32, не отбирает фокус) |
| `offset / fillet / chamfer` | Нет | Да |

### Проверка backend

```
mcp__autocad-mcp__system  operation=status
# должно вернуть "backend": "file_ipc"
```

### Канал связи

JSON-файлы в `C:/temp/*.json` + `PostMessageW(WM_CHAR)` к MDIClient окну AutoCAD, триггерит `(c:mcp-dispatch)` в LISP. **Не отбирает фокус** — можно работать в других окнах параллельно.

### Когда использовать прямой `win32com.client` (как описано выше)

Только если:
- AutoCAD сборка не поддерживает AutoLISP (LT < 2024 на Windows; LT на Mac вообще не поддерживает)
- Нужны операции которых нет в LISP-плагине mcp_dispatch
- Тестируется новая функция перед добавлением в LISP-плагин

В **штатном** режиме после настройки Startup Suite — всё идёт через File IPC.

---

## Связанные

- 2026-05-21_acad-mcp-hovs-tables (заметка не заведена) — session report со всей хронологией и рабочими скриптами (`com_fill_hovs_v5.py`, `com_fill_vent_v2.py`). Также там полная инструкция по настройке Startup Suite.
- `~/.claude/skills/cad-reader/SKILL.md` — методология чтения DXF через ezdxf (для **чтения**, не редактирования)
- `~/.claude/mcp-servers/autocad-mcp/lisp-code/mcp_dispatch.lsp` — основной AutoLISP-dispatcher
