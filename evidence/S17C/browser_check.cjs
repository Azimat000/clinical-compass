// Local synthetic self-check. Requires the already installed Playwright bundle.
const {chromium} = require(process.env.COMPASS_PLAYWRIGHT);
const {spawn, execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.cwd(), out = path.join(root,'evidence/S17C');
const temp = fs.mkdtempSync(path.join(os.tmpdir(),'compass-s17c-'));
const database = path.join(temp,'synthetic.sqlite3'), python = path.join(root,'.venv/bin/python');
const origin = 'http://127.0.0.1:18037';
execFileSync(python,['-c',`import sys
sys.path.insert(0,'apps/tests')
from test_first_visits import fixture
from apps.compass.db import connect,migrate
db=connect(sys.argv[1]);migrate(db);fixture(db);db.close()`,database],{cwd:root});
let server, browser;
const report = {kind:'agent self-check; synthetic only', checks:[]};
async function start(){
  server=spawn(python,['-m','apps.compass','--db',database,'serve','--port','18037'],{cwd:root,stdio:'ignore'});
  for(let i=0;i<100;i++){
    try {if((await fetch(origin+'/healthz')).ok)return;}catch{}
    await new Promise(r=>setTimeout(r,50));
  }
  throw Error('fixture did not start');
}
async function stop(){if(server && server.exitCode===null){const ended=new Promise(r=>server.once('exit',r));server.kill();await ended;}}
async function login(page,uid){
  await page.goto(origin+'/login');
  await page.getByLabel('Логин').fill(uid);
  await page.getByLabel('Пароль',{exact:true}).fill('synthetic-test-password-2026');
  await Promise.all([page.waitForURL(u=>!u.pathname.includes('login')),page.getByRole('button',{name:'Войти',exact:true}).click()]);
}
(async()=>{
  try{
    await start();browser=await chromium.launch({headless:true});report.browser=browser.version();
    const doctor=await browser.newContext({viewport:{width:1440,height:1000}}), page=await doctor.newPage();
    await login(page,'doc-a');await page.goto(origin+'/demo/FV01');
    await page.screenshot({path:out+'/doctor-card.png'});
    await page.getByRole('link',{name:'Первый приём без готового диагноза'}).click();
    await page.screenshot({path:out+'/new-visit-desktop.png'});
    await page.locator('[name=complaints_status]').selectOption('known');
    await page.locator('[name=complaints_text]').fill('Синтетический случай: утомляемость и плохой сон, диагноз не установлен.');
    await page.locator('[name=complaints_basis]').fill('Беседа с вымышленным пациентом сегодня');
    await Promise.all([page.waitForURL(/first-visits\/[a-f0-9]{32}$/),page.getByRole('button',{name:'Сохранить черновик',exact:true}).click()]);
    const saved=page.url();
    assert.match(await page.locator('[role=status]').innerText(),/черновик/);
    report.checks.push('doctor opens diagnosis-free FV01, saves incomplete draft');
    await stop();await start();await page.goto(saved);
    assert.match(await page.locator('[name=complaints_text]').inputValue(),/утомляемость/);
    report.checks.push('real Waitress process restart; same authenticated doctor reopens persisted draft');
    await page.locator('#visit-summary').scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/saved-summary.png'});
    // Native keyboard focus; no custom controls or traps.
    await page.locator('[name=complaints_text]').focus();await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.name),'complaints_basis');
    report.checks.push('Tab moves from complaint text to its source basis; native focus visible');
    await page.setViewportSize({width:320,height:800});await page.goto(saved);
    report.overflow=await page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(el=>el.getBoundingClientRect().right>innerWidth+1).map(el=>({tag:el.tagName,cls:el.className,name:el.getAttribute('name'),width:el.getBoundingClientRect().width})).slice(0,25));
    await page.screenshot({path:out+'/draft-320.png'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:out+'/draft-320.png'});
    await page.locator('[name=state][value=draft]').scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/draft-actions-320.png'});
    report.checks.push('320px viewport, no horizontal overflow; save controls available');
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('[name=complaints_text]').fill('Синтетическое уточнение жалобы после возврата');
    await page.getByRole('button',{name:'Завершить запись',exact:true}).click();
    await page.waitForLoadState();
    assert.match(await page.locator('[role=status]').innerText(),/запись завершена/);
    assert.equal(await page.locator('#visit-form').count(),0);
    await page.locator('#visit-history details').last().locator('summary').click();
    assert.match(await page.locator('#visit-history').innerText(),/утомляемость/);
    await page.screenshot({path:out+'/completed-desktop.png'});
    report.checks.push('completed revision is read-only; original revision and new text remain in history');
    const patient=await browser.newContext({viewport:{width:1280,height:900}}), pat=await patient.newPage();
    await login(pat,'pat-fv');await pat.goto(origin+'/demo/FV01');
    assert.equal(await pat.getByRole('link',{name:'Первый приём без готового диагноза'}).count(),0);
    await pat.screenshot({path:out+'/patient-card.png'});
    assert.equal((await pat.goto(saved)).status(),403);
    await pat.screenshot({path:out+'/patient-denied.png'});
    report.checks.push('patient retains self-report and cabinet; direct first-visit URL is 403');
    report.status='PASS';
  }finally{
    if(browser)await browser.close();await stop();fs.rmSync(temp,{recursive:true,force:true});
    fs.writeFileSync(out+'/browser-result.json',JSON.stringify(report,null,2)+'\n');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
