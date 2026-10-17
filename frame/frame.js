// AB to T 在 FRAME 里的场景图层：读入作品里的场景 JSON，用播放核心按 FRAME 给的时间渲染。
// 作品的 scenes/abt-<镜头>.ts 只写：
//   export function createScene(options) { return createAbtFrameScene(shot, options); }
// FRAME 的 time 从镜头第一帧算起（time 0 = JSON 里 meta.frames 的起始帧）。不联网：字体用素材库里的 opentype.js 解析。
import { assetUrl } from "@frame/engine/types";
import { createAbtScene, createFontCache } from "./engine.js";
import { parse } from "./opentype.mjs";
import { COMPONENTS, FONTS } from "./registry.js";

const loadFontUrl = createFontCache(parse);

export async function createAbtFrameScene(shot, { width, height, quality }) {
  const abt = await createAbtScene(shot, { width, height, quality, preserveDrawingBuffer: true }, {
    async loadComponent(spec) {
      const component = COMPONENTS[spec.split("@")[0]];
      if (!component) throw new Error(`AB to T 素材库里没有组件 ${spec}：先用 abt-scene skill 更新素材库`);
      return component;
    },
    loadFont(path) {
      const url = FONTS[path.split("/").pop()];
      if (!url) throw new Error(`AB to T 素材库里没有字体 ${path}：先把字体放进素材库的 fonts/`);
      return loadFontUrl(assetUrl(url));
    },
  });
  return {
    canvas: abt.canvas,
    render: (time) => abt.render(time),
    dispose: () => abt.dispose(),
  };
}
