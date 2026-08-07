#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py — health-check веб-лестницы: какая ступень жива, какая мертва и чем чинить.

Боль: о мёртвой ступени узнавали В БОЮ — посреди рабочей задачи, когда цель уже
нужна. Ступень могла отвалиться молча (истёк ключ, сдох прокси, сервер сменил
политику), и это читалось как «сайт недоступен». Doctor проверяет ступени ЗАРАНЕЕ
и на каждую поломку печатает рецепт.

Проверяет РЕАЛЬНОЙ пробой (не «команда существует»):
  - egress: страна выхода + жив ли обход прокси (--noproxy);
  - кодовые ступени: direct / noproxy / jina (с ключом и без);
  - ru-слой: наличие ru_fetch.py + задан ли RU_PROXY;
  - MCP-ступени: зарегистрированы ли exa / firecrawl / playwright (по конфигу,
    без сети — сетевой health-check делает `claude mcp list`, он медленный);
  - ключи: наличие (НЕ значение — секреты не печатаются).

Usage:
  python doctor.py [--json] [--timeout 15]
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_get import UA, egress_probe, secret, force_utf8_stdio  # noqa: E402

PROBE_PAGE = "https://example.com"
JINA_PROBE = "https://r.jina.ai/https://example.com"
CLAUDE_JSON = os.path.join(os.path.expanduser("~"), ".claude.json")
RU_FETCH = os.path.join(os.path.expanduser("~"), ".claude", "skills",
                        "ru-gov-access", "tools", "ru_fetch.py")
MCP_STAGES = {
    "exa": "ступень semantic-поиска и чтения (первая MCP после кодовых)",
    "firecrawl": "скрейп антибот/RU-коммерческих сайтов",
    "playwright": "JS/SPA, антибот-cookies, скриншот глазами",
}
OK, WARN, BAD = "OK", "WARN", "FAIL"
MARK = {OK: "[ok]  ", WARN: "[warn]", BAD: "[FAIL]"}


def curl_probe(url, noproxy=False, timeout=15, headers=None):
    """Реальный запрос. Возвращает (http_code, секунды, размер)."""
    args = ["curl", "-sSL", "-A", UA, "-o", os.devnull,
            "-w", "%{http_code} %{size_download}", "--max-time", str(timeout)]
    if noproxy:
        args += ["--noproxy", "*"]
    for h in (headers or []):
        args += ["-H", h]
    args += [url]
    t0 = time.time()
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout + 6)
        dt = time.time() - t0
        parts = (p.stdout or b"").decode("utf-8", "replace").split()
        code = parts[0] if parts else "000"
        size = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return code, round(dt, 1), size
    except Exception:
        return "000", round(time.time() - t0, 1), 0


def check_direct(timeout):
    code, dt, size = curl_probe(PROBE_PAGE, noproxy=False, timeout=timeout)
    if code.startswith(("2", "3")):
        return OK, f"direct       {code} за {dt}с", None
    return BAD, f"direct       {code} за {dt}с", \
        "Прямой curl не проходит. Проверь сеть/корп-прокси; ступень noproxy ниже."


def check_noproxy(timeout):
    code, dt, size = curl_probe(PROBE_PAGE, noproxy=True, timeout=timeout)
    if code.startswith(("2", "3")):
        return OK, f"noproxy      {code} за {dt}с", None
    return WARN, f"noproxy      {code} за {dt}с", \
        ("Обход прокси мёртв (норма на WARP/VPN-машине) — лестница его исключит "
         "автоматически, деградации нет.")


def check_jina(timeout):
    key = secret("JINA_API_KEY")
    hdr = [f"Authorization: Bearer {key}"] if key else []
    code, dt, size = curl_probe(JINA_PROBE, timeout=timeout, headers=hdr)
    tag = "ключ есть" if key else "БЕЗ ключа"
    if code.startswith("2"):
        return OK, f"jina         {code} за {dt}с [{tag}]", None
    if not key:
        return BAD, f"jina         {code} за {dt}с [{tag}]", \
            ("Без ключа r.jina.ai отдаёт 403 на антибот-целях и режет частые запросы. "
             "Возьми free-ключ jina.ai/reader и положи JINA_API_KEY "
             "в ~/.claude/.local-state/secrets.env")
    return BAD, f"jina         {code} за {dt}с [{tag}]", \
        "Ключ задан, но ответа нет — проверь, не истёк ли он (jina.ai/reader)."


def check_ru_layer():
    if not os.path.exists(RU_FETCH):
        return BAD, "ru-слой      ru_fetch.py НЕ найден", \
            "Ожидался skills/ru-gov-access/tools/ru_fetch.py — проверь /sync-base."
    if secret("RU_PROXY") or os.environ.get("RU_PROXY"):
        return OK, "ru-слой      ru_fetch.py + RU_PROXY задан", None
    return WARN, "ru-слой      ru_fetch.py есть, RU_PROXY не задан", \
        ("Без своего RU-прокси ru_fetch ищет бесплатный — это десятки секунд. "
         "Свой адрес → RU_PROXY в ~/.claude/.local-state/secrets.env")


def registered_mcp():
    """Имена MCP из ~/.claude.json (быстро, без сети)."""
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as f:
            return set(json.load(f).get("mcpServers", {}) or {})
    except Exception:
        return set()


def check_mcp_stages():
    have = registered_mcp()
    out = []
    for name, purpose in MCP_STAGES.items():
        if name in have:
            out.append((OK, f"{name:<12} зарегистрирован — {purpose}", None))
        else:
            out.append((BAD, f"{name:<12} НЕ зарегистрирован — {purpose}",
                        f"Ступень недоступна. Поставить: см. ~/.claude/mcp-manifest.json ({name})"))
    return out


def check_keys():
    out = []
    for name, why in (("JINA_API_KEY", "ступень jina без 403 на антиботе"),
                      ("FIRECRAWL_API_KEY", "MCP-ступень firecrawl"),
                      ("EXA_API_KEY", "своя квота exa вместо общей")):
        out.append((OK, f"{name:<18} есть — {why}", None) if secret(name)
                   else (WARN, f"{name:<18} НЕТ — {why}",
                         f"Положи {name} в ~/.claude/.local-state/secrets.env (gitignored)."))
    return out


def check_ytdlp():
    try:
        p = subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=30)
        if p.returncode == 0:
            v = (p.stdout or b"").decode("utf-8", "replace").strip()
            return OK, f"yt-dlp       {v} — субтитры YouTube по URL", None
    except Exception:
        pass
    return WARN, "yt-dlp       не установлен — субтитры YouTube недоступны", \
        'Установить: pip install -U "yt-dlp[default]"'


def run_all(timeout):
    egress, noproxy_ok = egress_probe()
    groups = [
        ("Кодовые ступени (перебираются автоматически)",
         [check_direct(timeout), check_noproxy(timeout), check_jina(timeout), check_ru_layer()]),
        ("MCP-ступени (берёт Claude по next_hint)", check_mcp_stages()),
        ("Ключи (per-machine, значения не печатаются)", check_keys()),
        ("Прочие каналы", [check_ytdlp()]),
    ]
    return egress, noproxy_ok, groups


def render(egress, noproxy_ok, groups):
    lines = ["=== web-access doctor ===",
             f"egress: {egress}   обход прокси (--noproxy): "
             f"{'жив' if noproxy_ok else 'мёртв (ступень исключается)'}", ""]
    fixes, tot, good = [], 0, 0
    for title, checks in groups:
        lines.append(title)
        for status, text, fix in checks:
            lines.append(f"  {MARK[status]} {text}")
            tot += 1
            good += status == OK
            if fix:
                fixes.append(f"  - {text.split()[0]}: {fix}")
        lines.append("")
    lines.append(f"Итог: {good}/{tot} проверок в норме")
    if fixes:
        lines.append("\nЧто починить:")
        lines.extend(fixes)
    return "\n".join(lines)


def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Health-check веб-лестницы")
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    ap.add_argument("--timeout", type=int, default=15)
    a = ap.parse_args()
    egress, noproxy_ok, groups = run_all(a.timeout)
    if a.json:
        payload = {"egress": egress, "noproxy_ok": noproxy_ok, "groups": [
            {"title": t, "checks": [{"status": s, "text": x, "fix": f} for s, x, f in c]}
            for t, c in groups]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(egress, noproxy_ok, groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
