"""生成 web/agx-lut.js：让 three.js 的色调映射和 Blender 的 AgX（sRGB 显示）逐步一致。

Blender 的 AgX = 场景线性 Rec.709 → 线性 E-Gamut → log2（[-12.47393, 12.5260688117] 映射到 0–1）
→ 查 3D 表 AgX_Base_sRGB.cube（四面体插值）→ ^2.4 → sRGB 编码（见 Blender 的 colormanagement/config.ocio）。
这里把那张 57³ 的表存成 8 位、deflate 压缩后 base64，矩阵一起写进去；着色器在 web/abt-engine.js。
这张表在 Blender 4.2 – 5.2 里完全相同，换 Blender 版本后一般不用重新生成。

    python tools/make_agx_lut.py <Blender 目录>/<版本>/datafiles/colormanagement
"""
import base64
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Blender 5.2 config.ocio 里的矩阵（行优先）：CIE XYZ D65 → 线性 Rec.709、CIE XYZ D65 → 线性 E-Gamut
XYZ_TO_REC709 = [[3.2409699, -1.5373832, -0.4986108], [-0.9692436, 1.8759675, 0.0415551], [0.0556301, -0.2039770, 1.0569715]]
XYZ_TO_EGAMUT = [[1.5250528, -0.3159135, -0.1226583], [-0.5091526, 1.3333274, 0.1382844], [0.0957153, 0.0508974, 0.7879558]]
LOG_MIN, LOG_MAX = -12.47393, 12.5260688117


def inverse(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


def matmul(x, y):
    return [[sum(x[r][k] * y[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = os.path.join(sys.argv[1], "luts", "AgX_Base_sRGB.cube")
    size, values = None, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0].startswith("#") or parts[0] in ("TITLE", "DOMAIN_MIN", "DOMAIN_MAX"):
                continue
            if parts[0] == "LUT_3D_SIZE":
                size = int(parts[1])
            else:
                values += [min(255, max(0, round(float(v) * 255))) for v in parts[:3]]
    assert size and len(values) == size ** 3 * 3, (size, len(values))
    data = base64.b64encode(zlib.compress(bytes(values), 9)).decode("ascii")  # 红色变化最快，和 three 的 3D 纹理顺序一致
    to_egamut = matmul(XYZ_TO_EGAMUT, inverse(XYZ_TO_REC709))
    text = "\n".join([
        "// 自动生成（tools/make_agx_lut.py），不要手改：Blender 的 AgX 色调映射（sRGB 显示）。",
        "// 场景线性 Rec.709 → toEGamut → log2，[lo, hi] 映射到 0–1 → 查 3D 表（四面体插值）→ ^2.4 → sRGB 编码。",
        f"// 3D 表 {size}³ 来自 Blender 自带的 datafiles/colormanagement/luts/AgX_Base_sRGB.cube（Blender 4.2 – 5.2 相同，",
        "// 随 Blender 以 GPL 发布），8 位存储，deflate 压缩后 base64。",
        "export const AGX = {",
        f"  size: {size}, lo: {LOG_MIN}, hi: {LOG_MAX},",
        f"  toEGamut: [{', '.join(f'{v:.9f}' for row in to_egamut for v in row)}],",
        f'  data: "{data}",',
        "};",
        "",
    ])
    out = os.path.join(ROOT, "web", "agx-lut.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{out}  {len(text) // 1024} KB")


if __name__ == "__main__":
    main()
