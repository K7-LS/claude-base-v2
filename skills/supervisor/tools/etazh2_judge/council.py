# council.py — агрегатор СОВЕТА судей-2 (этаж 2, часть 3, точка №1 «судья судьи как совет»).
#
# Превращает N независимых заключений судей-2 — каждый вынес свой вердикт СВОИМ МЕТОДОМ
# рассуждения (инверсия / первопринципы / наивный аудит) — в ОДИН синтез в ФОРМАТЕ verdict2.
# Благодаря этому adjudicate.py потребляет синтез совета БЕЗ изменений (тот же контракт).
#
# Механизмы против groupthink (из PoLL / Diverse Multi-Agent Debate):
#   • мажоритарный вердикт (не один критик — панель);
#   • dissent фиксируется (раскол показывается, не прячется);
#   • ФЛАГ correlated-bias при ЕДИНОГЛАСИИ — единодушие есть самый опасный failure mode:
#     надёжно, только если РАЗНЫЕ методы дали РАЗНЫЕ доводы к одному выводу, а не копию.
#
# CLI: python council.py <out_synthesis.json> <member1.json> <member2.json> [...]
import json, sys, io, pathlib

REVIEW_KEYS = ("task_completed_ok", "truthfulness_call_ok", "accusations_grounded", "escalation_call_ok")


def aggregate(members: list) -> dict:
    """members = список заключений судей-2 (agrees_with_judge1, judge1_verdict_review,
    corrected_verdict, escalate_to_owner, one_liner, method?). → verdict2-совместимый синтез."""
    members = [m for m in members if m]
    n = len(members)
    if n == 0:
        return {}

    agrees = [m.get("agrees_with_judge1") for m in members]
    n_agree = sum(1 for a in agrees if a is True)
    n_disagree = sum(1 for a in agrees if a is False)
    council_agrees = n_agree > n_disagree                      # мажоритарно
    unanimous = n >= 2 and (n_agree == n or n_disagree == n)

    # сторона большинства — её мнением синтезируем
    side = [m for m in members if m.get("agrees_with_judge1") is council_agrees]

    # агрегированный judge1_verdict_review: ключ ok=False, если ХОТЬ ОДИН судья стороны
    # большинства возразил по нему. Консервативно к существенному: любое существенное
    # возражение большинства (честность/обвинения/эскалация) идёт к владельцу, а
    # чисто-оценочное расхождение (task/score) остаётся мягким.
    agg_review = {}
    for k in REVIEW_KEYS:
        agg_review[k] = not any((m.get("judge1_verdict_review") or {}).get(k) is False for m in side)

    flags = []
    if unanimous:
        flags.append("unanimous — единодушие судей: проверить, что разные методы дали РАЗНЫЕ "
                     "доводы к одному выводу (надёжно), а не одинаковую копию (theatrical-consensus)")
    if n_agree and n_disagree:
        flags.append(f"split {n_agree}/{n_disagree} — совет разделился, dissent зафиксирован")

    corrected = next((m.get("corrected_verdict") for m in side if m.get("corrected_verdict")), None)

    per_member = "; ".join(f"[{m.get('method', '?')}] {str(m.get('one_liner', ''))[:110]}" for m in members)
    return {
        "agrees_with_judge1": council_agrees,
        "judge1_verdict_review": agg_review,
        "corrected_verdict": corrected if not council_agrees else None,
        "escalate_to_owner": any(m.get("escalate_to_owner") for m in members),
        "reason": f"СОВЕТ {n} судей разными методами ({n_agree} согл./{n_disagree} несогл.). {per_member}",
        "one_liner": (f"Совет {n} судей: {'СОГЛАСЕН' if council_agrees else 'НЕ согласен'} с судьёй-1 "
                      f"({n_agree}/{n})" + (" · " + " · ".join(flags) if flags else "")),
        "council_flags": flags,
        "n_members": n, "n_agree": n_agree, "n_disagree": n_disagree, "unanimous": unanimous,
    }


def _load(path):
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        return json.loads(raw[i:j + 1]) if i >= 0 and j > i else {}


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        print("usage: python council.py <out_synthesis.json> <member1.json> [member2.json ...]")
        sys.exit(1)
    out, member_paths = sys.argv[1], sys.argv[2:]
    members = [_load(p) for p in member_paths]
    synthesis = aggregate(members)
    pathlib.Path(out).write_text(json.dumps(synthesis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {out}")
    print(f"СОВЕТ: {'СОГЛАСЕН' if synthesis['agrees_with_judge1'] else 'НЕ согласен'} с судьёй-1 "
          f"| {synthesis['n_agree']}/{synthesis['n_members']} согл. | unanimous={synthesis['unanimous']}")
    for f in synthesis["council_flags"]:
        print(f"  ⚑ {f}")


if __name__ == "__main__":
    main()
