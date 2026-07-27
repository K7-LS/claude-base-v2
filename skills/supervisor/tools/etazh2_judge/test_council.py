# test_council.py — приёмка агрегатора совета (council.aggregate) на синтетике. Без спавна.
# Запуск: $env:PYTHONIOENCODING='utf-8'; python test_council.py
import sys, io, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import council

_pass, _fail = 0, 0
def check(name, cond, detail=""):
    global _pass, _fail
    ok = bool(cond); _pass += ok; _fail += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))

OK_REVIEW = {"task_completed_ok": True, "truthfulness_call_ok": True,
             "accusations_grounded": True, "escalation_call_ok": True}
def member(agrees, review=None, corrected=None, escalate=False, method="m", one_liner="x"):
    return {"agrees_with_judge1": agrees, "judge1_verdict_review": review or dict(OK_REVIEW),
            "corrected_verdict": corrected, "escalate_to_owner": escalate,
            "method": method, "one_liner": one_liner}

print("=== АГРЕГАЦИЯ СОВЕТА ===")

# 1. Единогласное согласие (3 agree) → совет согласен, unanimous-флаг, corrected=None
s = council.aggregate([member(True, method="inversion"), member(True, method="first_principles"),
                       member(True, method="naive")])
check("3 agree: совет СОГЛАСЕН", s["agrees_with_judge1"] is True, s)
check("3 agree: unanimous", s["unanimous"] is True, s)
check("3 agree: флаг correlated-bias", any("unanimous" in f for f in s["council_flags"]), s["council_flags"])
check("3 agree: corrected=None", s["corrected_verdict"] is None, s)

# 2. Единогласное несогласие по СУЩЕСТВУ (кейс №4-подобный) → совет не согл., существенное, corrected взят
disc = {"task_completed_ok": True, "truthfulness_call_ok": False,
        "accusations_grounded": False, "escalation_call_ok": False}
corr = {"task_completed": "yes", "self_report_truthful": True, "quality_score_0_10": 7, "escalate_to_owner": False}
s = council.aggregate([member(False, disc, corr, True, "inversion"),
                       member(False, disc, corr, True, "first_principles"),
                       member(False, disc, corr, True, "naive")])
check("3 disagree(существ.): совет НЕ согласен", s["agrees_with_judge1"] is False, s)
check("3 disagree: truthfulness_call_ok=False (существенное)", s["judge1_verdict_review"]["truthfulness_call_ok"] is False, s)
check("3 disagree: corrected взят", s["corrected_verdict"] == corr, s)
check("3 disagree: unanimous-флаг", s["unanimous"] is True, s)

# 3. Раскол 1 disagree / 2 agree → совет СОГЛАСЕН (большинство), split-флаг
s = council.aggregate([member(False, disc, corr, True, "inversion"),
                       member(True, method="first_principles"), member(True, method="naive")])
check("split 1/2: совет СОГЛАСЕН (большинство)", s["agrees_with_judge1"] is True, s)
check("split 1/2: split-флаг", any("split" in f for f in s["council_flags"]), s["council_flags"])
check("split 1/2: НЕ unanimous", s["unanimous"] is False, s)

# 4. Несогласное большинство по РАЗНЫМ существенным ключам → существенное не теряется
d1 = {**OK_REVIEW, "truthfulness_call_ok": False}
d2 = {**OK_REVIEW, "accusations_grounded": False}
s = council.aggregate([member(False, d1, corr, True, "inversion"),
                       member(False, d2, corr, True, "naive"), member(True, method="fp")])
check("2 disagree разн.ключи: совет НЕ согласен", s["agrees_with_judge1"] is False, s)
check("2 disagree разн.ключи: truthfulness ИЛИ accusations = False (существенное сохранено)",
      s["judge1_verdict_review"]["truthfulness_call_ok"] is False or s["judge1_verdict_review"]["accusations_grounded"] is False, s)

# 5. Несогласие ТОЛЬКО по оценке (task_completed_ok) → существенные ключи ok (мягкое)
soft = {"task_completed_ok": False, "truthfulness_call_ok": True,
        "accusations_grounded": True, "escalation_call_ok": True}
s = council.aggregate([member(False, soft, corr, True, "inversion"),
                       member(False, soft, corr, True, "naive"), member(False, soft, corr, True, "fp")])
check("3 disagree(оценка): существенные ключи ok (→ мягкое)",
      s["judge1_verdict_review"]["truthfulness_call_ok"] and s["judge1_verdict_review"]["accusations_grounded"]
      and s["judge1_verdict_review"]["escalation_call_ok"], s["judge1_verdict_review"])

print(f"\n=== ИТОГ: PASS={_pass}  FAIL={_fail} ===")
sys.exit(1 if _fail else 0)
