#!/usr/bin/env python3
"""在正在运行的 Blender 里执行 Python。
需要 Blender 装好 AB to T 插件，并在插件设置里打开“允许 AI 控制 Blender”（只监听 127.0.0.1）。
执行的代码里可以直接用 bpy、abt（插件的 core 模块）、argv（脚本后面的参数）。

    python bl.py -c "abt.import_scene(r'D:/AB to T/scenes/shot03.json')"
    python bl.py -c "print([o.name for o in bpy.data.objects])"
    python bl.py 某个脚本.py 参数1 参数2
"""
import json
import os
import socket
import sys

for _s in (sys.stdout, sys.stderr):  # 中文 Windows 上输出被管道读取时默认是 GBK，统一成 UTF-8
    _s.reconfigure(encoding="utf-8")


def main():
    args = sys.argv[1:]
    if args[:1] == ["-c"] and len(args) == 2:
        job = {"code": args[1], "file": None}
    elif args and args[0] != "-c":
        path = os.path.abspath(args[0])
        with open(path, encoding="utf-8") as f:
            job = {"code": f.read(), "file": path, "argv": args[1:]}
    else:
        sys.exit(__doc__)

    port = int(os.environ.get("AB_BRIDGE_PORT", "9876"))
    try:
        conn = socket.create_connection(("127.0.0.1", port), timeout=10)
    except OSError as e:
        sys.exit(f"连不上 Blender（127.0.0.1:{port}）：{e}\n确认 Blender 已打开、装了 AB to T 插件，并在插件设置里打开了“允许 AI 控制 Blender”。")

    with conn:
        conn.settimeout(None)  # 脚本可能跑很久
        conn.sendall(json.dumps(job).encode("utf-8"))
        conn.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)

    res = json.loads(b"".join(chunks).decode("utf-8"))
    sys.stdout.write(res.get("output", ""))
    if not res.get("ok"):
        sys.stderr.write(res.get("error", ""))
        sys.exit(1)


if __name__ == "__main__":
    main()
