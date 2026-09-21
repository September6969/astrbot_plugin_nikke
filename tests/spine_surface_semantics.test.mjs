import assert from 'node:assert/strict';
import test from 'node:test';
import {classifySurfaceSemantics} from '../scripts/spine_surface_semantics.mjs';

test('face attachment remains face even inside a head slot', () => {
  assert.deepEqual(
    classifySurfaceSemantics('head', 'face'),
    {kind: 'face_attachment', source: 'attachment'},
  );
});
test('explicit head attachments are head surfaces', () => {
  for (const name of ['head', 'head_main', 'head_base']) {
    assert.deepEqual(
      classifySurfaceSemantics('head', name),
      {kind: 'head_attachment', source: 'attachment'},
    );
  }
});

test('hair and headwear never become head surfaces', () => {
  for (const name of ['hair', 'head_hair', 'headwear', 'helmet', 'hat']) {
    assert.deepEqual(
      classifySurfaceSemantics('head', name),
      {kind: null, source: 'rejected'},
    );
  }
});

test('face slot can be a documented face-only fallback', () => {
  assert.deepEqual(
    classifySurfaceSemantics('face', 'skin'),
    {kind: 'face_attachment', source: 'slot_context'},
  );
});

test('unrelated attachments are rejected', () => {
  assert.deepEqual(
    classifySurfaceSemantics('body', 'torso'),
    {kind: null, source: 'rejected'},
  );
});
