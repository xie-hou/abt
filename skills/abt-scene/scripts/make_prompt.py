#!/usr/bin/env python3
"""生成 <项目>/PROMPT.md：给聊天 AI（ChatGPT、网页版 Claude 等）用的提示词。
内容 = 规范（../references/spec.md）+ 项目的组件目录（components/*/component.json）+ 可用字体。

    python make_prompt.py [项目目录]     # 不写就从当前目录往上找
"""
import json
import os
import sys

SPEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references", "spec.md")


def find_root(start):
    d = os.path.abspath(start)
    while not (os.path.isdir(os.path.join(d, "components")) and os.path.isdir(os.path.join(d, "web"))):
        if os.path.dirname(d) == d:
            sys.exit(f"找不到 AB to T 项目目录（同时含 components 和 web 的文件夹）：{start}")
        d = os.path.dirname(d)
    return d


def component_catalog(root):
    lines = []
    comp_dir = os.path.join(root, "components")
    for name in sorted(os.listdir(comp_dir)):
        path = os.path.join(comp_dir, name, "component.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        kind = "材质组件，放在 materials 里" if s.get("kind") == "material" else "物体组件，放在 objects 里"
        lines += [f"### `{s['name']}@{s['version']}`（{kind}）", "", s.get("description", ""), "",
                  "| 参数 | 类型 | 默认值 | 范围 | 说明 |", "|---|---|---|---|---|"]
        for key, p in s["params"].items():
            rng = f"{p['min']} – {p['max']}" if "min" in p else ""
            lines.append(f"| `{key}` | {p['type']} | `{json.dumps(p['default'])}` | {rng} | {p.get('desc', '')} |")
        lines.append("")
    return "\n".join(lines)


def fonts(root):
    d = os.path.join(root, "assets", "fonts")
    return ", ".join(f"`assets/fonts/{f}`" for f in sorted(os.listdir(d))) if os.path.isdir(d) else "（无）"


def main():
    root = find_root(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    with open(SPEC, encoding="utf-8") as f:
        spec = f.read().split("## 新建组件")[0].rstrip()  # 聊天 AI 写不了文件，不给它新建组件的说明
    text = f"""<!-- 自动生成，不要手改：python skills/abt-scene/scripts/make_prompt.py -->
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

{spec}

## 可用组件

{component_catalog(root)}
## 可用字体

{fonts(root)}

## 我想要的镜头

（在这里描述，比如：5 秒，暗色背景，金色粒子漩涡慢慢展开，相机从高处推近，标题 “NEW YEAR” 在第 2 秒浮现）
"""
    out = os.path.join(root, "PROMPT.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{out}  {len(text)} 字符")


if __name__ == "__main__":
    main()
