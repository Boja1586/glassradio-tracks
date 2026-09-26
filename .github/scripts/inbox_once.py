"""Разовый прогон inbox для GitHub Actions (крон, без ПК).

Читает BOT_TOKEN и OWNER_IDS из окружения, забирает новые апдейты
(офсет хранится в inbox_offset.txt рядом и коммитится), вытаскивает ID,
проверяет аудио, дописывает tracks.json. Коммит делает воркфлоу-шаг.
"""

import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(BASE))
TRACKS = os.path.join(REPO, "tracks.json")
OFFSET_FILE = os.path.join(REPO, "inbox_offset.txt")

ID_RE = re.compile(r"\d{6,15}")
TOKEN = os.environ.get("BOT_TOKEN", "")
OWNERS = {x.strip() for x in os.environ.get("OWNER_IDS", "").split(",") if x.strip()}


def api(method, params=None):
    import urllib.error
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}", data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("поллинг занят другим процессом, выхожу без ошибки")
            raise SystemExit(0)
        raise


def economy_check(code):
    try:
        req = urllib.request.Request(
            f"https://economy.roblox.com/v2/assets/{code}/details",
            headers={"User-Agent": "GlassRadio/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
        if int(info.get("AssetTypeId", -1)) == 3:
            return True, str(info.get("Name") or code)
        return False, None
    except Exception:
        return None, None


def extract_titles(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    found = {}
    for line in lines:
        if not line:
            continue
        m = re.match(r"^(\d{6,15})\s*[-–—:;|/]+\s*(.+)$", line)
        if m:
            found[m.group(1)] = m.group(2).strip()[:80]
            continue
        m = re.match(r"^(.+?)\s*[-–—:;|/]+\s*(\d{6,15})\s*$", line)
        if m and len(m.group(1).strip()) >= 2:
            found[m.group(2)] = m.group(1).strip()[:80]
            continue
        for code in set(ID_RE.findall(line)):
            if code not in found:
                rest = re.sub(r"^[\s\-–—:;|/.]+|[\s\-–—:;|/.]+$",
                              "", line.replace(code, "")).strip()
                found[code] = rest[:80]
    fallback = ""
    for line in lines:
        letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", line)
        if len(letters) >= 3 and not ID_RE.search(line):
            fallback = line[:80]
            break
    for code in set(ID_RE.findall(text or "")):
        if not found.get(code):
            found[code] = fallback
    return found


def main():
    if not TOKEN:
        print("нет BOT_TOKEN")
        return
    try:
        offset = int(open(OFFSET_FILE, encoding="utf-8").read().strip())
    except Exception:
        offset = 0
    data = api("getUpdates", {"offset": offset, "timeout": 25, "limit": 30})
    updates = data.get("result", [])
    if not updates:
        print("нового нет")
        return
    try:
        tracks = json.load(open(TRACKS, encoding="utf-8"))
    except Exception:
        tracks = []
    have = {t["id"] for t in tracks if isinstance(t, dict) and "id" in t}
    added = 0
    for u in updates:
        offset = max(offset, int(u.get("update_id", 0)) + 1)
        msg = u.get("message") or u.get("channel_post") or {}
        sender = msg.get("from", {})
        text = msg.get("text") or msg.get("caption") or ""
        if OWNERS and str(sender.get("id")) not in OWNERS:
            continue
        if not text or (text.startswith("/")
                        and "forward_origin" not in msg
                        and "forward_from_chat" not in msg):
            continue
        titles = extract_titles(text)
        for code in sorted(set(ID_RE.findall(text))):
            if code in have:
                continue
            ok, name = economy_check(code)
            if ok is False:
                continue
            tracks.append({"id": code,
                           "name": (titles.get(code) or name or code)[:80]})
            have.add(code)
            added += 1
    with open(TRACKS, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=1)
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        f.write(str(offset))
    print(f"добавлено: {added}, всего: {len(tracks)}")


main()
