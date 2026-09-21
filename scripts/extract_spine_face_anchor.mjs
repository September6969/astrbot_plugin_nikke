// Offline-only Spine geometry extractor. Production rendering does not load this script.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {classifySurfaceSemantics} from './spine_surface_semantics.mjs';

const [runtime, skelPath, atlasPath, renderId, animation, output] = process.argv.slice(2);
if (!output) throw new Error('args: runtime/index.js skeleton atlas render_id animation output.json');

let spine;
try {
  const mod = await import(pathToFileURL(runtime).href);
  spine = mod.TextureAtlas ? mod : (mod.default?.TextureAtlas ? mod.default : null);
} catch (e) {}
if (!spine || !spine.TextureAtlas) {
  const code = fs.readFileSync(runtime, 'utf8');
  const context = {globalThis, console};
  vm.runInNewContext(code, context);
  spine = context.spine;
}

const atlas = new spine.TextureAtlas(fs.readFileSync(atlasPath, 'utf8'));
for (const page of atlas.pages) {
  page.setTexture({
    getImage: () => ({width: page.width, height: page.height}),
    setFilters() {}, setWraps() {}, dispose() {},
  });
}

const raw = fs.readFileSync(skelPath);
const reader = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas));
const data = reader.readSkeletonData(new Uint8Array(raw));
const skeleton = new spine.Skeleton(data);
skeleton.scaleY = -1;
if (data.skins.length === 1) skeleton.setSkin(data.skins[0]);
skeleton.setToSetupPose();
if (!data.findAnimation(animation)) throw new Error('missing requested idle animation');
const state = new spine.AnimationState(new spine.AnimationStateData(data));
state.setAnimation(0, animation, false);
state.update(0);
state.apply(skeleton);
skeleton.updateWorldTransform();

const offset = new spine.Vector2();
const size = new spine.Vector2();
skeleton.getBounds(offset, size);

function worldVertices(slot, attachment) {
  let vertices = [];
  if (attachment instanceof spine.RegionAttachment) {
    vertices = new Array(8);
    attachment.computeWorldVertices(data.version.startsWith('4.0') ? slot.bone : slot, vertices, 0, 2);
  } else if (attachment instanceof spine.MeshAttachment) {
    vertices = new Array(attachment.worldVerticesLength);
    attachment.computeWorldVertices(slot, 0, vertices.length, vertices, 0, 2);
  } else {
    return null;
  }
  const xs = vertices.filter((_, i) => i % 2 === 0);
  const ys = vertices.filter((_, i) => i % 2 === 1);
  const box = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  if (!box.every(Number.isFinite) || box[2] <= box[0] || box[3] <= box[1]) return null;
  return box;
}

// Keep the current face-anchor selection contract unchanged.
const candidates = [];
for (const slot of skeleton.drawOrder) {
  const attachment = slot.getAttachment();
  if (!attachment || slot.color.a === 0 || attachment.color?.a === 0 || !slot.bone.active) continue;
  const name = `${slot.data.name}/${attachment.name}`;
  const lower = name.toLowerCase();
  const priority = /eye/.test(lower) && !/brow|blow|lash|highlight|spark/.test(lower)
    ? 0 : /face/.test(lower) ? 1 : /head/.test(lower) ? 2 : -1;
  if (priority < 0) continue;
  const box = worldVertices(slot, attachment);
  if (!box) continue;
  candidates.push({name, priority, box});
}

let chosen = [];
let point;
let extent;
if (candidates.length) {
  const priority = Math.min(...candidates.map(x => x.priority));
  chosen = candidates.filter(x => x.priority === priority);
  const box = [
    Math.min(...chosen.map(x => x.box[0])),
    Math.min(...chosen.map(x => x.box[1])),
    Math.max(...chosen.map(x => x.box[2])),
    Math.max(...chosen.map(x => x.box[3])),
  ];
  point = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  extent = [box[2] - box[0], box[3] - box[1]];
} else {
  const bone = skeleton.bones.find(x => /(^|[_\-])head($|[_\-\d])/.test(x.data.name.toLowerCase()));
  if (!bone) throw new Error('missing eye/face/head attachment and head bone');
  point = [bone.worldX, bone.worldY];
  extent = null;
  chosen = [{name: bone.data.name, priority: 3}];
}

// Existing 1024×1024 / 8% padding transform.
const scale = Math.min(1024 * .84 / size.x, 1024 * .84 / size.y);
const position = [
  (1024 - size.x * scale) / 2 - offset.x * scale,
  (1024 - size.y * scale) / 2 - offset.y * scale,
];
const to1024 = ([x, y]) => [x * scale + position[0], y * scale + position[1]];
const boxTo1024 = box => [
  box[0] * scale + position[0],
  box[1] * scale + position[1],
  box[2] * scale + position[0],
  box[3] * scale + position[1],
];

// Export raw bone positions only; Python applies strict, tested anatomy rules.
const anatomyBones1024 = skeleton.bones
  .filter(b => b.active && Number.isFinite(b.worldX) && Number.isFinite(b.worldY))
  .map(b => ({
    name: b.data.name,
    parent: b.parent?.data?.name ?? '',
    x: to1024([b.worldX, b.worldY])[0],
    y: to1024([b.worldX, b.worldY])[1],
  }));

// Export conservative head/face surface candidates separately from the legacy
// anchor selection. Strict token matching prevents hair/headwear from being
// treated as the semantic head surface.
const headSurfaceCandidates1024 = [];
for (const slot of skeleton.drawOrder) {
  const attachment = slot.getAttachment();
  if (!attachment || slot.color.a === 0 || attachment.color?.a === 0 || !slot.bone.active) continue;
  const name = `${slot.data.name}/${attachment.name}`;
  const semantic = classifySurfaceSemantics(slot.data.name, attachment.name);
  if (!semantic.kind) continue;
  const box = worldVertices(slot, attachment);
  if (!box) continue;
  headSurfaceCandidates1024.push({
    name,
    kind: semantic.kind,
    semantic_source: semantic.source,
    box: boxTo1024(box),
  });
}

const result = {
  schema: 1,
  render_id: renderId,
  runtime: data.version,
  animation,
  time: 0,
  skeleton_sha256: crypto.createHash('sha256').update(raw).digest('hex'),
  atlas_sha256: crypto.createHash('sha256').update(fs.readFileSync(atlasPath)).digest('hex'),
  anchor_kind: ['eye_attachment', 'face_attachment', 'head_attachment', 'head_bone'][chosen[0].priority],
  attachments: chosen.map(x => x.name),
  point_1024: to1024(point),
  extent_1024: extent?.map(x => x * scale),
  candidates,
  bounds: [offset.x, offset.y, size.x, size.y],
  anatomy_bones_1024: anatomyBones1024,
  head_surface_candidates_1024: headSurfaceCandidates1024,
};

fs.writeFileSync(output, JSON.stringify(result, null, 2), 'utf8');
console.log(JSON.stringify({
  renderId,
  kind: result.anchor_kind,
  point: result.point_1024,
  names: result.attachments,
  anatomyBoneCount: anatomyBones1024.length,
  headSurfaceCandidateCount: headSurfaceCandidates1024.length,
}));
