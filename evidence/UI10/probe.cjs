const fs=require('fs'); const {chromium}=require('playwright');
const origin=process.env.UI10_ORIGIN||'http://127.0.0.1:8010'; const phase=process.env.UI10_PHASE||'before';
const out='evidence/UI10/'+phase; fs.mkdirSync(out,{recursive:true});
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261026-accounts.json')).accounts;
const axe=fs.readFileSync('var/UI10-tools/node_modules/axe-core/axe.min.js','utf8');
(async()=>{const browser=await chromium.launch({headless:true});const results=[];
for(const role of ['doctor','patient']){
 const auth=await browser.newContext();const p=await auth.newPage();const a=accounts.find(a=>a.login===(role==='doctor'?'e.orlova':'anna.larina'));
 await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>u.pathname!='/login');
 const state=await auth.storageState();await auth.close();
 const routes=role==='doctor'?['/','/demo/P201','/patients/P201/decisions','/patients/P201/communication','/patients/P201/imports']:
 ['/demo/P201','/demo/P201/diary','/demo/P201/report','/demo/P201/forms','/patients/P201/decisions','/patients/P201/communication'];
 for(const width of [360,1440])for(let i=0;i<routes.length;i++){
  const ctx=await browser.newContext({storageState:state,viewport:{width,height:900},hasTouch:width===360,isMobile:width===360,reducedMotion:'reduce'});const page=await ctx.newPage();const log={console:[],pageErrors:[],failed:[],badStatus:[]};
  page.on('pageerror',e=>log.pageErrors.push(e.message));page.on('console',m=>{if(['error','warning'].includes(m.type()))log.console.push(m.text())});page.on('requestfailed',r=>log.failed.push(r.url()));page.on('response',r=>{if(r.status()>=400)log.badStatus.push([r.url(),r.status()])});
  const response=await page.goto(origin+routes[i]);await page.evaluate(()=>document.fonts.ready);if(new URL(page.url()).pathname!==routes[i])throw Error('Unexpected redirect '+page.url());
  const key=role+'-'+i+'-'+width;await page.screenshot({path:out+'/'+key+'.png'});
  const metrics=await page.evaluate(()=>{
   const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};
   const visible=e=>e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})&&e.getBoundingClientRect().height>0;
   const targets=[...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary')].filter(visible).map(e=>({tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||e.name||'').slice(0,80),cls:e.className,box:rect(e),font:getComputedStyle(e).fontSize,inProse:e.matches('a')&&getComputedStyle(e).display==='inline'&&!!e.closest('p')}));
   return {overflow:document.documentElement.scrollWidth>innerWidth+1,bodyFont:getComputedStyle(document.body).fontSize,targets,headings:[...document.querySelectorAll('h1,h2,h3')].filter(visible).map(e=>({text:e.innerText,box:rect(e),font:getComputedStyle(e).fontSize})),wordCount:document.body.innerText.split(/\s+/).length};
  });
  // axe is test instrumentation only; CSP remains unchanged in the application.
  await page.evaluate(axe);const ar=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}}));
  fs.writeFileSync(out+'/'+key+'-axe.json',JSON.stringify(ar,null,2));
  await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));await page.screenshot({path:out+'/'+key+'-bottom.png'});
  const item={role,route:routes[i],width,status:response.status(),...metrics,axe:ar.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),log};results.push(item);fs.writeFileSync(out+'/'+key+'.json',JSON.stringify(item,null,2));await ctx.close();
 }
}
await browser.close();fs.writeFileSync(out+'/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results.map(x=>({role:x.role,route:x.route,width:x.width,overflow:x.overflow,axe:x.axe,small:x.targets.filter(t=>(t.box.w<43||t.box.h<43)&&!t.inProse).map(t=>({text:t.text,box:t.box})).slice(0,10)}))));
})().catch(e=>{console.error(e);process.exit(1)});
