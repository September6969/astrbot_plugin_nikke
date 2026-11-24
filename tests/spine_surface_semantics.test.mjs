import assert from 'node:assert/strict';
import test from 'node:test';
// G9-scripts-docs-a5（PR-6C）：根兼容壳已删除，直接导入分类实现。
import {classifySurfaceSemantics} from '../scripts/spine/spine_surface_semantics.mjs';

test('face attachment keeps face semantics inside a head slot', () => {
  assert.deepEqual(
    classifySurfaceSemantics('head', 'face'),
    {kind: 'face_attachment', source: 'attachment'},
  );
});

test('explicit head attachment is a head surface', () => {
  assert.deepEqual(
    classifySurfaceSemantics('head', 'head_main'),
    {kind: 'head_attachment', source: 'attachment'},
  );
});

test('hair and headwear are rejected', () => {
  for (const name of ['hair', 'head_hair', 'headwear', 'helmet', 'hat']) {
    assert.deepEqual(
      classifySurfaceSemantics('head', name),
      {kind: null, source: 'rejected'},
    );
  }
});

test('face slot is a documented fallback', () => {
  assert.deepEqual(
    classifySurfaceSemantics('face', 'skin'),
    {kind: 'face_attachment', source: 'slot_context'},
  );
});
