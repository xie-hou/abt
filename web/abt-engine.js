// AB to T 播放核心：把场景 JSON（abt-scene/0.1）搭成 three.js 场景，按帧号或时间渲染。
// 浏览器预览（runtime.js）和 FRAME 的场景图层（frame/frame.js）共用这一份。
// 画面只由“帧号 + 文档”决定，不读系统时钟。组件和字体从哪里来由调用方传入：
//   loaders = { loadComponent(spec) → Promise<{ schema, module }>, loadFont(path) → Promise<opentype 字体> }
// 字体用 opentype.js 解析（调用方传入，见 createFontCache）；不用 three 的 TTFLoader：新版 three 的 TTFLoader
// 在导入时会从 CDN 加载 opentype.js，FRAME 里不允许联网，导出时也可能断网。
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Font } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';

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
      default: console.warn('AB to T：three.js 暂不支持的类型', o.type); continue;
    }
    node.object.position.fromArray(o.position || [0, 0, 0]);
    if (o.scale !== undefined) setPath(node, 'scale', o.scale);
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

function setPath(node, path, v) {
  const [base, sub] = path.split('.');
  const o = node.object;
  switch (base) {
    case 'position': sub ? (o.position[sub] = v) : o.position.fromArray(v); break;
    case 'scale': sub ? (o.scale[sub] = v) : typeof v === 'number' ? o.scale.setScalar(v) : o.scale.fromArray(v); break;
    case 'lens': node.lens = v; break;
    case 'intensity': o.intensity = v; break;
    case 'params': if (node.params) node.params[sub] = v; break;
  }
}

/**
 * 创建一个镜头。返回 { canvas, doc, frames, fps, duration, setSize, renderFrame, render, dispose }：
 * renderFrame(帧号) 按场景 JSON 的帧号画；render(秒) 从镜头第一帧起算（FRAME 用这个）。
 */
export async function createAbtScene(doc, { width = 1920, height = 1080, quality = 'high', pixelRatio = 1, preserveDrawingBuffer = false } = {}, loaders) {
  const renderer = new THREE.WebGLRenderer({ antialias: quality !== 'draft', preserveDrawingBuffer });
  renderer.toneMapping = THREE.AgXToneMapping;
  renderer.toneMappingExposure = 2 ** (doc.color?.exposure ?? 0);
  let world;
  try {
    world = await build(doc, loaders);
  } catch (e) {
    renderer.dispose();
    renderer.forceContextLoss();
    throw e;
  }
  const { scene, camera, nodes } = world;
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const b = doc.post?.bloom;
  if (b) composer.addPass(new UnrealBloomPass(new THREE.Vector2(1, 1), b.strength ?? 1, b.radius ?? 0.5, b.threshold ?? 1));
  composer.addPass(new OutputPass()); // 色调映射（AgX）+ sRGB 输出

  const camNode = Object.values(nodes).find((n) => n.object === camera);
  const [start, end] = doc.meta.frames;
  const fps = doc.meta.fps;
  const target = new THREE.Vector3();

  function setSize(w, h, ratio = pixelRatio) {
    renderer.setPixelRatio(ratio);
    renderer.setSize(w, h);
    composer.setPixelRatio(ratio);
    composer.setSize(w, h);
    camera.aspect = w / h;
  }

  function renderFrame(frame) {
    for (const node of Object.values(nodes)) {
      const o = node.def;
      node.object?.position.fromArray(o.position || [0, 0, 0]);
      node.lens = o.lens;
      if (node.params) Object.assign(node.params, o.params || {});
    }
    for (const tr of doc.animation || []) {
      const node = nodes[tr.target];
      if (node) setPath(node, tr.path, evalTrack(tr.keys, frame));
    }
    const t = frame / fps;
    for (const node of Object.values(nodes)) node.comp?.update(t, node.params);
    camera.setFocalLength(camNode.lens ?? 50);
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
      scene.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
      for (const n of Object.values(nodes)) n.comp?.dispose();
      composer.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
