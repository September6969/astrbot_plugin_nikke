"""在 Node 沙箱中验证扩展默认不读取请求体，额外选择后仅保留白名单。"""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_extension_request_observer_is_optin_and_exactly_scoped():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 不可用")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const listeners = [], state = {};
const chrome = { storage: { local: {
  get: async () => state, set: async value => Object.assign(state, value)
}}, webRequest: {
  onBeforeSendHeaders: { addListener() {} },
  onBeforeRequest: { addListener: (...args) => listeners.push(args) }
}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), { chrome, TextDecoder });
(async () => {
  const [observe, filter] = listeners[0];
  assert.deepEqual(Array.from(filter.urls), ['https://api.blablalink.com/api/user/Login']);
  let reads = 0;
  const event = { method: 'POST', get requestBody() { reads++; throw Error('must not read'); }};
  await observe(event);
  assert.equal(reads, 0);
  assert.equal(state.renewalLoginPayload, undefined);
  state.keepRenewalMaterial = true;
  const payload = {game_token:'synthetic-token',game_openid:'synthetic-id',game_expire_time:1234567890,
    password:'never-store',unknown:'never-store',game_channelid:131};
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  await observe({method:'POST',requestBody:{raw:[{bytes:bytes.buffer}]}});
  assert.equal(state.renewalLoginPayload.password, undefined);
  assert.equal(state.renewalLoginPayload.unknown, undefined);
  assert.equal(state.renewalLoginPayload.game_expire_time, 1234567890);
  assert.equal(state.renewalLoginPayload.game_token, 'synthetic-token');
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
'''
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "-e", script, str(root / "extension/background.js")], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
