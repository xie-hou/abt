// AB to T 浏览器预览：用播放核心（abt-engine.js）播放场景 JSON，带时间线和播放按钮。
// 场景文件一变就自动重建（Blender 写回后这里跟着刷新）。组件和字体按网址从项目目录加载。
import { createAbtScene, createFontCache } from './abt-engine.js';
import { parse as parseFont } from '../vendor/opentype.min.mjs';

const ROOT = new URL('../', location.href); // 项目根目录：字体、组件路径都相对它
const QUERY = new URLSearchParams(location.search);
const SCENE_URL = new URL(QUERY.get('scene') || 'scenes/shot02.json', ROOT);
const POLL_MS = 500;

const $ = (id) => document.getElementById(id);
const stage = $('stage'), scrub = $('scrub'), frameLabel = $('frame'), status = $('status'), playBtn = $('play');

const components = new Map();
const loadFontUrl = createFontCache(parseFont);
const loaders = {
  loadComponent(spec) {
    const name = spec.split('@')[0];
    if (!components.has(name)) {
      const dir = new URL(`components/${name}/`, ROOT);
      components.set(name, (async () => ({
        schema: await (await fetch(new URL('component.json', dir), { cache: 'no-store' })).json(),
        module: await import(new URL('three.js', dir).href),
      }))());
    }
    return components.get(name);
  },
  loadFont: (path) => loadFontUrl(new URL(path, ROOT).href),
};

let shot = null, docText = '';
let frame = +QUERY.get('frame') || 1, playing = false, lastTime = 0, dirty = true;

function fit() {
  const [rw, rh] = shot.doc.meta.resolution;
  const aspect = rw / rh;
  let w = stage.clientWidth, h = w / aspect;
  if (h > stage.clientHeight) { h = stage.clientHeight; w = h * aspect; }
  shot.setSize(Math.floor(w), Math.floor(h), Math.min(devicePixelRatio, 2));
  dirty = true;
}
addEventListener('resize', () => shot && fit());

function tick(now) {
  requestAnimationFrame(tick);
  if (!shot) return;
  const [start, end] = shot.frames;
  if (playing) {
    frame += ((now - lastTime) / 1000) * shot.fps;
    if (frame > end) frame = start + ((frame - start) % (end - start + 1));
    dirty = true;
  }
  lastTime = now;
  if (dirty) {
    dirty = false;
    shot.renderFrame(frame);
    frameLabel.textContent = `${Math.round(frame)} / ${end}`;
    scrub.value = Math.round(frame);
  }
}

async function load() {
  const text = await (await fetch(SCENE_URL, { cache: 'no-store' })).text();
  if (text === docText) return;
  const next = await createAbtScene(JSON.parse(text), { quality: 'high' }, loaders);
  if (shot) { shot.canvas.remove(); shot.dispose(); }
  shot = next;
  docText = text;
  stage.appendChild(shot.canvas);
  fit();
  const [start, end] = shot.frames;
  scrub.min = start;
  scrub.max = end;
  frame = Math.min(Math.max(frame, start), end);
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
window.__abt = { setFrame: (f) => { frame = f; dirty = true; }, get doc() { return shot?.doc; } };

poll();
requestAnimationFrame(tick);
