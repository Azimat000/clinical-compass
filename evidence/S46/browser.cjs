const {chromium,firefox,webkit}=require('playwright'),fs=require('fs');
const origin=process.env.S46_ORIGIN||'http://127.0.0.1:8046',runtime=origin.endsWith(':8000');
const accounts=JSON.parse(fs.readFileSync('var/clinic-20261023-accounts.json')).accounts;
const fixture=JSON.parse(fs.readFileSync(__dirname+'/browser-fixture.json'));
const checks=[],errors=[];function check(ok,msg){if(!ok)throw Error(msg);}
async function login(b,js=true){const c=await b.newContext({javaScriptEnabled:js,reducedMotion:'reduce'}),p=await c.newPage(),a=accounts.find(a=>a.login==='m.sokolova');p.on('pageerror',e=>errors.push(String(e)));await p.goto(origin+'/login');await p.locator('[name=login]').fill(a.login);await p.locator('[name=password]').fill(a.password);await p.getByRole('button',{name:'Войти',exact:true}).click();await p.waitForURL(u=>!u.pathname.includes('login'));return {c,p};}
(async()=>{for(const [name,engine] of Object.entries(runtime?{chromium}:{chromium,firefox,webkit})){
 const b=await engine.launch({headless:true});try{const {c,p}=await login(b);
 for(const width of runtime?[1440]:[375,1440]){await p.setViewportSize({width,height:900});await p.goto(origin+'/demo/P101#visit-history');
  check(await p.getByRole('heading',{name:'История приёмов',exact:true}).count()===1,'Card history missing');
  check(await p.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return new Set(ids).size===ids.length}),'Duplicate IDs');
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Card overflow');
  const vid=runtime?(await p.locator('#visit-history details.visit').first().getAttribute('id')).slice(6):fixture.visit_id;
  if(!runtime){for(const n of [1,2])check(await p.locator('#visit-version-'+vid+'-'+n).count()===1,'Version missing '+n);const text=await p.locator('#visit-'+vid).textContent();for(const t of ['текст А','текст Б','документа А','документа Б','Проект А','Проект Б'])check(text.includes(t),'Lost '+t);}
  if(name==='chromium'&&!runtime){await p.locator('#visit-'+vid+' > summary').scrollIntoViewIfNeeded();await p.screenshot({path:__dirname+'/card-'+width+'.png'});}
  checks.push({browser:name,width,page:'card',history:true,versions:runtime?'existing':2,overflow:false});
  await p.goto(origin+'/patients/P101/first-visits/'+vid);check(p.url().includes('/demo/P101#visit-'+vid),'Completed URL not redirected');checks.push({browser:name,width,completed_bookmark:true});
  await p.goto(origin+'/patients/P101/first-visits');check(await p.getByRole('heading',{name:'История приёмов',exact:true}).count()===0,'Duplicate editor history');check(await p.locator('.visit,.entry-table,#v-list.block').count()===0,'Duplicate records in editor');check(await p.locator('[name=state][value=draft]').count()===1,'Draft action missing');check(await p.locator('[name=state][value=completed]').count()===1,'Completion missing');check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Editor overflow');
  if(name==='chromium'&&!runtime)await p.screenshot({path:__dirname+'/editor-'+width+'.png'});
  await p.locator('#v-list').click();await p.waitForURL(u=>u.pathname==='/demo/P101'&&u.hash==='#visit-history');checks.push({browser:name,width,page:'editor',no_duplicate_history:true,history_link:true});
 }
 if(!runtime){const {c:pc,p:plain}=await login(b,false);await plain.goto(origin+'/demo/P101');const top=plain.locator('#visit-'+fixture.visit_id);if(await top.getAttribute('open')===null)await top.locator(':scope > summary').click();await top.getByText('Предыдущие версии (1)',{exact:true}).click();await plain.locator('#visit-version-'+fixture.visit_id+'-1 > summary').click();check(await plain.locator('#visit-version-'+fixture.visit_id+'-1').innerText().then(t=>t.includes('текст А')),'NoJS old revision missing');await plain.goto(origin+'/patients/P101/records/'+fixture.short_id);check(plain.url().includes('/demo/P101#entry-'+fixture.short_id),'Short record link');await pc.close();checks.push({browser:name,no_js:true,previous_version:true,typed_record_link:true});}
 await c.close();}finally{await b.close();}
}check(!errors.length,'Browser errors '+errors.join(','));fs.writeFileSync(__dirname+(runtime?'/runtime-browser.json':'/browser.json'),JSON.stringify({status:'PASS',checks,submissions:0,errors},null,2)+'\n');console.log('PASS:',checks.length,'checks; 0 browser submissions;',runtime?'runtime':'isolated');})().catch(e=>{console.error(e);process.exitCode=1});
