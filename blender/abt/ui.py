"""界面：3D 视图侧边栏（N）里的 “AB to T” 面板，以及插件设置。"""
import os
import urllib.parse
import webbrowser

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bridge, core, frame_link, server


# Blender 扩展仓库形式的更新源：每个 Release 都带 index.json，这个地址总是指向最新版
UPDATE_URL = "https://github.com/xie-hou/abt/releases/latest/download/index.json"
UPDATE_MODULE = "abt_updates"  # 仓库的模块名：从这个仓库装的插件，包名是 bl_ext.abt_updates.abt


def update_repo():
    return next((r for r in bpy.context.preferences.extensions.repos if r.remote_url == UPDATE_URL), None)


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
        description="在 127.0.0.1 上开一个端口，让同一台电脑上的 AI 通过 skill 里的 bl.py 操作 Blender。它能执行任意代码，只在需要时打开",
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
        col.label(text="FRAME 在另一台电脑上时：在 3D 视图侧边栏 AB to T 面板里「连接 FRAME」", icon="LINKED")

        box = self.layout.box()
        repo = update_repo()
        if repo and __package__.split(".")[1:2] == [repo.module]:
            box.label(text="自动更新：已开启。有新版本时 Blender 会提示，在「获取扩展」里点更新", icon="CHECKMARK")
        elif repo:
            box.label(text="已添加更新源。还差一步：在「获取扩展」里卸载现在这个从磁盘装的 AB to T，", icon="INFO")
            box.label(text="再搜索 AB to T，从「AB to T」仓库安装，以后就能自动更新")
        else:
            box.label(text="现在是从磁盘装的，不会自动更新", icon="INFO")
            box.operator("abt.add_update_repo", icon="URL")


class ABT_OT_add_update_repo(bpy.types.Operator):
    bl_idname = "abt.add_update_repo"
    bl_label = "添加更新源（以后自动检查新版本）"
    bl_description = "在 Blender 的扩展仓库里添加 AB to T 的更新源，并开启启动时检查更新"

    def execute(self, context):
        repo = update_repo() or context.preferences.extensions.repos.new(name="AB to T", module=UPDATE_MODULE, remote_url=UPDATE_URL)
        repo.enabled = True
        repo.use_sync_on_startup = True
        if not bpy.app.online_access:
            self.report({"WARNING"}, "已添加更新源，但 Blender 还不能联网：偏好设置 → 系统 → 网络 里勾选「允许联网」")
            return {"FINISHED"}
        try:
            bpy.ops.extensions.repo_sync_all()
        except Exception as e:  # 同步失败不影响已添加的更新源，Blender 下次启动会再查
            print("[AB to T] 同步更新源失败：", e)
        self.report({"INFO"}, "已添加更新源：在「获取扩展」里卸载现在这个 AB to T，再从「AB to T」仓库安装")
        return {"FINISHED"}


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
        if core.is_frame_library(root):
            self.report({"INFO"}, "这是 FRAME 作品里的镜头：在 FRAME 的播放器里预览，实时同步写回后会自动刷新")
            return {"CANCELLED"}
        port = prefs().viewer_port
        err = server.start(root, port)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        rel = os.path.relpath(src, root).replace(os.sep, "/")
        webbrowser.open(f"http://127.0.0.1:{port}/web/?scene={rel}&frame={context.scene.frame_current}")
        return {"FINISHED"}


class ABT_OT_frame_pair(bpy.types.Operator):
    bl_idname = "abt.frame_pair"
    bl_label = "连接 FRAME"
    bl_description = "FRAME 在另一台电脑（服务器）上时：粘贴 FRAME「Blender」选项卡里的连接码，那里的 AI 就能在这个 Blender 里打开、修改镜头"
    code: StringProperty(name="连接码", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text="连接")

    def draw(self, context):
        col = self.layout.column()
        col.label(text="在 FRAME 作品的「Blender」选项卡里点「复制连接码」，粘贴到这里：")
        col.prop(self, "code", text="")
        col.label(text="连上以后，那个作品库的 AI 能在这个 Blender 里执行代码；不用时在面板里断开。", icon="INFO")

    def execute(self, context):
        try:
            cfg = frame_link.pair(self.code)
        except (frame_link.LinkError, frame_link.Offline) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        names = "、".join(r["title"] for r in cfg.get("repos", []))
        self.report({"INFO"}, f"已连接 FRAME（作品库：{names}）")
        return {"FINISHED"}


class ABT_OT_frame_toggle(bpy.types.Operator):
    bl_idname = "abt.frame_toggle"
    bl_label = "连接 FRAME"
    bl_description = "开着时 FRAME 的 AI 能在这个 Blender 里打开镜头、执行代码；关掉后它用不了这个 Blender（配对还在，随时再打开）"

    def execute(self, context):
        frame_link.set_enabled(not frame_link.running())
        return {"FINISHED"}


class ABT_OT_frame_unpair(bpy.types.Operator):
    bl_idname = "abt.frame_unpair"
    bl_label = "断开配对"
    bl_description = "删掉和 FRAME 的配对（要再用时重新粘贴连接码）。电脑上的镜头副本和 .blend 不删"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="AB to T：断开 FRAME", message="删掉和 FRAME 的配对？", confirm_text="断开")

    def execute(self, context):
        frame_link.unpair()
        return {"FINISHED"}


class ABT_OT_frame_resolve(bpy.types.Operator):
    bl_idname = "abt.frame_resolve"
    bl_label = "解决写回冲突"
    bl_description = "作品里的镜头 JSON 在 Blender 外面改过时，选用哪一边"
    keep_blender: BoolProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        try:
            frame_link.resolve(self.keep_blender)
        except (frame_link.LinkError, frame_link.Offline) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


def _frame_box(lay, context):
    box = lay.box()
    box.label(text="FRAME", icon="LINKED")
    cfg = frame_link.config()
    if not cfg.get("token"):
        box.operator("abt.frame_pair", text="连接 FRAME…", icon="URL")
        return
    on = frame_link.running()
    st = frame_link.status()
    host = urllib.parse.urlsplit(cfg.get("server", "")).netloc
    repos = "、".join(r["title"] for r in cfg.get("repos", []))
    box.operator("abt.frame_toggle", text="连接 FRAME：开" if on else "连接 FRAME：关", icon="LINKED" if on else "UNLINKED", depress=on)
    if not on:
        box.label(text="已关闭：FRAME 的 AI 用不了这个 Blender")
    elif st["state"] == "online":
        box.label(text=f"已连接 {host}", icon="CHECKMARK")
        box.label(text=f"作品库：{repos}")
    elif st["state"] == "connecting":
        box.label(text=f"正在连接 {host}…", icon="SORTTIME")
    else:
        box.label(text=st["error"] or "连不上 FRAME", icon="ERROR")
    shot = frame_link.shot_of(core.source_path(context.scene))
    if shot:
        box.label(text=f"镜头：abt/{shot['path'].split('/')[-1]}", icon="FILE")
    c = frame_link.conflict()
    if c:
        box.label(text="写回冲突：作品里的镜头在 Blender 外面改过", icon="ERROR")
        col = box.column(align=True)
        col.operator("abt.frame_resolve", text="用 Blender 的覆盖作品里的").keep_blender = True
        col.operator("abt.frame_resolve", text="用作品里的重新导入（冲掉手调）").keep_blender = False
    lines = frame_link.activity()[-3:]
    if lines:
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="通过 FRAME 做的：")
        for line in lines:
            col.label(text=line)
    row = box.row(align=True)
    row.operator("abt.frame_pair", text="再连一个作品库…")
    row.operator("abt.frame_unpair", text="断开配对")


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
        ob = context.active_object
        if ob and ob.get("abt_id") and all(k in ob for k in core.IMAGE_PROPS):  # 图片：不透明度、亮度存在物体上，可以打关键帧
            box = lay.box()
            box.label(text=ob.name, icon="IMAGE_DATA")
            for key, (name, _, _) in core.IMAGE_PROPS.items():
                box.prop(ob, f'["{key}"]', text=name)
        p = bridge.port()
        lay.label(text=f"AI 控制：127.0.0.1:{p}" if p else "AI 控制：未开启（插件设置里打开）", icon="CONSOLE")
        _frame_box(lay, context)


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


classes = (ABT_Preferences, ABT_OT_add_update_repo, ABT_OT_import, ABT_OT_export, ABT_OT_live, ABT_OT_open_viewer, ABT_OT_frame_pair, ABT_OT_frame_toggle,
           ABT_OT_frame_unpair, ABT_OT_frame_resolve, ABT_PT_panel, ABT_FH_scene_json)


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
    frame_link.start()


def unregister():
    _remove_load_handler()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
