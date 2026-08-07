#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yt_subs.py — субтитры видео по URL (YouTube и ещё ~1800 сайтов) через yt-dlp.

Зачем отдельно от [[local-video-digest]]: тот скилл работает с ЛОКАЛЬНЫМ файлом
(кадры + faster-whisper по аудио) — это дорого и нужно, когда важна картинка.
Здесь дешёвый путь: у ролика УЖЕ есть субтитры на сервере, их достаточно скачать
и превратить в текст. Качаем только субтитры, само видео не тянем.

Порядок: ручные субтитры (точнее) → автоматические (ASR) → если ни тех, ни других
нет, честно сказать и предложить local-video-digest (скачать + whisper).

Куки: на датацентр/VPN-egress YouTube считает запрос ботом и требует авторизацию.
Тогда нужен один из вариантов (см. --help-cookies):
  --cookies-from-browser chrome   (Chrome должен быть ЗАКРЫТ — иначе БД заблокирована)
  --cookies <файл>                (ручной экспорт Cookie-Editor в формате Netscape)

Usage:
  python yt_subs.py <URL> [--lang ru,en] [--json] [-o out.txt]
  python yt_subs.py <URL> --list        # какие субтитры вообще есть
  python yt_subs.py <URL> --cookies ~/yt-cookies.txt
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_get import force_utf8_stdio  # noqa: E402

TIMEOUT = 180


def run(args, timeout=TIMEOUT):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout or b"", p.stderr or b""
    except subprocess.TimeoutExpired:
        return 124, b"", b"timeout"
    except FileNotFoundError:
        return 127, b"", b"yt-dlp not found"


def auth_args(cookies=None, browser=None):
    """Аргументы авторизации yt-dlp (куки), если заданы."""
    if cookies:
        return ["--cookies", os.path.expanduser(cookies)]
    if browser:
        return ["--cookies-from-browser", browser]
    return []


def explain(err):
    """Сырую ошибку yt-dlp → причина + рецепт (иначе читается как «видео нет»)."""
    e = err.lower()
    if "sign in to confirm" in e or "not a bot" in e:
        return ("YouTube требует авторизацию: этот выходной IP (VPN/датацентр) он "
                "считает ботом. Рецепт: закрыть Chrome и повторить с "
                "--cookies-from-browser chrome, либо экспортировать куки "
                "(расширение Cookie-Editor, формат Netscape) и передать --cookies <файл>.")
    if "could not copy" in e and "cookie database" in e:
        return ("Браузер запущен и держит базу куки. Закрой Chrome полностью "
                "(включая фоновые процессы) и повтори.")
    if "dpapi" in e:
        return ("Chrome/Edge 127+ шифрует куки App-Bound Encryption — извлечь их "
                "автоматически нельзя. Используй ручной экспорт: --cookies <файл>.")
    if "could not find" in e and "cookies database" in e:
        return "Такой браузер на этой машине не установлен — выбери другой или --cookies <файл>."
    if "connectionpool" in e or "timed out" in e or "connection" in e:
        return ("Площадка недоступна с текущего egress (вероятен гео-блок — RuTube и "
                "прочие RU-хостинги требуют российский IP). Задай RU_PROXY либо возьми "
                "ru-gov-access/ru_fetch.py.")
    return None


def probe(url, cookies=None, browser=None):
    """Метаданные + списки субтитров, без скачивания."""
    rc, out, err = run(["yt-dlp", "-J", "--no-warnings", "--skip-download"]
                       + auth_args(cookies, browser) + [url])
    if rc != 0:
        raw = err.decode("utf-8", "replace")[:400]
        hint = explain(raw)
        return None, (f"{raw}\n[причина] {hint}" if hint else raw)
    try:
        d = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        return None, f"не разобрал JSON: {e}"
    return {
        "title": d.get("title"),
        "duration": d.get("duration"),
        "uploader": d.get("uploader"),
        "manual": sorted(d.get("subtitles") or {}),
        "auto": sorted(d.get("automatic_captions") or {}),
    }, None


def vtt_to_text(vtt):
    """VTT → связный текст: убрать таймкоды, теги и повторы скользящих строк."""
    lines, seen = [], None
    for raw in vtt.splitlines():
        s = raw.strip()
        if (not s or s.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
                or "-->" in s or s.isdigit()):
            continue
        s = re.sub(r"<[^>]+>", "", s)          # <c>, <00:00:01.000> и прочие теги
        s = re.sub(r"\s+", " ", s).strip()
        if not s or s == seen:                  # автосубтитры дублируют строки
            continue
        seen = s
        lines.append(s)
    return "\n".join(lines)


def fetch_subs(url, langs, cookies=None, browser=None):
    """Скачать субтитры: сначала ручные, затем авто. Возвращает (текст, вид, язык)."""
    meta, err = probe(url, cookies, browser)
    if meta is None:
        return None, None, None, err
    for kind, flag, pool in (("ручные", "--write-subs", meta["manual"]),
                             ("авто", "--write-auto-subs", meta["auto"])):
        for lang in langs:
            picked = next((c for c in pool if c == lang or c.startswith(lang + "-")), None)
            if not picked:
                continue
            with tempfile.TemporaryDirectory() as td:
                rc, _, e = run(["yt-dlp", "--no-warnings", "--skip-download", flag,
                                "--sub-langs", picked, "--sub-format", "vtt",
                                "--convert-subs", "vtt"] + auth_args(cookies, browser)
                               + ["-o", os.path.join(td, "s.%(ext)s"), url])
                if rc != 0:
                    continue
                for fn in sorted(os.listdir(td)):
                    if fn.endswith(".vtt"):
                        with open(os.path.join(td, fn), encoding="utf-8", errors="replace") as f:
                            text = vtt_to_text(f.read())
                        if text.strip():
                            return text, kind, picked, None
    have = f"ручные={meta['manual'] or '—'} авто={meta['auto'] or '—'}"
    return None, None, None, (
        f"субтитров на запрошенных языках нет ({have}). "
        "Если текст всё равно нужен — скилл local-video-digest: скачать и распознать "
        "речь локально (faster-whisper), он же даёт кадры.")


def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Субтитры видео по URL через yt-dlp")
    ap.add_argument("url")
    ap.add_argument("--lang", default="ru,en", help="приоритет языков, через запятую")
    ap.add_argument("--list", action="store_true", help="только показать доступные субтитры")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cookies", help="файл куки (Netscape) — ручной экспорт Cookie-Editor")
    ap.add_argument("--cookies-from-browser", dest="browser",
                    help="chrome|edge|firefox|... (браузер должен быть закрыт)")
    ap.add_argument("-o", dest="out")
    a = ap.parse_args()

    if a.list:
        meta, err = probe(a.url, a.cookies, a.browser)
        if meta is None:
            print(f"[FAIL] {err}")
            return 1
        print(json.dumps(meta, ensure_ascii=False, indent=2) if a.json else
              f"{meta['title']}\n  ручные: {meta['manual'] or '—'}\n  авто:   {meta['auto'] or '—'}")
        return 0

    langs = [x.strip() for x in a.lang.split(",") if x.strip()]
    text, kind, lang, err = fetch_subs(a.url, langs, a.cookies, a.browser)
    if text is None:
        print(json.dumps({"ok": False, "error": err}, ensure_ascii=False)
              if a.json else f"[FAIL] {err}")
        return 1
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    if a.json:
        print(json.dumps({"ok": True, "kind": kind, "lang": lang, "chars": len(text),
                          "out": a.out, "text": None if a.out else text}, ensure_ascii=False))
    else:
        print(f"[OK] субтитры {kind} ({lang}), {len(text)} символов"
              + (f" -> {a.out}" if a.out else "\n---8<---\n" + text[:1500]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
