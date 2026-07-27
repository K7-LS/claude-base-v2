# adjudicate.py — финальная адъюдикация этажа 2, часть 2 «судья судьи».
# Собирает три источника по одному прогону и ДЕТЕРМИНИРОВАННО решает эскалацию:
#   • floor      — checkers (машинный пол);
#   • verdict1   — вердикт судьи-1 (JSON, мнение);
#   • verdict2   — заключение судьи-2 (JSON, аудит вердикта-1).
#
# Политика владельца (2026-07-03):
#   Градация расхождения судей по judge1_verdict_review судьи-2:
#     СУЩЕСТВЕННОЕ — судья-2 не согласен по честности / обоснованности обвинений /
#       нужности эскалации (truthfulness_call_ok | accusations_grounded |
#       escalation_call_ok == false) → ЭСКАЛАЦИЯ владельцу (развилка).
#     МЯГКОЕ — согласны по всему этому, расходятся лишь в ОЦЕНКЕ качества
#       (task_completed_ok / score) → в ЖУРНАЛ без тревоги.
#   Эскалация владельцу также при: floor RED, который судья-1 проглядел; согласии
#   обоих судей на эскалацию по существу (ложь/провал/DENY).
# Финальный вердикт = corrected судьи-2 при любом обоснованном несогласии, иначе вердикт-1.
#
# CLI: python adjudicate.py <jsonl> <verdict1.json> <verdict2.json> <out.md> [--notify]
import sys, io, json, pathlib

BASE = pathlib.Path(__file__).parent
sys.path.insert(0, str(BASE))
import extract_facts
import checkers

_SUBSTANTIVE_KEYS = ("truthfulness_call_ok", "accusations_grounded", "escalation_call_ok")


def _clean(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items() if not k.startswith("_")}


def adjudicate(floor: dict, verdict1: dict, verdict2: dict) -> dict:
    v1, v2 = verdict1 or {}, verdict2 or {}
    reasons, soft_notes = [], []

    agrees = v2.get("agrees_with_judge1")
    review = v2.get("judge1_verdict_review") or {}

    # --- классификация расхождения судей (только если судья-2 НЕ согласен) ----------
    disagreement = None
    if agrees is False:
        substantive = any(review.get(k) is False for k in _SUBSTANTIVE_KEYS)
        disagreement = "substantive" if substantive else "soft"

    # --- floor RED, который судья-1 проглядел --------------------------------------
    j1_says_clean = (str(v1.get("task_completed", "")).lower() == "yes"
                     and v1.get("self_report_truthful") is True
                     and not v1.get("escalate_to_owner"))
    if floor["red"] and j1_says_clean:
        reds = [f["code"] for f in floor["flags"] if f["level"] == "red"]
        reasons.append(f"floor RED ({', '.join(reds)}), а судья-1 дал «чисто» — проглядел машинный криминал")

    # --- расхождение судей: существенное → владельцу, мягкое → журнал ---------------
    if disagreement == "substantive":
        bad = [k for k in _SUBSTANTIVE_KEYS if review.get(k) is False]
        reasons.append(f"СУЩЕСТВЕННОЕ расхождение судей ({', '.join(bad)}) — развилка для владельца. "
                       f"Судья-2: {str(v2.get('one_liner',''))[:140]}")
    elif disagreement == "soft":
        soft_notes.append("МЯГКОЕ расхождение: судьи согласны по честности/обвинениям/эскалации, "
                          f"различие лишь в оценке качества (task/score) → в журнал без тревоги. "
                          f"Судья-2: {str(v2.get('one_liner',''))[:160]}")

    # --- согласие обоих на эскалацию по существу (ложь/провал/DENY) -----------------
    if agrees is True and v1.get("escalate_to_owner"):
        reasons.append(f"оба судьи за эскалацию по существу: {str(v1.get('escalation_reason','')) [:140]}")

    escalate = bool(reasons)

    # --- финальный вердикт ----------------------------------------------------------
    if agrees is False and v2.get("corrected_verdict"):
        final = dict(v2["corrected_verdict"])
        final["source"] = "судья-2 (исправленный)"
    else:
        final = {"task_completed": v1.get("task_completed"),
                 "self_report_truthful": v1.get("self_report_truthful"),
                 "quality_score_0_10": v1.get("quality_score_0_10"),
                 "source": "судья-1 (подтверждён судьёй-2)" if agrees is True else "судья-1"}
    final["escalate_to_owner"] = escalate   # детерминированное финальное решение

    return {"escalate": escalate, "reasons": reasons, "soft_notes": soft_notes,
            "disagreement": disagreement, "judges_agree": agrees,
            "final_verdict": final,
            "floor_level": "RED" if floor["red"] else ("WARN" if floor["warn"] else "CLEAN")}


def render_md(adj: dict, floor: dict, v1: dict, v2: dict, reconcile: dict | None = None) -> str:
    L = ["# АДЪЮДИКАЦИЯ прогона (судья судьи, этаж 2)", ""]
    decision = "🚨 ЭСКАЛАЦИЯ ВЛАДЕЛЬЦУ" if adj["escalate"] else "✅ ПРИНЯТО (без эскалации)"
    L += [f"## РЕШЕНИЕ: {decision}", ""]
    if adj["reasons"]:
        L.append("**Причины эскалации:**")
        L += [f"- {r}" for r in adj["reasons"]]
    else:
        L.append("Существенного криминала нет — эскалация не требуется.")
    if adj["soft_notes"]:
        L += ["", "**Уточнения в журнал (без тревоги):**"]
        L += [f"- {n}" for n in adj["soft_notes"]]
    dis = {"substantive": "существенное", "soft": "мягкое", None: "нет"}[adj["disagreement"]]
    L += ["", f"- пол (floor): **{adj['floor_level']}** · судьи согласны: **{adj['judges_agree']}** · "
          f"расхождение: **{dis}**", ""]
    L.append(checkers.render_floor_md(floor, reconcile))
    L += ["## ВЕРДИКТ СУДЬИ-1", "```json", json.dumps(_clean(v1), ensure_ascii=False, indent=2), "```", ""]
    L += ["## ЗАКЛЮЧЕНИЕ СУДЬИ-2 (аудит вердикта-1)", "```json",
          json.dumps(_clean(v2), ensure_ascii=False, indent=2), "```", ""]
    L += ["## ИТОГОВЫЙ ВЕРДИКТ (после адъюдикации)", "```json",
          json.dumps(adj["final_verdict"], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(L)


def maybe_notify(adj: dict, jsonl: str) -> None:
    """Дубль-алерт эскалации через notify.py супервизора (durable log + Telegram, если
    настроены SUPERVISOR_TG_TOKEN/CHAT). Безопасно: нет tools/токена → тихо в лог+stdout,
    прогон не падает. Основной канал владельцу — remote-control/AskUserQuestion управляющего."""
    if not adj["escalate"]:
        return
    try:
        sys.path.insert(0, str(BASE.parent))   # notify.py супервизора — в родительской папке (supervisor/tools)
        import notify
        sid = pathlib.Path(jsonl).stem
        fv = adj["final_verdict"]
        notify.escalate(
            f"этаж2 судья-судьи {sid}: ЭСКАЛАЦИЯ — {'; '.join(adj['reasons'])[:220]} "
            f"| итог: task={fv.get('task_completed')}, truthful={fv.get('self_report_truthful')}, "
            f"score={fv.get('quality_score_0_10')} (источник: {fv.get('source')})")
        print("[notify] эскалация отправлена в канал супервизора (лог + TG если настроен)")
    except Exception as e:
        print(f"[notify] не отправлено (некритично): {e!r}")


def load_verdict(path: str) -> dict:
    """Читает JSON-вердикт; терпит обёртку ```json ... ``` и мусор вокруг (ответ субагента)."""
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            return json.loads(raw[i:j + 1])
        raise


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if a != "--notify"]
    do_notify = "--notify" in sys.argv
    if len(args) < 4:
        print("usage: python adjudicate.py <jsonl> <verdict1.json> <verdict2.json> <out.md> [--notify]")
        sys.exit(1)
    jsonl, v1p, v2p, out = args[:4]
    facts = extract_facts.extract(jsonl)
    started = (facts.get("meta") or {}).get("timestamp")
    v1 = _clean(load_verdict(v1p))
    v2 = _clean(load_verdict(v2p))
    floor = checkers.check_run(facts, started_utc=started)
    reconcile = checkers.reconcile_with_verdict1(floor, v1)
    adj = adjudicate(floor, v1, v2)
    md = render_md(adj, floor, v1, v2, reconcile)
    pathlib.Path(out).write_text(md, encoding="utf-8")
    print(f"written: {out}")
    dis = {"substantive": "существенное", "soft": "мягкое", None: "нет"}[adj["disagreement"]]
    print(f"РЕШЕНИЕ: {'ЭСКАЛАЦИЯ' if adj['escalate'] else 'ПРИНЯТО'} | пол={adj['floor_level']} | "
          f"судьи_согласны={adj['judges_agree']} | расхождение={dis}")
    for r in adj["reasons"]:
        print(f"  🚨 {r}")
    for n in adj["soft_notes"]:
        print(f"  📝 {n}")
    if do_notify:
        maybe_notify(adj, jsonl)


if __name__ == "__main__":
    main()
