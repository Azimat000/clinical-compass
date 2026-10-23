/* Disposable synthetic browser verification, no external pages or working-service writes. */
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const out = path.join(__dirname, 'screenshots'); fs.mkdirSync(out, {recursive:true});
const checks = [], errors = [];
const push = checks.push.bind(checks); checks.push = value => {console.log(JSON.stringify(value));return push(value);};
const url = 'http://127.0.0.1:8034';
(async()=>{
const browser = await chromium.launch({headless:true});
async function login(uid, js=true) {
 const context=await browser.newContext({viewport:{width:1440,height:1000},javaScriptEnabled:js,reducedMotion:'reduce'});
 const page=await context.newPage();page.on('pageerror', e=>errors.push(String(e)));
 page.on('console', msg=>{if(msg.type()==='error') errors.push(msg.text());});
 await page.goto(url+'/login'); await page.locator('[name=login]').fill(uid);
 await page.locator('[name=password]').fill('synthetic-test-password-2026');
 await page.getByRole('button',{name:'Войти',exact:true}).click();
 return {context,page};
}
const {page:doctor,context:dc}=await login('doc-a');
await doctor.goto(url+'/demo/D01#assessments'); await doctor.evaluate(()=>document.fonts.ready);
for(const width of [1440,1280,1130,1101,1100,1000,940,900,860,761,760,375,360]){
 await doctor.setViewportSize({width,height:1000});await doctor.goto(url+'/demo/D01');
 await doctor.evaluate(()=>document.fonts.ready);
 if([1440,375].includes(width)) await doctor.screenshot({path:path.join(out,width===1440?'desktop.png':'mobile.png'),fullPage:true,animations:'disabled'});
 if([1440,375,900].includes(width)) await doctor.locator('#assessments').screenshot({path:path.join(out,'assessments-'+width+'.png'),animations:'disabled'});
 const fonts=await doctor.locator('.assessment-plot svg').evaluateAll(nodes=>nodes.flatMap(svg=>{const r=svg.getBoundingClientRect(),v=svg.viewBox.baseVal;return [...svg.querySelectorAll('text')].map(t=>parseFloat(getComputedStyle(t).fontSize)*Math.min(r.width/v.width,r.height/v.height));}));
 if(Math.min(...fonts)<12) throw Error('SVG labels smaller than12px at '+width+': '+Math.min(...fonts));
 checks.push({view:'doctor',width,min_graph_font_px:Math.min(...fonts),plots:await doctor.locator('.assessment-plot').count(),overflow:await doctor.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
}
// Date anchor opens closed native details and reaches the exact source.
await doctor.locator('.assessment-plot svg a').first().click();
checks.push({point_link:await doctor.evaluate(()=>location.hash.startsWith('#assessment-'))});
await doctor.locator('#assessment-form [value="GAD7-RU-Z-2023-demo-v1"]').check();
await doctor.locator('#assessment-form [name=age_basis]').fill('Вымышленный профиль, браузерная проверка.');
await doctor.locator('#assessment-form button').click();
checks.push({assigned_gad:await doctor.getByText('GAD-7 · Предложена, ждёт ответа',{exact:true}).count()===1});
const {page:patient,context:pc}=await login('pat-a');
await patient.goto(url+'/demo/D01/forms');
checks.push({patient_task_name:await patient.locator('.task').filter({hasText:'GAD-7'}).count()>0});
await patient.getByRole('link',{name:'Начать',exact:true}).click();
for(const width of [1440,375]){
 await patient.setViewportSize({width,height:1000});
 await patient.screenshot({path:path.join(out,'gad-form-'+width+'.png'),fullPage:true,animations:'disabled'});
 checks.push({view:'gad-form',width,questions:await patient.locator('fieldset.q').count(),overflow:await patient.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
}
for(let i=1;i<=7;i++) await patient.locator('[name=answer_'+i+'][value="1"]').check();
await patient.getByRole('button',{name:'Передать анкету врачу',exact:true}).click();
await patient.getByRole('heading',{name:'Анкета отправлена врачу'}).waitFor();
checks.push({gad_receipt:await patient.getByRole('heading',{name:'Анкета отправлена врачу'}).count()===1,
 patient_scores:await patient.locator('.assessment-plot').count()});
// Earlier same-day repeat is explicitly allowed, not a 14-day project prohibition.
await doctor.reload();
await doctor.goto(url+'/demo/D01#assessments');
await doctor.locator('#assessment-form [value="GAD7-RU-Z-2023-demo-v1"]').check();
await doctor.locator('#assessment-form [name=age_basis]').fill('Повтор без обязательного интервала.');
await doctor.locator('#assessment-form button').click();
checks.push({same_day_repeat_allowed:await doctor.getByText('GAD-7 · Предложена, ждёт ответа',{exact:true}).count()===1});
await doctor.goto(url+'/patients/D01/follow-up');
checks.push({followup_status:await doctor.title(),followup_graphs:await doctor.locator('.assessment-plot').count()});
await doctor.setViewportSize({width:375,height:1000});
await doctor.screenshot({path:path.join(out,'followup-375.png'),fullPage:true,animations:'disabled'});
// JavaScript-free form sends chosen PHQ-9; no automatic clinical action.
const {page:nodoc,context:nc}=await login('doc-a',false);
await nodoc.goto(url+'/demo/D01#assessment-form');
await nodoc.locator('#assessment-form [value="PHQ9-RU-Z-2023-demo-v1"]').check();
await nodoc.locator('#assessment-form [name=age_basis]').fill('Без JavaScript, вымышленный возраст.');
await nodoc.locator('#assessment-form button').click();
const {page:nopat,context:np}=await login('pat-a',false);
await nopat.goto(url+'/demo/D01/forms');
const phq=await nopat.locator('.task').filter({hasText:'PHQ-9'}).getByRole('link',{name:'Начать'}).getAttribute('href');
await nopat.goto(url+phq);
for(let i=1;i<=9;i++) await nopat.locator('[name=answer_'+i+'][value="0"]').check();
await nopat.getByRole('button',{name:'Передать анкету врачу',exact:true}).click();
await nopat.getByRole('heading',{name:'Анкета отправлена врачу'}).waitFor();
checks.push({phq_without_js:await nopat.getByRole('heading',{name:'Анкета отправлена врачу'}).count()===1});
await browser.close();
fs.writeFileSync(path.join(__dirname,'browser.json'),JSON.stringify({checks,errors},null,2)+'\n');
if(errors.length || checks.some(c=>c.overflow) || checks.some(c=>Object.entries(c).some(([k,v])=>v===false && k!=='overflow'))) throw Error('Browser errors/overflow');
console.log(JSON.stringify({checks,errors},null,2));
})().catch(e=>{console.error(e);process.exit(1)});
