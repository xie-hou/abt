"""AI 桥接：让 tools/bl.py（Claude Code）在当前 Blender 里执行 Python。

只监听 127.0.0.1，默认关闭（插件设置里打开）。这个端口能执行任意代码，不要改成对外监听。
执行的代码里可以直接用 bpy、abt（本插件的 core）、argv（bl.py 传来的参数）。
"""
import contextlib
import io
import json
import queue
import socket
import threading
import traceback

import bpy

from . import core

_jobs = queue.Queue()
_sock = None


def _run(job):
    out = io.StringIO()
    ns = {"bpy": bpy, "abt": core, "__name__": "__main__", "__file__": job.get("file"), "argv": job.get("argv", [])}
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(job["code"], job.get("file") or "<bl>", "exec"), ns)
        result = {"ok": True, "output": out.getvalue()}
    except Exception:
        result = {"ok": False, "output": out.getvalue(), "error": traceback.format_exc()}

    # 每次执行记一步撤销，AI 的改动可以在 Blender 里 Ctrl+Z
    wm = bpy.context.window_manager
    if wm.windows:
        with contextlib.suppress(Exception):
            with bpy.context.temp_override(window=wm.windows[0]):
                bpy.ops.ed.undo_push(message="AI")
        for win in wm.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    return result


def _pump():
    # bpy 不是线程安全的，代码统一放到主线程的定时器里执行
    while True:
        try:
            job, box, done = _jobs.get_nowait()
        except queue.Empty:
            return 0.05
        box.update(_run(job))
        done.set()


def _serve(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return  # 已关闭
        with conn:
            chunks = []
            while chunk := conn.recv(65536):
                chunks.append(chunk)
            try:
                job = json.loads(b"".join(chunks).decode("utf-8"))
            except ValueError as e:
                box = {"ok": False, "output": "", "error": f"bad request: {e}"}
            else:
                box, done = {}, threading.Event()
                _jobs.put((job, box, done))
                done.wait()
            with contextlib.suppress(OSError):
                conn.sendall(json.dumps(box).encode("utf-8"))


def start(port):
    """返回 None 表示成功，否则返回错误说明。"""
    global _sock
    stop()
    try:
        _sock = socket.create_server(("127.0.0.1", port))
    except OSError as e:
        return f"AI 端口 {port} 不可用：{e}"
    threading.Thread(target=_serve, args=(_sock,), daemon=True).start()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, persistent=True)
    return None


def stop():
    global _sock
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _sock:
        with contextlib.suppress(OSError):
            _sock.shutdown(socket.SHUT_RDWR)
        _sock.close()
        _sock = None


def port():
    return _sock.getsockname()[1] if _sock else None
