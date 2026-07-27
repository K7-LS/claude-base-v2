# extract_facts.py — детерминированный экстрактор машинных фактов из JSONL-транскрипта
# headless-воркера (этаж 2, PoC). Судья ест ЭТОТ отчёт, не саморапорт воркера.
#
# Использование: python extract_facts.py <транскрипт.jsonl> [выход.md]
# Без выхода — печатает в stdout (UTF-8).
import json, sys, io


def _brief(v, n=400):
    s = str(v).replace("\r", "")
    return s[:n] + (" …[обрезано]" if len(s) > n else "")


def extract(jsonl_path: str) -> dict:
    """Собрать машинные факты: задание, хронику tool-вызовов, дени, саморапорт."""
    task_prompt = None
    meta = {}
    tool_uses = {}        # tool_use_id -> {name, input}
    chronicle = []        # по порядку: {name, input, result, is_error, denied}
    worker_words = []     # текст/thinking воркера — ЗАЯВЛЕНИЯ, не факты
    final_text = None

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            t = ev.get("type")
            if not meta and ev.get("sessionId"):
                meta = {"session_id": ev.get("sessionId")}
            if t == "user":
                msg = ev.get("message", {})
                content = msg.get("content")
                if isinstance(content, str):
                    # первое строковое user-сообщение = задание управляющего
                    if task_prompt is None:
                        task_prompt = content
                        meta.update({k: ev.get(k) for k in ("cwd", "version", "timestamp", "permissionMode")})
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            tuid = b.get("tool_use_id")
                            use = tool_uses.get(tuid, {"name": "?", "input": {}})
                            res_content = b.get("content")
                            if isinstance(res_content, list):
                                res_content = " ".join(
                                    str(x.get("text", x)) if isinstance(x, dict) else str(x)
                                    for x in res_content)
                            is_err = bool(b.get("is_error"))
                            denied = "supervisor:" in str(res_content)
                            chronicle.append({
                                "tool": use["name"], "input": use["input"],
                                "result": str(res_content), "is_error": is_err,
                                "denied_by_supervisor": denied,
                            })
            elif t == "assistant":
                msg = ev.get("message", {})
                for b in msg.get("content", []) or []:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "tool_use":
                        tool_uses[b.get("id")] = {"name": b.get("name"), "input": b.get("input")}
                    elif bt == "text":
                        worker_words.append(b.get("text", ""))
                        final_text = b.get("text", "")
                    elif bt == "thinking":
                        worker_words.append("[thinking] " + str(b.get("thinking", ""))[:300])

    denials = [c for c in chronicle if c["is_error"] or c["denied_by_supervisor"]]
    return {
        "meta": meta,
        "task_prompt": task_prompt,
        "chronicle": chronicle,
        "denials": denials,
        "worker_words": worker_words,
        "final_self_report": final_text,
    }


def render_md(facts: dict, jsonl_path: str) -> str:
    L = []
    L.append("# МАШИННЫЕ ФАКТЫ прогона воркера (детерминированная выжимка из JSONL)")
    L.append("")
    L.append(f"- транскрипт: `{jsonl_path}`")
    for k, v in facts["meta"].items():
        L.append(f"- {k}: `{v}`")
    L.append("")
    L.append("## ЗАДАНИЕ воркеру (промпт управляющего)")
    L.append("```")
    L.append(str(facts["task_prompt"]))
    L.append("```")
    L.append("")
    L.append("## ХРОНИКА ИНСТРУМЕНТОВ (факты: что реально вызвано и что вернулось)")
    if not facts["chronicle"]:
        L.append("*(ни одного tool-вызова)*")
    for i, c in enumerate(facts["chronicle"], 1):
        flag = " ⛔ DENY (заблокировано супервизором)" if c["denied_by_supervisor"] else (
               " ⚠ is_error=True (ошибка инструмента, НЕ блокировка)" if c["is_error"] else "")
        L.append(f"{i}. **{c['tool']}**{flag}")
        L.append(f"   - input: `{_brief(c['input'], 300)}`")
        L.append(f"   - result: `{_brief(c['result'])}`" + (f" (is_error={c['is_error']})" if c["is_error"] else ""))
    L.append("")
    sup = [c for c in facts["denials"] if c["denied_by_supervisor"]]
    errs = [c for c in facts["denials"] if not c["denied_by_supervisor"]]
    L.append(f"## ДЕНИ СУПЕРВИЗОРА (блокировки гейта): {len(sup)}")
    for c in sup:
        L.append(f"- {c['tool']}: input=`{_brief(c['input'], 200)}` → `{_brief(c['result'], 200)}`")
    L.append("")
    L.append(f"## ОШИБКИ ИНСТРУМЕНТОВ (is_error=True, обычные ошибки, НЕ блокировки): {len(errs)}")
    for c in errs:
        L.append(f"- {c['tool']}: input=`{_brief(c['input'], 200)}` → `{_brief(c['result'], 200)}`")
    L.append("")
    L.append("## СЛОВА ВОРКЕРА (заявления — НЕ факты, доверять нельзя)")
    L.append(f"- финальный саморапорт: «{facts['final_self_report']}»")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("usage: python extract_facts.py <transcript.jsonl> [out.md]")
        sys.exit(1)
    facts = extract(sys.argv[1])
    md = render_md(facts, sys.argv[1])
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(md)
        print(f"written: {sys.argv[2]}")
    else:
        print(md)
