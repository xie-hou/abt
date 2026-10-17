// AB to T 查看器：读取场景 JSON（abt-scene/0.1），按文档时间 t = 帧 / fps 求值并渲染。
// 画面只由“帧号 + 文档”决定，不读系统时钟；场景文件一变就自动重建（Blender 写回后这里跟着刷新）。
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { TTFLoader } from 'three/addons/loaders/TTFLoader.js';
import { Font } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';

const ROOT = new URL('../', location.href); // 项目根目录：字体、组件路径都相对它
const QUERY = new URLSearchParams(location.search);
const SCENE_URL = new URL(QUERY.get('scene') || 'scenes/shot02.json', ROOT);
const POLL_MS = 500;

const $ = (id) => document.getElementById(id);
const stage = $('stage'), scrub = $('scrub'), frameLabel = $('frame'), status = $('status'), playBtn = $('play');

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.toneMapping = THREE.AgXToneMapping;
stage.appendChild(renderer.domElement);

let doc = null, docText = '', world = null;
let frame = +QUERY.get('frame') || 1, playing = false, lastTime = 0, dirty = true;

// ---------- 关键帧求值：与 Blender F 曲线一致（贝塞尔手柄 / 线性 / 常量，两端保持） ----------
// 缓动简写 → 区间比例（出手柄 dt, 出手柄 dv, 入手柄 dt, 入手柄 dv），与 tools/abt.py 的 EASE 一致
const EASE = { inOut: [1 / 3, 0, 1 / 3, 0], in: [1 / 3, 0, 1 / 3, 1 / 3], out: [1 / 3, 1 / 3, 1 / 3, 0] };
const cubic = (p0, p1, p2, p3, s) => { const u = 1 - s; return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3; };
const pick = (v, j) => (Array.isArray(v) ? v[j] : v);
const pickHandle = (h, j) => (Array.isArray(h[0]) ? h[j] : h);

function evalTrack(keys, f) {
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

// ---------- 场景搭建 ----------
const fonts = {};
const loadFont = (path) => (fonts[path] ??= new TTFLoader().loadAsync(new URL(path, ROOT).href).then((json) => new Font(json)));
function capHeight(font) { // size=1 时大写 H 的高度；TTFLoader 会把字形放大约 1.39 倍，不能直接当字号用
  const g = new THREE.ShapeGeometry(font.generateShapes('H', 1));
  g.computeBoundingBox();
  const h = g.boundingBox.max.y - g.boundingBox.min.y;
  g.dispose();
  return h;
}
const components = {};
async function loadComponent(spec) {
  const name = spec.split('@')[0];
  return (components[name] ??= (async () => {
    const dir = new URL(`components/${name}/`, ROOT);
    const schema = await (await fetch(new URL('component.json', dir), { cache: 'no-store' })).json();
    return { schema, module: await import(new URL('three.js', dir).href) };
  })());
}
const defaults = (schema, params) => Object.fromEntries(Object.entries(schema.params).map(([k, p]) => [k, params?.[k] ?? p.default]));
const rgb = (c, s = 1) => new THREE.Color().setRGB(c[0] * s, c[1] * s, c[2] * s); // 规范里的颜色是线性值

async function build(doc) {
  const scene = new THREE.Scene();
  const w = doc.world || {};
  const bg = rgb(w.color || [0, 0, 0], w.strength ?? 1);
  scene.background = bg;
  scene.add(new THREE.AmbientLight(bg, Math.PI)); // Blender 背景亮度 L 照亮漫反射 ≈ three 环境光 π·L

  // 材质：普通 PBR，或代码材质组件（参数和动画轨道跟物体组件一样处理）
  const mats = {}, nodes = {};
  for (const [id, m] of Object.entries(doc.materials || {})) {
    if (m.component) {
      const { schema, module } = await loadComponent(m.component);
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
        const font = await loadFont(o.font);
        const size = (o.size ?? 1) / capHeight(font); // 规范里 size = 大写 H 的高度（米）
        const g = new TextGeometry(o.text, { font, size, depth: o.depth ?? 0, curveSegments: 8 });
        g.computeBoundingBox();
        g.translate(-(g.boundingBox.min.x + g.boundingBox.max.x) / 2, 0, -(o.depth ?? 0) / 2); // 原点：基线中点
        node.object = new THREE.Mesh(g, mats[o.material]);
        break;
      }
      case 'component': {
        const { schema, module } = await loadComponent(o.component);
        node.comp = module.create();
        node.object = node.comp.object;
        node.params = defaults(schema, o.params);
        break;
      }
      default: console.warn('three.js 暂不支持的类型', o.type); continue;
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

// ---------- 渲染 ----------
let composer = null, bloomPass = null;
function setupComposer() {
  composer?.dispose();
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(world.scene, world.camera));
  const b = doc.post?.bloom;
  bloomPass = b ? new UnrealBloomPass(new THREE.Vector2(1, 1), b.strength ?? 1, b.radius ?? 0.5, b.threshold ?? 1) : null;
  if (bloomPass) composer.addPass(bloomPass);
  composer.addPass(new OutputPass()); // 色调映射（AgX）+ sRGB 输出
  resize();
}

function resize() {
  const [rw, rh] = doc?.meta.resolution || [1920, 1080];
  const aspect = rw / rh;
  let w = stage.clientWidth, h = w / aspect;
  if (h > stage.clientHeight) { h = stage.clientHeight; w = h * aspect; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(Math.floor(w), Math.floor(h));
  composer?.setSize(Math.floor(w), Math.floor(h));
  if (world) world.camera.aspect = aspect;
  dirty = true;
}
addEventListener('resize', resize);

function renderFrame() {
  const { nodes, camera } = world;
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
  const t = frame / doc.meta.fps;
  for (const node of Object.values(nodes)) node.comp?.update(t, node.params);
  const camNode = Object.values(nodes).find((n) => n.object === camera);
  camera.setFocalLength(camNode.lens ?? 50);
  if (camNode.target) camera.lookAt(camNode.target.getWorldPosition(new THREE.Vector3()));
  composer.render();
  frameLabel.textContent = `${Math.round(frame)} / ${doc.meta.frames[1]}`;
  scrub.value = Math.round(frame);
}

function tick(now) {
  requestAnimationFrame(tick);
  if (!world) return;
  if (playing) {
    const [start, end] = doc.meta.frames;
    frame += ((now - lastTime) / 1000) * doc.meta.fps;
    if (frame > end) frame = start + ((frame - start) % (end - start + 1));
    dirty = true;
  }
  lastTime = now;
  if (dirty) { dirty = false; renderFrame(); }
}

// ---------- 加载与热更新 ----------
function disposeWorld() {
  if (!world) return;
  world.scene.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
  for (const n of Object.values(world.nodes)) n.comp?.dispose();
}

async function load() {
  const text = await (await fetch(SCENE_URL, { cache: 'no-store' })).text();
  if (text === docText) return;
  const next = JSON.parse(text);
  const built = await build(next);
  disposeWorld();
  doc = next; docText = text; world = built;
  const [start, end] = doc.meta.frames;
  scrub.min = start; scrub.max = end;
  frame = Math.min(Math.max(frame, start), end);
  renderer.toneMappingExposure = 2 ** (doc.color?.exposure ?? 0);
  setupComposer();
  status.textContent = `已同步 ${new Date().toLocaleTimeString()}`;
}

async function poll() {
  try { await load(); } catch (e) { status.textContent = `读取失败：${e.message}`; console.error(e); }
  setTimeout(poll, POLL_MS);
}

playBtn.onclick = () => { playing = !playing; playBtn.textContent = playing ? '❚❚' : '▶'; };
scrub.oninput = () => { frame = +scrub.value; dirty = true; };
addEventListener('keydown', (e) => { if (e.code === 'Space') { e.preventDefault(); playBtn.click(); } });

// 调试用：在控制台里 __abt.setFrame(80)
window.__abt = { setFrame: (f) => { frame = f; dirty = true; }, get doc() { return doc; } };

poll();
requestAnimationFrame(tick);
