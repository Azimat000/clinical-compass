// Same patient checks in Chromium, Firefox and WebKit (Playwright builds on macOS). Agent self-check; not real Safari/Firefox releases on user devices.
// Usage: node evidence/S26C/browsers.cjs <fixture.sqlite3>
const pw=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.cwd(),src=process.argv[2],tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26c-')),db=path.join(tmp,'s.sqlite3');
fs.copyFileSync(src,db);const meta=JSON.parse(fs.readFileSync(src+'.json'));
const python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18265';
const report={kind:'agent self-check, synthetic; Playwright builds, no physical device, no screen reader',browsers:[]};let server;
async function start(){server=spawn(python,['evidence/S26C/serve.py',db,'18265'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
(async()=>{try{await start();
for(const name of ['chromium','firefox','webkit']){const row={engine:name,checks:[],failures:[]};let browser;
 try{browser=await pw[name].launch({headless:true});row.version=browser.version();
  const ctx=await browser.newContext({viewport:{width:1440,height:900}});const p=await ctx.newPage();const errs=[];p.on('pageerror',e=>errs.push(String(e)));p.on('dialog',d=>d.accept());
  await p.goto(origin+'/login');await p.getByLabel('Логин').fill('pat-a');await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);
  await p.goto(origin+'/demo/D01');assert(await p.locator('a.today-action').isVisible());row.checks.push('Сегодня: одно главное действие видно');
  assert.equal(await p.locator('a.today-action').count(),1);
  const font=await p.evaluate(()=>document.fonts.check('16px "HAC Sans"'));row.checks.push('шрифт HAC Sans загружен: '+font);
  await p.getByRole('link',{name:'Самоотчёт',exact:true}).click();await p.locator('#report-step-1').waitFor({state:'visible'});
  for(let i=0;i<4;i++)await p.locator('[data-step-next]').click();
  assert(await p.locator('[data-review]').isVisible());assert(await p.getByRole('button',{name:'Отправить самоотчёт'}).isVisible());row.checks.push('самоотчёт: пять шагов, проверка перед отправкой, кнопка отправки видна');
  await Promise.all([p.waitForURL(u=>u.hash.startsWith('#entry-')),p.getByRole('button',{name:'Отправить самоотчёт'}).click()]);row.checks.push('самоотчёт отправлен, переход к сохранённой записи');
  await p.goto(origin+'/assessments/'+meta.assessment_request);
  await p.locator('input[name=answer_1][value="2"]').check();assert.match(await p.locator('[data-answer-progress]').innerText(),/Отвечено: 1 из 42/);row.checks.push('анкета: счётчик ответов работает, 42 вопроса');
  for(const w of [320,768,1024,1440]){await p.setViewportSize({width:w,height:900});for(const u of ['/demo/D01','/patients/D01/communication','/patients/D01/decisions','/assessments/'+meta.assessment_request]){const r=await p.goto(origin+u);assert.equal(r.status(),200);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,u+'@'+w);}}
  row.checks.push('4 страницы × 4 ширины: статус 200, без горизонтальной прокрутки');
  if(errs.length)row.failures.push('page errors: '+errs.join('; '));
  await ctx.close();
 }catch(e){row.failures.push(String(e.message||e).slice(0,300));}finally{await browser?.close();}
 row.status=row.failures.length?'FAIL':'PASS';report.browsers.push(row);}
report.status=report.browsers.every(b=>b.status==='PASS')?'PASS':'FAIL';
}catch(e){report.status='FAIL';report.error=String(e.stack||e);}finally{if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(root,'evidence/S26C/browsers.json'),JSON.stringify(report,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(report,null,1));process.exitCode=report.status==='PASS'?0:1;}})();
