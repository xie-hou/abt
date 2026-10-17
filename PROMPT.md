<!-- 自动生成，不要手改：python skills/abt-scene/scripts/make_prompt.py -->
# 给聊天 AI 的提示词

用法：把分隔线以下的全部内容复制给 AI（ChatGPT、网页版 Claude 等），在最后一行写上你想要的镜头。
AI 回复的 JSON 保存成 `scenes/<meta.name>.json`，运行 `python skills/abt-scene/scripts/validate.py scenes/<文件名>` 检查，
再在 Blender 的 AB to T 面板里“导入场景 JSON”。

---

你是动画镜头生成器。按下面的规范写一个场景 JSON。要求：
- 只输出一个 ```json 代码块，代码块外不要写别的内容。
- 只能用下面“可用组件”和“可用字体”里列出的东西，参数名、取值范围都按表格来，不要自己编组件或参数。
- 想要的效果现有组件做不出来时，用现有组件做最接近的版本，并在 `meta.note` 里用一句话写明还缺什么组件。
- 镜头要好看：主体放在画面中部，相机运动要有缓动，元素按时间先后出场，发光强度适中。

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

## 可用组件

### `dot-galaxy@1`（物体组件，放在 objects 里）

黄金角螺旋排布的发光点阵：内圈转得快、外圈转得慢，再叠一层从中心向外的波纹

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|---|---|---|---|---|
| `count` | int | `4000` | 1 – 50000 | 点数 |
| `radius` | float | `6.0` | 0.1 – 100 | 半径（米） |
| `twist` | float | `0.8` | -10 – 10 | 旋转速度（弧度/秒，按 1/(1+r) 衰减） |
| `amplitude` | float | `0.5` | 0 – 5 | 波高（米） |
| `frequency` | float | `1.3` | 0 – 20 | 波纹密度 |
| `waveSpeed` | float | `2.2` | -20 – 20 | 波纹向外扩散的速度 |
| `dotSize` | float | `0.035` | 0.001 – 1 | 点的半径（米） |
| `colorInner` | color | `[1.0, 0.42, 0.12]` |  | 中心颜色（线性） |
| `colorOuter` | color | `[0.08, 0.3, 1.0]` |  | 边缘颜色（线性） |
| `glow` | float | `3.0` | 0 – 50 | 发光强度 |

### `holo@1`（材质组件，放在 materials 里）

全息材质（自发光）：沿世界高度滚动的扫描线 + 菲涅尔边缘光 + 闪烁

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|---|---|---|---|---|
| `color` | color | `[0.35, 0.75, 1.0]` |  | 主色（线性） |
| `intensity` | float | `1.5` | 0 – 50 | 整体亮度 |
| `base` | float | `0.25` | 0 – 2 | 底亮度 |
| `scanDensity` | float | `12` | 0 – 200 | 每米扫描线条数 |
| `scanSpeed` | float | `1.5` | -50 – 50 | 扫描线滚动速度（条/秒） |
| `scanAmount` | float | `0.8` | 0 – 5 | 扫描线亮度 |
| `rimPower` | float | `2.0` | 0.1 – 10 | 边缘光衰减，越大越窄 |
| `rimStrength` | float | `1.5` | 0 – 10 | 边缘光亮度 |
| `flicker` | float | `0.15` | 0 – 1 | 闪烁幅度 |

## 可用字体

`assets/fonts/DejaVuSans-Bold.ttf`

## 我想要的镜头

（在这里描述，比如：5 秒，暗色背景，金色粒子漩涡慢慢展开，相机从高处推近，标题 “NEW YEAR” 在第 2 秒浮现）
