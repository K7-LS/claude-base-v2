// ТН-приёмка тома ИД — параметризованный Workflow-шаблон.
// Запуск: Workflow({ scriptPath: ".../priemka_workflow.js", args: {...} })
// args:
//   pdf          (string, required) — путь к собранному тому PDF
//   map          (string, required) — эталонная карта "страница: что должно быть" (из build_map.py + ручные дополнения)
//   forbidden    (string, required) — список ЗАПРЕЩЁННОГО (старое/удалённое/чужое) + исключения (многомодельные паспорта)
//   pages        (number, optional) — всего страниц (если не задано — агент берёт из pdf_info)
//   batch        (number, default 10)  — страниц на одного проверяющего
//   model        (string, default 'sonnet') — модель агентов 1-й фазы (review)
//   verifyModel  (string, default 'sonnet') — модель агентов фазы верификации
//   effort       (string, default 'medium')
// ТОЧКА РАСШИРЕНИЯ (ПТО): перед запуском дать пользователю выбрать model/batch и показать прогноз токенов.

export const meta = {
  name: 'tn-priemka-toma',
  description: 'ТН-приёмка тома ИД: постраничная проверка с верификацией находок',
  phases: [
    { title: 'Постраничная проверка', detail: 'агенты по N стр (vision/OCR)' },
    { title: 'Верификация', detail: 'адверсариальная перепроверка CRITICAL/MAJOR' },
  ],
}

const A = args || {}
const PDF = A.pdf
const MAP = A.map || '(карта не передана — агент опирается на штампы и здравый смысл ТН)'
const FORB = A.forbidden || '(список запрещённого не передан)'
const TOTAL = A.pages || 0
const BATCH = A.batch || 10
const MODEL = A.model || 'sonnet'
const VMODEL = A.verifyModel || 'sonnet'
const EFFORT = A.effort || 'medium'

const RULES = `ТЫ — СТРОГИЙ, ПРИДИРЧИВЫЙ ТЕХНИЧЕСКИЙ НАДЗОР, принимающий том ИД. Смотри КАЖДУЮ страницу глазами (рендер), не пропускай ничего; лучше отметить сомнительное, чем пропустить.
СМОТРЕТЬ (pdf-mcp): pdf_render_pages(path=<путь>, pages="<N>", dpi 100-120); oversized → Read PNG с диска (file_path_on_disk) или clip=[x0,y0,x1,y1] (доли 0..1; штамп правый-низ [0.6,0.8,1,1]); сканы — читать глазами (vision).
ЧЕК-ЛИСТ: 1.ЦЕЛОСТНОСТЬ (пустая/чёрная/перевёрнутая/дубль/обрезана); 2.ОРИЕНТАЦИЯ (навигаторы/реестры — книжная); 3.ОФОРМЛЕНИЕ (штамп на месте, ФИО/подписи не обрезаны, нет цветной заливки/рекламных хвостов фабричных инструкций); 4.СООТВЕТСТВИЕ карте; 5.ЗАПРЕЩЁННОЕ (см. ниже); 6.РЕЕСТРЫ (нумерация без разрывов, листаж, жирность); 7.КОНСИСТЕНТНОСТЬ (даты/номера актов/шифр).
ЗАПРЕЩЁННОЕ:\n${FORB}\n
severity: CRITICAL (старое/удалённое оборуд, чужой раздел, битая/пустая/чужая страница, неверный акт); MAJOR (обрезка текста, кривой/отсутствующий штамп, неверная ориентация навигатора, разрыв нумерации, неподписанный акт, просроченный/образец-документ); MINOR (косметика); INFO. Идеальная страница — finding не создавать.`

const FINDINGS = { type: 'object', additionalProperties: false, properties: {
  range: { type: 'string' }, pages_checked: { type: 'array', items: { type: 'integer' } },
  findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
    page: { type: 'integer' },
    severity: { type: 'string', enum: ['CRITICAL', 'MAJOR', 'MINOR', 'INFO'] },
    category: { type: 'string', enum: ['целостность','ориентация','оформление','соответствие','запрещённое','реестр','консистентность'] },
    issue: { type: 'string' }, detail: { type: 'string' },
  }, required: ['page','severity','category','issue','detail'] } },
}, required: ['range','pages_checked','findings'] }

const VERDICT = { type: 'object', additionalProperties: false, properties: {
  page: { type: 'integer' }, confirmed: { type: 'boolean' },
  severity_final: { type: 'string', enum: ['CRITICAL','MAJOR','MINOR','INFO','FALSE_ALARM'] },
  explanation: { type: 'string' },
}, required: ['page','confirmed','severity_final','explanation'] }

if (!TOTAL) throw new Error('Передай args.pages (всего страниц) — узнай через pdf_info заранее.')
const BATCHES = []
for (let s = 1; s <= TOTAL; s += BATCH) BATCHES.push({ a: s, b: Math.min(s + BATCH - 1, TOTAL) })

phase('Постраничная проверка')
log(`ТН-приёмка: ${BATCHES.length} агентов (${MODEL}) по ${BATCH} стр, том ${TOTAL} стр.`)
const reviews = await parallel(BATCHES.map((bt) => () =>
  agent(`${RULES}\n\nТОМ (pdf): ${PDF}\n\nКАРТА:\n${MAP}\n\nТВОЙ УЧАСТОК: страницы ${bt.a}-${bt.b}. Прорендерь и придирчиво проверь КАЖДУЮ. Верни все несоответствия; pages_checked — все реально просмотренные.`,
    { label: `ТН ${bt.a}-${bt.b}`, phase: 'Постраничная проверка', schema: FINDINGS, model: MODEL, effort: EFFORT })
))
const all = reviews.filter(Boolean).flatMap((r) => (r.findings || []).map((f) => ({ ...f, range: r.range })))
const checked = new Set(reviews.filter(Boolean).flatMap((r) => r.pages_checked || []))
log(`Проверено ${checked.size}/${TOTAL}. Сырых находок: ${all.length}.`)

phase('Верификация')
const toVerify = all.filter((f) => f.severity === 'CRITICAL' || f.severity === 'MAJOR')
log(`Верификация ${toVerify.length} находок (CRITICAL/MAJOR), модель ${VMODEL}.`)
const verds = await parallel(toVerify.map((f) => () =>
  agent(`Ты — ВТОРОЙ, ещё более скептичный ТН. Перепроверь претензию сам (открой страницу), не верь на слово.\nТОМ: ${PDF}\npdf_render_pages(path=..., pages="${f.page}", dpi 110); oversized→Read PNG/clip.\nПретензия к стр.${f.page} [${f.severity}/${f.category}]: ${f.issue}\nДетали: ${f.detail}\nОжидание по карте:\n${MAP}\nconfirmed=true если РЕАЛЬНА; false если ложная/норма. severity_final — итог. В explanation — что видишь.`,
    { label: `проверка стр.${f.page}`, phase: 'Верификация', schema: VERDICT, model: VMODEL, effort: EFFORT })
    .then((v) => (v ? { ...f, verdict: v } : null))
))
const ver = verds.filter(Boolean)
const confirmed = ver.filter((v) => v.verdict.confirmed && v.verdict.severity_final !== 'FALSE_ALARM')
const lvl = (L) => confirmed.filter((c) => c.verdict.severity_final === L).map((c) => ({ page: c.page, issue: c.issue, why: c.verdict.explanation }))

return {
  pages_checked: checked.size, raw_findings: all.length, verified: ver.length,
  confirmed_critical: lvl('CRITICAL'), confirmed_major: lvl('MAJOR'),
  confirmed_minor: lvl('MINOR'),
  minor_unverified: all.filter((f) => f.severity === 'MINOR').map((f) => ({ page: f.page, issue: f.issue, detail: f.detail })),
  false_alarms: ver.filter((v) => !v.verdict.confirmed || v.verdict.severity_final === 'FALSE_ALARM').map((v) => ({ page: v.page, claim: v.issue, why: v.verdict.explanation })),
}
