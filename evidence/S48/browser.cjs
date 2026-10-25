const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S48_ORIGIN||'http://127.0.0.1:8048',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[];function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/first-visits#v-plan');
  check(await p.locator('section#v-plan,#h-vplan,[id^=decision-]').count()===0,'Plan repeated in editor');
  check(!(await p.locator('body').innerText()).includes('Подтверждённый план'),'Old plan heading');
  check(await p.locator('#v-plan').count()===1,'Legacy anchor lost');
  check(await p.locator('[name=state][value=draft]').count()===1,'Draft missing');check(await p.locator('[name=state][value=completed]').count()===1,'Completion missing');
  check(await p.locator('[name=action_draft]').count()===1,'Unique note lost');
  const warning=p.getByText('Короткая оценка пока недоступна',{exact:true});await warning.scrollIntoViewIfNeeded();check(await warning.isVisible(),'Warning missing');
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Editor overflow');
  if(name==='chromium'&&!runtime)await p.screenshot({path:__dirname+'/editor-'+width+'.png'});
  await p.locator('.patient-nav').getByRole('link',{name:'План и решения',exact:true}).click();await p.waitForURL(u=>u.pathname==='/patients/P101/decisions');
  const response=await p.request.get(origin+'/api/patients/P101/decisions');check(response.ok(),'Decision API unavailable');const rows=(await response.json()).decisions;check(rows.length>0,'No decisions fixture');
  check(await p.getByRole('heading',{name:'Текущий план',exact:true}).count()===1,'Current plan missing');
  for(const row of rows){const item=p.locator('#decision-'+row.id);check(await item.count()===1,'Decision lost '+row.id);check((await item.textContent()).includes(row.payload.content),'Decision text lost');if(row.confirmed_at)check(await item.locator('time[datetime="'+row.confirmed_at+'"]').count()>=1,'Confirmation date lost');}
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Decisions overflow');
  check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length}),'Duplicate IDs');
  if(name==='chromium'&&!runtime){await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:__dirname+'/plan-'+width+'.png'});}
  checks.push({browser:name,width,editor_without_plan:true,legacy_anchor:true,form_and_note:true,warning:true,plan_link:true,all_decisions:rows.length,confirmation_dates:true,overflow:false});
 }
 if(!runtime){const {c:nc,p:plain}=await login(b,false);await plain.goto(origin+'/patients/P101/first-visits#v-plan');await plain.locator('.patient-nav').getByRole('link',{name:'План и решения',exact:true}).click();await plain.waitForURL(u=>u.pathname==='/patients/P101/decisions');check(await plain.locator('.current-plan .plan-main-text').isVisible(),'NoJS current plan');await plain.getByText('Основание и подробности решения',{exact:true}).click();check(await plain.locator('.current-plan .fold-body').isVisible(),'NoJS basis');await nc.close();checks.push({browser:name,no_js:true,plan_link_and_basis:true});}
 await c.close();}finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions:0,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks; 0 browser submissions;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
