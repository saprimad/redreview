// Real Chrome through CDP; temporary data and explicit test-only provider fixture.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import WebSocket from 'ws';
const temp=await mkdtemp(join(tmpdir(),'redreview-browser-'));
const server=spawn('python3',['-m','tests.browser_server',join(temp,'test.sqlite3')],{stdio:['ignore','pipe','inherit']});
let chrome,ws;
try{
 const port=await new Promise((resolve,reject)=>{server.stdout.once('data',b=>resolve(Number(b.toString().trim())));server.once('exit',()=>reject(new Error('Browser test backend failed to start.')));});
 chrome=spawn(process.env.REDREVIEW_CHROME||'google-chrome',['--headless=new','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=0','--user-data-dir='+join(temp,'chrome'),'about:blank'],{stdio:['ignore','ignore','ignore']});
 const poll=async(fn,label)=>{for(let i=0;i<120;i++){try{const value=await fn();if(value)return value;}catch{}await new Promise(r=>setTimeout(r,100));}throw new Error('Timeout: '+label);};
 const debug=await poll(async()=>Number((await readFile(join(temp,'chrome','DevToolsActivePort'),'utf8')).split('\n')[0]),'Chrome debugger');
 const pages=await (await fetch(`http://127.0.0.1:${debug}/json/list`)).json();
 ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
 let seq=0;const pending=new Map();
 ws.on('message',raw=>{const m=JSON.parse(raw);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}});
 const cdp=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const evaluate=async(expression)=>{const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async(expression)=>poll(()=>evaluate(expression),expression);
 const click=async(id)=>evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
 const screenshots=join(process.cwd(),'browser-artifacts');await mkdir(screenshots,{recursive:true});
 for(const [name,width,height,mobile] of [['desktop',1440,1000,false],['iphone',390,844,true]]){
  await cdp('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/`});
  await wait("document.getElementById('open-project')");
  await evaluate("const s=document.getElementById('open-project');s.value=s.options[1].value;s.dispatchEvent(new Event('change'))");
  await wait("document.getElementById('tab-discover')");await click('tab-discover');
  await evaluate("document.getElementById('discovery-query').value='gardening';document.getElementById('discovery-form').requestSubmit()");
  await wait("document.querySelector('[data-discovery]')");
  const size=await evaluate("({scroll:document.documentElement.scrollWidth,viewport:innerWidth,button:document.getElementById('run-discovery').getBoundingClientRect().height})");
  assert.ok(size.scroll<=size.viewport+1,`${name}: search overflow ${JSON.stringify(size)}`);
  assert.ok(size.button>=44,`${name}: search button below touch target`);
  await writeFile(join(screenshots,name+'-search.png'),Buffer.from((await cdp('Page.captureScreenshot',{captureBeyondViewport:true})).data,'base64'));
  await click('select-discovery');await click('import-discovery');
  await wait("document.querySelector('dialog').open && document.getElementById('modal-body').textContent.includes('Article import report')");
  await click('close-modal');await click('tab-screen');
  await wait("document.querySelector('[data-record]')");
  await click('decision-include');await wait("document.querySelector('.history')?.textContent.includes('include')");
  assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'),name+': screening overflow');
  await writeFile(join(screenshots,name+'-screening.png'),Buffer.from((await cdp('Page.captureScreenshot',{captureBeyondViewport:true})).data,'base64'));
  console.log(`PASS real Chrome ${name}: search, import, screening, no horizontal overflow and 44px search touch target.`);
 }
}finally{
 ws?.close();chrome?.kill();server.kill();
 await new Promise(r=>setTimeout(r,500));await rm(temp,{recursive:true,force:true});
}
