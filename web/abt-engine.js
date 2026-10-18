// AB to T 播放核心：把场景 JSON（abt-scene/0.1）搭成 three.js 场景，按帧号或时间渲染。
// 浏览器预览（runtime.js）和 FRAME 的场景图层（frame/frame.js）共用这一份。
// 画面只由“帧号 + 文档”决定，不读系统时钟。组件、字体、图片从哪里来由调用方传入：
//   loaders = { loadComponent(spec) → Promise<{ schema, module }>, loadFont(path) → Promise<opentype 字体>,
//               imageUrl(src) → 图片网址 }
// 字体用 opentype.js 解析（调用方传入，见 createFontCache）；不用 three 的 TTFLoader：新版 three 的 TTFLoader
// 在导入时会从 CDN 加载 opentype.js，FRAME 里不允许联网，导出时也可能断网。
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { Font } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';
import { AGX } from './agx-lut.js';

// ---------- 关键帧求值：与 Blender F 曲线一致（贝塞尔手柄 / 线性 / 常量，两端保持） ----------
// 缓动简写 → 区间比例（出手柄 dt, 出手柄 dv, 入手柄 dt, 入手柄 dv），与 blender/abt/core.py 的 EASE 一致
const EASE = { inOut: [1 / 3, 0, 1 / 3, 0], in: [1 / 3, 0, 1 / 3, 1 / 3], out: [1 / 3, 1 / 3, 1 / 3, 0] };
const cubic = (p0, p1, p2, p3, s) => { const u = 1 - s; return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3; };
const pick = (v, j) => (Array.isArray(v) ? v[j] : v);
const pickHandle = (h, j) => (Array.isArray(h[0]) ? h[j] : h);

export function evalTrack(keys, f) {
  const last = keys.length - 1;
  if (f <= keys[0].f) return keys[0].v;
  if (f >= keys[last].f) return keys[last].v;
  let k = 0;
  while (keys[k + 1].f < f) k++;
  const a = keys[k], b = keys[k + 1];
  const interp = a.interp || 'bezier';
  if (interp === 'constant') return a.v;
  const one = (j) => {
    const v0 = pick(a.v, j), v1 = pick(b.v, j), dt = b.f - a.f, dv = v1 - v0;
    if (interp === 'linear') return v0 + (dv * (f - a.f)) / dt;
    const e = EASE[a.ease || 'inOut'] || EASE.inOut;
    const r = a.r ? pickHandle(a.r, j) : [e[0] * dt, e[1] * dv];
    const l = b.l ? pickHandle(b.l, j) : [-e[2] * dt, -e[3] * dv];
    // 解 x(s) = f 再取 y(s)；手柄时间落在区间内时 x(s) 单调，二分即可
    let lo = 0, hi = 1, s = 0.5;
    for (let i = 0; i < 40; i++) {
      s = (lo + hi) / 2;
      if (cubic(a.f, a.f + r[0], b.f + l[0], b.f, s) < f) lo = s; else hi = s;
    }
    return cubic(v0, v0 + r[1], v1 + l[1], v1, s);
  };
  return Array.isArray(a.v) ? a.v.map((_, j) => one(j)) : one(0);
}

// ---------- 色调映射：和 Blender 的 AgX 逐步一致 ----------
// three 自带的 AgX 是近似公式，中间调偏亮、饱和色偏淡（最多差 40/255）。这里照 Blender 的 OCIO 配置做：
// 线性 Rec.709 → 线性 E-Gamut → log2 → 查 Blender 的 3D 表（四面体插值，和 OCIO 一样）→ ^2.4 → sRGB。
let agxTable = null; // 解压后的 RGBA 表，所有镜头共用
function loadAgxTable() {
  agxTable ??= (async () => {
    const packed = Uint8Array.from(atob(AGX.data), (c) => c.charCodeAt(0));
    const rgb = new Uint8Array(await new Response(new Blob([packed]).stream().pipeThrough(new DecompressionStream('deflate'))).arrayBuffer());
    const n = AGX.size ** 3, rgba = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) {
      rgba[i * 4] = rgb[i * 3]; rgba[i * 4 + 1] = rgb[i * 3 + 1]; rgba[i * 4 + 2] = rgb[i * 3 + 2]; rgba[i * 4 + 3] = 255;
    }
    return rgba;
  })();
  return agxTable;
}

async function agxPass(exposure, sigma) {
  const n = AGX.size;
  const lut = new THREE.Data3DTexture(await loadAgxTable(), n, n, n);
  lut.minFilter = lut.magFilter = THREE.NearestFilter; // 插值在着色器里做（四面体），不用 GPU 的三线性
  lut.unpackAlignment = 1;
  lut.needsUpdate = true;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      tDiffuse: { value: null },
      lut: { value: lut },
      exposure: { value: 2 ** exposure },
      toEGamut: { value: new THREE.Matrix3().set(...AGX.toEGamut) },
      texel: { value: new THREE.Vector2() },
      weights: { value: [0, 1, 2, 4, 5, 8].map((d2) => (sigma > 0 ? Math.exp(-d2 / (2 * sigma * sigma)) : +(d2 === 0))) },
    },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `
      precision highp sampler3D;
      uniform sampler2D tDiffuse;
      uniform sampler3D lut;
      uniform float exposure;
      uniform mat3 toEGamut;
      uniform vec2 texel;
      uniform float weights[6]; // 按到中心距离的平方 0、1、2、4、5、8 取的高斯权重
      varying vec2 vUv;
      vec3 at(ivec3 p) { return texelFetch(lut, p, 0).rgb; }
      void main() {
        // 像素滤镜：Blender 在色调映射前把每个像素按 1.5 像素宽的滤镜混合，小而亮的东西会显得大一圈
        vec3 sum = vec3(0.0); float total = 0.0;
        for (int y = -2; y <= 2; y++) for (int x = -2; x <= 2; x++) {
          int d2 = x * x + y * y;
          float w = weights[d2 == 0 ? 0 : d2 == 1 ? 1 : d2 == 2 ? 2 : d2 == 4 ? 3 : d2 == 5 ? 4 : 5];
          sum += w * texture2D(tDiffuse, vUv + vec2(x, y) * texel).rgb;
          total += w;
        }
        vec3 e = toEGamut * (sum / total * exposure);
        vec3 x = clamp((log2(max(e, vec3(${2 ** AGX.lo}))) - ${AGX.lo.toFixed(8)}) / ${(AGX.hi - AGX.lo).toFixed(8)}, 0.0, 1.0) * ${(n - 1).toFixed(1)};
        vec3 i = min(floor(x), vec3(${(n - 2).toFixed(1)}));
        vec3 f = x - i;
        ivec3 p = ivec3(i);
        vec3 c0 = at(p), c1 = at(p + ivec3(1));
        vec3 v;
        if (f.r >= f.g) {
          if (f.g >= f.b) v = (1.0 - f.r) * c0 + (f.r - f.g) * at(p + ivec3(1, 0, 0)) + (f.g - f.b) * at(p + ivec3(1, 1, 0)) + f.b * c1;
          else if (f.r >= f.b) v = (1.0 - f.r) * c0 + (f.r - f.b) * at(p + ivec3(1, 0, 0)) + (f.b - f.g) * at(p + ivec3(1, 0, 1)) + f.g * c1;
          else v = (1.0 - f.b) * c0 + (f.b - f.r) * at(p + ivec3(0, 0, 1)) + (f.r - f.g) * at(p + ivec3(1, 0, 1)) + f.g * c1;
        } else {
          if (f.b > f.g) v = (1.0 - f.b) * c0 + (f.b - f.g) * at(p + ivec3(0, 0, 1)) + (f.g - f.r) * at(p + ivec3(0, 1, 1)) + f.r * c1;
          else if (f.b > f.r) v = (1.0 - f.g) * c0 + (f.g - f.b) * at(p + ivec3(0, 1, 0)) + (f.b - f.r) * at(p + ivec3(0, 1, 1)) + f.r * c1;
          else v = (1.0 - f.g) * c0 + (f.g - f.r) * at(p + ivec3(0, 1, 0)) + (f.r - f.b) * at(p + ivec3(1, 1, 0)) + f.b * c1;
        }
        vec3 l = pow(clamp(v, 0.0, 1.0), vec3(2.4)); // 表里是 2.4 次方编码，还原成显示线性
        gl_FragColor = vec4(mix(l * 12.92, 1.055 * pow(l, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, l)), 1.0); // sRGB
      }`,
  });
  const pass = new ShaderPass(material);
  const dispose = pass.dispose.bind(pass);
  pass.dispose = () => { dispose(); lut.dispose(); };
  return pass;
}

// ---------- 字体 ----------
/** 返回 loadFontUrl(url)：下载并用 opentype.js 的 parse 解析字体，同一地址只读一次。 */
export function createFontCache(parse) {
  const cache = new Map();
  return (url) => {
    if (!cache.has(url)) {
      cache.set(url, fetch(url).then((r) => {
        if (!r.ok) throw new Error(`AB to T：字体加载失败 ${url}（HTTP ${r.status}）`);
        return r.arrayBuffer();
      }).then(parse));
    }
    return cache.get(url);
  };
}

/** 把 opentype 字体里这段文字用到的字转成 three 的 Font（只转用到的字，中文字体也很快）。
 *  换算和 three 的 TTFLoader 相同（坐标 × 100000 / (unitsPerEm × 72)，resolution 1000），字形和以前一致。 */
function typeface(ot, text) {
  const scale = 100000 / ((ot.unitsPerEm || 2048) * 72);
  const round = Math.round;
  const xy = (x, y) => (x === undefined ? '' : `${round(x * scale)} ${round(y * scale)} `);
  const glyphs = {};
  for (const ch of new Set([...text, 'H'])) {
    const g = ot.charToGlyph(ch);
    const m = g.getMetrics();
    let o = '';
    for (const c of g.path.commands) o += `${c.type === 'C' ? 'b' : c.type.toLowerCase()} ${xy(c.x, c.y)}${xy(c.x1, c.y1)}${xy(c.x2, c.y2)}`;
    glyphs[ch] = { ha: round(g.advanceWidth * scale), x_min: round(m.xMin * scale), x_max: round(m.xMax * scale), o };
  }
  const head = ot.tables.head;
  return new Font({
    glyphs, resolution: 1000,
    ascender: round(ot.ascender * scale), descender: round(ot.descender * scale),
    underlinePosition: ot.tables.post?.underlinePosition, underlineThickness: ot.tables.post?.underlineThickness,
    boundingBox: { xMin: head.xMin, xMax: head.xMax, yMin: head.yMin, yMax: head.yMax },
  });
}

function capHeight(font) { // size=1 时大写 H 的高度；TTFLoader 会把字形放大约 1.39 倍，不能直接当字号用
  const g = new THREE.ShapeGeometry(font.generateShapes('H', 1));
  g.computeBoundingBox();
  const h = g.boundingBox.max.y - g.boundingBox.min.y;
  g.dispose();
  return h;
}
/** width / height 只写一个时另一个按图片比例；都不写时高 1 米。和 blender/abt/core.py 的 image_size 一致。 */
function imageSize(o, aspect) {
  if (o.width && o.height) return [o.width, o.height];
  if (o.width) return [o.width, o.width / aspect];
  const h = o.height ?? 1;
  return [h * aspect, h];
}

async function loadTexture(url) {
  let texture;
  try {
    texture = await new THREE.TextureLoader().loadAsync(url);
  } catch {
    throw new Error(`AB to T：图片加载失败 ${url}`);
  }
  texture.colorSpace = THREE.SRGBColorSpace; // 和 Blender 图片的 sRGB 色彩空间一致
  return texture;
}

const DEG = Math.PI / 180;
const defaults = (schema, params) => Object.fromEntries(Object.entries(schema.params).map(([k, p]) => [k, params?.[k] ?? p.default]));
const rgb = (c, s = 1) => new THREE.Color().setRGB(c[0] * s, c[1] * s, c[2] * s); // 规范里的颜色是线性值

// ---------- 场景搭建 ----------
async function build(doc, loaders) {
  const scene = new THREE.Scene();
  const w = doc.world || {};
  const bg = rgb(w.color || [0, 0, 0], w.strength ?? 1);
  scene.background = bg;
  scene.add(new THREE.AmbientLight(bg, Math.PI)); // Blender 背景亮度 L 照亮漫反射 ≈ three 环境光 π·L

  // 材质：普通 PBR，或代码材质组件（参数和动画轨道跟物体组件一样处理）
  const mats = {}, nodes = {};
  for (const [id, m] of Object.entries(doc.materials || {})) {
    if (m.component) {
      const { schema, module } = await loaders.loadComponent(m.component);
      const comp = module.createMaterial();
      mats[id] = comp.material;
      nodes[id] = { def: m, comp, params: defaults(schema, m.params) };
    } else {
      mats[id] = new THREE.MeshStandardMaterial({
        color: rgb(m.color || [0.8, 0.8, 0.8]), roughness: m.roughness ?? 0.5, metalness: m.metalness ?? 0,
        emissive: rgb(m.emissive || [0, 0, 0]), emissiveIntensity: m.emissiveIntensity ?? 0,
      });
    }
  }

  let camera = null;
  for (const o of doc.objects) {
    const node = { def: o, params: null, comp: null, lens: o.lens };
    switch (o.type) {
      case 'empty': node.object = new THREE.Object3D(); break;
      case 'camera':
        node.object = camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
        camera.filmGauge = o.sensor ?? 36; // 横向传感器宽度，对应 Blender 的 sensor_fit = HORIZONTAL
        break;
      case 'sun': node.object = new THREE.DirectionalLight(rgb(o.color || [1, 1, 1]), o.intensity ?? 1); break;
      case 'text': {
        const font = typeface(await loaders.loadFont(o.font), o.text);
        const size = (o.size ?? 1) / capHeight(font); // 规范里 size = 大写 H 的高度（米）
        const g = new TextGeometry(o.text, { font, size, depth: o.depth ?? 0, curveSegments: 8 });
        g.computeBoundingBox();
        g.translate(-(g.boundingBox.min.x + g.boundingBox.max.x) / 2, 0, -(o.depth ?? 0) / 2); // 原点：基线中点
        node.object = new THREE.Mesh(g, mats[o.material]);
        break;
      }
      case 'component': {
        const { schema, module } = await loaders.loadComponent(o.component);
        node.comp = module.create();
        node.object = node.comp.object;
        node.params = defaults(schema, o.params);
        break;
      }
      case 'image': { // 不受灯光影响，颜色 × 亮度，alpha × 不透明度；双面可见（Blender 的平面默认也是）
        const map = await loadTexture(loaders.imageUrl(o.src));
        const img = map.image;
        const [w, h] = imageSize(o, (img.naturalWidth || img.width) / (img.naturalHeight || img.height));
        node.material = new THREE.MeshBasicMaterial({ map, transparent: true, side: THREE.DoubleSide });
        node.object = new THREE.Mesh(new THREE.PlaneGeometry(w, h), node.material);
        node.object.userData.abtNoShadow = true; // Blender 里图片也不投影
        break;
      }
      default: console.warn('AB to T：three.js 暂不支持的类型', o.type); continue;
    }
    applyStatic(node);
    scene.add(node.object);
    nodes[o.id] = node;
  }
  for (const node of Object.values(nodes)) {
    const target = nodes[node.def.target]?.object;
    if (target && node.def.type === 'sun') node.object.target = target;
    node.target = target;
  }
  if (!camera) throw new Error('AB to T：场景里没有 camera');
  return { scene, camera, nodes };
}

/** 对象的静态值（每帧先恢复，再叠加动画轨道）。 */
function applyStatic(node) {
  const o = node.def;
  node.object.position.fromArray(o.position || [0, 0, 0]);
  setPath(node, 'rotation', o.rotation || [0, 0, 0]);
  setPath(node, 'scale', o.scale ?? 1);
  node.lens = o.lens;
  node.opacity = o.opacity ?? 1;
  node.intensity = o.intensity ?? 1;
  if (node.params) Object.assign(node.params, o.params || {});
}

function setPath(node, path, v) {
  const [base, sub] = path.split('.');
  const o = node.object;
  switch (base) {
    case 'position': sub ? (o.position[sub] = v) : o.position.fromArray(v); break;
    case 'rotation': sub ? (o.rotation[sub] = v * DEG) : o.rotation.set(v[0] * DEG, v[1] * DEG, v[2] * DEG); break; // 度，XYZ 顺序
    case 'scale': sub ? (o.scale[sub] = v) : typeof v === 'number' ? o.scale.setScalar(v) : o.scale.fromArray(v); break;
    case 'lens': node.lens = v; break;
    case 'intensity': node.def.type === 'sun' ? (o.intensity = v) : (node.intensity = v); break;
    case 'opacity': node.opacity = v; break;
    case 'params': if (node.params) node.params[sub] = v; break;
  }
}

/**
 * 创建一个镜头。返回 { canvas, doc, frames, fps, duration, setSize, renderFrame, render, dispose }：
 * renderFrame(帧号) 按场景 JSON 的帧号画；render(秒) 从镜头第一帧起算（FRAME 用这个）。
 */
// pixelFilter：色调映射前的高斯滤镜 σ（像素），0.4 是对照 Blender 默认 1.5 像素滤镜的渲染拟合出来的；draft 质量不用
export async function createAbtScene(doc, { width = 1920, height = 1080, quality = 'high', pixelRatio = 1, preserveDrawingBuffer = false, pixelFilter = 0.4 } = {}, loaders) {
  // 画面先画进半精度缓冲（后期要用），抗锯齿得开在这个缓冲上：渲染器自己的 antialias 只管直接画到屏幕
  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer });
  renderer.shadowMap.enabled = true; // 太阳光投影，和 Blender（EEVEE）一样
  renderer.shadowMap.type = THREE.PCFShadowMap;
  let world, toneMap;
  try {
    world = await build(doc, loaders);
    toneMap = await agxPass(doc.color?.exposure ?? 0, quality === 'draft' ? 0 : pixelFilter);
  } catch (e) {
    renderer.dispose();
    renderer.forceContextLoss();
    throw e;
  }
  const { scene, camera, nodes } = world;
  const buffer = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: quality === 'draft' ? 0 : 4 });
  const composer = new EffectComposer(renderer, buffer);
  composer.addPass(new RenderPass(scene, camera));
  const b = doc.post?.bloom;
  if (b) composer.addPass(new UnrealBloomPass(new THREE.Vector2(1, 1), b.strength ?? 1, b.radius ?? 0.5, b.threshold ?? 1));
  composer.addPass(toneMap); // AgX + sRGB 输出

  const camNode = Object.values(nodes).find((n) => n.object === camera);
  const suns = Object.values(nodes).filter((n) => n.def.type === 'sun').map((n) => n.object);
  for (const sun of suns) {
    sun.castShadow = true;
    sun.shadow.mapSize.setScalar(quality === 'draft' ? 1024 : 4096);
    sun.shadow.bias = -0.0002;
    sun.shadow.normalBias = 0.01;
  }
  const bounds = new THREE.Box3(), part = new THREE.Box3(), view = new THREE.Matrix4();
  const eye = new THREE.Vector3(), corner = new THREE.Vector3(), lo = new THREE.Vector3(), hi = new THREE.Vector3();

  /** 每帧把太阳光的投影范围贴合到场景里的物体上（组件的实例每帧都在变）。 */
  function fitShadows() {
    if (!suns.length) return;
    scene.updateMatrixWorld();
    bounds.makeEmpty();
    scene.traverse((o) => {
      if (!o.isMesh) return;
      o.receiveShadow = true;
      o.castShadow = !o.userData.abtNoShadow;
      if (!o.castShadow) return;
      if (o.isInstancedMesh) o.computeBoundingBox();
      else if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      bounds.union(part.copy(o.isInstancedMesh ? o.boundingBox : o.geometry.boundingBox).applyMatrix4(o.matrixWorld));
    });
    if (bounds.isEmpty()) return;
    for (const sun of suns) {
      const cam = sun.shadow.camera;
      // 和 three 渲染投影时一样：相机放在光源位置，看向目标
      view.lookAt(sun.getWorldPosition(eye), sun.target.getWorldPosition(target), cam.up).invert();
      lo.setScalar(Infinity);
      hi.setScalar(-Infinity);
      for (let i = 0; i < 8; i++) {
        corner.set(i & 1 ? bounds.max.x : bounds.min.x, i & 2 ? bounds.max.y : bounds.min.y, i & 4 ? bounds.max.z : bounds.min.z);
        corner.sub(eye).applyMatrix4(view);
        lo.min(corner); hi.max(corner);
      }
      const pad = 0.02 * Math.max(hi.x - lo.x, hi.y - lo.y);
      Object.assign(cam, { left: lo.x - pad, right: hi.x + pad, bottom: lo.y - pad, top: hi.y + pad, near: -hi.z - pad, far: -lo.z + pad });
      cam.updateProjectionMatrix();
    }
  }
  const [start, end] = doc.meta.frames;
  const fps = doc.meta.fps;
  const target = new THREE.Vector3();

  function setSize(w, h, ratio = pixelRatio) {
    renderer.setPixelRatio(ratio);
    renderer.setSize(w, h);
    composer.setPixelRatio(ratio);
    composer.setSize(w, h);
    toneMap.material.uniforms.texel.value.set(1 / (w * ratio), 1 / (h * ratio));
    camera.aspect = w / h;
  }

  function renderFrame(frame) {
    for (const node of Object.values(nodes)) {
      if (node.object) applyStatic(node);
      else if (node.params) Object.assign(node.params, node.def.params || {}); // 代码材质
    }
    for (const tr of doc.animation || []) {
      const node = nodes[tr.target];
      if (node) setPath(node, tr.path, evalTrack(tr.keys, frame));
    }
    const t = frame / fps;
    for (const node of Object.values(nodes)) {
      node.comp?.update(t, node.params);
      if (node.def.type === 'image') {
        node.material.opacity = node.opacity;
        node.material.color.setScalar(node.intensity);
      }
    }
    camera.setFocalLength(camNode.lens ?? 50);
    fitShadows();
    if (camNode.target) camera.lookAt(camNode.target.getWorldPosition(target));
    composer.render(0); // 0：不让后期按自己的时钟推进
  }

  setSize(width, height);
  return {
    canvas: renderer.domElement,
    doc,
    frames: [start, end],
    fps,
    duration: (end - start + 1) / fps,
    setSize,
    renderFrame,
    render(time) { renderFrame(start + time * fps); },
    dispose() {
      scene.traverse((o) => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); });
      for (const n of Object.values(nodes)) n.comp?.dispose();
      toneMap.dispose();
      composer.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
