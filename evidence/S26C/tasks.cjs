// Counts actions (click / field fill / select) for the same patient tasks in two builds on one synthetic fixture.
// Agent self-check in Chromium, not a patient trial. Usage (from the build's root): node <path>/tasks.cjs <label> <fixture.sqlite3> <serve.py>
const {chromium}=require('/Users/azamatsibgatullin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=process.cwd(),label=process.argv[2],src=process.argv[3],serve=process.argv[4];
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'compass-s26t-')),db=path.join(tmp,'s.sqlite3');fs.copyFileSync(src,db);
const python=path.join(process.env.VENV_ROOT||root,'.venv/bin/python'),origin='http://127.0.0.1:18264';
const result={kind:'agent self-check, synthetic, not a patient trial',label,tasks:[]};let server,browser;
async function start(){server=spawn(python,[serve,db,'18264'],{stdio:'ignore',cwd:root});for(let i=0;i<100;i++){try{if((await fetch(origin+'/healthz')).ok)return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('server timeout');}
(async()=>{try{await start();browser=await chromium.launch({headless:true});result.browser={name:'Chromium',version:browser.version(),platform:process.platform};
const ctx=await browser.newContext({viewport:{width:1440,height:900}});const p=await ctx.newPage();p.on('dialog',d=>d.accept());
await p.goto(origin+'/login');await p.getByLabel('Логин').fill('pat-a');await p.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');
await Promise.all([p.waitForURL(u=>!u.pathname.includes('login')),p.getByRole('button',{name:'Войти',exact:true}).click()]);
async function task(name,goal,fn){let n=0;const act=async f=>{n++;await f();};try{const ok=await fn(act,p);result.tasks.push({name,goal,actions:n,reached:ok});}catch(e){result.tasks.push({name,goal,actions:n,reached:false,error:String(e).slice(0,200)});}}
const link=re=>p.getByRole('link',{name:re}).first();
for(const [w,h] of [[1440,900],[375,812]]){await p.setViewportSize({width:w,height:h});await p.goto(origin+'/demo/D01');
 result['first_screen_'+w]=await p.evaluate(()=>{const b=[...document.querySelectorAll('a.button,.patient-heading a.button')].map(e=>({text:e.textContent.trim().slice(0,40),top:Math.round(e.getBoundingClientRect().top),bottom:Math.round(e.getBoundingClientRect().bottom)}));return {viewport_height:innerHeight,primary_buttons_in_main:b};});}
await p.setViewportSize({width:1440,height:900});
await task('P1','Главная → отправить самоотчёт с полями по умолчанию',async act=>{await p.goto(origin+'/demo/D01');
 await act(()=>link(/^(Добавить самоотчёт|Самоотчёт)$/).click());await p.waitForTimeout(400);
 while(await p.getByRole('button',{name:'Далее',exact:true}).isVisible()){await act(()=>p.getByRole('button',{name:'Далее',exact:true}).click());}
 await Promise.all([p.waitForURL(u=>u.hash.startsWith('#entry-')),act(()=>p.getByRole('button',{name:'Отправить самоотчёт'}).click())]);return true;});
await task('P2','Главная → открыта анкета DASS-42, предложенная врачом',async act=>{await p.goto(origin+'/demo/D01');
 if(await p.locator('a.today-action',{hasText:'анкету'}).count()){await act(()=>p.locator('a.today-action').click());}
 else{await act(()=>link(/^Анкеты$/).click());await act(()=>link(/Заполнить предложенную DASS-42/).click());}
 await p.waitForLoadState();return await p.getByRole('heading',{name:/DASS/}).isVisible();});
await task('P3','Главная → отметить пункт плана «Выполнено»',async act=>{await p.goto(origin+'/demo/D01');
 await act(()=>link(/^(Сообщения и выполнение плана|К выполнению плана)$/).click());await p.waitForLoadState();
 await act(()=>p.locator('select[name=outcome]').first().selectOption('taken'));
 await act(()=>p.getByRole('button',{name:'Сохранить отметку'}).first().click());await p.waitForTimeout(600);
 return /Выполнено/.test(await p.locator('main').innerText());});
await task('P4','Главная → отправить сообщение врачу',async act=>{await p.goto(origin+'/demo/D01');
 await act(()=>link(/^(Сообщения и выполнение плана|Сообщения и план)$/).click());await p.waitForLoadState();
 await act(()=>p.locator('textarea[name=body]').fill('Синтетическое сообщение врачу'));
 await act(()=>p.getByRole('button',{name:'Отправить сообщение'}).click());await p.waitForTimeout(600);
 return /Синтетическое сообщение врачу/.test(await p.locator('main').innerText());});
}catch(e){result.error=String(e.stack||e);process.exitCode=1;}finally{await browser?.close();if(server?.exitCode===null){const d=new Promise(r=>server.once('exit',r));server.kill();await d;}
fs.writeFileSync(path.join(process.env.OUT_DIR||path.join(root,'evidence/S26C'),'tasks-'+label+'.json'),JSON.stringify(result,null,2)+'\n');fs.rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify(result,null,1));}})();
