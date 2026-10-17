# 开发 AB to T 仓库

AI 写场景 JSON → three.js 播放 → Blender 插件导入、手调、实时写回。用户文档见 README.md。

## 做镜头、改镜头
按 `skills/abt-scene/SKILL.md` 做（规范在 `skills/abt-scene/references/spec.md`）。下文 `<skill>` = `skills/abt-scene`。
- 检查：`python <skill>/scripts/validate.py scenes/x.json`（Linux 上用 python3）
- 操作 Blender：`python <skill>/scripts/bl.py -c "..."`，可直接用 `bpy`、`abt`（插件 core）
- 导入后以 Blender 为准：改 Blender，不要直接改 JSON；重新导入会冲掉手调，必须先问

## 仓库结构
- `blender/abt/`：Blender 扩展（core 导入导出和实时同步、bridge 给 AI 用的本机端口、server 预览服务器、ui 面板）
- `components/<名>/`：效果组件，`component.json` + `three.js` + `blender.py`，两边公式必须一致
- `web/`：three.js 播放器；`skills/abt-scene/`：skill，规范只在这里存一份
- `.claude-plugin/`：仓库根目录同时是 Claude Code 插件市场和插件，改完运行 `claude plugin validate .`
- `PROMPT.md`：给聊天 AI 的提示词，由 `<skill>/scripts/make_prompt.py` 生成，新增组件后要重新生成
- 打包：`python tools/package.py` → `dist/abt-<版本>.zip`（Blender 插件）、`dist/abt-scene-skill.zip`

## 改插件
- 支持 Blender 4.2+：版本差异（修改器输入 5.x 在 `mod.properties.inputs`、4.x 是 `mod["Socket_N"]`；合成器 5.x 是 `scene.compositing_node_group`、4.x 是 `scene.node_tree`；4.4 起动作是分层的；EEVEE 名字；EXR 输出）都在 core.py 里分支处理，改完在 4.2、4.5、5.x 上都测
- 改完在 Blender 里停用再启用插件（`__init__.py` 会重载子模块）
- 界面是中文时新建节点的默认名会被翻译：按 `bl_idname` 找节点
- 本服务器的内置浏览器建不了 WebGL，验证 three.js 画面用无头 Chrome：`google-chrome --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader --screenshot=... URL`

## 规则
- 不写死：动画只用关键帧、驱动器、Geometry Nodes；不用 Python 回调驱动画面；不应用修改器
- 数据只存一份：素材放 `assets/`，相对路径引用，不打包进 .blend；`dist/ renders/ cache/` 和 .blend 都不进版本库
- 省 token：只查要改的对象；用户没要求时不截图、不渲染
