"""打包到 dist/（不进版本库，发布时上传到 GitHub Releases）：
  abt-<版本>.zip         Blender 插件，在 Blender 里“从磁盘安装”
  abt-scene-skill.zip    skill（含 frame-install.json），可上传到 claude.ai、FRAME 的「技能」，或解压到其他 AI 工具的 skills 目录
  frame-install.json     在 FRAME 里装素材库 abt 的 material_write 操作：文件都从 GitHub 上标签 v<版本> 下载
  frame-library/         素材库 abt 装好后的样子（播放核心、组件、字体），测试用
打包前会重新生成 PROMPT.md。frame-install.json 里的网址指向标签 v<版本>：先提交、打标签并推送，再打包发布。

    python tools/package.py
"""
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SKILL = os.path.join(ROOT, "skills", "abt-scene")
ADDON = os.path.join(ROOT, "blender", "abt")
FRAME_LIB = os.path.join(DIST, "frame-library")
FRAME_LIB_NAME = "abt"  # FRAME 里素材库的文件夹名，作品里写 @materials/abt/...
RAW_URL = "https://raw.githubusercontent.com/xie-hou/abt"


def add_tree(z, src, arc_prefix):
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if not f.endswith(".pyc"):
                p = os.path.join(d, f)
                z.write(p, os.path.join(arc_prefix, os.path.relpath(p, src)))


def license_of(repo_path):
    if repo_path.startswith("vendor/"):
        return "MIT（opentype.js）"
    if repo_path.startswith("assets/fonts/"):
        return "见 fonts/ 里的字体许可文件"
    return "GPL-3.0-or-later"


def build_frame_library(version):
    """组装 FRAME 素材库：源码各只存一份，这里复制过去。registry.js 里的地址写成字面量，FRAME 才能识别并锁定版本。
    返回 {素材库里的路径: 仓库里的路径}，自动生成的文件不在里面。"""
    shutil.rmtree(FRAME_LIB, ignore_errors=True)
    sources = {}

    def copy(repo_path, lib_path):
        dst = os.path.join(FRAME_LIB, lib_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(os.path.join(ROOT, repo_path), dst)
        sources[lib_path] = repo_path

    with open(os.path.join(ROOT, "frame", "README.md"), encoding="utf-8") as f:
        readme = f.read().replace("{version}", version)
    os.makedirs(FRAME_LIB)
    with open(os.path.join(FRAME_LIB, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    copy("frame/frame.js", "frame.js")
    copy("web/abt-engine.js", "engine.js")
    copy("LICENSE", "LICENSE")
    copy("vendor/opentype.min.mjs", "opentype.mjs")
    copy("vendor/LICENSE-opentype.txt", "LICENSE-opentype.txt")

    imports, components, blender = [], [], []
    comp_root = os.path.join(ROOT, "components")
    for name in sorted(os.listdir(comp_root)):
        src = os.path.join(comp_root, name)
        if not os.path.isfile(os.path.join(src, "component.json")):
            continue
        for f in sorted(os.listdir(src)):
            if os.path.isfile(os.path.join(src, f)) and not f.endswith(".pyc"):
                copy(f"components/{name}/{f}", f"components/{name}/{f}")
        var = re.sub(r"\W", "_", name)
        imports += [f'import * as {var} from "./components/{name}/three.js";',
                    f'import {var}_schema from "./components/{name}/component.json";']
        components.append(f'  "{name}": {{ module: {var}, schema: {var}_schema }},')
        blender.append(f'  "{name}": "materials/{FRAME_LIB_NAME}/components/{name}/blender.py",')

    fonts = []
    for f in sorted(os.listdir(os.path.join(ROOT, "assets", "fonts"))):
        copy(f"assets/fonts/{f}", f"fonts/{f}")
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
    return sources


def build_frame_install(version, sources):
    """FRAME 的 material_write 一次调用装好素材库：registry.js 和 README 是生成的，直接写内容（几 KB）；
    其余文件写成标签 v<版本> 的网址，由 FRAME 服务器下载，AI 不用把文件内容抄一遍。
    FRAME 每放一个带来源的文件就在 README 末尾追加一条记录（重放也追加），所以 README 自带完整的
    「来源与许可」并放在最后：FRAME 写 README 时会丢掉新内容里已有的旧记录，装几次都是同一份。
    README 最后写也让它的版本号只在其他文件都放好后才更新。"""
    tag = f"v{version}"
    readme_path = os.path.join(FRAME_LIB, "README.md")
    with open(os.path.join(FRAME_LIB, "registry.js"), encoding="utf-8") as f:
        ops = [{"op": "put", "path": "registry.js", "content": f.read()}]
    notes = []
    for lib_path, repo_path in sorted(sources.items()):
        url, lic = f"{RAW_URL}/{tag}/{repo_path}", license_of(repo_path)
        ops.append({"op": "put", "path": lib_path, "url": url, "license": lic})
        notes.append(f"- `{lib_path}`：来源 {url}；许可 {lic}")  # 和 FRAME 自己写的记录逐字一致
    with open(readme_path, encoding="utf-8") as f:
        readme = f.read().rstrip("\n") + "\n\n## 来源与许可\n\n" + "\n".join(notes) + "\n"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)
    ops.append({"op": "put", "path": "README.md", "content": readme})
    head = {
        "version": version,
        "library": FRAME_LIB_NAME,
        "note": f"调用一次 material_write：library 用 {FRAME_LIB_NAME}，operations 原样用下面的数组，不要改动或自己写文件内容。失败的项只重试失败的。",
    }
    body = ",\n".join("  " + json.dumps(op, ensure_ascii=False) for op in ops)
    head_text = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    with open(os.path.join(DIST, "frame-install.json"), "w", encoding="utf-8") as f:
        f.write(f'{head_text},\n "operations": [\n{body}\n ]\n}}\n')

    # 网址取的是标签里的文件：标签不存在或和当前文件不一致时，FRAME 装到的就不是这次打包的内容
    paths = sorted(set(sources.values()))
    try:
        has_tag = subprocess.run(["git", "-C", ROOT, "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                                 capture_output=True).returncode == 0
        changed = has_tag and (
            subprocess.run(["git", "-C", ROOT, "diff", "--quiet", tag, "--", *paths]).returncode != 0
            or subprocess.run(["git", "-C", ROOT, "ls-files", "--others", "--exclude-standard", "--", *paths],
                              capture_output=True, text=True).stdout.strip())
    except OSError:
        has_tag, changed = False, False
    if not has_tag:
        print(f"注意：还没有标签 {tag}。frame-install.json 的网址指向它，发布前提交、打标签并推送后再打包。")
    elif changed:
        print(f"注意：素材库的文件和标签 {tag} 里的不一致，FRAME 会装到标签里的版本。改了文件就升版本号再打标签。")


sys.argv = ["make_prompt.py", ROOT]
runpy.run_path(os.path.join(SKILL, "scripts", "make_prompt.py"), run_name="__main__")

os.makedirs(DIST, exist_ok=True)
with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
    version = re.search(r'^version = "(.+)"', f.read(), re.M).group(1)
build_frame_install(version, build_frame_library(version))

outputs = {
    f"abt-{version}.zip": ("", [(ADDON, "")]),
    "abt-scene-skill.zip": ("abt-scene", [(SKILL, "abt-scene"), (os.path.join(DIST, "frame-install.json"), "abt-scene/frame-install.json")]),
}
for name, (prefix, items) in outputs.items():
    path = os.path.join(DIST, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in items:
            if os.path.isdir(src):
                add_tree(z, src, arc)
            else:
                z.write(src, arc)
        z.write(os.path.join(ROOT, "LICENSE"), os.path.join(prefix, "LICENSE"))
    print(f"dist/{name}  {os.path.getsize(path) / 1024:.0f} KB")
print(f"dist/frame-install.json  {os.path.getsize(os.path.join(DIST, 'frame-install.json')) / 1024:.1f} KB")
print(f"dist/frame-library/  {sum(len(fs) for _, _, fs in os.walk(FRAME_LIB))} 个文件")
