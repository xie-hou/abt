"""holo 材质的 Blender 实现：和 three.js 版同一套公式，用着色器节点搭。

参数接口（含 Time 输入）由插件按 component.json 建好，这里只连节点。
Time 由材质里的驱动器 frame / fps 提供；高度取世界坐标 Z（three.js 的 Y）。
"""
from math import tau


def build(ng, gi, go):
    N, link = ng.nodes, ng.links.new
    gi.location, go.location = (-1300, 0), (900, 0)

    def node(kind, x, y, **props):
        n = N.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math(op, a, b, x, y):
        m = node("ShaderNodeMath", x, y, operation=op)
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            elif v is not None:
                link(v, m.inputs[i])
        return m.outputs[0]

    p, t = gi.outputs, gi.outputs["Time"]

    # 扫描线
    height = node("ShaderNodeSeparateXYZ", -1050, 300)
    link(node("ShaderNodeNewGeometry", -1250, 300).outputs["Position"], height.inputs[0])
    phase = math("SUBTRACT", math("MULTIPLY", height.outputs["Z"], p["Scan Density"], -850, 300),
                 math("MULTIPLY", t, p["Scan Speed"], -850, 150), -680, 250)
    wave = math("ADD", math("MULTIPLY", math("SINE", math("MULTIPLY", phase, tau, -520, 250), None, -360, 250), 0.5, -200, 250), 0.5, -40, 250)
    scan = math("MULTIPLY", math("POWER", wave, 4.0, 120, 250), p["Scan Amount"], 280, 250)

    # 边缘光：Layer Weight 的 Facing（混合 0.5）= 1 − |N·V|
    facing = node("ShaderNodeLayerWeight", -360, 0)
    facing.inputs["Blend"].default_value = 0.5
    rim = math("MULTIPLY", math("POWER", facing.outputs["Facing"], p["Rim Power"], -160, 0), p["Rim Strength"], 20, 0)

    # 闪烁
    flick_wave = math("MULTIPLY", math("SINE", math("MULTIPLY", t, 23.0, -680, -250), None, -520, -250),
                      math("SINE", math("MULTIPLY", t, 7.3, -680, -400), None, -520, -400), -360, -300)
    flick = math("SUBTRACT", 1.0, math("MULTIPLY", p["Flicker"], math("ADD", math("MULTIPLY", flick_wave, 0.5, -200, -300), 0.5, -40, -300), 120, -300), 280, -300)

    level = math("MULTIPLY", math("MULTIPLY", math("ADD", math("ADD", p["Base"], scan, 440, 150), rim, 580, 100), flick, 720, 0), p["Intensity"], 720, -150)
    color = node("ShaderNodeVectorMath", 720, 200, operation="SCALE")
    link(p["Color"], color.inputs[0])
    link(level, color.inputs["Scale"])
    emission = node("ShaderNodeEmission", 860, 200)
    link(color.outputs["Vector"], emission.inputs["Color"])
    link(emission.outputs["Emission"], go.inputs["Shader"])
