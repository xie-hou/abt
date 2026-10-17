#!/usr/bin/env python3
"""检查场景 JSON 是否符合 abt-scene/0.1（规范见 ../references/spec.md），只用标准库。

    python validate.py <项目>/scenes/shot03.json

项目目录 = 场景文件往上找到的、同时含 components/ 和 web/ 的文件夹。有错误时退出码为 1。
"""
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):  # 中文 Windows 上输出被管道读取时默认是 GBK，统一成 UTF-8
    _s.reconfigure(encoding="utf-8")

TYPES = ("empty", "camera", "sun", "text", "component")
EASE = ("inOut", "in", "out")
INTERP = ("bezier", "linear", "constant")


def find_root(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.isdir(os.path.join(d, "components")) and os.path.isdir(os.path.join(d, "web")):
            return d
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_vec(x):
    return isinstance(x, list) and len(x) == 3 and all(is_num(v) for v in x)


def load_component(root, spec, errors, where):
    name = spec.split("@")[0] if isinstance(spec, str) else ""
    path = os.path.join(root, "components", name, "component.json")
    if not name or not os.path.isfile(path):
        have = ", ".join(sorted(os.listdir(os.path.join(root, "components"))))
        errors.append(f"{where}：组件 {spec!r} 不存在（现有：{have}）")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_params(schema, params, errors, where):
    if not isinstance(params, dict):
        errors.append(f"{where}.params 应该是对象")
        return
    for k, v in params.items():
        p = schema["params"].get(k)
        if p is None:
            errors.append(f"{where}.params.{k}：组件 {schema['name']} 没有这个参数（可用：{', '.join(schema['params'])}）")
            continue
        t = p["type"]
        ok = {"color": is_vec(v), "int": isinstance(v, int) and not isinstance(v, bool),
              "float": is_num(v), "bool": isinstance(v, bool)}[t]
        if not ok:
            errors.append(f"{where}.params.{k}：应为 {t}，实际是 {v!r}")
        elif t in ("int", "float") and "min" in p and not p["min"] <= v <= p["max"]:
            errors.append(f"{where}.params.{k} = {v} 超出范围 [{p['min']}, {p['max']}]")


def validate(path):
    errors, warns = [], []
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        return [f"读不了 JSON：{e}"], []
    root = find_root(path)
    if not root:
        return ["场景文件不在 AB to T 项目里（往上找不到同时含 components 和 web 的文件夹）"], []

    if doc.get("spec") != "abt-scene/0.1":
        errors.append('spec 应为 "abt-scene/0.1"')
    meta = doc.get("meta") or {}
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        errors.append("meta.name 缺失")
    elif name != os.path.splitext(os.path.basename(path))[0]:
        warns.append(f"meta.name（{name}）和文件名不一致，导入后会存成 scenes/{name}.blend")
    if not (isinstance(meta.get("fps"), int) and meta["fps"] > 0):
        errors.append("meta.fps 应为正整数")
    frames = meta.get("frames")
    if not (isinstance(frames, list) and len(frames) == 2 and all(isinstance(x, int) for x in frames) and frames[0] <= frames[1]):
        errors.append("meta.frames 应为 [起始帧, 结束帧]")
        frames = None
    res = meta.get("resolution")
    if not (isinstance(res, list) and len(res) == 2 and all(isinstance(x, int) and x > 0 for x in res)):
        errors.append("meta.resolution 应为 [宽, 高]")
    if "color" in doc.get("world", {}) and not is_vec(doc["world"]["color"]):
        errors.append("world.color 应为 [r, g, b]")
    bloom = doc.get("post", {}).get("bloom")
    if bloom is not None and not all(is_num(bloom.get(k, 0)) for k in ("threshold", "strength", "radius")):
        errors.append("post.bloom 的 threshold / strength / radius 应为数字")

    mats = doc.get("materials", {})
    if not isinstance(mats, dict):
        errors.append("materials 应为对象（键是材质 id）")
        mats = {}
    mat_comps = {}
    for mid, m in mats.items():
        w = f"materials.{mid}"
        if "component" in m:
            s = load_component(root, m["component"], errors, w)
            if s and s.get("kind") != "material":
                errors.append(f"{w}：{m['component']} 不是材质组件")
            elif s:
                check_params(s, m.get("params", {}), errors, w)
                mat_comps[mid] = s
        else:
            for k in ("color", "emissive"):
                if k in m and not is_vec(m[k]):
                    errors.append(f"{w}.{k} 应为 [r, g, b]")
            for k in ("roughness", "metalness", "emissiveIntensity"):
                if k in m and not is_num(m[k]):
                    errors.append(f"{w}.{k} 应为数字")

    objs = {}
    for i, o in enumerate(doc.get("objects", [])):
        oid = o.get("id")
        w = f"objects[{i}]" + (f"（{oid}）" if oid else "")
        if not isinstance(oid, str) or not oid:
            errors.append(f"{w}：缺少 id")
            continue
        if oid in objs or oid in mats:
            errors.append(f"{w}：id 和其他对象或材质重复")
        t = o.get("type")
        if t not in TYPES:
            errors.append(f"{w}：type 应为 {' / '.join(TYPES)} 之一")
            continue
        objs[oid] = (o, None)
        if "position" in o and not is_vec(o["position"]):
            errors.append(f"{w}.position 应为 [x, y, z]")
        if "scale" in o and not (is_num(o["scale"]) or is_vec(o["scale"])):
            errors.append(f"{w}.scale 应为一个数或 [x, y, z]")
        if "rotation" in o:
            warns.append(f"{w}：暂不支持 rotation，会被忽略；朝向请用 target")
        for k in {"camera": ("lens", "sensor"), "sun": ("intensity",), "text": ("size", "depth")}.get(t, ()):
            if k in o and not is_num(o[k]):
                errors.append(f"{w}.{k} 应为数字")
        if t == "text":
            if not isinstance(o.get("text"), str) or not o["text"]:
                errors.append(f"{w}.text 缺失")
            font = o.get("font")
            if not isinstance(font, str) or not os.path.isfile(os.path.join(root, font)):
                errors.append(f"{w}.font：字体文件 {font!r} 不存在（放在 assets/fonts/ 下）")
            if o.get("material") and o["material"] not in mats:
                errors.append(f"{w}.material：材质 {o['material']!r} 没有在 materials 里定义")
        if t == "component":
            s = load_component(root, o.get("component"), errors, w)
            if s and s.get("kind") == "material":
                errors.append(f"{w}：{o['component']} 是材质组件，应该放在 materials 里")
            elif s:
                check_params(s, o.get("params", {}), errors, w)
                objs[oid] = (o, s)
    for oid, (o, _) in objs.items():
        if "target" in o and o["target"] not in objs:
            errors.append(f"{oid}.target：对象 {o['target']!r} 不存在")
    cams = [oid for oid, (o, _) in objs.items() if o["type"] == "camera"]
    if len(cams) != 1:
        errors.append(f"需要且只能有一个 camera（现在有 {len(cams)} 个）")

    for i, tr in enumerate(doc.get("animation", [])):
        target, path, keys = tr.get("target"), tr.get("path", ""), tr.get("keys")
        w = f"animation[{i}]（{target}.{path}）"
        base, _, sub = path.partition(".")
        if target in mat_comps:
            kind, schema = "material", mat_comps[target]
        elif target in objs:
            kind, schema = objs[target][0]["type"], objs[target][1]
        else:
            errors.append(f"{w}：target 不是已定义的对象或代码材质")
            continue
        vector = False
        if base in ("position", "scale") and kind != "material":
            if sub and sub not in ("x", "y", "z"):
                errors.append(f"{w}：只能写 {base}、{base}.x、{base}.y 或 {base}.z")
                continue
            vector = not sub
        elif (base, kind) in (("lens", "camera"), ("intensity", "sun")) and not sub:
            pass
        elif base == "params" and schema:
            p = schema["params"].get(sub)
            if not p:
                errors.append(f"{w}：组件 {schema['name']} 没有参数 {sub!r}")
                continue
            if p["type"] == "color":
                errors.append(f"{w}：颜色参数暂不能做动画")
                continue
        else:
            errors.append(f"{w}：{kind} 不支持动画路径 {path!r}")
            continue
        if not isinstance(keys, list) or not keys:
            errors.append(f"{w}：keys 不能为空")
            continue
        prev = None
        for j, k in enumerate(keys):
            kw = f"{w}.keys[{j}]"
            f = k.get("f")
            if not is_num(f):
                errors.append(f"{kw}.f 应为帧号")
                continue
            if prev is not None and f <= prev:
                errors.append(f"{kw}：帧号要递增")
            prev = f
            v = k.get("v")
            if not ((is_vec(v) or (base == "scale" and is_num(v))) if vector else is_num(v)):
                errors.append(f"{kw}.v 应为 {'[x, y, z]' if vector else '一个数'}")
            if k.get("ease", "inOut") not in EASE:
                errors.append(f"{kw}.ease 应为 {' / '.join(EASE)} 之一")
            if k.get("interp", "bezier") not in INTERP:
                errors.append(f"{kw}.interp 应为 {' / '.join(INTERP)} 之一")
            if frames and not frames[0] <= f <= frames[1]:
                warns.append(f"{kw}：第 {f} 帧在镜头范围 {frames} 之外")
    return errors, warns


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    errors, warns = validate(sys.argv[1])
    for w in warns:
        print("提醒：", w)
    for e in errors:
        print("错误：", e)
    print(f"{'通过' if not errors else f'{len(errors)} 个错误'}：{sys.argv[1]}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
