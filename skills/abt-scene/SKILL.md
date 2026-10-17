---
name: abt-scene
description: 按 AB to T 规范（abt-scene/0.1）制作动画镜头：AI 写场景 JSON，three.js 直接播放，Blender 插件导入后每个参数都能手调，改动实时写回。用户想让 AI 生成 three.js 动画、镜头、片头、动态海报，又想之后在 Blender 里调整时使用；新增效果组件、检查场景 JSON、把场景导入 Blender 或修改已导入的镜头时也用；在 FRAME Studio 作品里也能用（作为 three 场景图层）。
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
- 让用户在 Blender 里操作：把场景 JSON 从文件夹拖进 3D 视图（或侧边栏 N → AB to T → **导入场景 JSON**），再点 **打开浏览器预览**。导入会自动开启实时同步；以后直接打开生成的 .blend 也会自动开启。
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

## 在 FRAME Studio 里用
工作目录是 FRAME 作品时（根目录 AGENTS.md 写着“FRAME 作品工作区”，作品在 `projects/<名称>/`），**不要** clone 仓库或另建 AB to T 项目，镜头作为一个 three 场景图层放进作品，FRAME 的播放器照常实时预览、导出。不用这个 skill 的作品照常写代码，不受影响。下文 `<作品>` = `projects/<名称>`。

**1. 素材库 abt（同一作品库只做一次，以后只在版本变了时更新）**
装素材库要做的操作都在 `<skill>/frame-install.json` 里（skill 包里有；从仓库装的 skill 没有它，在仓库根目录运行 `python tools/package.py` 后用 `dist/frame-install.json`）。
- `materials_list` 看有没有 `abt`。没有就用 `materials_link` 的 `create` 新建，文件夹名必须是 `abt`（代码里写 `@materials/abt/...`）。
- 已经有 `abt` 时，看它 README 里的版本号：和 frame-install.json 的 `version` 一样就跳过下一步。
- 调用**一次** `material_write`：`library` 写 `abt`，`operations` 原样用 frame-install.json 里的数组。不要改动，也不要自己写文件内容：大文件是 GitHub 上固定版本的网址，FRAME 服务器自己下载（同名文件成为新版本）。失败的项只重试失败的；下载失败多半是服务器连不上 GitHub，告诉用户，不要改成手写内容。
- 更新了旧版本时，作品里 `materials_use` 加 `update: true`。
- `materials_link` 让本作品引用 `abt`。

**2. 每个镜头**
- 镜头 JSON 写在 `<作品>/abt/<镜头>.json`，规范同上；字体写 `assets/fonts/<文件名>`，FRAME 里按文件名到素材库的 `fonts/` 找。
- 场景图层模块 `<作品>/scenes/abt-<镜头>.ts`，只有这几行，不写画面代码：
  ```ts
  import type { SceneOptions } from "@frame/engine/types";
  import { createAbtFrameScene } from "@materials/abt/frame";
  import shot from "../abt/<镜头>.json";

  export function createScene(options: SceneOptions) {
    return createAbtFrameScene(shot, options);
  }
  ```
- `scene.ts` 的 `createCompositionScene` 里注册 `"abt-<镜头>": () => import("./scenes/abt-<镜头>")`。
- 图层（`layers_edit` 或直接改 `visual.json`）：`{ "id": "abt-<镜头>", "name": "AB to T <镜头>", "source": { "kind": "scene", "module": "abt-<镜头>", "engine": "three" }, "start": <开始秒>, "duration": <镜头时长> }`。镜头时长 =（结束帧 − 起始帧 + 1）÷ fps，图层时间 0 对应 JSON 的起始帧；作品不够长就用 `work_update` 改时长。
- 作品画面的宽高比和 JSON 的 `meta.resolution` 保持一致（渲染尺寸由 FRAME 决定）。
- 检查：`python3 <skill>/scripts/validate.py <作品>/abt/<镜头>.json`，再用 FRAME 的 `work_check`；看画面用 `preview_frames`（三维场景软件渲染较慢，取少量时间点）。

**3. Blender**：和 FRAME 在同一台电脑上的 Blender 可以直接导入 `<作品>/abt/<镜头>.json`（拖进 3D 视图），组件和字体自动从素材库找，.blend 存在 JSON 旁边并自动加进作品的 `.gitignore`；手调实时写回 JSON，FRAME 预览跟着刷新。其他电脑上的 Blender 读不到 FRAME 服务器上的文件，暂不支持。

## 省 token
- 只查要改的对象，不要导出整个场景。
- 默认不截图、不渲染，让用户自己在 Blender 或浏览器里看；用户要求时再做。
