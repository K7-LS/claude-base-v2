# notify.py — escalation channel: durable log (always) + Telegram (optional) + stdout.
import os, json, urllib.request, datetime, pathlib

# Append-only audit floor — survives a dead Telegram / unattended runs.
_LOG = os.environ.get("SUPERVISOR_LOG") or str(pathlib.Path(__file__).with_name("supervisor-escalations.log"))

def _record(text: str) -> None:
    try:
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{stamp} | {text}\n")
    except Exception:
        pass  # logging must NEVER break the deny path

def escalate(text: str) -> None:
    _record(text)  # durable floor first — before any network
    tok = os.environ.get("SUPERVISOR_TG_TOKEN")
    chat = os.environ.get("SUPERVISOR_TG_CHAT")
    if not (tok and chat):
        print("[ESCALATE]", text)  # no Telegram configured — recorded above + stdout
        return
    data = json.dumps({"chat_id": chat, "text": "supervisor: " + text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=int(os.environ.get("SUPERVISOR_TG_TIMEOUT", "30")))
    except Exception as e:
        print("[ESCALATE-FALLBACK]", text, "| tg-error:", e)  # recorded above regardless
