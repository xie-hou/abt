# 场景规范 abt-scene/0.1

一个镜头 = 一个 JSON 文件，放在 `scenes/<镜头名>.json`。浏览器（three.js）直接播放它，Blender 插件把它导入成可以手调的原生场景，手调结果再写回这个文件。

## 约定
- 坐标：**Y 向上**、右手系、单位米（three.js / glTF 约定）。地面是 XZ 平面，相机一般放在 +Z 一侧看向原点附近。
- 颜色：场景线性 RGB。0–1 是常规范围，大于 1 表示更亮的发光（配合 bloom 出光晕）。
- 时间：用帧号。组件和代码材质拿到的时间 t = 帧 / fps（秒）。
- 色调映射统一用 AgX，亮部会偏白：想保留颜色，发光强度别太高（1–3 左右）。
- 文字 `size` = 大写字母 H 的高度（米）。

## 顶层结构
```json
{
  "spec": "abt-scene/0.1",
  "meta": {"name": "shot03", "fps": 24, "frames": [1, 144], "resolution": [1920, 1080], "preview_frame": 100},
  "color": {"exposure": 0},
  "world": {"color": [0.006, 0.008, 0.018], "strength": 1},
  "post": {"bloom": {"threshold": 1.0, "strength": 0.35, "radius": 0.3}},
  "materials": {},
  "objects": [],
  "animation": []
}
```
- `meta.name` 必须和文件名一致；`preview_frame` 可选，导入后 Blender 停在这一帧。
- `color`、`world`、`post` 都可以省略；`post.bloom` 只有一种后期：辉光。

## 材质 `materials`
键是材质 id，值是下面两种之一：
- 普通 PBR：`{"color": [r,g,b], "roughness": 0.5, "metalness": 0, "emissive": [r,g,b], "emissiveIntensity": 0}`
- 代码材质：`{"component": "holo@1", "params": {...}}`，只能用组件目录里 `kind` 为 `material` 的组件，`params` 只写要改的参数。

## 对象 `objects`
每个对象都有：`id`（唯一，小写加下划线，如 `cam_main`）、`type`、`position` `[x, y, z]`，可选 `scale`（一个数或 `[x, y, z]`）。

| type | 其他字段 |
|---|---|
| `empty` | 无。常用作相机或灯光的目标点 |
| `camera` | `lens` 焦距 mm（默认 50，常用 24–50）、`sensor` 传感器宽 mm（默认 36）、`target` 对准的对象 id |
| `sun` | `intensity`（常用 1–5）、`color`、`target`：光从 `position` 照向 `target` |
| `text` | `text`、`font`（字体路径，如 `assets/fonts/DejaVuSans-Bold.ttf`）、`size`（H 的高度，米）、`depth`（厚度，米）、`material`（材质 id）。原点在基线中点，正面朝 +Z |
| `component` | `component`（如 `dot-galaxy@1`）、`params`（只写要改的参数，其余用默认值） |

- 必须有且只有一个 `camera`。
- 暂不支持旋转：需要朝向的用 `target`，文字永远正面朝 +Z。

## 动画 `animation`
```json
{"target": "cam_main", "path": "position", "keys": [{"f": 1, "v": [0, 7, 13]}, {"f": 144, "v": [3, 2.2, 8.5], "ease": "out"}]}
```
- `target`：对象 id，或代码材质的 id。
- `path`：
  - `position`、`scale`：`v` 是 `[x, y, z]`（`scale` 也可以是一个数）；只动一个轴就写 `position.y`，`v` 是一个数。
  - `lens`（camera）、`intensity`（sun）：`v` 是一个数。
  - `params.<参数名>`（component 对象或代码材质）：`v` 是一个数。颜色参数暂不能做动画。
- 关键帧：`f` 帧号（递增）、`v` 值、`ease` 本段缓动（`inOut` 默认 / `in` 慢起 / `out` 慢停）、`interp`（`bezier` 默认 / `linear` / `constant`）。
- 第一帧之前、最后一帧之后保持端点的值。

## 完整示例
```json
{
  "spec": "abt-scene/0.1",
  "meta": {"name": "example", "fps": 24, "frames": [1, 120], "resolution": [1920, 1080], "preview_frame": 90},
  "world": {"color": [0.006, 0.008, 0.018], "strength": 1},
  "post": {"bloom": {"threshold": 1.0, "strength": 0.35, "radius": 0.3}},
  "materials": {
    "mat_title": {"component": "holo@1", "params": {"color": [1.0, 0.5, 0.2], "scanSpeed": 3}}
  },
  "objects": [
    {"id": "cam_target", "type": "empty", "position": [0, 0.6, 0]},
    {"id": "cam_main", "type": "camera", "lens": 35, "position": [0, 4, 12], "target": "cam_target"},
    {"id": "fx_galaxy", "type": "component", "component": "dot-galaxy@1", "position": [0, 0, 0], "params": {"radius": 5, "glow": 1.5}},
    {"id": "txt_title", "type": "text", "text": "HELLO", "font": "assets/fonts/DejaVuSans-Bold.ttf", "size": 0.5, "depth": 0.06,
     "material": "mat_title", "position": [0, 1.5, -1]}
  ],
  "animation": [
    {"target": "cam_main", "path": "position", "keys": [{"f": 1, "v": [0, 4, 12]}, {"f": 120, "v": [2, 2, 8]}]},
    {"target": "fx_galaxy", "path": "params.amplitude", "keys": [{"f": 1, "v": 0, "ease": "out"}, {"f": 48, "v": 0.5}]},
    {"target": "txt_title", "path": "scale", "keys": [{"f": 30, "v": 0.001, "ease": "out"}, {"f": 60, "v": 1}]},
    {"target": "mat_title", "path": "params.intensity", "keys": [{"f": 30, "v": 0}, {"f": 60, "v": 1.5}]}
  ]
}
```

## 新建组件（需要能写文件的 AI，比如 Claude Code）
现有组件做不出想要的效果时，新建 `components/<名>/`，三个文件缺一不可：
- `component.json`：`name`、`version`、`description`、`params`（每个参数 `label`、`type`（int/float/color/bool）、`default`、`min`/`max`、`desc`）；材质组件加 `"kind": "material"`。
- `three.js`：物体组件导出 `create()` → `{object, update(t, params), dispose()}`；材质组件导出 `createMaterial()` → `{material, update(t, params), dispose()}`。
- `blender.py`：`build(ng, gi, go)`，物体组件用 Geometry Nodes 搭，材质组件用着色器节点搭（有 `Time` 输入）。参数接口由插件按 `component.json` 自动建好。

规则：两边公式完全一致；画面只由 (t, 参数) 决定，不用随机数和系统时钟；three.js 的 Y 是 Blender 的 Z（Blender y = −three z）。噪声类效果两边算法不同，要么避开，要么两边用同一份噪声实现。光线步进、屏幕空间这类节点表达不了的效果，不适合做成组件。
