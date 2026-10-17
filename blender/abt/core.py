"""场景 JSON（abt-scene/0.1）↔ Blender：导入、写回、实时同步。

规范约定：three.js 坐标（Y 向上、右手系、米），颜色为场景线性，文档时间 t = 帧 / fps，
文字 size = 大写 H 的高度（米）。项目目录 = 同时含 components/ 和 web/ 的文件夹，
组件（components/<名>/blender.py）和字体都从项目目录加载，插件本身不带场景内容。
"""
import contextlib
import importlib.util
import json
import os
import re
import time
from math import radians

import bpy
from bpy.app.handlers import persistent
from bpy_extras import anim_utils
from mathutils import Vector

COMP_NODE = "abt_component"  # 材质里代码材质组件的节点名（固定名字，动画路径靠它）

# ---------- 项目目录 ----------
def find_root(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.isdir(os.path.join(d, "components")) and os.path.isdir(os.path.join(d, "web")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError(f"找不到项目目录（同时含 components 和 web 文件夹）：{path}")
        d = parent


def source_path(scene):
    """场景关联的 JSON 的绝对路径；没有关联或 .blend 未保存时返回 None。"""
    src = scene.get("abt_source")
    if not src or not bpy.data.filepath:
        return None
    return os.path.normpath(os.path.join(os.path.dirname(bpy.data.filepath), src))


# ---------- 坐标 ----------
# three 轴 → (Blender 通道, 符号)。Blender 是 Z 向上：x = x，y = −z，z = y
POS_CH = {"x": (0, 1), "y": (2, 1), "z": (1, -1)}
SCALE_CH = {"x": (0, 1), "y": (2, 1), "z": (1, 1)}
TEXT_SCALE_CH = {"x": (0, 1), "y": (1, 1), "z": (2, 1)}  # 文字物体自身转了 90°，局部轴与 three 一致


def to_bl(v, ch=POS_CH):
    out = [0.0, 0.0, 0.0]
    for i, a in enumerate("xyz"):
        out[ch[a][0]] = ch[a][1] * v[i]
    return Vector(out)


def from_bl(v, ch=POS_CH):
    return [_num(ch[a][1] * v[ch[a][0]]) for a in "xyz"]


def _num(x):
    x = round(float(x), 4)
    return int(x) if x.is_integer() else x


def _rgb(c):
    return [_num(x) for x in c[:3]]


# 缓动简写 → 区间比例（出手柄 dt, 出手柄 dv, 入手柄 dt, 入手柄 dv），与 web/runtime.js 的 EASE 一致
EASE = {"inOut": (1 / 3, 0, 1 / 3, 0), "in": (1 / 3, 0, 1 / 3, 1 / 3), "out": (1 / 3, 1 / 3, 1 / 3, 0)}
INTERP_TO_BL = {"bezier": "BEZIER", "linear": "LINEAR", "constant": "CONSTANT"}
INTERP_FROM_BL = {v: k for k, v in INTERP_TO_BL.items()}

# ---------- 组件 ----------
SOCKET = {"int": "NodeSocketInt", "float": "NodeSocketFloat", "color": "NodeSocketColor", "bool": "NodeSocketBool"}
_schemas = {}


def schema_of(root, component):
    name = component.split("@")[0]
    if (root, name) not in _schemas:
        with open(os.path.join(root, "components", name, "component.json"), encoding="utf-8") as f:
            _schemas[root, name] = json.load(f)
    return _schemas[root, name]


def _component_group(root, component, tree_type, prefix, output, time_input=False):
    """按 component.json 建参数接口，再交给组件自己的 blender.py 连节点。同一组件只建一份节点组。"""
    schema = schema_of(root, component)
    name = schema["name"]
    ng = bpy.data.node_groups.get(f"{prefix}_{name}")
    if ng:
        return ng
    ng = bpy.data.node_groups.new(f"{prefix}_{name}", tree_type)
    ng.interface.new_socket(output[0], in_out="OUTPUT", socket_type=output[1])
    for p in schema["params"].values():
        s = ng.interface.new_socket(p["label"], description=p.get("desc", ""), in_out="INPUT", socket_type=SOCKET[p["type"]])
        s.default_value = (*p["default"], 1.0) if p["type"] == "color" else p["default"]
        if "min" in p:
            s.min_value, s.max_value = p["min"], p["max"]
    if time_input:
        ng.interface.new_socket("Time", description="文档时间（秒），由驱动器 frame / fps 提供", in_out="INPUT", socket_type="NodeSocketFloat")
    spec = importlib.util.spec_from_file_location(f"abt_{name.replace('-', '_')}", os.path.join(root, "components", name, "blender.py"))
    impl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(impl)
    impl.build(ng, ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput"))
    return ng


def input_ids(ng):
    return {i.name: i.identifier for i in ng.interface.items_tree if i.item_type == "SOCKET" and i.in_out == "INPUT"}


def param_input(ob, root, component, key):
    """物体组件参数 key → (修改器, 输入接口 id)。"""
    schema = schema_of(root, component)
    mod = ob.modifiers[schema["name"]]
    return mod, input_ids(mod.node_group)[schema["params"][key]["label"]]


# 修改器输入值：Blender 5.x 在 mod.properties.inputs.<id>.value，4.x 是修改器上的自定义属性 mod["<id>"]
def mod_input_get(mod, ident):
    return getattr(mod.properties.inputs, ident).value if hasattr(mod, "properties") else mod[ident]


def mod_input_set(mod, ident, value):
    if hasattr(mod, "properties"):
        getattr(mod.properties.inputs, ident).value = value
    else:
        mod[ident] = value


def input_path(mod, ident):
    if hasattr(mod, "properties"):
        return f'modifiers["{mod.name}"].properties.inputs.{ident}.value'
    return f'modifiers["{mod.name}"]["{ident}"]'


_INPUT_PATH = re.compile(r'^modifiers\["[^"]+"\](?:\.properties\.inputs\.(\w+)\.value|\["(\w+)"\])$')


def _ident_from_path(data_path):
    m = _INPUT_PATH.match(data_path)
    return (m.group(1) or m.group(2)) if m else None


def _component_mod(ob):
    return next(m for m in ob.modifiers if m.type == "NODES" and m.node_group and m.node_group.name.startswith("GN_"))


def get_param(ob, key):
    """读物体组件的参数（各版本通用），如 abt.get_param(bpy.data.objects["fx_galaxy"], "twist")。"""
    mod = _component_mod(ob)
    schema = schema_of(find_root(bpy.data.filepath), mod.node_group.name[3:])
    v = mod_input_get(mod, input_ids(mod.node_group)[schema["params"][key]["label"]])
    return list(v)[:3] if schema["params"][key]["type"] == "color" else v


def set_param(ob, key, value):
    """改物体组件的参数（各版本通用），如 abt.set_param(bpy.data.objects["fx_galaxy"], "twist", 1.2)。"""
    mod = _component_mod(ob)
    schema = schema_of(find_root(bpy.data.filepath), mod.node_group.name[3:])
    mod_input_set(mod, input_ids(mod.node_group)[schema["params"][key]["label"]], _param_value(value))
    ob.update_tag()


def material_input_path(label):
    return f'nodes["{COMP_NODE}"].inputs["{label}"].default_value'


def _param_value(v):
    return (*v, 1.0) if isinstance(v, list) else v


def _drive_time(socket, scene):
    drv = socket.driver_add("default_value").driver
    drv.type, drv.expression = "SCRIPTED", "frame / fps"
    var = drv.variables.new()
    var.name, var.type = "fps", "SINGLE_PROP"
    var.targets[0].id_type, var.targets[0].id, var.targets[0].data_path = "SCENE", scene, "render.fps"


# ---------- 关键帧 ----------
def _fcurve(idb, path, index):
    idb.keyframe_insert(path, index=index)
    return next(fc for fc in fcurves_of(idb) if fc.data_path == path and fc.array_index == max(index, 0))


def write_track(idb, path, keys, channels):
    """channels：[(Blender 通道, 规范值里的下标或 None, 符号)]，标量属性用 [(-1, None, 1)]。
    手柄按 Blender 方式存成绝对位置（FREE），和 runtime.js 的贝塞尔求值一一对应。"""
    for bl_index, src, sign in channels:
        def val(v, src=src, sign=sign):
            return sign * (v[src] if src is not None and isinstance(v, list) else v)

        def hnd(k, side, src=src, sign=sign):
            h = k.get(side)
            if h is None:
                return None
            if isinstance(h[0], list):
                h = h[src]
            return h[0], sign * h[1]

        fc = _fcurve(idb, path, bl_index)
        pts = fc.keyframe_points
        while len(pts):
            pts.remove(pts[0], fast=True)
        pts.add(len(keys))
        for p, k in zip(pts, keys):
            p.co = (k["f"], val(k["v"]))
            p.interpolation = INTERP_TO_BL[k.get("interp", "bezier")]
            p.handle_left_type = p.handle_right_type = "FREE"
            p.handle_left, p.handle_right = p.co + Vector((-1, 0)), p.co + Vector((1, 0))
        for a, b, ka, kb in zip(pts, pts[1:], keys, keys[1:]):
            dt, dv = b.co.x - a.co.x, b.co.y - a.co.y
            e = EASE.get(ka.get("ease", "inOut"), EASE["inOut"])
            r = hnd(ka, "r") or (e[0] * dt, e[1] * dv)
            l = hnd(kb, "l") or (-e[2] * dt, -e[3] * dv)
            a.handle_right = (a.co.x + r[0], a.co.y + r[1])
            b.handle_left = (b.co.x + l[0], b.co.y + l[1])
        fc.update()


def read_fcurve(fc, sign=1):
    keys = []
    for p in fc.keyframe_points:
        k = {"f": _num(p.co.x), "v": _num(sign * p.co.y)}
        if p.interpolation != "BEZIER":
            k["interp"] = INTERP_FROM_BL.get(p.interpolation, "linear")
        else:
            k["l"] = [_num(p.handle_left.x - p.co.x), _num(sign * (p.handle_left.y - p.co.y))]
            k["r"] = [_num(p.handle_right.x - p.co.x), _num(sign * (p.handle_right.y - p.co.y))]
        keys.append(k)
    return keys


def fcurves_of(idb):
    ad = idb.animation_data if idb else None
    if not (ad and ad.action):
        return []
    if hasattr(anim_utils, "action_get_channelbag_for_slot"):  # 4.4 起是分层动作，曲线在槽位的 channelbag 里
        cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot) if ad.action_slot else None
        return list(cb.fcurves) if cb else []
    return list(ad.action.fcurves)


# ---------- 节点小工具 ----------
def fresh_tree(idblock):
    if idblock.node_tree is None:
        idblock.use_nodes = True
    idblock.node_tree.nodes.clear()
    return idblock.node_tree


def _node_set(node, socket, prop, value):
    """合成节点的设置：5.x 是输入接口，4.x 多是节点属性。两种都没有时返回 False。"""
    if socket in node.inputs:
        node.inputs[socket].default_value = value
    elif hasattr(node, prop):
        setattr(node, prop, value)
    else:
        return False
    return True


def _node_get(node, socket, prop):
    return node.inputs[socket].default_value if socket in node.inputs else getattr(node, prop, None)


def _old_glare_size(gl):
    """早期 4.x 的辉光尺寸是 6–9 的整数档，之后改成 0–1 的相对值。"""
    p = gl.bl_rna.properties.get("size")
    return "Size" not in gl.inputs and p is not None and p.type == "INT"


BLOOM_ADD = "abt_bloom_add"  # 旧版里把光晕按强度叠回原图的 Mix 节点
# 早期 4.x 的 Bloom 光晕能量约是新版的 6 倍：叠加系数 = 强度 × 0.17。
# 在 4.2.23 上对照 5.2 渲染校准（强度 0.35、尺寸档 7 时平均像素差 0.59/255，与两版原始渲染本身的差异相当）
OLD_BLOOM_GAIN = 0.17


def build_bloom(ng, image, out, bloom):
    """在合成节点树里搭辉光：image 是渲染图输出接口，out 是最终输出节点。效果 = 原图 + 光晕 × 强度。"""
    threshold, strength, radius = bloom.get("threshold", 1), bloom.get("strength", 1), bloom.get("radius", 0.5)
    gl = ng.nodes.new("CompositorNodeGlare")
    gl.location = (300, 0)
    ng.links.new(image, gl.inputs["Image"])
    if "Type" in gl.inputs:
        gl.inputs["Type"].default_value = "Bloom"
    else:
        gl.glare_type = "BLOOM"
    _node_set(gl, "Threshold", "threshold", threshold)
    if _old_glare_size(gl):
        gl.size = max(6, min(9, round(6 + 3 * radius)))
    else:
        _node_set(gl, "Size", "size", radius)
    if _node_set(gl, "Strength", "strength", strength):
        ng.links.new(gl.outputs["Image"], out.inputs["Image"])
        return
    # 早期 4.x 没有强度：辉光节点只输出光晕（mix = 1），再用“相加”按强度叠回原图
    gl.mix = 1.0
    add = ng.nodes.new("CompositorNodeMixRGB")
    add.name, add.label, add.blend_type = BLOOM_ADD, "辉光强度", "ADD"
    add.location = (500, 0)
    add.inputs[0].default_value = strength * OLD_BLOOM_GAIN
    ng.links.new(image, add.inputs[1])
    ng.links.new(gl.outputs["Image"], add.inputs[2])
    ng.links.new(add.outputs["Image"], out.inputs["Image"])


def bloom_get(ng, old=None):
    """读回辉光设置；没有辉光节点时返回 None。old 是 JSON 里原来的值：旧版尺寸只有整数档，档位没变就保留原值。"""
    gl = find_node(ng, "CompositorNodeGlare")
    if not gl:
        return None
    strength = _node_get(gl, "Strength", "strength")
    if strength is None:
        add = ng.nodes.get(BLOOM_ADD)
        strength = add.inputs[0].default_value / OLD_BLOOM_GAIN if add else 1.0
    if _old_glare_size(gl):
        old_r = (old or {}).get("radius")
        radius = old_r if old_r is not None and round(6 + 3 * old_r) == gl.size else (gl.size - 6) / 3
    else:
        radius = _node_get(gl, "Size", "size")
    return {"threshold": _num(_node_get(gl, "Threshold", "threshold")), "strength": _num(strength), "radius": _num(radius)}


def _window_context():
    wm = bpy.context.window_manager
    return bpy.context.temp_override(window=wm.windows[0]) if wm.windows else contextlib.nullcontext()


def find_node(nt, bl_idname):
    return next((n for n in nt.nodes if n.bl_idname == bl_idname), None) if nt else None


_caps = {}


def cap_height(font):
    """规范里文字的 size 是大写 H 的高度（米）。各软件对字号的定义不同，这里量出 Blender 在 size=1 时 H 有多高。"""
    if font.name not in _caps:
        curve = bpy.data.curves.new("_abt_cap", "FONT")
        curve.body, curve.font, curve.size = "H", font, 1
        ob = bpy.data.objects.new("_abt_cap", curve)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.update()
        _caps[font.name] = ob.dimensions.y
        bpy.data.objects.remove(ob)
        bpy.data.curves.remove(curve)
    return _caps[font.name]


# ---------- 导入 ----------
_STARTUP_OBJECTS = {"Cube", "Camera", "Light", "立方体", "摄像机", "灯光"}


def _has_unsaved_work():
    """已保存过的文件有改动算；从没保存过的新文件，只有放了默认立方体、相机、灯光以外的东西才算。
    （4.x 装完插件会把空白文件标成已修改，不能只看 is_dirty）"""
    if not bpy.data.is_dirty:
        return False
    return bool(bpy.data.filepath) or any(o.name not in _STARTUP_OBJECTS for o in bpy.data.objects)


class ImportConflict(RuntimeError):
    """导入会放弃未保存的修改，或覆盖已有的 .blend（界面上让用户确认后再 force 导入）。"""


def check_import(path, force=False):
    """导入前检查，返回 (doc, 项目目录, .blend 路径)。会覆盖东西时抛 ImportConflict。"""
    path = os.path.abspath(path)
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"读不了 {os.path.basename(path)}：{e}") from e
    if not (isinstance(doc, dict) and str(doc.get("spec", "")).startswith("abt-scene/")):
        raise RuntimeError(f"{os.path.basename(path)} 不是 AB to T 场景文件（缺少 \"spec\": \"abt-scene/0.1\"）")
    root = find_root(path)
    blend = os.path.join(root, "scenes", f"{doc['meta']['name']}.blend")
    if not force:
        if _has_unsaved_work():
            raise ImportConflict("当前 Blender 文件有未保存的修改，导入会放弃这些修改")
        if os.path.exists(blend):
            raise ImportConflict(f"{os.path.basename(blend)} 已存在，重新导入会冲掉在 Blender 里的手调")
    return doc, root, blend


def import_scene(path, force=False):
    path = os.path.abspath(path)
    _schemas.clear()
    doc, root, blend = check_import(path, force)
    meta = doc["meta"]

    with _window_context():
        bpy.ops.wm.read_homefile(use_empty=True)
    wm = bpy.context.window_manager
    win = wm.windows[0] if wm.windows else None  # 后台模式（blender -b）没有窗口
    scene = win.scene if win else bpy.context.scene
    scene.name = meta["name"]

    scene.frame_start, scene.frame_end = meta["frames"]
    scene.render.fps = meta["fps"]
    scene.render.resolution_x, scene.render.resolution_y = meta["resolution"]
    scene.render.resolution_percentage = 100
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:  # 4.2 – 4.5 叫 EEVEE Next
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = doc.get("color", {}).get("exposure", 0)
    img = scene.render.image_settings
    if hasattr(img, "media_type"):  # 5.x 先选媒体类型
        img.media_type = "MULTI_LAYER_IMAGE"
    else:
        img.file_format = "OPEN_EXR_MULTILAYER"
    img.color_depth, img.exr_codec = "32", "ZIP"
    scene.render.filepath = f"//../renders/{meta['name']}/{meta['name']}_"
    scene.view_layers[0].use_pass_z = True
    scene.view_layers[0].use_pass_cryptomatte_object = True

    w = doc.get("world", {})
    world = bpy.data.worlds.new("world")
    nt = fresh_tree(world)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (*w.get("color", [0, 0, 0]), 1)
    bg.inputs["Strength"].default_value = w.get("strength", 1)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (250, 0)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world

    bloom = doc.get("post", {}).get("bloom")
    if bloom:
        if hasattr(scene, "compositing_node_group"):  # 5.x：合成器是一个节点组，用组输出
            ng = bpy.data.node_groups.new("compositor", "CompositorNodeTree")
            ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            out = ng.nodes.new("NodeGroupOutput")
            scene.compositing_node_group = ng
        else:  # 4.x：场景自带合成节点树，用 Composite 节点输出
            scene.use_nodes = True
            ng = scene.node_tree
            ng.nodes.clear()
            out = ng.nodes.new("CompositorNodeComposite")
        out.location = (750, 0)
        build_bloom(ng, ng.nodes.new("CompositorNodeRLayers").outputs["Image"], out, bloom)

    mats, mat_comps = {}, {}
    for mid, m in doc.get("materials", {}).items():
        mat = bpy.data.materials.new(mid)
        nt = fresh_tree(mat)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (350, 0)
        if "component" in m:
            # 代码材质：着色器节点组，参数在材质面板里显示成滑块
            g = nt.nodes.new("ShaderNodeGroup")
            g.name = COMP_NODE
            g.node_tree = _component_group(root, m["component"], "ShaderNodeTree", "SG", ("Shader", "NodeSocketShader"), time_input=True)
            g.width = 220
            schema = schema_of(root, m["component"])
            for key, v in m.get("params", {}).items():
                g.inputs[schema["params"][key]["label"]].default_value = _param_value(v)
            _drive_time(g.inputs["Time"], scene)
            nt.links.new(g.outputs["Shader"], out.inputs["Surface"])
            mat_comps[mid] = (mat, m)
        else:
            b = nt.nodes.new("ShaderNodeBsdfPrincipled")
            nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
            b.inputs["Base Color"].default_value = (*m.get("color", [0.8, 0.8, 0.8]), 1)
            b.inputs["Roughness"].default_value = m.get("roughness", 0.5)
            b.inputs["Metallic"].default_value = m.get("metalness", 0)
            b.inputs["Emission Color"].default_value = (*m.get("emissive", [0, 0, 0]), 1)
            b.inputs["Emission Strength"].default_value = m.get("emissiveIntensity", 0)
        mats[mid] = mat

    nodes = {}
    for o in doc["objects"]:
        kind, oid = o["type"], o["id"]
        if kind == "empty":
            data = None
        elif kind == "camera":
            data = bpy.data.cameras.new(oid)
            data.lens, data.sensor_width, data.sensor_fit = o.get("lens", 50), o.get("sensor", 36), "HORIZONTAL"
            data.clip_start, data.clip_end = 0.1, 1000
        elif kind == "sun":
            data = bpy.data.lights.new(oid, "SUN")
            data.energy, data.color, data.angle = o.get("intensity", 1), o.get("color", [1, 1, 1]), 0
        elif kind == "text":
            data = bpy.data.curves.new(oid, "FONT")
            data.body, data.extrude = o["text"], o.get("depth", 0) / 2
            data.align_x, data.align_y = "CENTER", "BOTTOM_BASELINE"
            if o.get("font"):
                data.font = bpy.data.fonts.load(os.path.join(root, o["font"]), check_existing=True)
            data.size = o.get("size", 1) / cap_height(data.font)
            if o.get("material"):
                data.materials.append(mats[o["material"]])
        elif kind == "component":
            data = bpy.data.meshes.new(oid)
        else:
            print(f"跳过 {oid}：Blender 暂不支持类型 {kind}")
            continue
        ob = bpy.data.objects.new(oid, data)
        scene.collection.objects.link(ob)
        ob["abt_id"] = oid
        ob.location = to_bl(o.get("position", [0, 0, 0]))
        if kind == "text":
            ob.rotation_euler = (radians(90), 0, 0)
        if "scale" in o:
            s = o["scale"] if isinstance(o["scale"], list) else [o["scale"]] * 3
            ob.scale = to_bl(s, TEXT_SCALE_CH if kind == "text" else SCALE_CH)
        if kind == "empty":
            ob.empty_display_size = 0.3
        if kind == "component":
            name = schema_of(root, o["component"])["name"]
            ob.modifiers.new(name, "NODES").node_group = _component_group(root, o["component"], "GeometryNodeTree", "GN", ("Geometry", "NodeSocketGeometry"))
            for key, v in o.get("params", {}).items():
                mod, ident = param_input(ob, root, o["component"], key)
                mod_input_set(mod, ident, _param_value(v))
            ob.update_tag()
        nodes[oid] = (ob, o)

    # 相机、太阳光用 Track To 对准目标物体：挪目标就能改朝向
    for ob, o in nodes.values():
        if o.get("target") in nodes:
            c = ob.constraints.new("TRACK_TO")
            c.target = nodes[o["target"]][0]
            c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
        if o["type"] == "camera":
            scene.camera = ob

    skipped = []
    for tr in doc.get("animation", []):
        target, (base, _, sub), keys = tr["target"], tr["path"].partition("."), tr["keys"]
        scalar = not isinstance(keys[0]["v"], list)
        if target in mat_comps and base == "params" and scalar:
            mat, m = mat_comps[target]
            label = schema_of(root, m["component"])["params"][sub]["label"]
            write_track(mat.node_tree, material_input_path(label), keys, [(-1, None, 1)])
            continue
        if target not in nodes:
            skipped.append(f"{target}.{tr['path']}")
            continue
        ob, o = nodes[target]
        if base in ("position", "scale"):
            ch = POS_CH if base == "position" else TEXT_SCALE_CH if o["type"] == "text" else SCALE_CH
            axes = [sub] if sub else list("xyz")
            channels = [(ch[a][0], None if sub else "xyz".index(a), ch[a][1]) for a in axes]
            write_track(ob, "location" if base == "position" else "scale", keys, channels)
        elif base == "lens" and o["type"] == "camera":
            write_track(ob.data, "lens", keys, [(-1, None, 1)])
        elif base == "intensity" and o["type"] == "sun":
            write_track(ob.data, "energy", keys, [(-1, None, 1)])
        elif base == "params" and o["type"] == "component" and scalar:
            mod, ident = param_input(ob, root, o["component"], sub)
            write_track(ob, input_path(mod, ident), keys, [(-1, None, 1)])
        else:
            skipped.append(f"{target}.{tr['path']}")

    scene.frame_set(meta.get("preview_frame", scene.frame_start))
    for area in win.screen.areas if win else []:
        if area.type == "VIEW_3D":
            sh = area.spaces.active.shading
            sh.type = "MATERIAL"
            sh.use_compositor = "CAMERA"
            area.spaces.active.region_3d.view_perspective = "CAMERA"

    scene["abt_source"] = os.path.relpath(path, os.path.dirname(blend)).replace(os.sep, "/")  # 跨系统打开 .blend 也能找到
    os.makedirs(os.path.dirname(blend), exist_ok=True)
    with _window_context():
        bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True, relative_remap=True)
    live(True)
    print(f"已导入 {len(nodes)} 个对象，保存到 {os.path.relpath(blend, root)}")
    if skipped:
        print("Blender 暂不支持、未导入的动画：", ", ".join(skipped))


# ---------- 导出 ----------
def export_all(quiet=False):
    """把所有关联了 JSON 的场景写回，返回说明文字列表。"""
    msgs = []
    for scene in bpy.data.scenes:
        path = source_path(scene)
        if path and os.path.isfile(path):  # JSON 被移走或删掉时跳过，不反复报错
            msgs += export_scene(scene, quiet)
        elif path:
            msgs.append(f"找不到 {path}，没有写回")
    return msgs


def has_linked_scene():
    """当前文件里有没有导入过、且对应 JSON 还在的场景。"""
    return any((p := source_path(s)) and os.path.isfile(p) for s in bpy.data.scenes)


def export_scene(scene, quiet=False):
    path = source_path(scene)
    root = find_root(path)
    with open(path, encoding="utf-8") as f:
        old = f.read()
    doc = json.loads(old)

    doc["meta"].update(frames=[scene.frame_start, scene.frame_end], fps=scene.render.fps,
                       resolution=[scene.render.resolution_x, scene.render.resolution_y])
    doc.setdefault("color", {})["exposure"] = _num(scene.view_settings.exposure)
    bg = find_node(scene.world.node_tree if scene.world else None, "ShaderNodeBackground")
    if bg:
        doc["world"] = {"color": _rgb(bg.inputs["Color"].default_value), "strength": _num(bg.inputs["Strength"].default_value)}
    comp_tree = scene.compositing_node_group if hasattr(scene, "compositing_node_group") else scene.node_tree
    if "bloom" in doc.get("post", {}):
        doc["post"]["bloom"] = bloom_get(comp_tree, doc["post"]["bloom"]) or doc["post"]["bloom"]

    tracks, unsynced, exported = [], [], set()
    for mid, m in doc.get("materials", {}).items():
        mat = bpy.data.materials.get(mid)
        if not (mat and mat.node_tree):
            continue
        if "component" in m:
            g = mat.node_tree.nodes.get(COMP_NODE)
            if not g:
                continue
            schema = schema_of(root, m["component"])
            fcs = fcurves_of(mat.node_tree)
            animated = {fc.data_path for fc in fcs}
            params = m.setdefault("params", {})
            for key, p in schema["params"].items():
                if material_input_path(p["label"]) not in animated:
                    v = g.inputs[p["label"]].default_value
                    params[key] = _rgb(v) if p["type"] == "color" else _num(v)
            by_path = {material_input_path(p["label"]): (k, p) for k, p in schema["params"].items()}
            for fc in fcs:
                key, p = by_path.get(fc.data_path, (None, None))
                if key and p["type"] != "color":
                    tracks.append({"target": mid, "path": f"params.{key}", "keys": read_fcurve(fc)})
                else:
                    unsynced.append(f"{mid}.{fc.data_path}[{fc.array_index}]")
            exported.add(mid)
        else:
            b = find_node(mat.node_tree, "ShaderNodeBsdfPrincipled")
            if b:
                m.update(color=_rgb(b.inputs["Base Color"].default_value), roughness=_num(b.inputs["Roughness"].default_value),
                         metalness=_num(b.inputs["Metallic"].default_value), emissive=_rgb(b.inputs["Emission Color"].default_value),
                         emissiveIntensity=_num(b.inputs["Emission Strength"].default_value))

    objs = {ob["abt_id"]: ob for ob in scene.objects if ob.get("abt_id")}
    for o in doc["objects"]:
        ob = objs.get(o["id"])
        if not ob:
            continue
        kind = o["type"]
        sch = TEXT_SCALE_CH if kind == "text" else SCALE_CH
        ident_to_key = {}
        # 有关键帧的通道只导出关键帧，静态值保持原样：否则拖时间线也会改写 JSON
        animated = {(fc.data_path, fc.array_index) for fc in fcurves_of(ob)}
        data_animated = {fc.data_path for fc in fcurves_of(ob.data if kind in ("camera", "sun") else None)}

        def static_vec(field, dp, values, ch, default):
            old = o.get(field, default)
            old = old if isinstance(old, list) else [old] * 3
            return [old[i] if (dp, ch[a][0]) in animated else values[i] for i, a in enumerate("xyz")]

        o["position"] = static_vec("position", "location", from_bl(ob.location), POS_CH, [0, 0, 0])
        scale = static_vec("scale", "scale", from_bl(ob.scale, sch), sch, 1)
        if "scale" in o or scale != [1, 1, 1]:
            o["scale"] = scale[0] if len(set(scale)) == 1 else scale
        if kind == "camera":
            o["sensor"] = _num(ob.data.sensor_width)
            if "lens" not in data_animated:
                o["lens"] = _num(ob.data.lens)
        elif kind == "sun":
            o["color"] = _rgb(ob.data.color)
            if "energy" not in data_animated:
                o["intensity"] = _num(ob.data.energy)
        elif kind == "text":
            o.update(text=ob.data.body, size=_num(ob.data.size * cap_height(ob.data.font)), depth=_num(ob.data.extrude * 2))
        elif kind == "component":
            schema = schema_of(root, o["component"])
            mod = ob.modifiers.get(schema["name"])
            if mod and mod.node_group:
                ids = input_ids(mod.node_group)
                label_to_key = {p["label"]: k for k, p in schema["params"].items()}
                ident_to_key = {ident: label_to_key.get(label) for label, ident in ids.items()}
                params = o.setdefault("params", {})
                for key, p in schema["params"].items():
                    if (input_path(mod, ids[p["label"]]), 0) in animated:
                        continue
                    v = mod_input_get(mod, ids[p["label"]])
                    params[key] = _rgb(v) if p["type"] == "color" else _num(v)
        for c in ob.constraints:
            if c.type == "TRACK_TO" and c.target and c.target.get("abt_id"):
                o["target"] = c.target["abt_id"]

        # 动画：按通道导出，手柄写成相对偏移
        for fc in fcurves_of(ob):
            dp = fc.data_path
            if dp in ("location", "scale"):
                ch = POS_CH if dp == "location" else sch
                a = next(a for a, (i, _) in ch.items() if i == fc.array_index)
                base = "position" if dp == "location" else "scale"
                tracks.append({"target": o["id"], "path": f"{base}.{a}", "keys": read_fcurve(fc, ch[a][1])})
            elif kind == "component" and ident_to_key.get(_ident_from_path(dp)):
                tracks.append({"target": o["id"], "path": f"params.{ident_to_key[_ident_from_path(dp)]}", "keys": read_fcurve(fc)})
            else:
                unsynced.append(f"{ob.name}.{dp}[{fc.array_index}]")
        data_paths = {"camera": {"lens": "lens"}, "sun": {"energy": "intensity"}}.get(kind, {})
        for fc in fcurves_of(ob.data if kind in ("camera", "sun") else None):
            if fc.data_path in data_paths:
                tracks.append({"target": o["id"], "path": data_paths[fc.data_path], "keys": read_fcurve(fc)})
            else:
                unsynced.append(f"{ob.name}.data.{fc.data_path}")

    # Blender 里找不到的对象 / 材质，原有轨道原样保留
    keep = [t for t in doc.get("animation", []) if t["target"] not in objs and t["target"] not in exported]
    doc["animation"] = keep + tracks

    text = dumps(doc) + "\n"
    if text != old:
        _write_replace(path, text)
    msgs = [f"{'已写回' if text != old else '无变化'} {os.path.basename(path)}"]
    if unsynced:
        msgs.append("规范暂不支持、未同步的动画：" + ", ".join(unsynced))
    if not quiet:
        print("\n".join(msgs))
    return msgs


def _write_replace(path, text):
    """先写临时文件再替换，浏览器不会读到写了一半的 JSON。
    Windows 上目标文件正被读取时替换会失败，稍等重试。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for _ in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.03)
    os.replace(tmp, path)


def dumps(o, ind=0):
    """紧凑的 JSON：一行放得下（≤100 字符）的对象和数组就写成一行。"""
    flat = json.dumps(o, ensure_ascii=False)
    if len(flat) <= 100 or not isinstance(o, (dict, list)):
        return flat
    pad = "  " * (ind + 1)
    if isinstance(o, dict):
        items = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {dumps(v, ind + 1)}" for k, v in o.items()]
        return "{\n" + ",\n".join(items) + "\n" + "  " * ind + "}"
    return "[\n" + ",\n".join(pad + dumps(v, ind + 1) for v in o) + "\n" + "  " * ind + "]"


# ---------- 实时同步：Blender 有改动就写回 JSON，浏览器轮询刷新 ----------
_live = {"dirty": False}


@persistent
def abt_live_handler(scene, depsgraph):
    _live["dirty"] = True


def _live_tick():
    if _live["dirty"]:
        _live["dirty"] = False
        try:
            export_all(quiet=True)
        except Exception as e:
            _live["dirty"] = True  # 下一轮再试，改动不会丢
            print("[AB to T] 实时同步出错：", e)
    return 0.3


def is_live():
    return bpy.app.timers.is_registered(_live_tick)


def live(on=True):
    hs = bpy.app.handlers.depsgraph_update_post
    for h in [h for h in hs if getattr(h, "__name__", "") == "abt_live_handler"]:
        hs.remove(h)
    old = bpy.app.driver_namespace.pop("abt_live_tick", None)
    if old and bpy.app.timers.is_registered(old):
        bpy.app.timers.unregister(old)
    if on:
        hs.append(abt_live_handler)
        bpy.app.driver_namespace["abt_live_tick"] = _live_tick
        bpy.app.timers.register(_live_tick, persistent=True)
