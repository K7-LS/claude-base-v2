# screenshot-source-zoom.ps1 — PreToolUse hook (этаж «визуальная сверка»).
# Срабатывает перед скрин-инструментами (matcher "screenshot|zoom" в settings.json).
# Инжектит модели напоминание (anti-pattern A11.1): для чтения МЕЛКОЙ детали поднимай
# разрешение У ИСТОЧНИКА, а не цифровым зумом готового растра (та же пиксельная каша).
# НЕ блокирует (allow) — только additionalContext. Обзорный скрин делается как обычно.
$ErrorActionPreference = "SilentlyContinue"
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$msg = "Скрин для чтения МЕЛКОЙ детали (текст/размер/номер)? Сначала подними разрешение " +
       "У ИСТОЧНИКА, не цифровой зум готового растра — пикселей не прибавится, будет та же " +
       "каша: (1) нативный зум В САМОМ ПО — AutoCAD/Revit колесом к области, браузер Ctrl-«+», " +
       "PDF-viewer масштаб — потом скрин; (2) растр из PDF (*_pN.png) → вернись к PDF: текст-слой " +
       "pdf-mcp (pdf_search/pdf_read_pages) или pdf_render_pages в высоком DPI; (3) скан без " +
       "текст-слоя → OCR (skill image-text-replace). Для ОБЗОРНОГО скрина — игнорируй это. [A11.1]"

@{ hookSpecificOutput = @{ hookEventName = "PreToolUse"; additionalContext = $msg } } |
    ConvertTo-Json -Compress -Depth 5
exit 0
