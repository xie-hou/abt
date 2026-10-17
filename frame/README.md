# AB to T

AB to T 的播放核心：作品写场景 JSON（abt-scene/0.1），这里把它渲染成 three.js 画面；同一份 JSON 还能导入 Blender 手调，改动实时写回。只给用 abt-scene skill 做的镜头用，其他作品不需要引用。

## 用法

一个镜头 = 作品里的 `abt/<镜头>.json` + 一个场景图层模块 `scenes/abt-<镜头>.ts`：

```ts
import type { SceneOptions } from "@frame/engine/types";
import { createAbtFrameScene } from "@materials/abt/frame";
import shot from "../abt/<镜头>.json";

// 画面由 ../abt/<镜头>.json 决定：改 JSON，或在 Blender 里调。这里不写画面代码。
export function createScene(options: SceneOptions) {
  return createAbtFrameScene(shot, options);
}
```

`scene.ts` 里注册模块（`"abt-<镜头>": () => import("./scenes/abt-<镜头>")`），`visual.json` 里放一个图层：
`{ "source": { "kind": "scene", "module": "abt-<镜头>", "engine": "three" }, "start": 0, "duration": <镜头时长> }`。
镜头时长 =（结束帧 − 起始帧 + 1）÷ fps。图层里的时间 0 对应 JSON 的起始帧。

## 内容

- FRAME 场景接口 `createAbtFrameScene(shot, options)`：`frame.js`
- 播放核心：`engine.js`
- 字体解析（opentype.js 2.0.0，MIT，见 `LICENSE-opentype.txt`），不联网：`opentype.mjs`
- 组件和字体清单（自动生成）：`registry.js`
- 效果组件（`three.js` 画面、`component.json` 参数说明、`blender.py` Blender 实现）：`components/<名>/`
- 字体：`fonts/`

版本 {version}，来自 https://github.com/xie-hou/abt 。不要在这里单独改文件：在 abt 仓库里改好、发布新版本后，用 abt-scene skill 里新的 frame-install.json 整体更新。
