"""打包到 dist/（不进版本库，发布时上传到 GitHub Releases）：
  abt-<版本>.zip         Blender 插件，在 Blender 里“从磁盘安装”
  abt-scene-skill.zip    skill（含 frame-library/），可上传到 claude.ai、FRAME 的「技能」，或解压到其他 AI 工具的 skills 目录
  frame-library/         FRAME 素材库 abt 的全部内容（播放核心、组件、字体）
打包前会重新生成 PROMPT.md。

    python tools/package.py
"""
import json
import os
import re
import runpy
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SKILL = os.path.join(ROOT, "skills", "abt-scene")
ADDON = os.path.join(ROOT, "blender", "abt")
FRAME_LIB = os.path.join(DIST, "frame-library")
FRAME_LIB_NAME = "abt"  # FRAME 里素材库的文件夹名，作品里写 @materials/abt/...


def add_tree(z, src, arc_prefix):
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if not f.endswith(".pyc"):
                p = os.path.join(d, f)
                z.write(p, os.path.join(arc_prefix, os.path.relpath(p, src)))


def build_frame_library(version):
    """组装 FRAME 素材库：源码各只存一份，这里复制过去。registry.js 里的地址写成字面量，FRAME 才能识别并锁定版本。"""
    shutil.rmtree(FRAME_LIB, ignore_errors=True)
    os.makedirs(os.path.join(FRAME_LIB, "fonts"))
    with open(os.path.join(ROOT, "frame", "README.md"), encoding="utf-8") as f:
        readme = f.read().replace("{version}", version)
    with open(os.path.join(FRAME_LIB, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    shutil.copy(os.path.join(ROOT, "frame", "frame.js"), FRAME_LIB)
    shutil.copy(os.path.join(ROOT, "web", "abt-engine.js"), os.path.join(FRAME_LIB, "engine.js"))
    shutil.copy(os.path.join(ROOT, "LICENSE"), FRAME_LIB)
    shutil.copy(os.path.join(ROOT, "vendor", "opentype.min.mjs"), os.path.join(FRAME_LIB, "opentype.mjs"))
    shutil.copy(os.path.join(ROOT, "vendor", "LICENSE-opentype.txt"), FRAME_LIB)

    imports, components, blender = [], [], []
    comp_root = os.path.join(ROOT, "components")
    for name in sorted(os.listdir(comp_root)):
        src = os.path.join(comp_root, name)
        if not os.path.isfile(os.path.join(src, "component.json")):
            continue
        shutil.copytree(src, os.path.join(FRAME_LIB, "components", name), ignore=shutil.ignore_patterns("__pycache__"))
        var = re.sub(r"\W", "_", name)
        imports += [f'import * as {var} from "./components/{name}/three.js";',
                    f'import {var}_schema from "./components/{name}/component.json";']
        components.append(f'  "{name}": {{ module: {var}, schema: {var}_schema }},')
        blender.append(f'  "{name}": "materials/{FRAME_LIB_NAME}/components/{name}/blender.py",')

    fonts = []
    for f in sorted(os.listdir(os.path.join(ROOT, "assets", "fonts"))):
        shutil.copy(os.path.join(ROOT, "assets", "fonts", f), os.path.join(FRAME_LIB, "fonts"))
        if f.lower().endswith((".ttf", ".otf")):
            fonts.append(f'  "{f}": "materials/{FRAME_LIB_NAME}/fonts/{f}",')

    registry = "\n".join([
        "// 自动生成（tools/package.py），不要手改：组件和字体清单。",
        "// 地址都写成字面量，FRAME 才能识别用到的文件并锁定版本。",
        *imports, "",
        "export const COMPONENTS = {", *components, "};", "",
        "/** 场景 JSON 里的字体文件名 → 素材库地址 */",
        "export const FONTS = {", *fonts, "};", "",
        "/** 组件的 Blender 实现（Blender 插件导入时用；列在这里，FRAME 会一起锁定版本） */",
        "export const BLENDER = {", *blender, "};", "",
    ])
    with open(os.path.join(FRAME_LIB, "registry.js"), "w", encoding="utf-8") as f:
        f.write(registry)


sys.argv = ["make_prompt.py", ROOT]
runpy.run_path(os.path.join(SKILL, "scripts", "make_prompt.py"), run_name="__main__")

os.makedirs(DIST, exist_ok=True)
with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
    version = re.search(r'^version = "(.+)"', f.read(), re.M).group(1)
build_frame_library(version)

outputs = {
    f"abt-{version}.zip": [(ADDON, "")],
    "abt-scene-skill.zip": [(SKILL, "abt-scene"), (FRAME_LIB, "abt-scene/frame-library")],
}
for name, trees in outputs.items():
    path = os.path.join(DIST, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, prefix in trees:
            add_tree(z, src, prefix)
        z.write(os.path.join(ROOT, "LICENSE"), os.path.join(trees[0][1], "LICENSE"))
    print(f"dist/{name}  {os.path.getsize(path) / 1024:.0f} KB")
print(f"dist/frame-library/  {sum(len(fs) for _, _, fs in os.walk(FRAME_LIB))} 个文件")
