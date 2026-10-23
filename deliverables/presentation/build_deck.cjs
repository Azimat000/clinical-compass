/* Builds the pre-defence / demo-day deck for «Клинический компас».
 * Run: NODE_PATH=<dir with pptxgenjs, sharp, react, react-dom, react-icons, qrcode> node build_deck.cjs [--url https://...]
 * Facts and measured numbers live in metrics.json; screenshots in assets/ (fictional data only). */
const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');
const sharp = require('sharp');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const lu = require('react-icons/lu');
const QRCode = require('qrcode');

const HERE = __dirname;
const A = (f) => path.join(HERE, 'assets', f);
const M = JSON.parse(fs.readFileSync(path.join(HERE, 'metrics.json'), 'utf8'));
const urlArg = process.argv.indexOf('--url');
const DEMO_URL = urlArg > 0 ? process.argv[urlArg + 1] : (M.demo_url || '');
const OUT = path.join(HERE, 'klinicheskiy-kompas-demo-day.pptx');

// Palette: deep petrol for trust, teal for structure, amber as the compass needle.
const K = {
  ink: '16252B', petrol: '123A40', teal: '1F6F68', tealL: 'DCEBE8', mist: 'F1F5F4',
  amber: 'D9822B', amberT: '9A5410', amberL: 'FBEBD9', green: '2E7D4F', red: 'B3412F',
  slate: '5A6B71', line: 'D3DEDB', white: 'FFFFFF', sea: '8FB9B2',
};
const THEME = {
  name: 'Klinicheskiy Kompas', headFontFace: 'Cambria', bodyFontFace: 'Calibri',
  colors: { dk1: K.ink, lt1: K.white, dk2: K.petrol, lt2: K.mist, accent1: K.teal, accent2: K.amber,
    accent3: K.green, accent4: K.red, accent5: K.slate, accent6: K.sea, hlink: K.teal, folHlink: K.slate },
};
const HEAD = 'Cambria', BODY = 'Calibri';
const W = 13.333, H = 7.5, MX = 0.6;
const FOOT = 'Клинический компас · кейс-чемпионат Авинейро · 2026';

// ---------- image helpers ----------
async function svgPng(svg, px = 256) {
  const buf = await sharp(Buffer.from(svg)).resize(px, px).png().toBuffer();
  return 'image/png;base64,' + buf.toString('base64');
}
async function icon(name, color) {
  const svg = renderToStaticMarkup(React.createElement(lu[name], { color: '#' + color, size: 256 }));
  return svgPng(svg.includes('xmlns=') ? svg : svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"'));
}
function compassSvg(ring, needle, tail) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="43" fill="none" stroke="#${ring}" stroke-width="7"/>
  <g transform="rotate(35 50 50)"><polygon points="50,15 60,50 40,50" fill="#${needle}"/>
  <polygon points="40,50 60,50 50,85" fill="#${tail}"/></g>
  <circle cx="50" cy="50" r="5" fill="#${ring}"/></svg>`;
}
const ICONS = {};
async function ic(name, color) {
  const k = name + color;
  if (!ICONS[k]) ICONS[k] = await icon(name, color);
  return ICONS[k];
}

(async () => {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';
  pres.title = 'Клинический компас — предзащита и демо-день';
  pres.author = 'Азамат Сибгатуллин и команда';
  pres.company = 'Команда «Клинический компас»';
  pres.theme = { headFontFace: HEAD, bodyFontFace: BODY };
  // Sections must exist before slides reference them; declare each on first use.
  const sections = new Set();
  const addSlide = pres.addSlide.bind(pres);
  pres.addSlide = (o) => {
    if (o && o.sectionTitle && !sections.has(o.sectionTitle)) { pres.addSection({ title: o.sectionTitle }); sections.add(o.sectionTitle); }
    return addSlide(o);
  };

  const markDark = await svgPng(compassSvg(K.petrol, K.amber, K.sea), 256);
  const markLight = await svgPng(compassSvg(K.white, K.amber, K.sea), 256);

  // ---------- layouts ----------
  pres.defineSlideMaster({
    title: 'CONTENT', background: { color: K.white },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { image: { data: markDark, x: 10.68, y: 0.4, w: 0.34, h: 0.34 } },
      { text: { text: 'Клинический компас', options: { x: 11.08, y: 0.4, w: 1.68, h: 0.34, fontFace: HEAD, fontSize: 11, bold: true, color: K.petrol, margin: 0, valign: 'middle' } } },
      { text: { text: FOOT, options: { x: MX, y: 7.04, w: 8, h: 0.26, fontFace: BODY, fontSize: 9, color: K.slate, margin: 0 } } },
      { placeholder: { options: { name: 'title', type: 'title', x: MX, y: 0.8, w: 10.3, h: 0.72, fontFace: HEAD, fontSize: 28, bold: true, color: K.petrol, align: 'left', valign: 'top', margin: 0 }, text: '' } },
    ],
    slideNumber: { x: 12.33, y: 7.02, w: 0.4, h: 0.28, fontFace: BODY, fontSize: 9, color: K.slate, align: 'right' },
  });
  pres.defineSlideMaster({ title: 'DARK', background: { color: K.petrol }, objects: [] });
  pres.defineSlideMaster({ title: 'COVER', background: { color: K.white }, objects: [] });

  // ---------- shape helpers ----------
  const T = (s, text, o) => s.addText(text, Object.assign({ fontFace: BODY, fontSize: 14, color: K.ink, margin: 0, valign: 'top', isTextBox: true }, o));
  const box = (s, x, y, w, h, fill, extra = {}) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, Object.assign({ x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 }, rectRadius: 0.08 }, extra));
  const shadow = () => ({ type: 'outer', color: '0B2226', opacity: 0.16, blur: 10, offset: 3, angle: 90 });
  function chip(s, text, dark = false) {
    const w = 0.34 + text.length * 0.102;
    box(s, MX, 0.42, w, 0.28, dark ? '1B4A51' : K.tealL, { rectRadius: 0.14 });
    T(s, text, { x: MX, y: 0.42, w, h: 0.28, fontSize: 9, bold: true, charSpacing: 1.5, color: dark ? K.sea : K.teal, align: 'center', valign: 'middle' });
  }
  function slide(section, label, title) {
    const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: section });
    chip(s, label);
    s.addText(title, { placeholder: 'title' });
    return s;
  }
  async function iconDot(s, name, x, y, d, bg, fg) {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg, width: 0 } });
    const p = d * 0.27;
    s.addImage({ data: await ic(name, fg), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p });
  }
  function num(s, n, x, y, d, bg, fg) {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg, width: 0 } });
    T(s, String(n), { x, y, w: d, h: d, fontSize: 11, bold: true, color: fg, align: 'center', valign: 'middle' });
  }
  function foot(s, text, y = 6.62) { T(s, text, { x: MX, y, w: W - 2 * MX, h: 0.3, fontSize: 10, color: K.slate }); }
  function screen(s, img, x, y, w, h) {
    s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: K.white }, line: { color: K.line, width: 0.75 }, shadow: shadow() });
    s.addImage({ path: A(img), x: x + 0.03, y: y + 0.03, w: w - 0.06, h: h - 0.06 });
  }
  function phone(s, img, x, y, w) {
    const h = w * (1688 / 780) + 0.16;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: w + 0.16, h, fill: { color: K.ink }, line: { color: K.ink, width: 0 }, rectRadius: 0.16, shadow: shadow() });
    s.addImage({ path: A(img), x: x + 0.08, y: y + 0.08, w, h: w * (1688 / 780) });
    return h;
  }

  // =====================================================================
  // 1. Title
  {
    const s = pres.addSlide({ masterName: 'COVER', sectionTitle: 'Титул' });
    s.addShape(pres.shapes.RECTANGLE, { x: 7.75, y: 0, w: W - 7.75, h: H, fill: { color: K.petrol }, line: { color: K.petrol, width: 0 } });
    s.addImage({ data: markLight, x: 8.2, y: 0.55, w: 0.5, h: 0.5, transparency: 70 });
    T(s, 'ПУТЬ ПАЦИЕНТА', { x: 8.85, y: 0.62, w: 3, h: 0.35, fontSize: 10, bold: true, charSpacing: 2, color: K.sea, valign: 'middle' });
    phone(s, 'patient-today.jpg', 9.55, 1.25, 2.3);
    const steps = [['Приём', 'врач задаёт план'], ['Дома', 'дневник, анкеты, таблетки'], ['Сводка', 'изменения за период'], ['Решение', 'подтверждает врач']];
    steps.forEach(([a, b], i) => {
      const y = 1.55 + i * 1.18;
      num(s, i + 1, 8.2, y, 0.38, i === 3 ? K.amber : '1B4A51', K.white);
      T(s, a, { x: 8.2, y: y + 0.44, w: 1.25, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: K.white });
      T(s, b, { x: 8.2, y: y + 0.72, w: 1.25, h: 0.42, fontSize: 9, color: K.sea });
    });
    chip(s, 'КЕЙС-ЧЕМПИОНАТ АВИНЕЙРО · ПРЕДЗАЩИТА И ДЕМО-ДЕНЬ');
    s.addImage({ data: markDark, x: MX, y: 1.15, w: 0.72, h: 0.72 });
    T(s, 'Клинический компас', { x: 1.5, y: 1.08, w: 6.1, h: 0.9, fontFace: HEAD, fontSize: 40, bold: true, color: K.petrol, valign: 'middle' });
    T(s, 'Врач видит, как пациент живёт между приёмами', { x: MX, y: 2.2, w: 6.8, h: 0.95, fontFace: HEAD, fontSize: 24, color: K.teal });
    T(s, 'Веб-сервис для психиатра и пациента с тревогой и депрессией: дневник самочувствия, анкеты DASS-42, PHQ-9 и GAD-7, календарь препаратов и план лечения, который подтверждает врач', { x: MX, y: 3.3, w: 6.6, h: 1.0, fontSize: 15, color: K.ink });
    box(s, MX, 4.55, 6.75, 0.78, K.mist);
    T(s, [{ text: 'Кейс  ', options: { bold: true, color: K.teal, fontSize: 10, charSpacing: 1 } }, { text: '«Клинический компас: инновационные решения для диагностики и ведения пациентов с тревогой и депрессией»', options: { color: K.ink, fontSize: 12 } }], { x: MX + 0.2, y: 4.6, w: 6.4, h: 0.68, valign: 'middle' });
    s.addShape(pres.shapes.OVAL, { x: MX, y: 5.65, w: 0.62, h: 0.62, fill: { color: K.petrol }, line: { color: K.petrol, width: 0 } });
    T(s, 'АС', { x: MX, y: 5.65, w: 0.62, h: 0.62, fontFace: HEAD, fontSize: 15, bold: true, color: K.white, align: 'center', valign: 'middle' });
    T(s, 'Азамат Сибгатуллин', { x: 1.38, y: 5.66, w: 3.2, h: 0.32, fontFace: HEAD, fontSize: 14, bold: true, color: K.ink });
    T(s, 'капитан команды, разработчик', { x: 1.38, y: 5.97, w: 3.2, h: 0.3, fontSize: 11, color: K.slate });
    s.addShape(pres.shapes.OVAL, { x: 4.45, y: 5.65, w: 0.62, h: 0.62, fill: { color: K.tealL }, line: { color: K.tealL, width: 0 } });
    T(s, '+4', { x: 4.45, y: 5.65, w: 0.62, h: 0.62, fontFace: HEAD, fontSize: 15, bold: true, color: K.teal, align: 'center', valign: 'middle' });
    T(s, 'участника команды', { x: 5.23, y: 5.66, w: 2.3, h: 0.32, fontFace: HEAD, fontSize: 14, bold: true, color: K.ink });
    T(s, 'состав на слайде «Команда»', { x: 5.23, y: 5.97, w: 2.3, h: 0.3, fontSize: 11, color: K.slate });
    T(s, 'Октябрь 2026', { x: MX, y: 6.85, w: 3, h: 0.3, fontSize: 11, color: K.slate });
    s.addNotes('Добрый день. Психиатр видит пациента раз в несколько недель, а всё важное происходит между приёмами. «Клинический компас» показывает врачу эту часть жизни пациента: самочувствие, анкеты, приём препаратов. При этом решение всегда остаётся за врачом. Я Азамат Сибгатуллин, капитан и разработчик команды.');
  }

  // =====================================================================
  // 2. Problem
  {
    const s = slide('1. Идея', 'ПРОБЛЕМА', 'Между приёмами врач не видит, как живёт пациент');
    const cols = [
      { x: MX, ic: 'LuStethoscope', h: 'Психиатр', bg: K.mist, items: ['На приёме узнаёт только то, что пациент вспомнил и успел рассказать', 'Ухудшение, побочные эффекты и пропуски таблеток всплывают с опозданием', 'Анкеты на бумаге: динамику приходится сводить вручную'] },
      { x: 6.79, ic: 'LuUser', h: 'Пациент', bg: K.amberL, items: ['Через две недели не помнит, как спал и что чувствовал', 'Бросает лечение, когда не видит эффекта или боится побочных действий', 'Не знает, можно ли написать врачу и дошло ли сообщение'] },
    ];
    for (const c of cols) {
      box(s, c.x, 1.72, 5.94, 3.0, c.bg);
      await iconDot(s, c.ic, c.x + 0.3, 1.95, 0.56, c === cols[0] ? K.teal : K.amber, K.white);
      T(s, c.h, { x: c.x + 1.0, y: 1.95, w: 4, h: 0.56, fontFace: HEAD, fontSize: 18, bold: true, color: K.petrol, valign: 'middle' });
      c.items.forEach((t, i) => {
        T(s, String(i + 1), { x: c.x + 0.35, y: 2.75 + i * 0.62, w: 0.4, h: 0.5, fontFace: HEAD, fontSize: 16, bold: true, color: c === cols[0] ? K.teal : K.amberT });
        T(s, t, { x: c.x + 0.85, y: 2.75 + i * 0.62, w: 4.85, h: 0.56, fontSize: 14 });
      });
    }
    const stats = [
      ['> 1 млрд', 'людей в мире живут с психическими расстройствами; тревога и депрессия — больше двух третей случаев', 'ВОЗ, 2025'],
      ['15 % и 14 %', 'жителей Москвы с признаками тревоги и депрессии по скринингу', 'Consortium Psychiatricum, 2024'],
      ['73,8 % vs 28,8 %', 'ремиссия при регулярных замерах между приёмами против обычного ведения', 'Guo et al., Am J Psychiatry, 2015'],
    ];
    stats.forEach(([n, t, src], i) => {
      const x = MX + i * 4.1;
      T(s, n, { x, y: 4.98, w: 3.9, h: 0.6, fontFace: HEAD, fontSize: 28, bold: true, color: i === 2 ? K.teal : K.petrol });
      T(s, t, { x, y: 5.6, w: 3.8, h: 0.66, fontSize: 12, color: K.ink });
      T(s, src, { x, y: 6.27, w: 3.8, h: 0.26, fontSize: 9, color: K.slate, italic: true });
    });
    s.addNotes('Психиатр видит пациента раз в несколько недель и узнаёт только то, что тот вспомнил. Пациент к приёму многое забывает и легко бросает лечение. Это не редкая история: по данным ВОЗ, психическими расстройствами страдает больше миллиарда человек, и большинство случаев приходится на тревогу и депрессию. Главное число справа: когда состояние регулярно измеряют между приёмами, ремиссия наступает намного чаще. Это мы и делаем удобным.');
  }

  // =====================================================================
  // 3. Solution
  {
    const s = slide('1. Идея', 'РЕШЕНИЕ', 'Одна история пациента от приёма до приёма');
    const cx = 3.55, cy = 3.95, r = 1.6;
    s.addShape(pres.shapes.OVAL, { x: cx - r, y: cy - r, w: 2 * r, h: 2 * r, fill: { color: K.white }, line: { color: K.line, width: 2, dashType: 'dash' } });
    s.addImage({ data: markDark, x: cx - 0.55, y: cy - 0.55, w: 1.1, h: 1.1 });
    const nodes = [
      ['Приём', 'врач фиксирует план и назначения', 0, -1, 'LuStethoscope'],
      ['Дома', 'дневник, анкеты и отметки о таблетках', 1, 0, 'LuNotebookPen'],
      ['Сводка', 'перед приёмом врач видит изменения за период', 0, 1, 'LuChartLine'],
      ['Решение', 'врач подтверждает, пациент сразу видит план', -1, 0, 'LuUserCheck'],
    ];
    for (const [i, [h, t, dx, dy, icn]] of nodes.entries()) {
      const nx = cx + dx * r - 0.36, ny = cy + dy * r - 0.36;
      await iconDot(s, icn, nx, ny, 0.72, i === 3 ? K.amber : K.teal, K.white);
      // Top and bottom nodes carry their label to the right; side nodes carry it underneath.
      const side = dx !== 0, tw = 2.2;
      const tx = side ? nx + 0.36 - tw / 2 : nx + 0.85, ty = side ? ny + 0.82 : ny - 0.02;
      const al = side ? 'center' : 'left';
      T(s, `${i + 1}. ${h}`, { x: tx, y: ty, w: tw, h: 0.3, fontFace: HEAD, fontSize: 13, bold: true, color: K.petrol, align: al });
      T(s, t, { x: tx, y: ty + 0.3, w: tw, h: 0.62, fontSize: 11, color: K.slate, align: al });
    }
    const pr = [
      ['LuUserCheck', 'Решает врач', 'Сервис ничего не назначает сам. Назначение, изменение и отмена терапии, направление и новый план действуют только после подтверждения врача.'],
      ['LuLink', 'У каждого факта есть источник', 'Кто записал, когда и что именно. Из сводки один щелчок до исходной записи пациента.'],
      ['LuCircleDashed', 'Неизвестное видно', 'Пропуск таблетки и отсутствие отметки показаны по-разному. Пустое поле не выдаётся за «всё хорошо».'],
    ];
    for (const [i, [icn, h, t]] of pr.entries()) {
      const y = 1.78 + i * 1.6;
      box(s, 7.15, y, 5.58, 1.42, K.mist);
      await iconDot(s, icn, 7.4, y + 0.27, 0.56, K.white, K.teal);
      T(s, h, { x: 8.15, y: y + 0.2, w: 4.4, h: 0.34, fontFace: HEAD, fontSize: 15, bold: true, color: K.petrol });
      T(s, t, { x: 8.15, y: y + 0.55, w: 4.4, h: 0.82, fontSize: 12, color: K.ink });
    }
    s.addNotes('Решение простое: одна история пациента от приёма до приёма. Врач задаёт план, пациент дома отмечает самочувствие, анкеты и таблетки, перед следующим приёмом врач видит сводку и принимает решение. Три правила мы не нарушаем нигде: решает врач, у каждого факта есть источник, а неизвестное показано как неизвестное.');
  }

  // =====================================================================
  // 4. How it works
  {
    const s = slide('1. Идея', 'КАК ЭТО РАБОТАЕТ', 'Два кабинета на одной базе: дома у пациента и у врача');
    const rows = [
      { who: 'Пациент', icn: 'LuSmartphone', bg: K.amberL, acc: K.amber, txt: K.amberT, steps: [['Сегодня', 'Главное действие дня, текущий план и таблетки на сегодня'], ['Дневник', 'Самочувствие, жалобы, нежелательные явления. Черновик не теряется'], ['Анкеты', 'DASS-42, PHQ-9 или GAD-7 по предложению врача, квитанция об отправке'], ['Препараты и связь', 'Отметка каждого приёма, даже половины таблетки. Сообщения врачу']] },
      { who: 'Врач', icn: 'LuStethoscope', bg: K.mist, acc: K.teal, txt: K.teal, steps: [['Пациенты', '«Нужно проверить» с конкретной причиной и ссылкой на запись'], ['Карточка', 'Графики анкет, исходные ответы, история записей'], ['Сводка к приёму', 'Всё за выбранный период на одном экране'], ['План и решения', 'Назначения и курс действуют после подтверждения врача']] },
    ];
    for (const [ri, r] of rows.entries()) {
      const y = 1.85 + ri * 2.15;
      await iconDot(s, r.icn, MX, y + 0.45, 0.7, r.acc, K.white);
      T(s, r.who, { x: MX - 0.2, y: y + 1.2, w: 1.1, h: 0.3, fontFace: HEAD, fontSize: 13, bold: true, color: K.petrol, align: 'center' });
      r.steps.forEach(([h, t], i) => {
        const x = 1.75 + i * 2.78;
        box(s, x, y, 2.6, 1.85, r.bg);
        num(s, i + 1, x + 0.2, y + 0.22, 0.4, r.acc, K.white);
        T(s, h, { x: x + 0.72, y: y + 0.22, w: 1.8, h: 0.4, fontFace: HEAD, fontSize: 13, bold: true, color: K.petrol, valign: 'middle' });
        T(s, t, { x: x + 0.2, y: y + 0.78, w: 2.25, h: 1.0, fontSize: 13, color: K.ink });
      });
    }
    foot(s, 'Телефон и компьютер полноценны для обеих ролей: экраны проверены на ширине от 320 до 1440 пикселей.');
    s.addNotes('У пациента пять разделов, и на каждом экране одно главное действие. У врача путь короткий: список тех, кого нужно проверить, карточка с графиками, сводка к приёму и план. Всё это одна база, поэтому врач и пациент видят одну и ту же запись, каждый в своём объёме.');
  }

  // =====================================================================
  // 5. Prototype — doctor
  {
    const s = slide('2. Прототип', 'ПРОТОТИП · ВРАЧ', 'Врач сразу видит, кому нужно внимание');
    const shots = [
      ['doctor-patients.jpg', 'Пациенты', 'Список с причинами для проверки и последними отметками самочувствия'],
      ['doctor-followup.jpg', 'Сводка к приёму', 'Записи за выбранный период; у каждой автор, время и неизвестные поля'],
      ['doctor-plan.jpg', 'План и решения', 'Текущий план с подтверждением врача и недельный календарь препаратов'],
    ];
    // Lead screenshot large on the left, the other two stacked on the right with captions beside them.
    const bw = 7.0, bh = bw * 1125 / 1800;
    screen(s, shots[0][0], MX, 1.72, bw, bh);
    T(s, [{ text: shots[0][1] + '  ', options: { fontFace: HEAD, bold: true, color: K.petrol, fontSize: 15 } }, { text: shots[0][2], options: { fontSize: 12, color: K.ink } }], { x: MX, y: 1.72 + bh + 0.15, w: bw, h: 0.4, valign: 'middle' });
    shots.slice(1).forEach(([img, h, t], i) => {
      const x = 7.95, y = 1.72 + i * 2.32, w = 2.85, hh = w * 1125 / 1800;
      screen(s, img, x, y, w, hh);
      T(s, h, { x: x + 3.05, y, w: 1.75, h: 0.6, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol });
      T(s, t, { x: x + 3.05, y: y + 0.62, w: 1.75, h: 1.2, fontSize: 11, color: K.ink });
    });
    foot(s, 'Снимки работающего сервиса от 23.10.2026. Все пациенты, врачи и препараты в демонстрации вымышленные.');
    s.addNotes('Это работающий кабинет врача, не макет. Слева список пациентов: сверху те, у кого есть что проверить, и рядом конкретная причина, например пропуск в плане или записанное нежелательное явление. В центре сводка к приёму за выбранный период. Справа план и календарь приёма препаратов, где видно, в какой день пациент пропустил таблетку.');
  }

  // =====================================================================
  // 6. Prototype — patient phone
  {
    const s = slide('2. Прототип', 'ПРОТОТИП · ПАЦИЕНТ', 'Пациенту достаточно телефона');
    const pts = [
      ['LuTarget', 'Одно главное действие', 'На каждом экране сразу видно, что сделать сейчас, без прокрутки'],
      ['LuFileCheck', 'Запись дошла', 'Пациент видит время сохранения на сервере и квитанцию об анкете'],
      ['LuEye', 'Баллы видит врач', 'Пациент получает квитанцию, а суммы и графики анкет остаются у врача'],
    ];
    for (const [i, [icn, h, t]] of pts.entries()) {
      const y = 1.85 + i * 1.5;
      await iconDot(s, icn, MX, y, 0.56, K.amberL, K.amberT);
      T(s, h, { x: 1.35, y: y - 0.02, w: 2.6, h: 0.32, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol });
      T(s, t, { x: 1.35, y: y + 0.32, w: 2.6, h: 0.9, fontSize: 12, color: K.ink });
    }
    const ph = [['patient-today.jpg', 'Сегодня'], ['patient-diary.jpg', 'Дневник'], ['patient-forms.jpg', 'Анкеты'], ['patient-plan.jpg', 'План']];
    ph.forEach(([img, cap], i) => {
      const x = 4.25 + i * 2.15, w = 1.86;
      const hh = phone(s, img, x, 1.7, w);
      T(s, cap, { x, y: 1.7 + hh + 0.1, w: w + 0.16, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: K.petrol, align: 'center' });
    });
    s.addNotes('Пациент чаще всего работает с телефона. Поэтому главное действие видно сразу: отметить самочувствие или заполнить анкету, которую предложил врач. После отправки пациент видит, что запись сохранена на сервере. Баллы анкет пациенту не показываем: это материал для врача, а не самодиагностика.');
  }

  // =====================================================================
  // 7. Prototype — questionnaires
  {
    const s = slide('2. Прототип', 'ПРОТОТИП · АНКЕТЫ', 'Динамика анкет видна сразу, ответы под рукой');
    screen(s, 'doctor-charts.jpg', MX, 1.7, 12.13, 12.13 * 629 / 2000);
    const cards = [
      ['LuBadgeCheck', 'Точные русские версии', 'DASS-42 (Фаттахов, Горобец), PHQ-9 и GAD-7 (Золотарева, 2023). Текст, порядок и варианты ответов не меняются'],
      ['LuCircleDashed', 'Пропуск не равен нулю', 'Неполная анкета не даёт ложную точку на графике. Каждая версия шкалы в своей серии'],
      ['LuShieldCheck', 'Баллы не диагноз', 'Суммы видит только врач, а повтор анкеты врач предлагает в один щелчок'],
    ];
    for (const [i, [icn, h, t]] of cards.entries()) {
      const x = MX + i * 4.1, y = 5.82;
      await iconDot(s, icn, x, y - 0.02, 0.5, K.tealL, K.teal);
      T(s, h, { x: x + 0.65, y: y - 0.02, w: 3.3, h: 0.32, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol });
      T(s, t, { x: x + 0.65, y: y + 0.3, w: 3.3, h: 0.7, fontSize: 11, color: K.ink });
    }
    s.addNotes('Анкеты врач предлагает сам. В карточке три шкалы DASS-42 и отдельно PHQ-9 и GAD-7: последнее значение, график и изменение. Мы используем точные русские версии и ничего в них не меняем. Если анкета заполнена не полностью, точка на графике не появляется: пропуск не превращается в ноль.');
  }

  // =====================================================================
  // 8. Safety
  {
    const s = slide('2. Прототип', 'БЕЗОПАСНОСТЬ', 'Врач в центре каждого клинического решения');
    const cards = [
      ['LuUserCheck', 'Подтверждение врача', 'Назначение, изменение и отмена терапии, направление и новый план вступают в силу только после подтверждения на сервере'],
      ['LuKeyRound', 'Права и связи', 'Врач видит только своих пациентов. Сервер проверяет роль и связь при каждом запросе, даже прямом'],
      ['LuHistory', 'Журнал происхождения', 'У каждой записи автор, время и исходный текст. Исправление дополняет историю и ничего не стирает'],
      ['LuLock', 'Защита входа', 'Токены против подделки запросов, истечение сессий, одноразовые приглашения и отзыв доступа'],
      ['LuServer', 'Без внешних сервисов', 'Шрифты и скрипты свои, строгая политика безопасности страниц. Данные не уходят третьим лицам'],
      ['LuUsers', 'Только вымышленные данные', 'В демонстрации 8 придуманных пациентов и 3 врача. Реальные данные людей не вводятся'],
    ];
    for (const [i, [icn, h, t]] of cards.entries()) {
      const x = MX + (i % 3) * 4.1, y = 1.78 + Math.floor(i / 3) * 2.3;
      box(s, x, y, 3.93, 2.08, i === 0 ? K.amberL : K.mist);
      await iconDot(s, icn, x + 0.28, y + 0.28, 0.56, i === 0 ? K.amber : K.petrol, K.white);
      T(s, h, { x: x + 1.0, y: y + 0.28, w: 2.8, h: 0.56, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol, valign: 'middle' });
      T(s, t, { x: x + 0.28, y: y + 1.0, w: 3.45, h: 1.0, fontSize: 12, color: K.ink });
    }
    foot(s, 'Технологии прототипа: Python и Flask, SQLite, HTML, CSS и JavaScript без сторонних библиотек в браузере.');
    s.addNotes('Безопасность заложена в устройство сервиса. Пять видов клинических действий без подтверждения врача не срабатывают, причём проверка идёт на сервере, а не только в интерфейсе. Врач видит только своих пациентов. У каждой записи есть автор и время, исправления ничего не стирают. В демонстрации только вымышленные люди.');
  }

  // =====================================================================
  // 9. Metrics — big numbers
  {
    const s = slide('3. Испытания', 'ИСПЫТАНИЯ', 'Технически сервис готов к первым врачам');
    const big = [
      [String(M.slices_accepted), 'принятых этапа разработки, каждый с проверкой и отчётом'],
      [`${M.coverage_service_pct} %`, 'кода веб-сервиса покрыто автотестами'],
      [String(M.tests_total), 'автотестов, все проходят'],
      [`${M.latency_worst_median_ms} мс`, 'медианное время ответа самой тяжёлой страницы врача'],
    ];
    big.forEach(([n, t], i) => {
      const x = MX + i * 3.08;
      T(s, n, { x, y: 1.75, w: 2.95, h: 0.95, fontFace: HEAD, fontSize: 44, bold: true, color: i === 1 ? K.teal : K.petrol, valign: 'middle' });
      T(s, t, { x, y: 2.72, w: 2.7, h: 0.62, fontSize: 13, color: K.ink });
    });
    const cards = [
      ['LuRefreshCw', 'Надёжность', [`Перезапуск сервера без потери данных`, 'Резервная копия базы перед каждым изменением', 'Повторная отправка формы не создаёт дублей']],
      ['LuShieldCheck', 'Защита', [`${M.security_tests} проверок прав и защиты: чужой пациент, подделка запроса, истёкшая сессия, отозванное приглашение`, 'Клинические действия без врача отклоняются']],
      ['LuMonitorSmartphone', 'Удобство', [`${M.screenshots_reviewed} снимков экрана просмотрено при приёмке этапов`, 'Телефон от 320 px и компьютер 1440 px без горизонтальной прокрутки']],
    ];
    for (const [i, [icn, h, items]] of cards.entries()) {
      const x = MX + i * 4.1, y = 3.62;
      box(s, x, y, 3.93, 2.62, K.mist);
      await iconDot(s, icn, x + 0.28, y + 0.25, 0.52, K.petrol, K.white);
      T(s, h, { x: x + 0.95, y: y + 0.25, w: 2.8, h: 0.52, fontFace: HEAD, fontSize: 15, bold: true, color: K.petrol, valign: 'middle' });
      T(s, items.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < items.length - 1, paraSpaceAfter: 5 } })), { x: x + 0.28, y: y + 0.95, w: 3.5, h: 1.6, fontSize: 13, color: K.ink });
    }
    foot(s, `Замеры ${M.measured_on}: unittest и coverage ${M.coverage_tool}. ${M.coverage_service_pct} % — код веб-сервиса, по всему пакету вместе с отложенными модулями ${M.coverage_package_pct} %. Методика — в приложении.`);
    s.addNotes(`Теперь о том, как мы проверяли сервис. ${M.slices_accepted} этапа разработки, каждый принят с отчётом и проверкой. ${M.tests_total} автотестов, все проходят, и они покрывают ${M.coverage_service_pct} процентов кода веб-сервиса. Самая тяжёлая страница врача отвечает примерно за ${M.latency_worst_median_ms} миллисекунд. Отдельно мы проверяем перезапуск без потери данных, права доступа и работу на телефоне.`);
  }

  // =====================================================================
  // 10. Metrics — charts
  {
    const s = slide('3. Испытания', 'МЕТРИКИ', 'Страницы врача открываются за сотые доли секунды');
    const L = M.latency;
    const labels = L.map((r) => r.label);
    const axis = { catAxisLabelColor: K.slate, valAxisLabelColor: K.slate, catAxisLabelFontFace: '+mn-lt', valAxisLabelFontFace: '+mn-lt', catAxisLabelFontSize: 11, valAxisLabelFontSize: 10, valGridLine: { color: 'E3EAE8', size: 0.5 }, catGridLine: { style: 'none' }, dataLabelFontFace: '+mn-lt', dataLabelFontSize: 10, dataLabelColor: K.ink, titleFontFace: '+mj-lt', titleFontSize: 14, titleColor: K.petrol };
    s.addChart(pres.charts.BAR, [
      { name: 'Медиана, мс', labels, values: L.map((r) => r.median) },
      { name: '95 % запросов быстрее, мс', labels, values: L.map((r) => r.p95) },
    ], Object.assign({ x: MX, y: 1.7, w: 6.6, h: 4.45, barDir: 'bar', barGrouping: 'clustered', chartColors: [K.teal, K.sea], showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '0', showLegend: true, legendPos: 'b', legendFontFace: '+mn-lt', legendFontSize: 11, legendColor: K.ink, showTitle: true, title: 'Время ответа сервера, мс (40 запросов на страницу)', catAxisOrientation: 'maxMin', valAxisMaxVal: 60, barGapWidthPct: 60 }, axis));
    const C = M.coverage_modules;
    s.addChart(pres.charts.BAR, [{ name: 'Покрытие, %', labels: C.map((r) => r.label), values: C.map((r) => r.pct) }],
      Object.assign({ x: 7.45, y: 1.7, w: 5.28, h: 4.45, barDir: 'bar', chartColors: [K.petrol], showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '0"%"', showLegend: false, showTitle: true, title: 'Покрытие автотестами ключевых модулей, %', catAxisOrientation: 'maxMin', valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 25, barGapWidthPct: 55 }, axis));
    const d = M.dataset;
    const strip = [[d.patients, 'пациентов'], [d.doctors, 'врача'], [d.weeks, 'недель истории'], [d.self_reports, 'самоотчёта'], [d.questionnaires, 'анкеты'], [d.medication_marks, 'отметок о препаратах']];
    box(s, MX, 6.22, W - 2 * MX, 0.62, K.mist);
    T(s, 'ВЫМЫШЛЕННАЯ КЛИНИКА', { x: MX + 0.25, y: 6.22, w: 2.0, h: 0.62, fontSize: 9, bold: true, charSpacing: 1.5, color: K.teal, valign: 'middle' });
    strip.forEach(([n, t], i) => {
      const x = 3.0 + i * 1.6;
      T(s, [{ text: String(n) + ' ', options: { bold: true, fontFace: HEAD, fontSize: 16, color: K.petrol } }, { text: t, options: { fontSize: 11, color: K.ink } }], { x, y: 6.22, w: 1.56, h: 0.62, valign: 'middle' });
    });
    s.addNotes('Скорость и покрытие мы измерили, а не оценили на глаз. Слева время ответа сервера для пяти главных страниц врача: медиана от четырёх до шестнадцати миллисекунд. Справа покрытие тестами ключевых модулей: доступ, препараты, анкеты, сообщения. Всё это проверено на полной вымышленной клинике: восемь пациентов, три врача, шесть недель истории.');
  }

  // =====================================================================
  // 11. Roadmap
  {
    const s = slide('4. Планы', 'ДОРОЖНАЯ КАРТА', 'Двенадцать месяцев: от пилота до работы в клинике');
    const steps = [
      ['Ноябрь 2026', 'Go', ['Сервер переписан на Go', 'PostgreSQL, нагрузочные тесты'], 'LuCpu'],
      ['Декабрь 2026', 'Пилот с врачами', ['3–5 психиатров на тестовых историях', 'Замер удобства по шкале SUS'], 'LuStethoscope'],
      ['I кв. 2027', 'Тревожные признаки', ['Модуль раннего выявления', 'Правила проверяют клинические эксперты'], 'LuBellRing'],
      ['II кв. 2027', 'Клиника', ['Пилот с пациентами по согласию', 'Хостинг в РФ, 152-ФЗ'], 'LuHospital'],
      ['III кв. 2027', 'Регистрация', ['Документы для Росздравнадзора', 'Клиническая оценка'], 'LuLandmark'],
      ['IV кв. 2027', 'Интеграция', ['Подключение к медицинским информационным системам клиник'], 'LuLink'],
    ];
    const y0 = 2.35, step = 2.03;
    s.addShape(pres.shapes.LINE, { x: MX + 0.3, y: y0 + 0.17, w: step * 5, h: 0, line: { color: K.line, width: 2 } });
    for (const [i, [d, h, items, icn]] of steps.entries()) {
      const x = MX + i * step;
      s.addShape(pres.shapes.OVAL, { x: x + 0.17, y: y0, w: 0.34, h: 0.34, fill: { color: i === 2 ? K.amber : K.teal }, line: { color: K.white, width: 2 } });
      T(s, d, { x, y: 1.82, w: 1.9, h: 0.32, fontSize: 12, bold: true, color: i === 2 ? K.amberT : K.teal });
      box(s, x, 2.95, 1.9, 2.55, i === 2 ? K.amberL : K.mist);
      await iconDot(s, icn, x + 0.2, 3.15, 0.5, i === 2 ? K.amber : K.white, i === 2 ? K.white : K.teal);
      T(s, h, { x: x + 0.2, y: 3.75, w: 1.6, h: 0.62, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol });
      T(s, items.map((t, j) => ({ text: t, options: { breakLine: j < items.length - 1, paraSpaceAfter: 4 } })), { x: x + 0.2, y: 4.4, w: 1.62, h: 1.05, fontSize: 12, color: K.ink });
    }
    foot(s, 'Перенос на Go даёт один исполняемый файл, быструю параллельную обработку уведомлений и простое развёртывание в клинике.', 5.8);
    s.addNotes('Дальше двенадцать месяцев. В ноябре переносим сервер на Go и PostgreSQL. В декабре даём сервис трём-пяти психиатрам на тестовых историях и меряем удобство. В первом квартале добавляем модуль тревожных признаков, о нём следующий слайд. Затем пилот в клинике, документы для регистрации и подключение к медицинским системам.');
  }

  // =====================================================================
  // 12. Early warning module
  {
    const s = slide('4. Планы', 'СЛЕДУЮЩИЙ МОДУЛЬ', 'Тревожные признаки сразу попадают к врачу');
    const flow = [
      ['LuActivity', 'Сигналы', 'Ответы анкет, записи дневника, пропуски препаратов, сообщения пациента'],
      ['LuListChecks', 'Правила', 'Критерии из клинических рекомендаций и проверенных шкал, у каждого правила источник'],
      ['LuBellRing', 'Срочное уведомление', 'Врач сразу получает сигнал с причиной и исходной записью, при молчании — повтор'],
      ['LuClipboardList', 'Варианты действий', 'Сервис предлагает варианты лечения и дальнейших шагов со ссылками на рекомендации'],
      ['LuUserCheck', 'Решение врача', 'Врач выбирает и подтверждает, пациент видит только одобренный план'],
    ];
    for (const [i, [icn, h, t]] of flow.entries()) {
      const x = MX + i * 2.47, y = 1.85, last = i === flow.length - 1;
      box(s, x, y, 2.25, 2.95, last ? K.petrol : i === 2 ? K.amberL : K.mist);
      await iconDot(s, icn, x + 0.22, y + 0.25, 0.58, last ? K.amber : i === 2 ? K.amber : K.teal, K.white);
      T(s, h, { x: x + 0.22, y: y + 0.98, w: 1.9, h: 0.62, fontFace: HEAD, fontSize: 14, bold: true, color: last ? K.white : K.petrol });
      T(s, t, { x: x + 0.22, y: y + 1.6, w: 1.88, h: 1.3, fontSize: 11, color: last ? 'E4EFED' : K.ink });
      if (!last) s.addImage({ data: await ic('LuArrowRight', K.slate), x: x + 2.27, y: y + 1.3, w: 0.18, h: 0.18 });
    }
    box(s, MX, 5.1, 7.3, 1.3, K.white, { line: { color: K.line, width: 1 } });
    T(s, [{ text: 'Пример правила\n', options: { bold: true, color: K.amberT, fontSize: 11, charSpacing: 1 } }, { text: 'Положительный ответ на 9-й вопрос PHQ-9 — срочное уведомление врачу с исходным ответом пациента и вариантами дальнейших действий', options: { fontSize: 13, color: K.ink } }], { x: MX + 0.25, y: 5.18, w: 6.85, h: 1.15, valign: 'middle' });
    box(s, 8.15, 5.1, 4.58, 1.3, K.tealL);
    T(s, 'Основа уже в прототипе: исходные ответы, происхождение каждой записи, подтверждение врача и уведомления с повтором', { x: 8.4, y: 5.1, w: 4.15, h: 1.3, fontSize: 12, color: K.petrol, valign: 'middle' });
    s.addNotes('Следующий большой шаг — система, которая сама замечает тревожные признаки. Она смотрит на анкеты, дневник, пропуски таблеток и сообщения, проверяет их по правилам из клинических рекомендаций и сразу сообщает врачу о серьёзном ухудшении или критическом состоянии. Сервис предложит варианты лечения и дальнейших действий со ссылками на источники, а выбирает и подтверждает врач. Для этого у нас уже есть фундамент: исходные ответы, происхождение каждой записи и подтверждение врачом.');
  }

  // =====================================================================
  // 13. Implementation
  {
    const s = slide('4. Планы', 'ВНЕДРЕНИЕ', 'Что нужно, чтобы сервис заработал в клинике');
    const cols = [
      ['LuScale', 'Закон', ['152-ФЗ, ст. 10: данные о здоровье — особая категория, нужно письменное согласие пациента', '323-ФЗ, ст. 13: врачебная тайна', 'ПО для лечения может быть медизделием (323-ФЗ, ст. 38); регистрация в Росздравнадзоре по ПП РФ № 1684']],
      ['LuCpu', 'Технологии', ['Сервер на Go и PostgreSQL', 'Хостинг в России, резервные копии и мониторинг', 'Интеграция с медицинскими информационными системами']],
      ['LuHospital', 'Клиника', ['Пилот с психиатрами: время подготовки к приёму и удобство', 'Короткое обучение врача на тестовых историях', 'Согласие пациента на наблюдение в сервисе']],
    ];
    for (const [i, [icn, h, items]] of cols.entries()) {
      const x = MX + i * 4.1;
      box(s, x, 1.78, 3.93, 3.85, K.mist);
      await iconDot(s, icn, x + 0.28, 2.02, 0.56, K.petrol, K.white);
      T(s, h, { x: x + 1.0, y: 2.02, w: 2.7, h: 0.56, fontFace: HEAD, fontSize: 16, bold: true, color: K.petrol, valign: 'middle' });
      T(s, items.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < items.length - 1, paraSpaceAfter: 8 } })), { x: x + 0.28, y: 2.8, w: 3.45, h: 2.75, fontSize: 14, color: K.ink });
    }
    box(s, MX, 5.85, W - 2 * MX, 0.68, K.petrol);
    T(s, [{ text: 'Просим у организаторов и партнёров:  ', options: { bold: true, color: K.amberL } }, { text: 'площадку для пилота и клинических экспертов, которые проверят правила тревожных признаков', options: { color: K.white } }], { x: MX + 0.3, y: 5.85, w: W - 2 * MX - 0.6, h: 0.68, fontSize: 13, valign: 'middle' });
    s.addNotes('Чтобы сервис работал с настоящими пациентами, нужны три вещи. Закон: данные о здоровье — особая категория по 152-ФЗ, врачебная тайна по 323-ФЗ, а программа, влияющая на лечение, может потребовать регистрации как медицинское изделие. Технологии: Go, PostgreSQL, хостинг в России. И клиника для пилота. От организаторов и партнёров мы просим площадку для пилота и экспертов для проверки правил.');
  }

  // =====================================================================
  // 14. Team
  {
    const s = slide('5. Команда', 'КОМАНДА', 'Команда проекта');
    box(s, MX, 1.78, 4.6, 4.75, K.petrol);
    s.addShape(pres.shapes.OVAL, { x: MX + 0.35, y: 2.1, w: 1.15, h: 1.15, fill: { color: K.amber }, line: { color: K.amber, width: 0 } });
    T(s, 'АС', { x: MX + 0.35, y: 2.1, w: 1.15, h: 1.15, fontFace: HEAD, fontSize: 26, bold: true, color: K.white, align: 'center', valign: 'middle' });
    T(s, 'Сибгатуллин\nАзамат Ильдарович', { x: MX + 0.35, y: 3.45, w: 4.0, h: 0.85, fontFace: HEAD, fontSize: 18, bold: true, color: K.white });
    T(s, 'КАПИТАН · РАЗРАБОТЧИК', { x: MX + 0.35, y: 4.33, w: 4.0, h: 0.3, fontSize: 10, bold: true, charSpacing: 1.5, color: K.amberL });
    const me = ['Спроектировал и написал сервис: сервер, база данных, кабинеты врача и пациента', `${M.tests_total} автотестов и ${M.slices_accepted} принятых этапа разработки`];
    T(s, me.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < me.length - 1, paraSpaceAfter: 6 } })), { x: MX + 0.35, y: 4.75, w: 3.95, h: 1.6, fontSize: 12, color: 'E4EFED' });
    for (let i = 0; i < 4; i++) {
      const x = 5.45 + (i % 2) * 3.67, y = 1.78 + Math.floor(i / 2) * 2.43;
      box(s, x, y, 3.5, 2.3, K.mist);
      s.addShape(pres.shapes.OVAL, { x: x + 0.28, y: y + 0.3, w: 0.85, h: 0.85, fill: { color: K.tealL }, line: { color: K.tealL, width: 0 } });
      s.addImage({ data: await ic('LuUser', K.teal), x: x + 0.48, y: y + 0.5, w: 0.45, h: 0.45 });
      T(s, 'Фамилия\nИмя Отчество', { x: x + 1.3, y: y + 0.3, w: 2.1, h: 0.85, fontFace: HEAD, fontSize: 14, bold: true, color: K.petrol, valign: 'middle' });
      T(s, 'РОЛЬ В ПРОЕКТЕ', { x: x + 0.28, y: y + 1.35, w: 3.0, h: 0.28, fontSize: 10, bold: true, charSpacing: 1.5, color: K.teal });
      T(s, 'Чем занимается в команде', { x: x + 0.28, y: y + 1.65, w: 3.0, h: 0.5, fontSize: 12, color: K.slate });
    }
    s.addNotes('Наша команда — пять человек. Я отвечаю за разработку: спроектировал и написал сервер, базу и оба кабинета. (Представить остальных участников и их роли.)');
  }

  // =====================================================================
  // 15. Thanks + QR
  {
    const s = slide('5. Команда', 'БЛАГОДАРНОСТИ', 'Спасибо тем, кто помогал нам в работе');
    const th = [
      ['LuHandshake', 'Организаторам кейс-чемпионата', 'Авинейро и партнёрам за задачу, которая действительно нужна врачам'],
      ['LuGraduationCap', 'Сеченовскому университету', 'соорганизатору чемпионата'],
      ['LuMessageSquare', 'Кураторам и трекеру', 'за встречи, вопросы и обратную связь по ходу работы'],
      ['LuUsers', 'Экспертам и жюри', 'за внимание к проекту и будущие замечания'],
    ];
    for (const [i, [icn, h, t]] of th.entries()) {
      const y = 1.8 + i * 1.18;
      await iconDot(s, icn, MX, y, 0.62, K.tealL, K.teal);
      T(s, h, { x: 1.45, y: y - 0.02, w: 6.4, h: 0.34, fontFace: HEAD, fontSize: 16, bold: true, color: K.petrol });
      T(s, t, { x: 1.45, y: y + 0.33, w: 6.4, h: 0.5, fontSize: 13, color: K.ink });
    }
    box(s, 8.55, 1.78, 4.18, 4.75, K.mist);
    if (DEMO_URL) {
      const qr = await QRCode.toDataURL(DEMO_URL, { errorCorrectionLevel: 'M', margin: 4, width: 900, color: { dark: '#000000', light: '#FFFFFF' } });
      s.addImage({ data: qr.replace('data:', ''), x: 9.17, y: 2.0, w: 2.95, h: 2.95 });
      T(s, 'Демо-стенд сервиса', { x: 8.75, y: 5.08, w: 3.8, h: 0.34, fontFace: HEAD, fontSize: 15, bold: true, color: K.petrol, align: 'center' });
      T(s, DEMO_URL.replace(/^https?:\/\//, ''), { x: 8.75, y: 5.45, w: 3.8, h: 0.32, fontSize: 12, color: K.teal, align: 'center', hyperlink: { url: DEMO_URL } });
      T(s, 'вход для жюри по запросу', { x: 8.75, y: 5.8, w: 3.8, h: 0.3, fontSize: 11, color: K.slate, align: 'center' });
    } else {
      box(s, 9.17, 2.0, 2.95, 2.95, K.white, { line: { color: K.sea, width: 1.5, dashType: 'dash' } });
      s.addImage({ data: await ic('LuQrCode', K.sea), x: 10.15, y: 2.98, w: 1.0, h: 1.0 });
      T(s, 'QR-код демо-стенда', { x: 8.75, y: 5.08, w: 3.8, h: 0.34, fontFace: HEAD, fontSize: 15, bold: true, color: K.petrol, align: 'center' });
      T(s, 'появится после публикации стенда', { x: 8.75, y: 5.45, w: 3.8, h: 0.32, fontSize: 12, color: K.slate, align: 'center' });
    }
    s.addNotes('Спасибо организаторам чемпионата, компании Авинейро и партнёрам, Сеченовскому университету, нашим кураторам и трекеру. По QR-коду открывается демо-стенд сервиса.');
  }

  // =====================================================================
  // 16. Close
  {
    const s = pres.addSlide({ masterName: 'DARK', sectionTitle: 'Финал' });
    s.addImage({ data: markLight, x: MX, y: 0.7, w: 0.9, h: 0.9 });
    T(s, 'Клинический компас', { x: 1.7, y: 0.7, w: 6, h: 0.9, fontFace: HEAD, fontSize: 26, bold: true, color: K.white, valign: 'middle' });
    T(s, 'Врач за минуту видит, что изменилось у пациента между приёмами. Решение всегда остаётся за врачом.', { x: MX, y: 2.2, w: 10.5, h: 1.9, fontFace: HEAD, fontSize: 32, color: K.white });
    const sum = [[String(M.tests_total), 'автотестов'], [`${M.coverage_service_pct} %`, 'покрытие кода сервиса'], ['2', 'кабинета: врач и пациент'], ['3', 'проверенные анкеты']];
    sum.forEach(([n, t], i) => {
      const x = MX + i * 2.7;
      T(s, n, { x, y: 4.45, w: 2.5, h: 0.6, fontFace: HEAD, fontSize: 28, bold: true, color: K.amber });
      T(s, t, { x, y: 5.05, w: 2.5, h: 0.3, fontSize: 12, color: K.sea });
    });
    T(s, 'Спасибо! Готовы ответить на вопросы', { x: MX, y: 5.95, w: 9, h: 0.5, fontFace: HEAD, fontSize: 20, bold: true, color: K.amberL });
    T(s, 'Азамат Сибгатуллин и команда · кейс-чемпионат Авинейро · 2026', { x: MX, y: 6.85, w: 9, h: 0.3, fontSize: 10, color: K.sea });
    s.addNotes('Клинический компас: врач за минуту видит, что изменилось у пациента между приёмами, а решение всегда остаётся за врачом. Спасибо, готовы ответить на вопросы.');
  }

  // =====================================================================
  // 17. Appendix — methods
  {
    const s = slide('Приложение', 'ПРИЛОЖЕНИЕ · МЕТОДИКА', 'Как мы получили цифры');
    const rows = [['Показатель', 'Значение', 'Как измерено']].concat(M.method_rows);
    s.addTable(rows.map((r, i) => r.map((c) => ({ text: c, options: { bold: i === 0, color: i === 0 ? K.white : K.ink, fill: { color: i === 0 ? K.petrol : i % 2 ? K.white : K.mist } } }))), { x: MX, y: 1.75, w: W - 2 * MX, colW: [2.6, 1.6, 7.93], fontFace: BODY, fontSize: 11, border: { type: 'solid', color: K.line, pt: 0.5 }, margin: 0.06, valign: 'middle' });
    s.addNotes('Слайд для вопросов жюри о методике измерений.');
  }

  // =====================================================================
  // 18. Appendix — sources
  {
    const s = slide('Приложение', 'ПРИЛОЖЕНИЕ · ИСТОЧНИКИ', 'Источники цифр и норм');
    M.sources.forEach((t, j) => {
      T(s, String(j + 1), { x: MX, y: 1.75 + j * 0.56, w: 0.35, h: 0.5, fontFace: HEAD, fontSize: 13, bold: true, color: K.teal });
      T(s, t, { x: MX + 0.45, y: 1.75 + j * 0.56, w: W - 2 * MX - 0.45, h: 0.5, fontSize: 11, color: K.ink });
    });
    s.addNotes('Слайд для вопросов жюри об источниках.');
  }

  await pres.writeFile({ fileName: OUT });
  const PPTX_SKILL = process.env.PPTX_SKILL;
  if (PPTX_SKILL) {
    const { applyTheme } = require(path.join(PPTX_SKILL, 'scripts/apply_theme.js'));
    await applyTheme(OUT, THEME);
  }
  console.log('written', OUT);
})().catch((e) => { console.error(e); process.exit(1); });
