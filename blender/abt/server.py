"""浏览器预览用的本地静态服务器（只监听 127.0.0.1），Windows 上不用另装 Python。"""
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

_srv = None


class _Handler(SimpleHTTPRequestHandler):
    # Windows 注册表可能把 .js 登记成 text/plain，浏览器会拒绝加载模块，这里写死正确的类型
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".json": "application/json",
                      ".ttf": "font/ttf", ".otf": "font/otf", ".woff2": "font/woff2"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def start(root, port):
    """返回 None 表示成功，否则返回错误说明。"""
    global _srv
    if _srv and _srv.root == root and _srv.server_port == port:
        return None
    stop()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(_Handler, directory=root))
    except OSError as e:
        return f"预览端口 {port} 不可用：{e}"
    srv.root = root
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _srv = srv
    return None


def stop():
    global _srv
    if _srv:
        _srv.shutdown()
        _srv.server_close()
        _srv = None
