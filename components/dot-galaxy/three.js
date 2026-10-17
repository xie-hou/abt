// dot-galaxy 的 three.js 实现。公式必须和 blender.py 保持一致。
// 第 i 个点：u = (i + 0.5) / count，r = radius·√u
//   θ = i·黄金角 + t·twist / (1 + r)
//   y = amplitude·sin(r·frequency − t·waveSpeed)
//   颜色 = mix(colorInner, colorOuter, u)·glow
import * as THREE from 'three';

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export function create() {
  const group = new THREE.Group();
  const geometry = new THREE.IcosahedronGeometry(1, 1);
  const material = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const m = new THREE.Matrix4();
  const c = new THREE.Color(), inner = new THREE.Color(), outer = new THREE.Color();
  let mesh = null;

  function ensure(count) {
    if (mesh && mesh.count === count) return;
    if (mesh) { group.remove(mesh); mesh.dispose(); }
    mesh = new THREE.InstancedMesh(geometry, material, count);
    mesh.frustumCulled = false;
    group.add(mesh);
  }

  function update(t, p) {
    const n = Math.max(1, Math.round(p.count));
    ensure(n);
    inner.setRGB(...p.colorInner);
    outer.setRGB(...p.colorOuter);
    for (let i = 0; i < n; i++) {
      const u = (i + 0.5) / n;
      const r = p.radius * Math.sqrt(u);
      const th = i * GOLDEN_ANGLE + (t * p.twist) / (1 + r);
      const y = p.amplitude * Math.sin(r * p.frequency - t * p.waveSpeed);
      m.makeScale(p.dotSize, p.dotSize, p.dotSize).setPosition(r * Math.cos(th), y, r * Math.sin(th));
      mesh.setMatrixAt(i, m);
      mesh.setColorAt(i, c.copy(inner).lerp(outer, u).multiplyScalar(p.glow));
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
