// voxel-wave 的 three.js 实现。公式必须和 blender.py 保持一致（坐标是 three 的，Y 向上）。
// 第 i 块：ix = i mod size，iz = ⌊i / size⌋ mod size，层 j = ⌊i / size²⌋
//   x = (ix − (size−1)/2)·cell，z = (iz − (size−1)/2)·cell，y = (j + 0.5)·cell
//   r = √(x² + z²)，rn = r / ((size−1)/2·cell·√2)
//   h = 0.5 + 0.5·amplitude·sin(r·frequency − t·speed)，这一列有 k = ⌊h·layers + 0.5⌋ 块
//   生长 s = clamp((1.3·reveal − rn) / 0.3, 0, 1)；j < k 且 s > 0 才显示，边长 = cell·(1 − gap)·s
//   颜色 = mix(colorLow, colorHigh, (j + 0.5) / layers)
import * as THREE from 'three';

export function create() {
  const group = new THREE.Group();
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5, metalness: 0 }); // 和 Blender 的原理化 BSDF 默认一致
  const m = new THREE.Matrix4(), zero = new THREE.Matrix4().makeScale(0, 0, 0);
  const c = new THREE.Color(), low = new THREE.Color(), high = new THREE.Color();
  let mesh = null;

  function ensure(count) {
    if (mesh && mesh.count === count) return;
    if (mesh) { group.remove(mesh); mesh.dispose(); }
    mesh = new THREE.InstancedMesh(geometry, material, count);
    mesh.frustumCulled = false;
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
  }

  function update(t, p) {
    const size = Math.max(2, Math.round(p.size)), layers = Math.max(1, Math.round(p.layers));
    ensure(size * size * layers);
    low.setRGB(...p.colorLow);
    high.setRGB(...p.colorHigh);
    const half = (size - 1) / 2, rmax = half * p.cell * Math.SQRT2, block = p.cell * (1 - p.gap);
    for (let i = 0; i < size * size * layers; i++) {
      const ix = i % size, iz = Math.floor(i / size) % size, j = Math.floor(i / (size * size));
      const x = (ix - half) * p.cell, z = (iz - half) * p.cell;
      const r = Math.sqrt(x * x + z * z);
      const h = 0.5 + 0.5 * p.amplitude * Math.sin(r * p.frequency - t * p.speed);
      const k = Math.floor(h * layers + 0.5);
      const s = Math.min(1, Math.max(0, (1.3 * p.reveal - r / rmax) / 0.3));
      if (j < k && s > 0) {
        mesh.setMatrixAt(i, m.makeScale(block * s, block * s, block * s).setPosition(x, (j + 0.5) * p.cell, z));
      } else {
        mesh.setMatrixAt(i, zero);
      }
      mesh.setColorAt(i, c.copy(low).lerp(high, (j + 0.5) / layers));
    }
    mesh.instanceMatrix.needsUpdate = true;
    mesh.instanceColor.needsUpdate = true;
  }

  function dispose() {
    mesh?.dispose();
    geometry.dispose();
    material.dispose();
  }

  return { object: group, update, dispose };
}
