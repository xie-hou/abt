// holo 材质的 three.js 实现（GLSL）。公式必须和 blender.py 保持一致：
//   scan  = (0.5 + 0.5·sin(2π·(高度·scanDensity − t·scanSpeed)))⁴ · scanAmount
//   rim   = (1 − |N·V|)^rimPower · rimStrength
//   flick = 1 − flicker·(0.5 + 0.5·sin(23t)·sin(7.3t))
//   颜色  = color · intensity · (base + scan + rim) · flick
// 高度用世界坐标 Y（Blender 里是 Z），t = 帧 / fps。
import * as THREE from 'three';

const vertexShader = /* glsl */ `
varying vec3 vWorldPos;
varying vec3 vWorldNormal;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
  vWorldNormal = normalize(mat3(modelMatrix) * normal);
  gl_Position = projectionMatrix * viewMatrix * wp;
}`;

const fragmentShader = /* glsl */ `
uniform float uTime, uIntensity, uBase, uScanDensity, uScanSpeed, uScanAmount, uRimPower, uRimStrength, uFlicker;
uniform vec3 uColor;
varying vec3 vWorldPos;
varying vec3 vWorldNormal;
void main() {
  vec3 n = normalize(vWorldNormal);
  vec3 v = normalize(cameraPosition - vWorldPos);
  float scan = pow(0.5 + 0.5 * sin(6.283185307 * (vWorldPos.y * uScanDensity - uTime * uScanSpeed)), 4.0) * uScanAmount;
  float rim = pow(1.0 - abs(dot(n, v)), uRimPower) * uRimStrength;
  float flick = 1.0 - uFlicker * (0.5 + 0.5 * sin(uTime * 23.0) * sin(uTime * 7.3));
  gl_FragColor = vec4(uColor * uIntensity * (uBase + scan + rim) * flick, 1.0);
}`;

const UNIFORM = {
  intensity: 'uIntensity', base: 'uBase', scanDensity: 'uScanDensity', scanSpeed: 'uScanSpeed',
  scanAmount: 'uScanAmount', rimPower: 'uRimPower', rimStrength: 'uRimStrength', flicker: 'uFlicker',
};

export function createMaterial() {
  const uniforms = { uTime: { value: 0 }, uColor: { value: new THREE.Color() } };
  for (const u of Object.values(UNIFORM)) uniforms[u] = { value: 0 };
  const material = new THREE.ShaderMaterial({ uniforms, vertexShader, fragmentShader });

  function update(t, p) {
    uniforms.uTime.value = t;
    uniforms.uColor.value.setRGB(...p.color);
    for (const [key, u] of Object.entries(UNIFORM)) uniforms[u].value = p[key];
  }

  return { material, update, dispose: () => material.dispose() };
}
