"""通过正式战役 T2I payload 对比五槽卡和五行版。"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import time

from jinja2 import Environment
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT.parent))
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.campaign.models import ClearLineupStatus
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer

spec=importlib.util.spec_from_file_location('campaign_fixture_builder',ROOT/'scripts'/'preview' / 'preview_t2i_ui.py')
fixture_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
fixture_record=fixture_module.fixture_record

CARDS_CSS='''
.cards { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); grid-template-rows:none; gap:22px; min-height:auto; }
.campaign .lineup,.campaign .portrait-card { min-height:auto; }
.campaign .portrait-card { display:block; grid-template-columns:none; align-items:normal; gap:normal; padding:0; }
.campaign .portrait { grid-column:auto; width:auto; height:220px; margin:0; background:#222731; }
.campaign .slot { left:14px; top:12px; font-size:18px; z-index:auto; }
.campaign .portrait-info { grid-column:auto; grid-row:auto; min-width:0; display:block; grid-template-columns:none; grid-template-rows:none; align-items:normal; gap:normal; padding:16px 18px 20px; }
.campaign .level { grid-column:auto; grid-row:auto; font-size:18px; color:var(--muted); }
.campaign .character-name { grid-column:auto; grid-row:auto; height:66px; margin-top:7px; font-size:22px; line-height:1.5; }
.campaign .character-name.long-name { font-size:18px; line-height:22px; }
.campaign .combat { grid-column:auto; grid-row:auto; align-self:auto; margin:6px 0 0; text-align:left; font-size:32px; line-height:38px; }
'''

class NoPortraits:
    def get_lineup_portrait(self, member):
        return None

class TimeoutPortraits:
    def get_lineup_portrait(self, member):
        raise TimeoutError("fixture asset timeout")

def campaign_cases():
    cases={name:fixture_record(name) for name in ('normal','hard','long-text','missing-asset','partial-data','empty','error','max-density')}
    mobile_name=fixture_record('normal')
    mobile_name.members[0].name_cn='指挥官测试用二十五字左右的战役成员名称完整显示验证'
    cases['mobile-long-name']=mobile_name
    rate=fixture_record('normal')
    rate.status=ClearLineupStatus.RATE_LIMITED
    rate.status_message='战役查询请求过频，请稍后再试'
    rate.members=[]
    cases['rate-limited']=rate
    unknown=fixture_record('normal')
    unknown.mode='UNVERIFIED'
    cases['unknown-mode']=unknown
    unknown_identity=fixture_record('normal')
    unknown_identity.members[0].name_cn=''
    unknown_identity.members[0].name_en=''
    unknown_identity.members[0].resource_id=None
    unknown_identity.members[0].name_code=None
    cases['unknown-identity']=unknown_identity
    zero=fixture_record('normal')
    for member in zero.members:
        member.combat=0
    cases['zero-combat']=zero
    cases['asset-timeout']=fixture_record('normal')
    return cases

def build_payload(renderer,record,*,no_portraits=False,asset_timeout=False):
    original=renderer.payload_builder.assets
    if no_portraits:
        renderer.payload_builder.assets=NoPortraits()
    elif asset_timeout:
        renderer.payload_builder.assets=TimeoutPortraits()
    try:
        return renderer.payload_builder.build(record)
    finally:
        renderer.payload_builder.assets=original

async def measure_page(browser,template,payload,variant,case_name,out_dir):
    html=Environment(autoescape=False).from_string(template).render(**payload)
    page=await browser.new_page(viewport={'width':1600,'height':900},device_scale_factor=1)
    await page.set_content(html)
    await page.evaluate('document.fonts.ready')
    await page.evaluate("Promise.all([...document.images].map(img => img.decode().catch(() => null)))")
    if variant=='cards':
        await page.add_style_tag(content=CARDS_CSS)
    metrics=await page.evaluate('''() => {
      const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
      const inside=(c,p)=>c.left>=p.left-1&&c.top>=p.top-1&&c.right<=p.right+1&&c.bottom<=p.bottom+1;
      const selector='h1,h2,p,span,th,td,.metric-label,.metric-value,.character-name,.level,.combat,.empty-state h2,.empty-state p';
      const overflow=[...document.querySelectorAll(selector)].filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);const clipsY=['hidden','clip','auto','scroll'].includes(s.overflowY);return r.width>0&&r.height>0&&(e.scrollWidth>e.clientWidth+2||(clipsY&&e.scrollHeight>e.clientHeight+2));}).map(e=>({tag:e.tagName,cls:e.className,text:(e.innerText||'').slice(0,72),scroll:[e.scrollWidth,e.scrollHeight],client:[e.clientWidth,e.clientHeight]}));
      const boundary=[];
      for(const e of document.querySelectorAll(selector)){
        const owner=e.closest('.portrait-card')||e.closest('.empty-state')||e.closest('.lineup')||e.closest('.summary')||e.closest('.title-line')||e.closest('.footer-meta')||e.closest('header')||e.closest('main');
        if(owner){const a=rect(e),b=rect(owner);if(!inside(a,b))boundary.push({text:(e.innerText||'').slice(0,72),owner:owner.className||owner.tagName,child:a,parent:b});}
      }
      const overlaps=[];
      for(const parent of document.querySelectorAll('main,header,.title-line,.lineup,.cards,.portrait-card,.portrait-info,.summary,.empty-state,.footer-meta')){
        const children=[...parent.children].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
        for(let i=0;i<children.length;i++)for(let j=i+1;j<children.length;j++){
          const a=rect(children[i]),b=rect(children[j]),w=Math.min(a.right,b.right)-Math.max(a.left,b.left),h=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
          if(w>1&&h>1)overlaps.push({parent:parent.className||parent.tagName,a:children[i].className||children[i].tagName,b:children[j].className||children[j].tagName,area:[w,h]});
        }
      }
      const main=document.querySelector('.campaign');
      const mobileScale=432/innerWidth;
      const mobileReadability={
        namePx:Math.min(...[...document.querySelectorAll('.character-name')].map(e=>parseFloat(getComputedStyle(e).fontSize)*mobileScale)),
        levelPx:Math.min(...[...document.querySelectorAll('.level')].map(e=>parseFloat(getComputedStyle(e).fontSize)*mobileScale)),
        longNamePx:document.querySelectorAll('.character-name.long-name').length ? Math.min(...[...document.querySelectorAll('.character-name.long-name')].map(e=>parseFloat(getComputedStyle(e).fontSize)*mobileScale)) : null,
        portrait:[...document.querySelectorAll('.portrait-card .portrait')].map(e=>{const r=rect(e);return [r.width*mobileScale,r.height*mobileScale];})
      };
      return {width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,viewport:innerWidth,viewportHeight:innerHeight,mainHeight:main.clientHeight,mainScrollHeight:main.scrollHeight,overflow,boundary,overlaps,mobileReadability,
        cards:document.querySelectorAll('.portrait-card').length,
        slots:[...document.querySelectorAll('.portrait-card .slot')].map(e=>e.innerText.trim()),
        images:[...document.images].map(e=>({complete:e.complete,width:e.naturalWidth,height:e.naturalHeight,alt:e.alt}))};
    }''')
    png=out_dir/f'{case_name}-1600.png'
    await page.screenshot(path=str(png),full_page=True)
    await page.close()
    with Image.open(png) as image:
        if image.width!=1600 or image.height!=900:
            metrics['boundary'].append({'document_size':[image.width,image.height],'expected':[1600,900]})
        image.resize((432,round(image.height*432/image.width)),Image.Resampling.LANCZOS).save(out_dir/f'{case_name}-432.png')
    metrics['case']=case_name
    metrics['variant']=variant
    metrics['png']=png.name
    metrics['mobile']=f'{case_name}-432.png'
    return metrics

def audit_assets(assets,record,payload):
    rows=[]
    payload_by_slot={int(m['slot']):m for m in payload['members']}
    for member in sorted(record.members,key=lambda item:item.slot):
        resolved=assets.resolve_lineup_portrait(resource_id=member.resource_id)
        path=resolved.local_path
        start=time.perf_counter(); first=assets.get_lineup_portrait(member); first_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter(); repeated=assets.get_lineup_portrait(member); repeat_ms=(time.perf_counter()-start)*1000
        if first is None or repeated is None:
            width=height=0; mode='missing'; alpha=False; image_sha=None
        else:
            width,height=first.size; mode=first.mode; alpha='A' in first.getbands()
            image_sha=hashlib.sha256(first.tobytes()).hexdigest()
        uri=payload_by_slot[member.slot]['portrait_data_uri']
        uri_bytes=len(uri.encode('utf-8')) if uri else 0
        rows.append({'slot':member.slot,'tid':member.tid,'resource_id':member.resource_id,'name_code':member.name_code,
            'name':member.name_cn,'resolved_resource_id':resolved.resource_id,'fallback':resolved.is_fallback,
            'path':str(path),'exists':path.is_file(),'file_bytes':path.stat().st_size if path.is_file() else None,
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            'width':width,'height':height,'mode':mode,'has_alpha':alpha,'pixel_sha256':image_sha,
            'first_local_read_ms':round(first_ms,3),'immediate_repeat_ms':round(repeat_ms,3),'data_uri_bytes':uri_bytes})
    root=ROOT/'assets'/'blablalink'/'character'
    mi_roots=[root/'mi',ROOT/'assets'/'character'/'mi']
    si_dir=root/'si'
    return {'network_enabled':False,'cold_semantics':'first local read in this process, OS filesystem cache not controlled',
        'si_directory':str(si_dir),'si_file_count':sum(1 for p in si_dir.iterdir() if p.is_file()) if si_dir.is_dir() else 0,
        'mi_candidate_paths':[{'path':str(p),'exists':p.is_dir()} for p in mi_roots],
        'spine_render_requested':False,'max_portrait_lookups':len(rows),'total_data_uri_bytes':sum(r['data_uri_bytes'] for r in rows),'members':rows}

def validation_checks(renderer,record):
    invalid=deepcopy(record)
    invalid.members[0].slot=6
    try:
        renderer.payload_builder.build(invalid)
    except ValueError as exc:
        invalid_slot={'rejected':True,'message':str(exc)}
    else:
        invalid_slot={'rejected':False,'message':None}
    return {'invalid_slot':invalid_slot,'expected_slots':[1,2,3,4,5]}

def contact_sheet(folder,variant,names):
    font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf',17)
    gap=14; label_h=30; columns=3; cell_w=432; cell_h=max(Image.open(folder/f'{n}-432.png').height for n in names)
    rows=(len(names)+columns-1)//columns
    canvas=Image.new('RGB',(columns*cell_w+(columns-1)*gap,rows*(cell_h+label_h)+(rows-1)*gap),'#e5e9ee')
    draw=ImageDraw.Draw(canvas)
    for index,name in enumerate(names):
        image=Image.open(folder/f'{name}-432.png').convert('RGB')
        x=(index%columns)*(cell_w+gap); y=(index//columns)*(cell_h+label_h+gap)
        draw.text((x+4,y+5),name,font=font,fill='#243648')
        canvas.paste(image,(x,y+label_h))
    path=folder/f'contact-{variant}-432.png'; canvas.save(path,optimize=True); return path

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    assets=AssetManager(args.output/'cache',ROOT/'assets',remote=False)
    renderer=T2IRenderer(None,assets)
    template=renderer.loader.load('campaign')
    cases=campaign_cases(); evidence=[]; index=[]
    try:
        cases['invalid-slot']={'status':'INVALID_INPUT'}
        sample=fixture_record('normal'); sample_payload=renderer.payload_builder.build(sample)
        assets_audit=audit_assets(assets,sample,sample_payload)
        validation=validation_checks(renderer,sample)
        for variant in ('cards','rows'):
            folder=args.output/variant; folder.mkdir(parents=True,exist_ok=True)
            async with async_playwright() as playwright:
                browser=await playwright.chromium.launch()
                for name,item in cases.items():
                    if name=='invalid-slot':
                        index.append({'case':name,'result':'expected validation rejection','message':validation['invalid_slot']['message']})
                        continue
                    record=item
                    payload=build_payload(renderer,record,no_portraits=(name=='missing-asset'),asset_timeout=(name=='asset-timeout'))
                    metrics=await measure_page(browser,template,payload,variant,name,folder)
                    evidence.append(metrics)
                    index.append({'case':name,'variant':variant,'status_code':payload['status_code'],'status_label':payload['status_label'],
                        'mode':payload['mode'],'mode_label':payload['mode_label'],'members':len(payload['members']),'formal_path':variant=='rows','comparison_only':variant=='cards',
                        'canvas':[metrics['width'],metrics['height']],'png':f'{variant}/{name}-1600.png','mobile':f'{variant}/{name}-432.png'})
                    print(variant,name,flush=True)
                await browser.close()
            (folder/'layout-checks.json').write_text(json.dumps([x for x in evidence if x['variant']==variant],ensure_ascii=False,indent=2),encoding='utf-8')
            contact_sheet(folder,variant,['normal','hard','long-text','mobile-long-name','partial-data','missing-asset','unknown-identity','asset-timeout','empty','rate-limited','error','zero-combat'])
        (args.output/'asset-audit.json').write_text(json.dumps(assets_audit,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'validation-checks.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'CASE_INDEX.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
        failures=[x for x in evidence if x['variant']=='rows' and (x['width']>x['viewport'] or x['height']>x['viewportHeight']+2 or x['mainScrollHeight']>x['mainHeight']+2 or x['overflow'] or x['boundary'] or x['overlaps'] or x['slots'] not in ([],['1','2','3','4','5']) or any(not img['complete'] or img['width']==0 for img in x['images']))]
        unreadable=[x for x in evidence if x['variant']=='rows' and (
            x['mobileReadability']['namePx']<10 or x['mobileReadability']['levelPx']<10 or
            (x['case']=='mobile-long-name' and (x['mobileReadability']['longNamePx'] is None or x['mobileReadability']['longNamePx']<10)) or
            any(width<40 or height<24 for width,height in x['mobileReadability']['portrait'])
        )]
        if failures or unreadable:
            raise AssertionError(json.dumps({'layout':failures,'mobile_readability':unreadable},ensure_ascii=False))
        if not validation['invalid_slot']['rejected']: raise AssertionError('invalid slot accepted')
        print('layout cases',len(evidence),'errors',len(failures),'asset bytes',assets_audit['total_data_uri_bytes'],flush=True)
    finally:
        assets.close()

if __name__=='__main__':
    asyncio.run(main())
