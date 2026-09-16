// 离线使用匹配版本的官方 Spine Core；生产出卡不加载此脚本。
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import crypto from 'node:crypto';

const [runtime, skelPath, atlasPath, renderId, animation, output] = process.argv.slice(2);
if (!output) throw new Error('参数：runtime/index.js skeleton atlas render_id animation output.json');
const spine = await import(pathToFileURL(runtime).href);
const atlas = new spine.TextureAtlas(fs.readFileSync(atlasPath, 'utf8'));
// 几何计算只需要 atlas 页尺寸；不下载或解码纹理。
for (const page of atlas.pages) page.setTexture({getImage: () => ({width: page.width, height: page.height}),
  setFilters() {}, setWraps() {}, dispose() {}});
const raw = fs.readFileSync(skelPath);
const reader = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas));
const data = reader.readSkeletonData(new Uint8Array(raw));
const skeleton = new spine.Skeleton(data);
skeleton.scaleY = -1;
if (data.skins.length === 1) skeleton.setSkin(data.skins[0]);
skeleton.setToSetupPose();
if (!data.findAnimation(animation)) throw new Error('没有指定的 idle 动画');
const state = new spine.AnimationState(new spine.AnimationStateData(data));
state.setAnimation(0, animation, false);
state.update(0);
state.apply(skeleton);
skeleton.updateWorldTransform();
const offset = new spine.Vector2(), size = new spine.Vector2();
skeleton.getBounds(offset, size);
const candidates = [];
for (const slot of skeleton.drawOrder) {
  const attachment = slot.getAttachment();
  if (!attachment || slot.color.a === 0 || attachment.color?.a === 0 || !slot.bone.active) continue;
  const name = `${slot.data.name}/${attachment.name}`;
  const lower = name.toLowerCase();
  let priority = /eye/.test(lower) && !/brow|blow|lash|highlight|spark/.test(lower) ? 0 : /face/.test(lower) ? 1 : /head/.test(lower) ? 2 : -1;
  if (priority < 0) continue;
  let vertices = [];
  if (attachment instanceof spine.RegionAttachment) {
    vertices = new Array(8);
    attachment.computeWorldVertices(data.version.startsWith('4.0') ? slot.bone : slot, vertices, 0, 2);
  } else if (attachment instanceof spine.MeshAttachment) {
    vertices = new Array(attachment.worldVerticesLength);
    attachment.computeWorldVertices(slot, 0, vertices.length, vertices, 0, 2);
  } else continue;
  const xs = vertices.filter((_, i) => i % 2 === 0), ys = vertices.filter((_, i) => i % 2 === 1);
  const box = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  if (!box.every(Number.isFinite) || box[2] <= box[0] || box[3] <= box[1]) continue;
  candidates.push({name, priority, box});
}
let chosen = [], point, extent;
if (candidates.length) {
  const priority = Math.min(...candidates.map(x => x.priority));
  chosen = candidates.filter(x => x.priority === priority);
  const box = [Math.min(...chosen.map(x => x.box[0])), Math.min(...chosen.map(x => x.box[1])),
               Math.max(...chosen.map(x => x.box[2])), Math.max(...chosen.map(x => x.box[3]))];
  point = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  extent = [box[2] - box[0], box[3] - box[1]];
} else {
  const bone = skeleton.bones.find(x => /(^|[_\-])head($|[_\-\d])/.test(x.data.name.toLowerCase()));
  if (!bone) throw new Error('缺少 eye/face/head attachment 和 head bone');
  point = [bone.worldX, bone.worldY];
  extent = null;
  chosen = [{name: bone.data.name, priority: 3}];
}
// 与现有 SFML 离线预渲染的 1024×1024 / 8% padding 使用相同的世界坐标映射。
const scale = Math.min(1024 * .84 / size.x, 1024 * .84 / size.y);
const position = [(1024 - size.x * scale) / 2 - offset.x * scale,
                  (1024 - size.y * scale) / 2 - offset.y * scale];
const result = {schema: 1, render_id: renderId, runtime: data.version, animation, time: 0,
  skeleton_sha256: crypto.createHash('sha256').update(raw).digest('hex'),
  atlas_sha256: crypto.createHash('sha256').update(fs.readFileSync(atlasPath)).digest('hex'),
  anchor_kind: ['eye_attachment', 'face_attachment', 'head_attachment', 'head_bone'][chosen[0].priority],
  attachments: chosen.map(x => x.name), point_1024: point.map((x, i) => x * scale + position[i]),
  extent_1024: extent?.map(x => x * scale), candidates, bounds: [offset.x, offset.y, size.x, size.y]};
fs.writeFileSync(output, JSON.stringify(result, null, 2), 'utf8');
console.log(JSON.stringify({renderId, kind: result.anchor_kind, point: result.point_1024, names: result.attachments}));
