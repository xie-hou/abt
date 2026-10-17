"""界面：3D 视图侧边栏（N）里的 “AB to T” 面板，以及插件设置。"""
import os
import webbrowser

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bridge, core, server


def prefs():
    return bpy.context.preferences.addons[__package__].preferences


def _apply_bridge(self, context):
    bridge.stop()
    if self.ai_bridge:
        err = bridge.start(self.bridge_port)
        if err:
            print("[AB to T]", err)


class ABT_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    ai_bridge: BoolProperty(
        name="允许 AI 控制 Blender",
        description="在 127.0.0.1 上开一个端口，让 AI 通过 skill 里的 bl.py 操作 Blender。它能执行任意代码，只在需要时打开",
        default=False, update=_apply_bridge)
    bridge_port: IntProperty(name="AI 端口", default=9876, min=1024, max=65535, update=_apply_bridge)
    viewer_port: IntProperty(name="预览端口", default=8000, min=1024, max=65535)
    auto_live: BoolProperty(name="打开导入过的场景时自动开启实时同步", default=True)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "auto_live")
        col.prop(self, "ai_bridge")
        row = col.row()
        row.prop(self, "bridge_port")
        row.prop(self, "viewer_port")
        p = bridge.port()
        col.label(text=f"AI 控制：正在监听 127.0.0.1:{p}" if p else "AI 控制：未开启", icon="CONSOLE")


def _popup(msg, icon="ERROR"):
    print("[AB to T]", msg)
    wm = bpy.context.window_manager
    if wm.windows:
        with bpy.context.temp_override(window=wm.windows[0]):
            wm.popup_menu(lambda self, ctx: self.layout.label(text=msg), title="AB to T", icon=icon)


class ABT_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "abt.import_scene"
    bl_label = "导入场景 JSON"
    bl_description = "把场景 JSON 导入成 Blender 场景，保存到项目的 scenes 文件夹，并开启实时同步"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    force: BoolProperty(name="覆盖", description="放弃当前文件未保存的修改，并覆盖已有的同名 .blend（会冲掉手调）",
                        default=False, options={"SKIP_SAVE"})  # 不记住上次的勾选，免得下次误覆盖

    def invoke(self, context, event):
        if not self.filepath:  # 点按钮：弹出选文件窗口
            return ImportHelper.invoke(self, context, event)
        # 拖进 3D 视图的文件：直接导入；会覆盖东西时先弹确认框，确认后再执行 execute
        try:
            core.check_import(self.filepath, self.force)
        except core.ImportConflict as e:
            self.force = True
            return context.window_manager.invoke_confirm(
                self, event, title="AB to T：导入会覆盖", message=f"{e}。确定导入吗？", confirm_text="覆盖并导入", icon="WARNING")
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        path, force = self.filepath, self.force
        try:
            core.check_import(path, force)
        except core.ImportConflict as e:
            self.report({"ERROR"}, f"{e}。确定要覆盖就在选文件窗口右侧勾选“覆盖”")
            return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        def run():  # 导入会重新打开空白文件，放到定时器里做，避免在操作符执行中途换文件
            try:
                core.import_scene(path, force=True)
            except Exception as e:
                _popup(f"导入失败：{e}")
            return None

        bpy.app.timers.register(run, first_interval=0.01)
        return {"FINISHED"}


class ABT_OT_export(bpy.types.Operator):
    bl_idname = "abt.export_scene"
    bl_label = "写回 JSON"
    bl_description = "把 Blender 里的改动写回场景 JSON"

    def execute(self, context):
        try:
            for msg in core.export_all(quiet=True):
                self.report({"INFO"}, msg)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class ABT_OT_live(bpy.types.Operator):
    bl_idname = "abt.live"
    bl_label = "实时同步"
    bl_description = "开启后，Blender 里一有改动就自动写回 JSON，浏览器预览跟着刷新"

    def execute(self, context):
        core.live(not core.is_live())
        return {"FINISHED"}


class ABT_OT_open_viewer(bpy.types.Operator):
    bl_idname = "abt.open_viewer"
    bl_label = "打开浏览器预览"
    bl_description = "启动本机预览服务器，在默认浏览器里打开 three.js 预览"

    def execute(self, context):
        src = core.source_path(context.scene)
        if not src:
            self.report({"ERROR"}, "当前场景没有关联场景 JSON，先导入")
            return {"CANCELLED"}
        root = core.find_root(src)
        port = prefs().viewer_port
        err = server.start(root, port)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        rel = os.path.relpath(src, root).replace(os.sep, "/")
        webbrowser.open(f"http://127.0.0.1:{port}/web/?scene={rel}&frame={context.scene.frame_current}")
        return {"FINISHED"}


class ABT_PT_panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AB to T"
    bl_label = "AB to T"

    def draw(self, context):
        lay = self.layout
        src = core.source_path(context.scene)
        lay.label(text=os.path.basename(src) if src else "当前场景未关联 JSON", icon="FILE")
        lay.operator("abt.import_scene", icon="IMPORT")
        lay.label(text="也可以把场景 JSON 拖进 3D 视图")
        col = lay.column(align=True)
        col.enabled = bool(src)
        live = core.is_live()
        col.operator("abt.live", text="实时同步：开" if live else "实时同步：关", icon="UV_SYNC_SELECT", depress=live)
        col.operator("abt.export_scene", icon="EXPORT")
        col.operator("abt.open_viewer", icon="URL")
        p = bridge.port()
        lay.label(text=f"AI 控制：127.0.0.1:{p}" if p else "AI 控制：未开启（插件设置里打开）", icon="CONSOLE")


class ABT_FH_scene_json(bpy.types.FileHandler):
    """把场景 JSON 从文件夹拖进 3D 视图就导入（Blender 4.1 起支持插件注册拖拽导入）。"""
    bl_idname = "ABT_FH_scene_json"
    bl_label = "AB to T 场景"
    bl_import_operator = "abt.import_scene"
    bl_file_extensions = ".json"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"


@persistent
def abt_load_post(*_args):
    """打开导入过的场景时自动开启实时同步。"""
    try:
        if prefs().auto_live and core.has_linked_scene():
            core.live(True)
    except Exception as e:
        print("[AB to T] 自动开启实时同步失败：", e)


classes = (ABT_Preferences, ABT_OT_import, ABT_OT_export, ABT_OT_live, ABT_OT_open_viewer, ABT_PT_panel, ABT_FH_scene_json)


def _remove_load_handler():
    hs = bpy.app.handlers.load_post
    for h in [h for h in hs if getattr(h, "__name__", "") == "abt_load_post"]:
        hs.remove(h)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    _remove_load_handler()
    bpy.app.handlers.load_post.append(abt_load_post)
    # 插件在文件已经打开后才启用时，补一次检查（注册期间不能访问 bpy.data，放到定时器里）
    bpy.app.timers.register(lambda: abt_load_post() or None, first_interval=0.1)
    p = prefs()
    if p.ai_bridge:
        err = bridge.start(p.bridge_port)
        if err:
            print("[AB to T]", err)


def unregister():
    _remove_load_handler()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
