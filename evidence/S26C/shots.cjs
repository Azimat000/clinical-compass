// Real Chromium on an isolated synthetic copy. Agent self-check, not a user trial.
// Usage: node shots.cjs <label> <fixture.sqlite3>
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=process.cwd(),label=process.argv[2],src=process.argv[3];
const out=path.join(root,'evidence/S26C/shots');fs.mkdirSync(out,{recursive:true});
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26c-')),db=path.join(tmp,'s.sqlite3');
fs.copyFileSync(src,db);const meta=JSON.parse(fs.readFileSync(src+'.json'));
const python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18260';
const report={kind:'agent self-check, synthetic, no clinical validation or user trial',label,pages:[],errors:[]};
let server,browser;
async function start(){server=spawn(python,['evidence/S26C/serve.py',db,'18260'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
async function login(p,id){await p.goto(origin+'/login');await p.getByLabel('Логин').fill(id);await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);}
const doctor=[['home','/'],['card','/demo/D01'],['card-signal','/demo/D01#clinical-data'],['dynamics','/demo/D01#dynamics'],['first-visit','/patients/D01/first-visits'],['follow-up','/patients/D01/follow-up'],['communication','/patients/D01/communication'],['decisions','/patients/D01/decisions'],['imports','/patients/D01/imports'],['inbox','/notifications'],['critical','/critical']];
const patient=[['today','/demo/D01'],['self-report','/demo/D01#new-record'],['dynamics','/demo/D01#dynamics'],['assessments','/demo/D01#assessments'],['assessment-form','/assessments/'+meta.assessment_request],['communication','/patients/D01/communication'],['decisions','/patients/D01/decisions'],['my-data','/demo/D01#clinical-data']];
(async()=>{try{
await start();browser=await chromium.launch({headless:true});report.browser={name:'Chromium',version:browser.version(),platform:process.platform};
for(const [role,uid,pages] of [['patient','pat-a',patient]]){
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}});const p=await ctx.newPage();
 p.on('pageerror',e=>report.errors.push(role+': '+String(e)));p.on('console',m=>{if(m.type()==='error')report.errors.push(role+' console: '+m.text());});
 await login(p,uid);
 for(const [name,url] of pages){
  for(const w of ([1440,320])){
   await p.setViewportSize({width:w,height:1000});
   const resp=await p.goto(origin+url);await p.waitForTimeout(150);
   const st=resp?resp.status():0;
   const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
   const font=await p.evaluate(()=>getComputedStyle(document.body).fontFamily.split(',')[0]);
   await p.screenshot({path:path.join(out,`${label}-${role}-${name}-${w}.png`),fullPage:true});
   report.pages.push({role,name,url,width:w,status:st,horizontal_overflow:overflow,body_font:font});
  }}
 await ctx.close();}
report.status='DONE';
}catch(e){report.status='FAIL';report.error=String(e.stack||e);process.exitCode=1;}finally{await browser?.close();if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(out,label+'.json'),JSON.stringify(report,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify({status:report.status,pages:report.pages.length,errors:report.errors,overflow:report.pages.filter(x=>x.horizontal_overflow).map(x=>x.role+'/'+x.name+'@'+x.width),bad:report.pages.filter(x=>x.status!==200).map(x=>x.role+'/'+x.name+':'+x.status)},null,1));}})();
