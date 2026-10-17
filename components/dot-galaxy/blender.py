"""dot-galaxy 的 Blender 实现：和 three.js 版同一套公式，用 Geometry Nodes 搭。

参数接口由 tools/abt.py 按 component.json 建好，这里只连节点。
坐标：three.js (r·cosθ, y, r·sinθ) → Blender (r·cosθ, −r·sinθ, y)
"""
import bpy

GOLDEN_ANGLE = 2.399963229728653  # π(3 − √5)，与 three.js 版一致
MATERIAL = "MAT_dot-galaxy"


def material():
    mat = bpy.data.materials.get(MATERIAL) or bpy.data.materials.new(MATERIAL)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "INSTANCER"
    attr.attribute_name = "dot_color"
    attr.location = (-400, 0)
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (250, 0)
    nt.links.new(attr.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def build(ng, gi, go):
    N, link = ng.nodes, ng.links.new
    gi.location, go.location = (-1400, 0), (1000, 0)

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

    def vmath(op, a, b, x, y, scale=None):
        m = node("ShaderNodeVectorMath", x, y, operation=op)
        link(a, m.inputs[0])
        if b is not None:
            link(b, m.inputs[1])
        if scale is not None:
            link(scale, m.inputs["Scale"])
        return m.outputs["Vector"]

    p = gi.outputs
    idx = node("GeometryNodeInputIndex", -1200, 300).outputs["Index"]
    t = node("GeometryNodeInputSceneTime", -1200, -300).outputs["Seconds"]

    u = math("DIVIDE", math("ADD", idx, 0.5, -1000, 300), p["Count"], -850, 300)
    r = math("MULTIPLY", math("SQRT", u, None, -700, 200), p["Radius"], -550, 200)
    spin = math("DIVIDE", math("MULTIPLY", t, p["Twist"], -700, -100), math("ADD", r, 1.0, -400, 0), -250, -50)
    theta = math("ADD", math("MULTIPLY", idx, GOLDEN_ANGLE, -700, 50), spin, -100, 50)
    phase = math("SUBTRACT", math("MULTIPLY", r, p["Frequency"], -400, -250), math("MULTIPLY", t, p["Wave Speed"], -400, -400), -250, -300)
    height = math("MULTIPLY", math("SINE", phase, None, -100, -300), p["Amplitude"], 50, -300)

    pos = node("ShaderNodeCombineXYZ", 250, 0)
    link(math("MULTIPLY", r, math("COSINE", theta, None, 50, 100), 150, 150), pos.inputs["X"])
    link(math("MULTIPLY", math("MULTIPLY", r, math("SINE", theta, None, 50, 0), 150, 0), -1.0, 250, -100), pos.inputs["Y"])
    link(height, pos.inputs["Z"])

    points = node("GeometryNodePoints", 450, 200)
    link(p["Count"], points.inputs["Count"])
    link(pos.outputs["Vector"], points.inputs["Position"])

    # 颜色 = (inner + (outer − inner)·u)·glow，存成点属性，材质里按实例读取
    color = vmath("ADD", p["Inner Color"], vmath("SCALE", vmath("SUBTRACT", p["Outer Color"], p["Inner Color"], -550, -600), None, -350, -600, scale=u), -150, -600)
    color = vmath("SCALE", color, None, 50, -600, scale=p["Glow"])
    store = node("GeometryNodeStoreNamedAttribute", 650, 200, data_type="FLOAT_COLOR", domain="POINT")
    store.inputs["Name"].default_value = "dot_color"
    link(points.outputs["Points"], store.inputs["Geometry"])
    link(color, store.inputs["Value"])

    ico = node("GeometryNodeMeshIcoSphere", 450, -250)
    ico.inputs["Subdivisions"].default_value = 2
    link(p["Dot Size"], ico.inputs["Radius"])
    setmat = node("GeometryNodeSetMaterial", 650, -250)
    setmat.inputs["Material"].default_value = material()
    link(ico.outputs["Mesh"], setmat.inputs["Geometry"])

    inst = node("GeometryNodeInstanceOnPoints", 850, 100)
    link(store.outputs["Geometry"], inst.inputs["Points"])
    link(setmat.outputs["Geometry"], inst.inputs["Instance"])
    link(inst.outputs["Instances"], go.inputs["Geometry"])
