---
name: abt-scene
description: 按 AB to T 规范（abt-scene/0.1）制作动画镜头：AI 写场景 JSON，three.js 直接播放，Blender 插件导入后每个参数都能手调，改动实时写回。用户想让 AI 生成 three.js 动画、镜头、片头、动态海报，又想之后在 Blender 里调整时使用；新增效果组件、检查场景 JSON、把场景导入 Blender 或修改已导入的镜头时也用。
license: GPL-3.0-or-later（全文见 https://github.com/xie-hou/abt/blob/main/LICENSE）
---

# AB to T 镜头

不要直接写 three.js 代码：代码导进 Blender 只剩烘焙的结果，没法调。这里 AI 写的是一个**场景 JSON**：
- 浏览器里的 three.js 播放器读它播放；
- Blender 插件把它导入成原生对象、带贝塞尔手柄的关键帧、参数可调的 Geometry Nodes / 着色器节点；
- 在 Blender 里的手调实时写回同一个 JSON，浏览器跟着刷新。

本 skill 目录下：`references/spec.md` 是规范，`scripts/` 是工具（只用 Python 标准库）。下文的 `<skill>` 指本 skill 所在目录。

## 0. 找到或准备项目
需要一个 AB to T 项目：同时含 `components/`（效果组件）和 `web/`（播放器）的文件夹。
- 当前工作目录或其上级就是项目：直接用。
- 没有：`git clone https://github.com/xie-hou/abt.git`，或者如果 `<skill>/../..` 就是 abt 仓库（含 `web/` 和 `components/`），复制一份过去。
- 用户还没装 Blender 插件时，告诉他：仓库 Releases 里的 `abt-<版本>.zip`，或运行 `python tools/package.py` 生成；Blender 4.2 及以上 → 偏好设置 → 获取扩展 → 右上角 ⌄ → 从磁盘安装。

## 1. 写新镜头
1. 读 `<skill>/references/spec.md`。
2. 看项目的 `components/*/component.json`（有哪些组件、参数和范围）和 `assets/fonts/`（有哪些字体）。
3. 写 `scenes/<镜头名>.json`，`meta.name` 和文件名一致。文件已存在时先问用户：对应的 .blend 里可能有手调。
4. 现有组件做不出想要的效果：按规范末尾“新建组件”新建 `components/<名>/` 的三个文件，然后运行 `python <skill>/scripts/make_prompt.py <项目>` 更新给聊天 AI 用的 `PROMPT.md`。

## 2. 检查
`python <skill>/scripts/validate.py scenes/<镜头名>.json`（Linux / Mac 上用 python3），有错误就改到通过。

## 3. 预览和导入
- 让用户在 Blender 里操作：侧边栏（N）→ AB to T → **导入场景 JSON** → **打开浏览器预览**。导入会自动开启实时同步。
- 用户在插件设置里打开了“允许 AI 控制 Blender”时，AI 可以直接导入：
  `python <skill>/scripts/bl.py -c "abt.import_scene(r'<场景 JSON 的绝对路径>')"`
- 没有 Blender、只想看 three.js：在项目根目录运行 `python -m http.server 8000 --bind 127.0.0.1`，打开 `http://127.0.0.1:8000/web/?scene=scenes/<镜头名>.json`（`&frame=100` 可以跳到某一帧）。

## 4. 修改已导入的镜头
导入后以 Blender 为准。改动用 `scripts/bl.py` 在 Blender 里增量修改，实时同步会写回 JSON；不要直接改 JSON（会被覆盖），也不要重新导入（会冲掉手调），除非用户同意（`abt.import_scene(路径, force=True)`）。

`bl.py -c` 执行的代码里可以直接用 `bpy`、`abt`（插件 core 模块）：
- 找对象：JSON 里的 id 就是 Blender 物体名，也存在 `ob["abt_id"]`。
- 物体组件参数：`abt.get_param(ob, "twist")` / `abt.set_param(ob, "twist", 1.2)`（各版本 Blender 通用，不要直接碰修改器的输入接口）。
- 代码材质参数：`bpy.data.materials["<材质 id>"].node_tree.nodes["abt_component"].inputs["<参数 label>"].default_value`。
- 实时同步：`abt.live(True)` / `abt.live(False)`；手动写回：`abt.export_all()`。
- Blender 界面是中文时，新建节点的默认名会被翻译：按 `bl_idname` 找节点，不要按名字。

## 省 token
- 只查要改的对象，不要导出整个场景。
- 默认不截图、不渲染，让用户自己在 Blender 或浏览器里看；用户要求时再做。
