import assert from 'node:assert/strict';
import test from 'node:test';
import {makeAttachmentCandidate} from '../scripts/spine_attachment_candidates.mjs';

test('attachment candidate exposes stable discovery fields and center point', () => {
  const candidate = makeAttachmentCandidate({
    slotName: 'torso_surface',
    attachmentName: 'torso_surface',
    boneName: 'body',
    parentName: 'pelvis',
    attachmentType: 'RegionAttachment',
    box: [10, 20, 30, 60],
    mappedBox: [100, 200, 300, 600],
    surfaceKind: null,
  });

  assert.deepEqual(candidate, {
    slot: 'torso_surface',
    attachment: 'torso_surface',
    bone: 'body',
    parent: 'pelvis',
    type: 'RegionAttachment',
    box: [100, 200, 300, 600],
    point: [200, 400],
    surface: null,
    semantic_source: null,
    source_box_world: [10, 20, 30, 60],
  });
});

test('surface classification is carried separately from attachment identity', () => {
  const candidate = makeAttachmentCandidate({
    slotName: 'head',
    attachmentName: 'head_main',
    boneName: 'face',
    parentName: 'neck',
    attachmentType: 'MeshAttachment',
    box: [0, 0, 1, 1],
    mappedBox: [0, 0, 10, 10],
    surfaceKind: 'head_attachment',
    semanticSource: 'attachment',
  });

  assert.equal(candidate.surface, 'head_attachment');
  assert.equal(candidate.semantic_source, 'attachment');
  assert.equal(candidate.attachment, 'head_main');
});
