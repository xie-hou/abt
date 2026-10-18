"""连接 FRAME：FRAME 在另一台电脑（服务器）上时，让那里的 AI 和你在这个 Blender 里一起调镜头。

插件主动连 FRAME（HTTPS 长轮询，不在本机开端口）。用 FRAME「Blender」选项卡里的连接码配对后，
FRAME 的 blender_* 工具发来的请求在这里执行：打开作品里的镜头、执行 Python、截一帧画面。
镜头和它用的组件、字体、图片放在本机的工作副本里，目录结构和 FRAME 作品一样，所以导入、
找组件、实时写回都照常走 core；写回的 JSON 再上传给 FRAME，FRAME 的预览跟着刷新。
.blend 只留在这台电脑上。

配对信息存在插件的用户目录（frame/link.json），不在 Blender 偏好设置里。
"""
import base64
import collections
import contextlib
import hashlib
import io
import json
import os
import queue
import re
import socket
import struct
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import bpy

from . import bridge, core

PROTOCOL = 1  # 和 FRAME 的 server/blender.mjs 一致
POLL_TIMEOUT = 40  # 秒；FRAME 最多让一次轮询等 25 秒
_manifest = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', open(_manifest, encoding="utf-8").read(), re.M)[1]


class LinkError(RuntimeError):
    def __init__(self, message, code="ERROR", status=None):
        super().__init__(message)
        self.code, self.status = code, status


class Offline(RuntimeError):
    """连不上 FRAME（网络、服务器重启）：稍后重试。"""


# ---------- 配对信息、工作副本 ----------
def _home():
    return bpy.utils.extension_path_user(__package__, path="frame", create=True)


def _config_file():
    return os.path.join(_home(), "link.json")


def load_config():
    try:
        with open(_config_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    path = _config_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o600)  # 令牌只给自己看
    os.replace(tmp, path)


def mirror_root():
    host = urllib.parse.urlsplit(_cfg.get("server", "")).netloc.replace(":", "_") or "frame"
    return os.path.join(_home(), host)


def work_dir(work):
    repo, wid = work.split("/")
    return os.path.join(mirror_root(), repo, wid)


def shot_of(path):
    """工作副本里的镜头 JSON → {"work": "库/作品", "path": "projects/…/abt/x.json"}；不是时返回 None。"""
    if not path or not _cfg.get("server"):
        return None
    rel = os.path.relpath(os.path.abspath(path), mirror_root())
    parts = rel.replace(os.sep, "/").split("/")
    if rel.startswith("..") or len(parts) < 6 or parts[2] != "projects" or parts[4] != "abt":
        return None
    return {"work": f"{parts[0]}/{parts[1]}", "path": "/".join(parts[2:])}


_meta_lock = threading.Lock()


def _meta_file(work):
    return os.path.join(work_dir(work), ".abt-frame.json")


def read_meta(work):
    """工作副本记录：base 是每个镜头上次和 FRAME 一致时的内容 sha256（判断冲突用），etags 是下载过的文件版本。"""
    with _meta_lock:
        try:
            with open(_meta_file(work), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    meta.setdefault("base", {})
    meta.setdefault("etags", {})
    return meta


def update_meta(work, fn):
    with _meta_lock:
        try:
            with open(_meta_file(work), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        meta.setdefault("base", {})
        meta.setdefault("etags", {})
        fn(meta)
        os.makedirs(work_dir(work), exist_ok=True)
        tmp = _meta_file(work) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _meta_file(work))


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


# ---------- HTTP ----------
_cfg = {}
_cfg_loaded = False


def config():
    """配对信息（面板用，不用每次重画都读文件）。"""
    global _cfg, _cfg_loaded
    if not _cfg_loaded:
        _cfg, _cfg_loaded = load_config(), True
    return _cfg

_opener = urllib.request.build_opener()  # 跟随系统代理设置


def is_local(server):
    host = urllib.parse.urlsplit(server).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost")


def request(method, path, body=None, timeout=30, headers=None, cfg=None):
    """返回 (状态码, 内容, 响应头)。FRAME 返回的错误抛 LinkError，连不上抛 Offline。"""
    cfg = cfg or _cfg
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["server"].rstrip("/") + path, data=data, method=method)
    req.add_header("User-Agent", f"AB-to-T/{VERSION} Blender/{bpy.app.version_string}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if cfg.get("token"):
        req.add_header("Authorization", "Bearer " + cfg["token"])
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", e.headers
        raw = e.read()
        try:
            err = json.loads(raw.decode("utf-8"))["error"]
            raise LinkError(err.get("message") or f"HTTP {e.code}", err.get("code") or "ERROR", e.code) from None
        except (ValueError, KeyError, TypeError):
            if e.code in (502, 503, 504, 520, 521, 522, 523, 524):  # 服务器重启中、反向代理连不上
                raise Offline(f"FRAME 暂时不可用（HTTP {e.code}）") from None
            raise LinkError(f"FRAME 返回 HTTP {e.code}", "HTTP", e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise Offline(f"连不上 FRAME：{getattr(e, 'reason', e)}") from None


def call(path, body=None, timeout=30, cfg=None):
    _, raw, _ = request("POST", path, body or {}, timeout, cfg=cfg)
    return json.loads(raw.decode("utf-8")) if raw else {}


def parse_code(text, server=""):
    """连接码：FRAME 复制出来的是“地址#配对码”，只填配对码时用上次的地址。"""
    text = text.strip()
    if "#" in text:
        server, code = text.rsplit("#", 1)
    else:
        code = text
    server = server.strip().rstrip("/")
    if server and not re.match(r"^https?://", server):
        server = "https://" + server
    code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    if not server or not code:
        raise LinkError("请粘贴 FRAME「Blender」选项卡里复制的连接码（地址#配对码）")
    return server, code


def this_name():
    return f"Blender {bpy.app.version_string} · {socket.gethostname()}"[:60]


def pair(text):
    """用连接码配对（主线程里调用，会等网络）。已经连着同一个 FRAME 时加一个作品库。"""
    global _cfg
    old = load_config()
    server, code = parse_code(text, old.get("server", ""))
    if not bpy.app.online_access and not is_local(server):
        raise LinkError("Blender 没有允许联网：偏好设置 → 系统 → 网络 → 勾选「允许联网」后再连接")
    body = {"protocol": PROTOCOL, "code": code, "name": this_name()}
    result = None
    if old.get("token") and old.get("server") == server:
        try:
            result = call("/api/blender-link/add", body, cfg=old)
            cfg = {**old, "repos": result["repos"], "enabled": True}
        except LinkError as e:
            if e.code != "UNPAIRED":
                raise
    if result is None:
        result = call("/api/blender-link/pair", body, cfg={"server": server})
        cfg = {"server": server, "token": result["token"], "repos": result["repos"], "enabled": True}
    save_config(cfg)
    _cfg = cfg
    start()
    return cfg


def unpair():
    global _cfg
    cfg = load_config()
    stop()
    if cfg.get("token"):
        with contextlib.suppress(Exception):
            call("/api/blender-link/unpair", {}, timeout=10, cfg=cfg)
    with contextlib.suppress(OSError):
        os.remove(_config_file())
    _cfg = {}
    _status.update(state="off", error=None)


def set_enabled(on):
    global _cfg
    cfg = load_config()
    if not cfg.get("token"):
        return
    cfg["enabled"] = bool(on)
    save_config(cfg)
    _cfg = cfg
    start() if on else stop()


# ---------- 线程：轮询、执行、上传 ----------
# bpy 只能在主线程用：网络在后台线程，碰 Blender 的部分交给主线程的定时器（_pump）执行。
# 每次 start() 开一组新线程（自己的停止信号和请求队列），旧的那组等手上的请求结束后自己退出。
_status = {"state": "off", "error": None, "since": 0.0}
_activity = collections.deque(maxlen=5)
_main_q = queue.Queue()
_run = None  # 当前这组线程：{"stop": Event, "jobs": Queue}
_shared = {"snapshot": {}, "pushed": None, "online_access": True, "name": "Blender"}
_saves = {}  # 镜头 JSON 路径 → 等待上传的 (镜头, 内容)，只留最新的
_saves_lock = threading.Lock()
_saves_wake = threading.Event()
_conflict = {}  # 有冲突时：{"work", "path", "message", "file"}


def status():
    return dict(_status)


def conflict():
    return dict(_conflict) if _conflict else None


def activity():
    return list(_activity)


def note(text):
    _activity.append(f"{time.strftime('%H:%M')} {text}")


def start():
    """按 link.json 连接（主线程里调用）。"""
    global _cfg, _cfg_loaded, _run
    stop()
    _cfg, _cfg_loaded = load_config(), True
    if not (_cfg.get("token") and _cfg.get("enabled", True)):
        _status.update(state="off", error=None)
        return
    _shared.update(online_access=bpy.app.online_access, name=this_name(), pushed=None)
    _run = {"stop": threading.Event(), "jobs": queue.Queue()}
    _status.update(state="connecting", error=None, since=time.time())
    for target in (_poll_loop, _job_loop, _save_loop):
        threading.Thread(target=target, args=(_run,), daemon=True, name=f"abt-frame{target.__name__}").start()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, persistent=True)
    with contextlib.suppress(ValueError):
        core.on_write.remove(written)
    core.on_write.append(written)


def stop():
    global _run
    if _run:
        _run["stop"].set()
        _run["jobs"].put(None)
        _run = None
    _saves_wake.set()
    _status.update(state="off")
    with contextlib.suppress(ValueError):
        core.on_write.remove(written)


def running():
    return _run is not None


def _poll_loop(run):
    stop, delay, hello = run["stop"], 2, True
    while not stop.is_set():
        if not _shared["online_access"] and not is_local(_cfg.get("server", "")):
            _status.update(state="error", error="Blender 没有允许联网：偏好设置 → 系统 → 网络 → 勾选「允许联网」")
            stop.wait(5)
            continue
        snapshot = _shared["snapshot"]
        try:
            res = call("/api/blender-link/poll", {"protocol": PROTOCOL, "name": _shared["name"], "state": snapshot, "hello": hello}, timeout=POLL_TIMEOUT)
        except Offline as e:
            if not stop.is_set():
                _status.update(state="retry", error=str(e))
            hello = True
            stop.wait(delay)
            delay = min(delay * 2, 30)
            continue
        except LinkError as e:
            if stop.is_set():
                return
            _status.update(state="error", error=str(e))
            if e.code in ("UNPAIRED", "VERSION"):
                return  # 配对失效或版本不对：重试没有用，等用户重新配对
            stop.wait(10)
            continue
        if stop.is_set():
            return  # 已经断开：这次拿到的请求在 FRAME 那边超时报错
        delay, hello = 2, False
        if _status["state"] != "online":
            _status.update(state="online", error=None, since=time.time())
        _shared["pushed"] = snapshot
        if res.get("repos") and res["repos"] != _cfg.get("repos"):
            _cfg["repos"] = res["repos"]
            with contextlib.suppress(OSError):
                save_config(_cfg)
        for job in res.get("jobs", []):
            run["jobs"].put(job)


def _job_loop(run):
    while True:
        job = run["jobs"].get()
        if job is None or run["stop"].is_set():
            return
        try:
            data = HANDLERS[job["op"]](job.get("args") or {}, job.get("timeout") or 60)
            reply = {"id": job["id"], "ok": True, "data": data}
        except LinkError as e:
            reply = {"id": job["id"], "ok": False, "error": str(e), "code": e.code}
            if job["id"] is None:
                note(f"出错：{str(e)[:80]}")
        except Exception as e:
            reply = {"id": job["id"], "ok": False, "error": f"{e}\n{traceback.format_exc()}"}
        if job["id"] is None:  # 插件自己发起的（面板上的按钮）：没有人等结果
            continue
        for attempt in range(3):
            try:
                call("/api/blender-link/result", reply, timeout=60)
                break
            except Offline:
                run["stop"].wait(2 + attempt * 3)
            except LinkError:
                break


def on_main(fn, timeout=60):
    """在主线程执行 fn 并等结果（Blender 正在渲染等忙的时候会多等一会儿）。"""
    box, done = {}, threading.Event()
    _main_q.put((fn, box, done))
    if not done.wait(timeout):
        raise LinkError("Blender 正忙（主线程被占着：渲染、弹出的对话框……），稍后再试", "BUSY")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _pump():
    while True:
        try:
            fn, box, done = _main_q.get_nowait()
        except queue.Empty:
            break
        try:
            box["value"] = fn()
        except Exception as e:  # noqa: BLE001 交给等结果的线程
            box["error"] = e if isinstance(e, LinkError) else LinkError(f"{e}\n{traceback.format_exc()}")
        done.set()
    try:
        _refresh_snapshot()
        _autosave()
    except Exception as e:
        print("[AB to T] 读状态出错：", e)
    _redraw_if_changed()
    return 0.1 if running() else None


_dirty_since = [0.0]
_last_write = [0.0]


def _autosave():
    """FRAME 镜头的 .blend 是这里的工作副本：改动停下 3 秒就存。
    不存的话 Blender 没保存就关掉，下次打开的是旧 .blend，实时同步会把旧值写回作品。"""
    path = bpy.data.filepath
    if not (path and bpy.data.is_dirty and shot_of_blend(path)) or _conflict:
        _dirty_since[0] = 0.0
        return
    now = time.time()
    if not _dirty_since[0]:
        _dirty_since[0] = now
        return
    if now - max(_dirty_since[0], _last_write[0]) < 3:
        return
    wm = bpy.context.window_manager
    if any(getattr(w, "modal_operators", None) for w in wm.windows):  # 正在拖动、框选：等用户松手
        return
    with core._window_context():
        bpy.ops.wm.save_mainfile()
    _dirty_since[0] = 0.0


_shown = [None]


def _redraw_if_changed():
    """后台线程改了连接状态、冲突、AI 做的事：重画侧边栏。"""
    with _saves_lock:
        uploading = bool(_saves)
    sig = (_status["state"], _status["error"], bool(_conflict), tuple(_activity), uploading)
    if sig == _shown[0]:
        return
    _shown[0] = sig
    wm = bpy.context.window_manager
    for win in wm.windows if wm else []:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _refresh_snapshot():
    scene = _scene()
    src = core.source_path(scene) if scene else None
    with _saves_lock:
        uploading = len(_saves)
    snapshot = {
        "blender": bpy.app.version_string, "addon": VERSION,
        "file": os.path.basename(bpy.data.filepath) or None, "shot": shot_of(src),
        "live": core.is_live(), "dirty": bool(bpy.data.is_dirty), "uploading": uploading,
        "conflict": {k: _conflict[k] for k in ("work", "path", "message")} if _conflict else None,
        "error": _status["error"] if _status["state"] != "online" else None,
        "activity": list(_activity),
    }
    # 后台线程只读整份替换的快照，不会读到改了一半的
    _shared.update(snapshot=snapshot, online_access=bpy.app.online_access)
    # 正在等的那次轮询带的是旧状态：变了就另外告诉 FRAME（冲突、打开的镜头这些要马上看到）
    same = lambda a, b: {k: v for k, v in a.items() if k != "dirty"} == {k: v for k, v in b.items() if k != "dirty"}
    if _status["state"] == "online" and _shared["pushed"] is not None and not same(_shared["pushed"], snapshot):
        _shared["pushed"] = snapshot
        threading.Thread(target=_push_state, args=(snapshot,), daemon=True).start()


def _push_state(state):
    with contextlib.suppress(Offline, LinkError):
        call("/api/blender-link/state", {"state": state}, timeout=15)


def _scene():
    wm = bpy.context.window_manager
    return wm.windows[0].scene if wm and wm.windows else bpy.context.scene


# ---------- 写回：实时同步写了工作副本里的 JSON，就上传给 FRAME ----------
def written(path, text):
    """core 每次写回 JSON 后调用（主线程）。"""
    shot = shot_of(path)
    if not shot:
        return
    _last_write[0] = time.time()
    with _saves_lock:
        _saves[os.path.abspath(path)] = (shot, text)
    _saves_wake.set()


def _save_loop(run):
    stop = run["stop"]
    while not stop.is_set():
        _saves_wake.wait(5)
        _saves_wake.clear()
        while not stop.is_set():
            with _saves_lock:
                if not _saves:
                    break
                path, (shot, text) = next(iter(_saves.items()))
            if _conflict and _conflict.get("file") == path:
                with _saves_lock:
                    _saves.pop(path, None)  # 冲突解决前不写回（解决时再写）
                continue
            try:
                upload(shot, text)
            except Offline:
                stop.wait(3)
                break
            except LinkError as e:
                if e.code == "CONFLICT":
                    _conflict.update(work=shot["work"], path=shot["path"], file=path, message=(
                        f"作品里的 {shot['path'].split('/', 2)[-1]} 在 Blender 外面改过，Blender 的改动没有写回。"
                        "请用户在 Blender 的 AB to T 面板里选：用 Blender 的覆盖作品里的，或者用作品里的重新导入"))
                    note("写回冲突")
                else:
                    note(f"写回失败：{str(e)[:80]}")
                    print("[AB to T] 写回 FRAME 失败：", e)
            with _saves_lock:
                if _saves.get(path, (None, None))[1] == text:
                    _saves.pop(path, None)


def upload(shot, text, force=False):
    base = read_meta(shot["work"])["base"].get(shot["path"], "")
    res = call("/api/blender-link/save", {"work": shot["work"], "path": shot["path"], "content": text, "base": base, "force": force}, timeout=30)
    update_meta(shot["work"], lambda m: m["base"].__setitem__(shot["path"], res["hash"]))


def resolve(keep_blender):
    """解决写回冲突：用 Blender 的覆盖作品里的，或者用作品里的重新导入（主线程里调用）。"""
    c = conflict()
    if not c:
        return
    if keep_blender:
        with open(c["file"], encoding="utf-8") as f:
            text = f.read()
        upload({"work": c["work"], "path": c["path"]}, text, force=True)
        _conflict.clear()
        note("用 Blender 的覆盖了作品里的镜头")
        if _run:  # 那个镜头的 .blend 还没打开时打开它（已经开着就只是确认实时同步开着）
            _run["jobs"].put({"id": None, "op": "open", "args": {"work": c["work"], "path": c["path"]}})
    else:
        _conflict.clear()
        if _run:
            _run["jobs"].put({"id": None, "op": "open", "args": {"work": c["work"], "path": c["path"], "reimport": True}})


# ---------- FRAME 发来的请求 ----------
def _download(work, ref, dest, meta, required=True):
    """下载作品或素材库的文件到工作副本；没变（ETag 一样）时不重新下载。"""
    q = urllib.parse.urlencode({"work": work, "path": ref})
    etag = meta["etags"].get(ref) if os.path.exists(dest) else None
    try:
        code, raw, headers = request("GET", f"/api/blender-link/file?{q}", headers={"If-None-Match": etag} if etag else None, timeout=120)
    except LinkError as e:
        if e.status == 404 and not required:
            return False
        raise LinkError(f"取不到 {ref}：{e}", e.code, e.status) from None
    if code == 304:
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, dest)
    if headers.get("ETag"):
        meta["etags"][ref] = headers["ETag"]
    return True


def local_path(root, ref):
    """作品里的路径 → 工作副本里的文件：素材库文件放 .materials/<库>/（core 在那里找组件、字体）。"""
    if ref.startswith("materials/"):
        return os.path.join(root, ".materials", *ref.split("/")[1:])
    return os.path.join(root, *ref.split("/"))


def needed(doc, shot_path):
    """镜头用到的文件：素材库 abt 的组件、字体，作品或素材库里的图片。"""
    slug = shot_path.split("/")[1]
    refs, comps = ["materials/abt/frame.js"], set()
    for m in (doc.get("materials") or {}).values():
        if isinstance(m, dict) and m.get("component"):
            comps.add(m["component"].split("@")[0])
    for o in doc.get("objects") or []:
        kind = o.get("type")
        if kind == "component" and o.get("component"):
            comps.add(o["component"].split("@")[0])
        elif kind == "text" and o.get("font"):
            refs.append(f"materials/abt/fonts/{os.path.basename(o['font'])}")
        elif kind == "image" and o.get("src"):
            m = re.match(r"films/([^/]+)/(.+)$", o["src"])
            if m and m[1] == slug:
                refs.append(f"projects/{slug}/public/{m[2]}")
            elif o["src"].startswith("materials/"):
                refs.append(o["src"])
    for c in sorted(comps):
        refs += [f"materials/abt/components/{c}/component.json", f"materials/abt/components/{c}/blender.py"]
    return list(dict.fromkeys(refs))


def handle_open(args, timeout):
    work, shot_path, reimport = args["work"], args["path"], bool(args.get("reimport"))
    root = work_dir(work)
    short = shot_path.split("/", 2)[-1]
    meta = read_meta(work)
    q = urllib.parse.urlencode({"work": work, "path": shot_path})
    _, raw, _ = request("GET", f"/api/blender-link/file?{q}", timeout=60)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise LinkError(f"{short} 不是有效的 JSON") from None
    if not str(doc.get("spec", "")).startswith("abt-scene/"):
        raise LinkError(f"{short} 不是 AB to T 镜头（缺少 \"spec\": \"abt-scene/0.1\"）")
    for ref in needed(doc, shot_path):
        _download(work, ref, local_path(root, ref), meta)
    local = local_path(root, shot_path)
    blend = os.path.join(os.path.dirname(local), f"{doc['meta']['name']}.blend")
    server_hash = sha256(raw)
    base = meta["base"].get(shot_path)
    if base is None and os.path.exists(local):
        with open(local, "rb") as f:
            base = sha256(f.read())
    mode = "open" if os.path.exists(blend) and not reimport else "import"
    if mode == "open" and base != server_hash:
        # 面板上也给用户两个选择
        _conflict.update(work=work, path=shot_path, file=local, message=(
            f"作品里的 {short} 在 Blender 外面改过，和 Blender 里上次同步的版本不一样"))
        note("打开时发现冲突")
        raise LinkError(
            f"作品里的 {short} 在 Blender 外面改过，和 Blender 里上次同步的版本不一样。要用作品里现在的版本，"
            "blender_open 加 reimport: true 重新导入（会冲掉 Blender 里没写进 JSON 的调整，先问用户）；"
            "要保留 Blender 里的，请用户在 Blender 的 AB to T 面板里点「用 Blender 的覆盖作品里的」", "CONFLICT")
    if mode == "import":
        os.makedirs(os.path.dirname(local), exist_ok=True)
        tmp = local + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, local)
        meta["base"][shot_path] = server_hash
    update_meta(work, lambda m: (m["base"].update(meta["base"]), m["etags"].update(meta["etags"])))
    with contextlib.suppress(KeyError):
        if _conflict.get("path") == shot_path and _conflict.get("work") == work:
            _conflict.clear()
    result = on_main(lambda: _open_main(mode, local, blend), timeout)
    note(f"{'导入' if mode == 'import' else '打开'}镜头 {short}")
    return result


def _open_main(mode, local, blend):
    current = bpy.data.filepath
    if bpy.data.is_dirty and core._has_unsaved_work():
        if current and shot_of_blend(current):
            with core._window_context():
                bpy.ops.wm.save_mainfile()  # FRAME 镜头的工作副本：先存好再换
        else:
            raise LinkError("Blender 里当前的文件有未保存的修改：请用户先保存（或关掉）它，再打开镜头", "UNSAVED")
    if mode == "open":
        if os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(blend)):
            with core._window_context():
                bpy.ops.wm.open_mainfile(filepath=blend)
        core.live(True)
        name = os.path.basename(blend)
        return {"mode": "open", "message": f"已在 Blender 里打开 {name}（上次的手调都在），实时同步已开启"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        core.import_scene(local, force=True)
    return {"mode": "import", "message": "已导入到 Blender，实时同步已开启。\n" + out.getvalue().strip()}


def shot_of_blend(path):
    rel = os.path.relpath(os.path.abspath(path), mirror_root())
    return not rel.startswith("..") and "/projects/" in "/" + rel.replace(os.sep, "/")


def handle_run(args, timeout):
    code = args["code"]
    first = next((line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("#")), "")
    note(f"执行代码：{first[:60]}")
    res = on_main(lambda: bridge._run({"code": code, "file": None}), timeout)
    if not res["ok"]:
        raise LinkError((res.get("output") or "") + res.get("error", ""), "PYTHON")
    return {"output": res["output"]}


def handle_view(args, timeout):
    what, frame = args.get("what", "camera"), args.get("frame")
    path = os.path.join(tempfile.gettempdir(), f"abt-frame-view-{os.getpid()}.png")
    with contextlib.suppress(OSError):
        os.remove(path)
    info = on_main(lambda: _view_main(what, frame, path), timeout)
    with open(path, "rb") as f:
        data = f.read()
    with contextlib.suppress(OSError):
        os.remove(path)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LinkError("Blender 没有画出画面")
    width, height = struct.unpack(">II", data[16:24])
    note({"camera": "看相机视角", "render": "渲染", "window": "截窗口"}[what] + (f" 第 {info['frame']} 帧" if what != "window" else ""))
    return {**info, "width": width, "height": height, "image": base64.b64encode(data).decode("ascii")}


def _view3d():
    wm = bpy.context.window_manager
    for win in wm.windows if wm else []:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region:
                    return win, area, region
    return None


def _view_main(what, frame, path):
    scene = _scene()
    if what == "window":
        wm = bpy.context.window_manager
        if not (wm and wm.windows):
            raise LinkError("Blender 没有窗口（后台模式），截不了窗口")
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.screen.screenshot(filepath=path)
        return {"frame": scene.frame_current}
    r, img = scene.render, scene.render.image_settings
    keep = {"frame": scene.frame_current, "pct": r.resolution_percentage,
            "img": {k: getattr(img, k) for k in ("media_type", "file_format", "color_mode", "color_depth", "exr_codec") if hasattr(img, k)}}
    view = _view3d() if what == "camera" else None
    shading = None
    try:
        if frame is not None:
            scene.frame_set(int(frame))
        r.resolution_percentage = max(1, min(100, -(-1280 * 100 // max(1, r.resolution_x))))  # 最宽约 1280
        if hasattr(img, "media_type"):  # 5.x 先选媒体类型
            img.media_type = "IMAGE"
        img.file_format, img.color_mode, img.color_depth = "PNG", "RGB", "8"
        if view:
            # 相机视角、材质预览、用场景自己的世界和灯光、不画网格这些辅助线；画完原样恢复用户的视图
            win, area, region = view
            space = area.spaces.active
            sh = space.shading
            shading = (space, sh.type, sh.use_scene_world, sh.use_scene_lights, space.overlay.show_overlays, space.region_3d.view_perspective)
            if sh.type in ("SOLID", "WIREFRAME"):
                sh.type = "MATERIAL"
            sh.use_scene_world = sh.use_scene_lights = True
            space.overlay.show_overlays = False
            space.region_3d.view_perspective = "CAMERA"
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.render.opengl(write_still=False, view_context=True)
        else:
            if what == "camera" and not scene.camera:
                raise LinkError("场景里没有相机")
            bpy.ops.render.render(write_still=False)
        result = bpy.data.images.get("Render Result")
        if not result:
            raise LinkError("Blender 没有画出画面")
        result.save_render(filepath=path, scene=scene)
        return {"frame": scene.frame_current, "engine": r.engine}
    finally:
        if shading:
            space, kind, world, lights, overlays, perspective = shading
            space.shading.type, space.shading.use_scene_world, space.shading.use_scene_lights = kind, world, lights
            space.overlay.show_overlays, space.region_3d.view_perspective = overlays, perspective
        for k, v in keep["img"].items():  # 先媒体类型后格式，才设得回去
            with contextlib.suppress(Exception):
                setattr(img, k, v)
        r.resolution_percentage = keep["pct"]
        if scene.frame_current != keep["frame"]:
            scene.frame_set(keep["frame"])


HANDLERS = {"open": handle_open, "run": handle_run, "view": handle_view}
