"""AB to T：把 AI 生成的场景 JSON 导入 Blender 手调，改动实时写回，浏览器里的 three.js 跟着刷新。"""
import importlib

from . import bridge, core, server, ui

# 重新启用插件时 Blender 只重载本文件，子模块要手动重载；core 在前，依赖它的 bridge、ui 在后
for _m in (core, server, bridge, ui):
    importlib.reload(_m)


def register():
    ui.register()


def unregister():
    core.live(False)
    bridge.stop()
    server.stop()
    ui.unregister()
