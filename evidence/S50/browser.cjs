const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S50_ORIGIN||'http://127.0.0.1:8050',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync(__dirname+'/browser-fixture.json'));
const checks=[],errors=[];let submissions=0;function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
async function noAction(p){check(await p.locator('[name=action_draft],section#v-action,a[href="#v-action"],#h-action').count()===0,'Action field/section/link remains');check(!(await p.locator('body').innerText()).includes('Проект действия'),'Action text remains');for(const state of ['draft','completed'])check(await p.locator('[name=state][value='+state+']').count()===1,'Save action missing');check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Editor overflow');}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 const editor=origin+'/patients/P101/first-visits'+(runtime?'':'/'+fixture.visit_id);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(editor+'#v-action');await noAction(p);
  if(!runtime&&name==='chromium'&&width===375){const posted=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/first-visits/'+fixture.visit_id));await p.getByRole('button',{name:'Сохранить черновик',exact:true}).click();check((await posted).status()===303,'Draft not saved');await p.waitForFunction(()=>document.querySelector('.card-state .num')?.textContent==='2');submissions++;await noAction(p);}
  if(name==='chromium'&&!runtime){await p.evaluate(()=>scrollTo(0,document.body.scrollHeight));await p.screenshot({path:__dirname+'/editor-'+width+'.png'});}
  if(!runtime){await p.goto(origin+'/demo/P101#visit-'+fixture.visit_id);const top=p.locator('#visit-'+fixture.visit_id);check((await top.textContent()).includes('Синтетическая прежняя заметка S50'),'Old note lost');check(await p.locator('#visit-version-'+fixture.visit_id+'-1').count()===1,'Original version lost');check(await p.locator('#visit-version-'+fixture.visit_id+'-2').count()===1,'Saved version lost');
   if(await top.getAttribute('open')===null)await top.locator(':scope > summary').click();await top.getByText('Предыдущие версии (1)',{exact:true}).click();await p.locator('#visit-version-'+fixture.visit_id+'-1 > summary').click();check((await p.locator('#visit-version-'+fixture.visit_id+'-1').innerText()).includes('Синтетическая прежняя заметка S50'),'Original note inaccessible');
   if(name==='chromium'){await p.locator('#visit-version-'+fixture.visit_id+'-1').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/history-'+width+'.png'});}
  }
  checks.push({browser:name,width,no_action_field_or_section:true,draft_and_completion:true,old_note_and_versions:!runtime,overflow:false});
 }
 if(!runtime){const {c:nc,p:plain}=await login(b,false);await plain.goto(editor);await noAction(plain);await plain.goto(origin+'/demo/P101#visit-'+fixture.visit_id);check((await plain.locator('#visit-'+fixture.visit_id).textContent()).includes('Синтетическая прежняя заметка S50'),'NoJS note lost');await nc.close();checks.push({browser:name,no_js:true,form_without_action_and_history:true});}
 await c.close();}finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks;',submissions,'draft submission;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
