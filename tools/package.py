"""打包到 dist/（不进版本库，发布时上传到 GitHub Releases）：
  abt-<版本>.zip         Blender 插件，在 Blender 里“从磁盘安装”
  abt-scene-skill.zip    skill，可上传到 claude.ai，或解压到其他 AI 工具的 skills 目录
打包前会重新生成 PROMPT.md。

    python tools/package.py
"""
import os
import re
import runpy
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SKILL = os.path.join(ROOT, "skills", "abt-scene")
ADDON = os.path.join(ROOT, "blender", "abt")


def add_tree(z, src, arc_prefix):
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if not f.endswith(".pyc"):
                p = os.path.join(d, f)
                z.write(p, os.path.join(arc_prefix, os.path.relpath(p, src)))


sys.argv = ["make_prompt.py", ROOT]
runpy.run_path(os.path.join(SKILL, "scripts", "make_prompt.py"), run_name="__main__")

os.makedirs(DIST, exist_ok=True)
with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
    version = re.search(r'^version = "(.+)"', f.read(), re.M).group(1)
outputs = {f"abt-{version}.zip": (ADDON, ""), "abt-scene-skill.zip": (SKILL, "abt-scene")}
for name, (src, prefix) in outputs.items():
    path = os.path.join(DIST, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        add_tree(z, src, prefix)
    print(f"dist/{name}  {os.path.getsize(path) / 1024:.0f} KB")
