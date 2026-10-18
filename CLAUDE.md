# 开发 AB to T 仓库

AI 写场景 JSON → three.js 播放 → Blender 插件导入、手调、实时写回。用户文档见 README.md。

## 做镜头、改镜头
按 `skills/abt-scene/SKILL.md` 做（规范在 `skills/abt-scene/references/spec.md`）。下文 `<skill>` = `skills/abt-scene`。
- 检查：`python <skill>/scripts/validate.py scenes/x.json`（Linux 上用 python3）
- 操作 Blender：`python <skill>/scripts/bl.py -c "..."`，可直接用 `bpy`、`abt`（插件 core）
- 导入后以 Blender 为准：改 Blender，不要直接改 JSON；重新导入会冲掉手调，必须先问

## 仓库结构
- `blender/abt/`：Blender 扩展（core 导入导出和实时同步、bridge 给 AI 用的本机端口、frame_link 连接服务器上的 FRAME（配对、长轮询、镜头副本、写回上传；协议和 frame-studio 的 server/blender.mjs 一致）、server 预览服务器、ui 面板）
- `components/<名>/`：效果组件，`component.json` + `three.js` + `blender.py`，两边公式必须一致
- `web/abt-engine.js`：播放核心（浏览器预览 `web/runtime.js` 和 FRAME 共用）；`frame/`：FRAME 场景图层接口和素材库 README；`vendor/`：opentype.js（不用 three 的 TTFLoader，新版会从 CDN 加载）
- `skills/abt-scene/`：skill，规范只在这里存一份
- `.claude-plugin/`：仓库根目录同时是 Claude Code 插件市场和插件，改完运行 `claude plugin validate .`
- `PROMPT.md`：给聊天 AI 的提示词，由 `<skill>/scripts/make_prompt.py` 生成，新增组件后要重新生成
- 打包：`python tools/package.py` → `dist/abt-<版本>.zip`（Blender 插件）、`dist/abt-scene-skill.zip`（含 `frame-install.json`）、`dist/frame-install.json`（FRAME 的 AI 用一次 `material_write` 装素材库 abt，大文件是标签 `v<版本>` 的 raw.githubusercontent 网址）、`dist/frame-library/`（装好后的素材库，测试用）
- 发布顺序：升版本号 → 提交 → 打标签并推送 → 再打包（网址指向标签，package.py 会检查标签和文件是否一致）
- 两种项目布局：AB to T 项目（components/ + web/）和 FRAME 作品（projects/<作品>/abt/<镜头>.json，组件字体在 .materials/abt），`core.find_root` 和 validate.py 都要认
- 测 FRAME：用 frame-studio 镜像起临时容器跑 Vite，别名 `@frame/engine`→/app/src/engine、`@materials`→模拟作品的 .materials，无头 Chrome 截图；不要动线上容器和数据
- 测连接 FRAME（frame_link）：本机起 frame-studio 开发服务器（独立的 FRAME_HOME），Blender 用 `BLENDER_USER_RESOURCES=<临时目录>` 隔离配置、`blender --command extension build/install-file` 装插件、`xvfb-run` 起界面；插件的本机 AI 端口（bl.py）用来模拟用户在面板里的操作，FRAME 那边用 `frame call blender_*` 调工具

## 改插件
- 支持 Blender 4.2+：版本差异（修改器输入 5.x 在 `mod.properties.inputs`、4.x 是 `mod["Socket_N"]`；合成器 5.x 是 `scene.compositing_node_group`、4.x 是 `scene.node_tree`；4.4 起动作是分层的；EEVEE 名字；EXR 输出）都在 core.py 里分支处理，改完在 4.2、4.5、5.x 上都测
- 改完重启 Blender 生效；不想重启就用 bl.py 在定时器里：停用插件 → `importlib.reload` core、server、bridge、frame_link、ui → 再启用（只改子模块时 Blender 不会自己重载）
- 旋转：规范是 three.js 的 XYZ 欧拉角（度）；Blender 里一般物体用 YZX 模式、文字和相机用 ZYX 模式（x 多 90°），这样通道一一对应、关键帧能原样往返（`core.rot_spec`）
- 界面是中文时新建节点的默认名会被翻译：按 `bl_idname` 找节点
- 本服务器的内置浏览器建不了 WebGL，验证 three.js 画面用无头 Chrome：`google-chrome --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader --screenshot=... URL`

## 规则
- 不写死：动画只用关键帧、驱动器、Geometry Nodes；不用 Python 回调驱动画面；不应用修改器
- 数据只存一份：素材放 `assets/`，相对路径引用，不打包进 .blend；`dist/ renders/ cache/` 和 .blend 都不进版本库
- 省 token：只查要改的对象；用户没要求时不截图、不渲染
