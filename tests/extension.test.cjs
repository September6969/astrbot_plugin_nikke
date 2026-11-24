const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync('extension/popup.js', 'utf8');
async function run(origin, cached, linkOrigin = origin) {
  const handlers = {};
  const elements = {bindUrl:{value:linkOrigin + '/bind/' + 'a'.repeat(40)},status:{dataset:{}}};
  let submitted;
  const cookieQueries = [];
  const cookies = ['game_token','game_uid','game_openid'].map(name => ({name,value:name === 'game_openid' ? 'current' : 'test'}));
  const context = {URL,document:{getElementById(id){return elements[id] ||= {addEventListener(event,fn){handlers[id]=fn;}};}},
    chrome:{runtime:{getManifest(){return {host_permissions:['https://*.blablalink.com/*',origin+'/*']};}},
      storage:{local:{get:async key => key === 'xCommonParams' ? {xCommonParams:'{"openid":"stale-local"}'} : {},set:async()=>{},remove:async()=>{}},
        session:{get:async key => key === 'xCommonParams' ? {xCommonParams:cached} : {},set:async()=>{},remove:async()=>{}}},
      cookies:{getAll:async query => { cookieQueries.push(query); return cookies; }}},
    navigator:{userAgent:'test'},fetch:async(url, options)=>{submitted=JSON.parse(options.body);return {ok:true,json:async()=>({ok:true,qq_id:'PRIVATE_ACCOUNT_ID'})};}};
  vm.runInNewContext(source,context);
  await handlers.submit();
  return {submitted,cookieQueries,status:elements.status.textContent,state:elements.status.dataset.state,disabled:elements.submit.disabled};
}
test('自建域名可以提交，其他域名在读取Cookie前拒绝',async()=>{
 assert.ok((await run('https://bot.example','')).submitted);
 assert.equal((await run('https://bot.example','','https://other.example')).submitted,undefined);
});
test('其他账号和损坏缓存回退到当前账号',async()=>{
 for(const cached of ['{"openid":"old"}','broken','']) {
  assert.equal(JSON.parse((await run('https://bot.example',cached)).submitted.x_common_params).openid,'current');
 }
});
test('当前账号上下文完整保留',async()=>{
 const cached=JSON.stringify({openid:'current',extra:'preserved'});
 assert.equal((await run('https://bot.example',cached)).submitted.x_common_params,cached);
});

test('成功不回显账号标识，结果状态清楚且按钮恢复',async()=>{
 const result=await run('https://bot.example','');
 assert.equal(result.state,'success');
 assert.equal(result.disabled,false);
 assert.ok(!result.status.includes('PRIVATE_ACCOUNT_ID'));
 const failed=await run('https://bot.example','','https://other.example');
 assert.equal(failed.state,'error');
 assert.equal(failed.disabled,false);
});

test('临时登录材料只从 session 存储读取，Cookie 查询口径一致',async()=>{
 const cached=JSON.stringify({openid:'current',extra:'session'});
 const result=await run('https://bot.example',cached);
 assert.equal(result.submitted.x_common_params,cached);
 assert.ok(result.cookieQueries.length>=2);
 for(const query of result.cookieQueries) assert.deepEqual({...query},{url:'https://www.blablalink.com/'});
});

test('扩展权限收窄为 activeTab，后台只把临时材料写入 session',()=>{
 const manifest=JSON.parse(fs.readFileSync('extension/manifest.json','utf8'));
 assert.ok(manifest.permissions.includes('activeTab'));
 assert.ok(!manifest.permissions.includes('tabs'));
 const background=fs.readFileSync('extension/background.js','utf8');
 assert.ok(!/storage\.local\.set\(\{\s*(xCommonParams|renewalLoginPayload)/.test(background));
 assert.match(background,/temporaryStore\.set\(\{ xCommonParams/);
 assert.match(background,/temporaryStore\.set\(\{ renewalLoginPayload/);
});
