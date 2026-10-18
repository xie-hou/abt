"""voxel-wave 的 Blender 实现：和 three.js 版同一套公式，用 Geometry Nodes 搭。

参数接口由插件按 component.json 建好，这里只连节点。
坐标：three.js (x, y, z) → Blender (x, −z, y)。不显示的方块直接删掉（three.js 那边是缩成 0）。
删点会让序号变，所以颜色和缩放在删之前按原序号算好，存成点属性。
"""
import bpy

MATERIAL = "MAT_voxel-wave"


def material():
    """原理化 BSDF，底色读每个实例的 voxel_color；粗糙度 0.5、金属度 0，和 three.js 的 MeshStandardMaterial 一致。"""
    mat = bpy.data.materials.get(MATERIAL) or bpy.data.materials.new(MATERIAL)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type, attr.attribute_name = "INSTANCER", "voxel_color"
    attr.location = (-400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.5
    bsdf.inputs["Metallic"].default_value = 0.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (350, 0)
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build(ng, gi, go):
    N, link = ng.nodes, ng.links.new
    gi.location, go.location = (-1600, 0), (1300, 0)

    def node(kind, x, y, **props):
        n = N.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math(op, a, b, x, y, c=None):
        m = node("ShaderNodeMath", x, y, operation=op)
        for i, v in enumerate((a, b, c)):
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            elif v is not None:
                link(v, m.inputs[i])
        return m.outputs[0]

    p = gi.outputs
    i = node("GeometryNodeInputIndex", -1400, 400).outputs["Index"]
    t = node("GeometryNodeInputSceneTime", -1400, -500).outputs["Seconds"]
    size, layers, cell = p["Size"], p["Layers"], p["Cell"]

    # 第 i 块所在的列 (ix, iz) 和层 j
    area = math("MULTIPLY", size, size, -1200, 600)
    row = math("FLOOR", math("DIVIDE", i, size, -1200, 400), None, -1050, 400)
    ix = math("SUBTRACT", i, math("MULTIPLY", row, size, -900, 450), -750, 450)
    iz = math("SUBTRACT", row, math("MULTIPLY", math("FLOOR", math("DIVIDE", row, size, -900, 300), None, -750, 300), size, -600, 300), -450, 350)
    j = math("FLOOR", math("DIVIDE", i, area, -1050, 600), None, -900, 600)

    half = math("MULTIPLY", math("SUBTRACT", size, 1.0, -1200, 150), 0.5, -1050, 150)
    x = math("MULTIPLY", math("SUBTRACT", ix, half, -300, 450), cell, -150, 450)
    z = math("MULTIPLY", math("SUBTRACT", iz, half, -300, 300), cell, -150, 300)
    y = math("MULTIPLY", math("ADD", j, 0.5, -300, 600), cell, -150, 600)

    # 波纹决定这一列堆几块：k = ⌊h·layers + 0.5⌋，h = 0.5 + 0.5·amplitude·sin(r·frequency − t·speed)
    r = math("SQRT", math("ADD", math("MULTIPLY", x, x, 0, 200), math("MULTIPLY", z, z, 0, 100), 150, 150), None, 300, 150)
    phase = math("SUBTRACT", math("MULTIPLY", r, p["Frequency"], 450, 0), math("MULTIPLY", t, p["Speed"], 450, -150), 600, -50)
    h = math("ADD", math("MULTIPLY", math("MULTIPLY", math("SINE", phase, None, 750, -50), p["Amplitude"], 900, -50), 0.5, 1050, -50), 0.5, 1200, -50)
    k = math("FLOOR", math("ADD", math("MULTIPLY", h, layers, 1350, -50), 0.5, 1500, -50), None, 1650, -50)

    # 生长：s = clamp((1.3·reveal − rn) / 0.3, 0, 1)，rn = r / ((size−1)/2·cell·√2)
    rmax = math("MULTIPLY", math("MULTIPLY", half, cell, 300, -300), 2 ** 0.5, 450, -300)
    grow = node("ShaderNodeMath", 900, -350, operation="DIVIDE", use_clamp=True)
    link(math("SUBTRACT", math("MULTIPLY", p["Reveal"], 1.3, 600, -450), math("DIVIDE", r, rmax, 600, -300), 750, -350), grow.inputs[0])
    grow.inputs[1].default_value = 0.3
    s = grow.outputs[0]

    pos = node("ShaderNodeCombineXYZ", 300, 600)
    link(x, pos.inputs["X"])
    link(math("MULTIPLY", z, -1.0, 150, 300), pos.inputs["Y"])
    link(y, pos.inputs["Z"])

    points = node("GeometryNodePoints", 500, 700)
    link(math("MULTIPLY", area, layers, -1050, 750), points.inputs["Count"])
    link(pos.outputs["Vector"], points.inputs["Position"])

    def vmath(op, a, b, x, y, scale=None):
        m = node("ShaderNodeVectorMath", x, y, operation=op)
        link(a, m.inputs[0])
        if b is not None:
            link(b, m.inputs[1])
        if scale is not None:
            link(scale, m.inputs["Scale"])
        return m.outputs["Vector"]

    # 颜色按层：low + (high − low)·(j + 0.5) / layers；颜色、缩放都存成点属性
    f = math("DIVIDE", math("ADD", j, 0.5, 0, 900), layers, 150, 900)
    color = vmath("ADD", p["Low Color"], vmath("SCALE", vmath("SUBTRACT", p["High Color"], p["Low Color"], 0, 1050), None, 150, 1050, scale=f), 300, 1000)
    store = node("GeometryNodeStoreNamedAttribute", 700, 700, data_type="FLOAT_COLOR", domain="POINT")
    store.inputs["Name"].default_value = "voxel_color"
    link(points.outputs["Points"], store.inputs["Geometry"])
    link(color, store.inputs["Value"])
    store_s = node("GeometryNodeStoreNamedAttribute", 800, 550, data_type="FLOAT", domain="POINT")
    store_s.inputs["Name"].default_value = "voxel_scale"
    link(store.outputs["Geometry"], store_s.inputs["Geometry"])
    link(s, store_s.inputs["Value"])

    # 不显示的方块（j ≥ k，或还没长出来）删掉
    hidden = math("MAXIMUM", math("GREATER_THAN", j, math("SUBTRACT", k, 0.5, 1800, 100), 1950, 100), math("LESS_THAN", s, 1e-6, 1050, -350), 2100, 100)
    delete = node("GeometryNodeDeleteGeometry", 900, 700, domain="POINT")
    link(store_s.outputs["Geometry"], delete.inputs["Geometry"])
    link(hidden, delete.inputs["Selection"])

    block = math("MULTIPLY", cell, math("SUBTRACT", 1.0, p["Gap"], -300, 0), -150, 0)
    cube = node("GeometryNodeMeshCube", 0, -700)
    link(block, cube.inputs["Size"])
    setmat = node("GeometryNodeSetMaterial", 200, -700)
    setmat.inputs["Material"].default_value = material()
    link(cube.outputs["Mesh"], setmat.inputs["Geometry"])

    inst = node("GeometryNodeInstanceOnPoints", 1100, 600)
    link(delete.outputs["Geometry"], inst.inputs["Points"])
    link(setmat.outputs["Geometry"], inst.inputs["Instance"])
    scale = node("GeometryNodeInputNamedAttribute", 900, 400, data_type="FLOAT")
    scale.inputs["Name"].default_value = "voxel_scale"
    link(scale.outputs["Attribute"], inst.inputs["Scale"])
    link(inst.outputs["Instances"], go.inputs["Geometry"])
