// Spine attachment discovery sidecar 的确定性候选格式；不参与产品渲染。

export function makeAttachmentCandidate({
  slotName,
  attachmentName,
  boneName,
  parentName,
  attachmentType,
  box,
  mappedBox,
  surfaceKind = null,
  semanticSource = null,
}) {
  if (!Array.isArray(mappedBox) || mappedBox.length !== 4) {
    throw new Error('attachment candidate requires a mapped box');
  }
  const point = [
    (mappedBox[0] + mappedBox[2]) / 2,
    (mappedBox[1] + mappedBox[3]) / 2,
  ];
  return {
    slot: String(slotName ?? ''),
    attachment: String(attachmentName ?? ''),
    bone: String(boneName ?? ''),
    parent: String(parentName ?? ''),
    type: String(attachmentType ?? 'unknown'),
    box: mappedBox,
    point,
    surface: surfaceKind,
    semantic_source: semanticSource,
    source_box_world: box,
  };
}

