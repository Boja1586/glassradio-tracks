"""DS Pull — копирует сообщения из Discord и тащит ID музыки в сборник.

Только Bot API (без селфботов — за юзер-токены Discord банит аккаунты):
  1. discord.com/developers -> New Application -> Bot -> токен
  2. OAuth2 -> URL Generator: scopes=bot, permissions = View Channels,
     Read Messages, Read Message History -> открыть URL, добавить на сервер
  3. Включить Developer Mode в Discord (Настройки -> Расширенные),
     ПКМ по серверу/каналу -> Копировать ID
  4. py ds_pull.py --token БОТ_ТОКЕН --guild СЕРВЕР_ID
     или py ds_pull.py --token БОТ_ТОКЕН --channel КАНАЛ_ID

Что делает: качает все сообщения текстовых каналов (пагинация),
складывает в ds_export/<id>.json и .txt, вытаскивает ID 6-15 цифр,
проверяет что это аудио Roblox, новые дописывает в AllTracks.json и пушит.
Токен можно сохранить в E:\\RadioBot\\ds_token.txt чтобы не вводить.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE, "ds_export")
REPO_DIR = r"C:\Users\rusla\AppData\Local\Temp\opencode\radio-bg"
TRACKS = os.path.join(REPO_DIR, "AllTracks.json")

ID_RE = re.compile(r"\d{6,15}")
TOKEN_FILE = os.path.join(BASE, "ds_token.txt")


class DS:
    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GlassRadio/1.0",
          "Authorization": ""}

    def __init__(self, token):
        self.base = "https://discord.com/api/v10"
        self.token = token

    def req(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for _ in range(5):
            req = urllib.request.Request(
                url, headers={"Authorization": "Bot " + self.token,
                              "User-Agent": self.UA["User-Agent"]})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry = json.loads(e.read().decode() or "{}")
                    time.sleep(float(retry.get("retry_after", 2)) + 0.5)
                    continue
                raise
        raise RuntimeError("rate limited 5 раз подряд")

    def channels_of(self, guild_id):
        chans = self.req(f"/guilds/{guild_id}/channels")
        return [c for c in chans if c.get("type") == 0]

    def all_messages(self, channel_id):
        out, before = [], None
        while True:
            p = {"limit": 100}
            if before:
                p["before"] = before
            batch = self.req(f"/channels/{channel_id}/messages", p)
            if not batch:
                break
            out += batch
            before = batch[-1]["id"]
            if len(batch) < 100:
                break
            time.sleep(0.4)
        return out


def economy_check(code):
    try:
        req = urllib.request.Request(
            f"https://economy.roblox.com/v2/assets/{code}/details",
            headers={"User-Agent": "GlassRadio/1.0"},
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
        if int(info.get("AssetTypeId", -1)) == 3:
            return (code, True, str(info.get("Name") or code))
        return (code, False, None)
    except Exception:
        return (code, None, None)


def git_push():
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", "add", "AllTracks.json"], cwd=REPO_DIR,
                   capture_output=True, env=env)
    done = subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=REPO_DIR, capture_output=True, env=env)
    if done.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-m", "Auto: tracks from Discord"],
                   cwd=REPO_DIR, capture_output=True, env=env)
    push = subprocess.run(["git", "push"], cwd=REPO_DIR,
                          capture_output=True, text=True, env=env, timeout=90)
    return push.returncode == 0


def main():
    args = sys.argv[1:]
    token, guild, channel = None, None, None
    targets_arg, repo_arg = None, None
    i = 0
    while i < len(args):
        if args[i] == "--token" and i + 1 < len(args):
            token, i = args[i + 1], i + 2
        elif args[i] == "--guild" and i + 1 < len(args):
            guild, i = args[i + 1], i + 2
        elif args[i] == "--channel" and i + 1 < len(args):
            channel, i = args[i + 1], i + 2
        elif args[i] == "--targets" and i + 1 < len(args):
            targets_arg, i = args[i + 1], i + 2
        elif args[i] == "--repo" and i + 1 < len(args):
            repo_arg, i = args[i + 1], i + 2
        else:
            i += 1
    if not token:
        token = os.environ.get("DS_TOKEN", "")
    if not token and os.path.isfile(TOKEN_FILE):
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if repo_arg:
        global REPO_DIR, TRACKS
        REPO_DIR = repo_arg
        TRACKS = os.path.join(REPO_DIR, "AllTracks.json")
    pairs = []
    if targets_arg:
        for part in targets_arg.split(","):
            part = part.strip()
            if ":" in part:
                kind, ident = part.split(":", 1)
                if kind in ("guild", "channel") and ident.strip():
                    pairs.append((kind, ident.strip()))
    elif guild:
        pairs = [("guild", guild)]
    elif channel:
        pairs = [("channel", channel)]
    if not token or not pairs:
        print(__doc__)
        return
    global EXPORT_DIR
    if os.environ.get("GITHUB_ACTIONS"):
        import tempfile
        EXPORT_DIR = tempfile.mkdtemp(prefix="ds_export_")
    ds = DS(token)
    me = ds.req("/users/@me")
    print("бот:", me.get("username"))
    os.makedirs(EXPORT_DIR, exist_ok=True)
    targets = []
    for kind, ident in pairs:
        if kind == "channel":
            try:
                ch = ds.req(f"/channels/{ident}")
                targets.append((ident, ch.get("name", ident)))
            except Exception as e:
                print(f"[канал {ident}] ошибка: {str(e)[:100]}")
        else:
            try:
                for c in ds.channels_of(ident):
                    targets.append((c["id"], c.get("name", c["id"])))
            except Exception as e:
                print(f"[сервер {ident}] ошибка: {str(e)[:100]}")
    print("каналов:", len(targets))
    all_codes = {}
    for cid, cname in targets:
        try:
            msgs = ds.all_messages(cid)
        except Exception as e:
            print(f"[{cname}] ошибка: {str(e)[:100]}")
            continue
        print(f"[{cname}] сообщений: {len(msgs)}")
        with open(os.path.join(EXPORT_DIR, f"{cid}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False)
        with open(os.path.join(EXPORT_DIR, f"{cid}.txt"),
                  "w", encoding="utf-8") as f:
            for m in msgs:
                au = (m.get("author") or {}).get("username", "?")
                f.write(f"[{m.get('id')}] {au}: {m.get('content', '')}\n")
        for m in msgs:
            for code in set(ID_RE.findall(m.get("content", ""))):
                all_codes.setdefault(code, f"{cname}: {(m.get('content') or '')[:60]}")
    print("уникальных кодов:", len(all_codes))
    try:
        tracks = json.load(open(TRACKS, encoding="utf-8"))
    except Exception:
        tracks = []
    have = {t["id"] for t in tracks if isinstance(t, dict) and "id" in t}
    fresh = [(c, t) for c, t in all_codes.items() if c not in have]
    print("новых кандидатов:", len(fresh))
    with ThreadPoolExecutor(max_workers=10) as ex:
        res = dict(ex.map(lambda c: (c[0], economy_check(c[0])[1]), fresh))
    added = 0
    for code, title in fresh:
        if res.get(code) is True:
            tracks.append({"id": code, "name": title[:80]})
            added += 1
    with open(TRACKS, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=1)
    pushed = git_push() if added else False
    print(f"добавлено: {added}, всего: {len(tracks)}, push: {pushed}")


main()
