const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S47_ORIGIN||'http://127.0.0.1:8047',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const checks=[],errors=[];function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(origin+'/patients/P101/first-visits#v-tool');
  check(await p.locator('section#v-tool,.assessment-series,.assessment-plot,[data-form-version]').count()===0,'Duplicate questionnaires in editor');
  check(await p.getByRole('heading',{name:'Результат инструмента отдельно'}).count()===0,'Old heading');
  check(await p.locator('[name=state][value=draft]').count()===1,'Draft missing');check(await p.locator('[name=state][value=completed]').count()===1,'Completion missing');
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Editor overflow');
  if(name==='chromium'&&!runtime){await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:__dirname+'/editor-'+width+'.png'});}
  await p.locator('#v-tool').click();await p.waitForURL(u=>u.pathname==='/demo/P101'&&u.hash==='#assessments');
  check(await p.locator('#assessments').count()===1,'Card home missing');check(await p.locator('.assessment-series').count()===3,'Lost form version');
  check(await p.locator('[id^=answers-]').count()>=6,'Lost raw answers');check(await p.locator('.assessment-plot').count()===5,'Lost plots');
  check(await p.getByRole('button',{name:'Предложить выбранную анкету',exact:true}).count()===1,'Offer missing');
  const raw=p.locator('[id^=answers-]').first();await raw.locator('summary').click();check(await raw.locator('ol.answers > li').count()>0,'Answers empty');
  const source=p.getByText('Версия, источник и ограничения · DASS-42',{exact:true});await source.click();check(await p.getByText('Бланк и источник',{exact:true}).first().isVisible(),'Sources hidden');
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Card overflow');
  check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length}),'Duplicate IDs');
  if(name==='chromium'&&!runtime){await p.locator('#assessments').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/card-'+width+'.png'});}
  checks.push({browser:name,width,editor_without_questionnaires:true,link_to_card:true,form_versions:3,plots:5,answers:true,sources:true,overflow:false});
 }
 if(!runtime){const {c:nc,p:plain}=await login(b,false);await plain.goto(origin+'/patients/P101/first-visits#v-tool');await plain.locator('#v-tool').click();await plain.waitForURL(u=>u.hash==='#assessments');const raw=plain.locator('[id^=answers-]').first();await raw.locator('summary').click();check(await raw.locator('ol.answers > li').first().isVisible(),'NoJS answers');await nc.close();checks.push({browser:name,no_js:true,link_and_answers:true});}
 await c.close();}finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions:0,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks; 0 browser submissions;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
