// Counts actions (click / field fill) for the same doctor tasks in two builds on one synthetic fixture.
// Agent self-check in Chromium, not a physician trial. Usage (from the build's root): node evidence/S26B/tasks.cjs <label> <fixture.sqlite3>
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=process.cwd(),label=process.argv[2],src=process.argv[3];
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26t-')),db=path.join(tmp,'s.sqlite3');fs.copyFileSync(src,db);
const python=path.join(root,'.venv/bin/python'),origin='http://127.0.0.1:18262';
const result={kind:'agent self-check, synthetic, not a physician trial',label,tasks:[]};let server,browser;
async function start(){server=spawn(python,['evidence/S26B/serve.py',db,'18262'],{stdio:'ignore'});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
(async()=>{try{await start();browser=await chromium.launch({headless:true});result.browser={name:'Chromium',version:browser.version(),platform:process.platform};
const ctx=await browser.newContext({viewport:{width:1440,height:900}});const p=await ctx.newPage();
await p.goto(origin+'/login');await p.getByLabel('Логин').fill('doc-a');await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');
await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);
async function task(name,goal,fn){let n=0;const act=async f=>{n++;await f();};try{const ok=await fn(act,p);result.tasks.push({name,goal,actions:n,reached:ok});}catch(e){result.tasks.push({name,goal,actions:n,reached:false,error:String(e).slice(0,200)});}}
const link=re=>p.getByRole('link',{name:re}).first();
await p.goto(origin+'/demo/D01');
const first=await p.evaluate(()=>{const h=innerHeight;const t=document.body.innerText;const el=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/без записанной реакции/i.test(e.textContent)&&!e.closest('#critical-banner'));
 const route=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Записанное направление|Последние записи направлений/.test(e.textContent));
 return {viewport:innerWidth+'x'+h,signal_text_top:el?Math.round(el.getBoundingClientRect().top):null,route_label_top:route?Math.round(route.getBoundingClientRect().top):null,card_nav_links:document.querySelectorAll('nav[aria-label="Разделы карточки"] a').length,task_links:document.querySelectorAll('nav[aria-label="Задача врача"] a').length};});
await task('T1','Главный экран → найти D01 → карточка → динамика',async act=>{await p.goto(origin+'/');
 await act(()=>p.locator('input[name=q]').fill('D01'));await act(()=>p.getByRole('button',{name:'Найти'}).click());
 await act(()=>link(/Открыть случай/).click());await act(()=>link(/^(Динамика|Посмотреть динамику)$/).click());
 await p.waitForTimeout(300);return await p.getByRole('heading',{name:/Динамика по вашим записям/}).isVisible();});
await task('T2','Карточка → форма нового проекта решения',async act=>{await p.goto(origin+'/demo/D01');
 await act(()=>link(/^(Решения врача|План и решения)$/).click());return await p.getByRole('heading',{name:/Новый проект решения/}).isVisible();});
await task('T3','Страница решений → сводка повторного приёма',async act=>{await p.goto(origin+'/patients/D01/decisions');
 if(!(await p.getByRole('link',{name:'Сводка повторного приёма'}).count())) await act(()=>link(/← Карточка/).click());
 await act(()=>link(/^Сводка повторного приёма$/).click());return await p.getByRole('heading',{name:/Сводка повторного приёма/}).isVisible();});
await task('T4','Страница первого приёма → сообщения и выполнение плана',async act=>{await p.goto(origin+'/patients/D01/first-visits');
 await act(()=>link(/^(Карточка Демо 01|Наблюдение)$/).click());
 await act(()=>link(/Сообщения и выполнение плана/).click());return await p.getByRole('heading',{name:/Сообщения и выполнение плана/}).isVisible();});
await task('T5','Главный экран → сигнал → просмотр → принятие → реакция',async act=>{await p.goto(origin+'/');
 await act(()=>link(/^(Открыть критические сигналы|Критические сигналы)$/).click());
 await act(()=>p.getByRole('button',{name:'Отметить просмотр'}).click());await act(()=>p.getByRole('button',{name:'Принять к работе'}).click());
 await act(()=>p.locator('textarea[name=reaction]').fill('Синтетическая проверка: врач связался с пациентом'));await act(()=>p.getByRole('button',{name:'Записать реакцию'}).click());
 return (await p.locator('body').innerText()).includes('Синтетическая проверка: врач связался');});
result.first_screen=first;result.status='DONE';
}catch(e){result.status='FAIL';result.error=String(e.stack||e);process.exitCode=1;}finally{await browser?.close();if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(root,'evidence/S26B/tasks-'+label+'.json'),JSON.stringify(result,null,1)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(result,null,1));}})();
