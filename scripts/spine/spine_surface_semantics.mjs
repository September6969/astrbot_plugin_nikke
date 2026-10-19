// 离线 Spine 表面语义分类；槽位语义与 attachment 语义必须分开判断。

const tokenized = value => String(value ?? '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '_')
  .replace(/^_+|_+$/g, '');

const FACE_NAMES = new Set(['face', 'face_main', 'face_base']);
const HEAD_NAMES = new Set(['head', 'head_main', 'head_base']);
const NON_SURFACE_RE = /(^|_)(hair|headwear|headset|helmet|hat)(_|$)/;

/** 返回 head/face 表面候选的语义来源。 */
export function classifySurfaceSemantics(slotName, attachmentName) {
  const slotToken = tokenized(slotName);
  const attachmentToken = tokenized(attachmentName);

  if (!attachmentToken || NON_SURFACE_RE.test(attachmentToken)) {
    return {kind: null, source: 'rejected'};
  }
  if (FACE_NAMES.has(attachmentToken)) {
    return {kind: 'face_attachment', source: 'attachment'};
  }
  if (HEAD_NAMES.has(attachmentToken)) {
    return {kind: 'head_attachment', source: 'attachment'};
  }
  if (slotToken === 'face' && !NON_SURFACE_RE.test(slotToken)) {
    return {kind: 'face_attachment', source: 'slot_context'};
  }
  return {kind: null, source: 'rejected'};
}
