// Сборка презентации «Шаг вперёд» к предзащите и демо-дню.
// Запуск: NODE_PATH=<папка с pptxgenjs>/node_modules node deliverables/presentation/build_deck.cjs
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const HERE = __dirname;
const A = (f) => path.join(HERE, "assets", f);
const M = JSON.parse(fs.readFileSync(path.join(HERE, "metrics.json"), "utf8"));
const OUT = path.join(HERE, "shag-vpered-demo-day.pptx");

const THEME = {
  name: "Shag vpered",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "15191D", lt1: "FFFFFF", dk2: "0E2A24", lt2: "F3F6F5",
    accent1: "176B5B", accent2: "E7F2EE", accent3: "FFF0C2",
    accent4: "B8261B", accent5: "56616B", accent6: "D3DAE0",
    hlink: "176B5B", folHlink: "56616B",
  },
};
const HEX = {
  ink: "15191D", muted: "56616B", green: "176B5B", soft: "E7F2EE", ground: "F3F6F5",
  border: "D3DAE0", marker: "FFF0C2", flag: "B8261B", dark: "0E2A24", onDark: "A8C9BE",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13,33 × 7,5 дюйма
pres.title = "Шаг вперёд — предзащита и демо-день";
pres.author = "Команда «Шаг вперёд», Казанский ГМУ";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333, X0 = 0.6, CW = W - 2 * X0;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: HEX.dark },
  objects: [],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "FFFFFF" },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: X0, y: 0.82, w: CW, h: 1.0,
      fontFace: THEME.headFontFace, fontSize: 28, bold: true, color: C.text1, valign: "top", align: "left", margin: 0 },
      text: "" } },
    { text: { text: "Шаг вперёд · кейс-чемпионат «Клинический компас» 2026",
      options: { x: X0, y: 7.02, w: 8, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: W - X0 - 0.6, y: 7.02, w: 0.6, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
});

// ---------- помощники ----------
function label(slide, text) {
  const w = 0.42 + text.length * 0.095;
  slide.addText(text, {
    shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.16, x: X0, y: 0.38, w, h: 0.32,
    fill: { color: HEX.soft }, line: { color: HEX.soft }, color: HEX.green, bold: true,
    fontSize: 11, charSpacing: 1.5, align: "center", valign: "middle", margin: 0, objectName: "Метка раздела",
  });
}
function num(slide, n, x, y, d = 0.42, opts = {}) {
  slide.addText(String(n), {
    shape: pres.shapes.OVAL, x, y, w: d, h: d, fill: { color: opts.fill || HEX.green },
    line: { color: opts.line || "FFFFFF", width: opts.lineW || 1.5 }, color: opts.color || "FFFFFF",
    bold: true, fontSize: opts.size || 14, align: "center", valign: "middle", margin: 0,
    objectName: "Номер " + n,
  });
}
function shot(slide, file, x, y, w, h, name) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h, fill: { color: "FFFFFF" }, line: { color: HEX.border, width: 0.75 },
    shadow: { type: "outer", color: "000000", opacity: 0.14, blur: 14, offset: 3, angle: 90 },
    objectName: "Рамка " + name,
  });
  slide.addImage({ path: A(file), x, y, w, h, altText: name, objectName: name });
}
function phone(slide, file, x, y, w, name, dark) {
  const h = w * (822 / 390), p = 0.07;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: x - p, y: y - p, w: w + 2 * p, h: h + 2 * p, rectRadius: 0.22,
    fill: { color: dark ? "1E2328" : "1B1F23" }, line: { color: dark ? "3A4A45" : "1B1F23", width: 1 },
    shadow: { type: "outer", color: "000000", opacity: dark ? 0.45 : 0.22, blur: 18, offset: 4, angle: 90 },
    objectName: "Корпус телефона " + name,
  });
  slide.addImage({ path: A(file), x, y, w, h, altText: name, objectName: name });
  return h;
}
function note(slide, text, y = 6.62) {
  slide.addText(text, { x: X0, y, w: CW, h: 0.3, fontSize: 10, color: HEX.muted, margin: 0, isTextBox: true,
    objectName: "Сноска" });
}
const S = (title, section) => {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  return s;
};

// ---------- 0. Титул ----------
pres.addSection({ title: "Титул" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Титул" });
  s.addText("КЕЙС-ЧЕМПИОНАТ «КЛИНИЧЕСКИЙ КОМПАС» · 2026", {
    x: 0.7, y: 0.6, w: 6.5, h: 0.3, fontSize: 12, bold: true, charSpacing: 2, color: HEX.onDark, margin: 0, isTextBox: true,
  });
  s.addText("Шаг вперёд", {
    x: 0.7, y: 1.55, w: 5.4, h: 1.2, fontFace: THEME.headFontFace, fontSize: 60, bold: true, color: "FFFFFF",
    margin: 0, valign: "top", isTextBox: true, objectName: "Название",
  });
  s.addText("Психиатр и пациент между приёмами видят одну историю болезни. Решение всегда за врачом.", {
    x: 0.7, y: 2.95, w: 4.9, h: 1.3, fontSize: 20, color: "E3EEEA", margin: 0, valign: "top", isTextBox: true,
    paraSpaceAfter: 0,
  });
  s.addText([
    { text: "Капитан — Идиятуллин Ильназ Алмазович", options: { bold: true, color: "FFFFFF", breakLine: true } },
    { text: "ФГБОУ ВО «Казанский ГМУ» Минздрава России", options: { color: HEX.onDark, breakLine: true } },
    { text: "Педиатрический факультет · Казань, 2026", options: { color: HEX.onDark } },
  ], { x: 0.7, y: 5.55, w: 5.2, h: 1.0, fontSize: 14, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 3 });
  shot(s, "doctor-list.png", 6.75, 0.95, 5.95, 5.95 * 844 / 1360, "Кабинет врача: список пациентов");
  phone(s, "patient-today.png", 6.15, 2.3, 2.15, "Кабинет пациента: Сегодня", true);
  s.addNotes("Здравствуйте! Мы из Казанского медуниверситета, проект «Шаг вперёд». Это сервис, который связывает психиатра и пациента в те недели, когда они не видятся.");
}

// ---------- 1. Идея ----------
pres.addSection({ title: "1. Идея" });
{
  const s = S("Между приёмами проходят недели, и врач узнаёт о них по памяти пациента", "1. Идея");
  label(s, "1 · ИДЕЯ");
  // левая колонка — проблема
  s.addText("280 млн", { x: X0, y: 2.05, w: 5.2, h: 1.0, fontFace: THEME.headFontFace, fontSize: 60, bold: true,
    color: C.accent1, margin: 0, isTextBox: true, objectName: "Число ВОЗ" });
  s.addText("человек в мире живут с депрессией (ВОЗ, 2023). Лечение длится месяцами, а врач видит пациента раз в несколько недель.", {
    x: X0, y: 3.1, w: 5.0, h: 1.0, fontSize: 16, color: C.text1, margin: 0, valign: "top", isTextBox: true });
  s.addText([
    { text: "Что сейчас теряется", options: { bold: true, color: HEX.ink, breakLine: true } },
    { text: "сон, побочные эффекты и пропуски таблеток вспоминают задним числом", options: { bullet: true, breakLine: true } },
    { text: "анкеты остаются на бумаге, динамики не видно", options: { bullet: true, breakLine: true } },
    { text: "переписка в мессенджере не связана с планом лечения", options: { bullet: true } },
  ], { x: X0, y: 4.3, w: 5.2, h: 2.0, fontSize: 15, color: HEX.muted, margin: 0, valign: "top", isTextBox: true,
    paraSpaceAfter: 6 });
  // правая колонка — решение
  const rx = 6.75, rw = W - X0 - rx;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx, y: 2.05, w: rw, h: 4.35, rectRadius: 0.12,
    fill: { color: HEX.ground }, line: { color: HEX.ground }, objectName: "Фон решения" });
  s.addText("Наше решение", { x: rx + 0.35, y: 2.25, w: 4, h: 0.4, fontSize: 13, bold: true, charSpacing: 1,
    color: C.accent1, margin: 0, isTextBox: true });
  const steps = [
    ["Врач на приёме", "утверждает план и расписание препаратов"],
    ["Пациент дома", "отмечает самочувствие и каждый приём таблеток, заполняет PHQ-9, GAD-7, DASS-42"],
    ["Перед приёмом", "врач видит, что изменилось, и откуда взят каждый факт"],
    ["Решение", "принимает врач. Сервис ничего не назначает сам"],
  ];
  const sy = 2.85, step = 0.86;
  s.addShape(pres.shapes.LINE, { x: rx + 0.56, y: sy + 0.21, w: 0, h: step * 3, line: { color: "9FC4B9", width: 1.5 },
    objectName: "Линия пути" });
  steps.forEach(([a, b], i) => {
    const y = sy + i * step;
    num(s, i + 1, rx + 0.35, y, 0.42, { line: HEX.ground, lineW: 3 });
    s.addText([
      { text: a + " ", options: { bold: true, color: HEX.ink } },
      { text: b, options: { color: HEX.ink } },
    ], { x: rx + 1.0, y: y - 0.02, w: rw - 1.3, h: 0.75, fontSize: 15, margin: 0, valign: "top", isTextBox: true });
  });
  s.addNotes("Депрессией в мире живут около двухсот восьмидесяти миллионов человек. Лечение идёт месяцами, а врач видит пациента раз в несколько недель. Что было со сном, пил ли пациент таблетки, стало ли хуже после смены дозы — всё это врач узнаёт по памяти. Мы собрали эти недели в одну цепочку. Врач утверждает план, пациент дома отмечает самочувствие и таблетки и заполняет анкеты, а к следующему приёму врач видит, что изменилось. Решает всегда врач.");
}

// ---------- 2. Прототип: врач ----------
pres.addSection({ title: "2. Прототип" });
{
  const s = S("Врач за минуту видит, кому из пациентов нужно внимание и почему", "2. Прототип");
  label(s, "2 · ПРОТОТИП");
  const iw = 7.45, ih = iw * 844 / 1360, ix = X0, iy = 2.0;
  shot(s, "doctor-list.png", ix, iy, iw, ih, "Кабинет врача: пациенты с причинами проверки");
  const px = (sx) => ix + iw * (sx - 40) / 1360, py = (sy) => iy + ih * (sy - 116) / 844;
  num(s, 1, px(425) - 0.42, py(455) - 0.21, 0.38, { size: 13 });
  num(s, 2, px(1050) - 0.42, py(455) - 0.21, 0.38, { size: 13 });
  num(s, 3, px(290), py(528) - 0.19, 0.38, { size: 13 });
  const rx = 8.55, rw = W - X0 - rx;
  const items = [
    "Конкретная причина проверки и ссылка на запись, из которой она взялась",
    "Приём препаратов за неделю. Пропуск и «нет отметки» показаны по-разному",
    "Из строки сразу в приём, план или сообщение пациенту",
  ];
  items.forEach((t, i) => {
    const y = 2.1 + i * 1.3;
    num(s, i + 1, rx, y, 0.42);
    s.addText(t, { x: rx + 0.6, y: y - 0.03, w: rw - 0.6, h: 1.1, fontSize: 16, color: C.text1, margin: 0,
      valign: "top", isTextBox: true });
  });
  s.addText("Список отсортирован: сначала те, у кого есть что проверить. Цвет всегда продублирован словом.", {
    x: rx, y: 5.95, w: rw, h: 0.75, fontSize: 13, color: HEX.muted, margin: 0, valign: "top", isTextBox: true });
  note(s, "Все пациенты и истории на снимках вымышленные.", 6.68);
  s.addNotes("Это кабинет врача. Сверху пациенты, у которых есть что проверить, и рядом конкретная причина: пропущенный препарат, нежелательное явление. Каждая причина ведёт к записи, из которой она взялась. Пропуск и отсутствие отметки мы показываем по-разному, клинически это разные вещи.");
}

// ---------- 2. Прототип: пациент ----------
{
  const s = S("Пациенту хватает нескольких касаний, и он видит, что запись дошла", "2. Прототип");
  label(s, "2 · ПРОТОТИП");
  const pw = 2.2;
  phone(s, "patient-today.png", X0 + 0.07, 2.05, pw, "Кабинет пациента: Сегодня");
  phone(s, "patient-plan.png", X0 + 0.07 + pw + 0.45, 2.05, pw, "Кабинет пациента: ответ под пунктом плана");
  const rx = 6.35, rw = W - X0 - rx;
  const rows = [
    ["Одна главная кнопка", "на телефоне видна без прокрутки"],
    ["Календарь препаратов", "отметка каждого приёма, даже половины таблетки"],
    ["Ответ под пунктом плана", "врач видит его рядом с этим пунктом"],
    ["Анкеты PHQ-9, GAD-7, DASS-42", "в точных русских версиях; баллы видит только врач"],
    ["Черновик хранится на сервере", "повторное нажатие ничего не задвоит"],
  ];
  rows.forEach(([a, b], i) => {
    const y = 2.1 + i * 0.86;
    s.addShape(pres.shapes.OVAL, { x: rx, y: y + 0.09, w: 0.16, h: 0.16, fill: { color: HEX.green },
      line: { color: HEX.green }, objectName: "Маркер" });
    s.addText([
      { text: a, options: { bold: true, color: HEX.ink, breakLine: true } },
      { text: b, options: { color: HEX.muted } },
    ], { x: rx + 0.38, y, w: rw - 0.38, h: 0.75, fontSize: 16, margin: 0, valign: "top", isTextBox: true });
  });
  s.addText("Оба кабинета полноценно работают на телефоне и компьютере, без установки приложения", {
    x: rx, y: 6.4, w: rw, h: 0.35, fontSize: 13, italic: true, color: C.accent1, margin: 0, isTextBox: true });
  s.addNotes("Кабинет пациента сделан для человека, которому сейчас тяжело. Одна большая кнопка «Отметить самочувствие», календарь таблеток, ответ прямо под пунктом плана. Анкеты в точных русских версиях, баллы видит только врач. Всё работает в браузере телефона, ставить ничего не нужно.");
}

// ---------- 2. Чем отличаемся ----------
{
  const s = S("Чем мы отличаемся от бумажного дневника и переписки в мессенджере", "2. Прототип");
  label(s, "ЧЕМ МЫ ЛУЧШЕ");
  const rows = [
    ["Сведения между приёмами", "со слов пациента, задним числом", "каждый день, с автором и временем записи"],
    ["Откуда взялся факт", "не восстановить", "ссылка на исходную запись пациента или врача"],
    ["Пропуски и пробелы", "выглядят как «всё хорошо»", "пропуск, «нет отметки» и неизвестное видны отдельно"],
    ["Анкеты", "бумага, сумма в уме", "исходные ответы, суммы по шкалам, графики динамики"],
    ["Данные пациента", "в личной переписке", "только у лечащего врача, без внешних ИИ-сервисов и CDN"],
  ];
  const hdr = (t, ours) => ({ text: t, options: { bold: true, fontSize: 13, color: ours ? "FFFFFF" : HEX.muted,
    fill: { color: ours ? HEX.green : "FFFFFF" }, valign: "middle" } });
  const tbl = [[hdr(""), hdr("Как сейчас"), hdr("Шаг вперёд", true)]];
  rows.forEach(([a, b, c]) => tbl.push([
    { text: a, options: { bold: true, color: HEX.ink } },
    { text: b, options: { color: HEX.muted } },
    { text: c, options: { color: HEX.ink, bold: true, fill: { color: HEX.soft } } },
  ]));
  s.addTable(tbl, {
    x: X0, y: 2.05, w: CW, colW: [3.0, 3.9, CW - 6.9], rowH: [0.5, 0.78, 0.78, 0.78, 0.78, 0.78],
    fontSize: 16, fontFace: THEME.bodyFontFace, valign: "middle", margin: [0.06, 0.18, 0.06, 0.18],
    border: [{ type: "none" }, { type: "none" }, { pt: 0.75, color: HEX.border }, { type: "none" }],
    objectName: "Сравнение",
  });
  note(s, "Врач по-прежнему принимает все клинические решения: назначение, изменение терапии и плана проходят только после его подтверждения на сервере.", 6.55);
  s.addNotes("Чем мы отличаемся от бумажного дневника и переписки? У каждого факта есть автор и время, и можно открыть исходную запись. Пропуск виден как пропуск, а не как «всё хорошо». Анкеты сразу складываются в графики. И данные не уходят во внешние сервисы.");
}

// ---------- 3. Метрики ----------
pres.addSection({ title: "3. Испытания" });
{
  const s = S("Прототип проверен автотестами на каждом этапе разработки", "3. Испытания");
  label(s, "3 · ИСПЫТАНИЯ");
  const stats = [
    [String(M.tests.total), "автотестов в наборе"],
    [M.tests.pass_rate_text, M.tests.passed === M.tests.total ? "проходят, ни одного пропущенного" : `проходят (${M.tests.passed} из ${M.tests.total})`],
    M.coverage.percent == null ? ["8", "внешних библиотек на весь сервис"] : [M.coverage.text, "кода покрыто тестами"],
    [String(M.slices.accepted), "этапа разработки приняты после проверки"],
  ];
  const gw = (CW - 3 * 0.3) / 4;
  stats.forEach(([v, t], i) => {
    const x = X0 + i * (gw + 0.3);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.05, w: gw, h: 2.05, rectRadius: 0.1,
      fill: { color: i === 1 ? HEX.soft : HEX.ground }, line: { color: i === 1 ? HEX.soft : HEX.ground },
      objectName: "Плитка " + t });
    s.addText(v, { x: x + 0.25, y: 2.25, w: gw - 0.5, h: 1.0, fontFace: THEME.headFontFace, fontSize: 50,
      bold: true, color: C.accent1, margin: 0, valign: "middle", isTextBox: true });
    s.addText(t, { x: x + 0.25, y: 3.3, w: gw - 0.5, h: 0.7, fontSize: 15, color: C.text1, margin: 0,
      valign: "top", isTextBox: true });
  });
  s.addText("Что проверяют отдельно", { x: X0, y: 4.45, w: 6, h: 0.35, fontSize: 14, bold: true, color: HEX.ink,
    margin: 0, isTextBox: true });
  const checks = [
    "Доступ по ролям: врач не открывает чужих пациентов, пациент — чужие записи",
    "Защита форм от подделки запросов (CSRF) и безопасный повтор отправки",
    "Перезапуск сервера без потери данных",
    "Вёрстка обоих кабинетов в Chromium и WebKit, экраны от 390 до 1440 px",
  ];
  const cw2 = (CW - 0.4) / 2;
  checks.forEach((t, i) => {
    const x = X0 + (i % 2) * (cw2 + 0.4), y = 4.92 + Math.floor(i / 2) * 0.68;
    s.addText("✓", { x, y, w: 0.3, h: 0.3, fontSize: 15, bold: true, color: HEX.green, margin: 0, isTextBox: true });
    s.addText(t, { x: x + 0.35, y, w: cw2 - 0.35, h: 0.6, fontSize: 15, color: C.text1, margin: 0, valign: "top",
      isTextBox: true });
  });
  note(s, M.footnote, 6.48);
  s.addNotes(`Теперь про испытания. В проекте ${M.tests.total} автотестов, проходят ${M.tests.pass_rate_speech}. ${M.coverage.percent == null ? "Внешних библиотек всего восемь, данные никуда не уходят. " : `Тестами покрыто ${M.coverage.speech} кода. `}Разработка шла ${M.slices.accepted} этапами, и каждый принимали только после проверки. Отдельно проверены доступ по ролям, защита форм и безопасный повтор отправки.`);
}

// ---------- 4. Дальше: тревожные признаки ----------
pres.addSection({ title: "4. Планы" });
{
  const s = S("Следующий шаг: сервис сам замечает тревожные признаки и зовёт врача", "4. Планы");
  label(s, "4 · ДАЛЬШЕ");
  const nodes = [
    ["Данные", "анкеты, дневник, анамнез, записи приёма"],
    ["Проверка", "проверяемые правила и языковая модель"],
    ["Сигнал врачу", "опасные сочетания и ухудшение — только лечащему врачу"],
    ["Предложение", "гипотеза диагноза с альтернативами, проект плана и лечения"],
    ["Решение врача", "без его подтверждения ничего не применяется"],
  ];
  const gap = 0.32, nw = (CW - 4 * gap) / 5, ny = 2.15, nh = 2.05;
  nodes.forEach(([a, b], i) => {
    const x = X0 + i * (nw + gap), last = i === nodes.length - 1;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: ny, w: nw, h: nh, rectRadius: 0.1,
      fill: { color: last ? HEX.green : HEX.ground }, line: { color: last ? HEX.green : HEX.ground },
      objectName: "Узел " + a });
    num(s, i + 1, x + 0.2, ny + 0.2, 0.38, last ? { fill: "FFFFFF", color: HEX.green, line: HEX.green, size: 13 } : { size: 13, line: HEX.ground });
    s.addText([
      { text: a, options: { bold: true, fontSize: 16, color: last ? "FFFFFF" : HEX.ink, breakLine: true } },
      { text: b, options: { fontSize: 13, color: last ? "E3EEEA" : HEX.muted } },
    ], { x: x + 0.2, y: ny + 0.72, w: nw - 0.4, h: nh - 0.85, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 4 });
    if (!last) s.addText("→", { x: x + nw, y: ny + nh / 2 - 0.2, w: gap, h: 0.4, fontSize: 18, bold: true,
      color: HEX.green, align: "center", valign: "middle", margin: 0, isTextBox: true });
  });
  // готовность серверной части
  const by = 4.65, done = M.alerts.done, total = M.alerts.total;
  s.addText([
    { text: `Серверная часть: ${done} из ${total} этапов приняты`, options: { bold: true, color: HEX.ink } },
  ], { x: X0, y: by, w: 7, h: 0.35, fontSize: 16, margin: 0, isTextBox: true });
  const bw = CW, bh = 0.18, bY = by + 0.48;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: bY, w: bw, h: bh, rectRadius: 0.09,
    fill: { color: HEX.border }, line: { color: HEX.border }, objectName: "Шкала готовности" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: bY, w: bw * done / total, h: bh, rectRadius: 0.09,
    fill: { color: HEX.green }, line: { color: HEX.green }, objectName: "Готово" });
  const cw2 = (CW - 0.4) / 2;
  s.addText([
    { text: "Готово", options: { bold: true, color: HEX.green, breakLine: true } },
    { text: "правила риска, гипотезы с основаниями и противоречиями, проверка лекарственных ограничений, доставка сигнала врачу", options: { color: HEX.ink } },
  ], { x: X0, y: bY + 0.4, w: cw2, h: 1.1, fontSize: 14, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 2 });
  s.addText([
    { text: "Осталось", options: { bold: true, color: HEX.muted, breakLine: true } },
    { text: "замер скорости и устойчивости, сквозная приёмка, проверка врачами-экспертами, вывод в кабинет врача", options: { color: HEX.ink } },
  ], { x: X0 + cw2 + 0.4, y: bY + 0.4, w: cw2, h: 1.1, fontSize: 14, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 2 });
  s.addNotes(`Дальше — то, ради чего мы собирали эти данные. Сервис будет сам замечать тревожные признаки в анкетах, дневнике и записях приёма и сразу сообщать лечащему врачу. Он предложит гипотезу диагноза с альтернативами и проект лечения. Применится это только после решения врача. Серверная часть уже прошла ${done} этапов из ${total}.`);
}

// ---------- 4. Дорожная карта ----------
{
  const s = S("За год доводим модуль, переходим на Go и выходим в пилот", "4. Планы");
  label(s, "4 · ВНЕДРЕНИЕ");
  const q = [
    ["IV кв. 2026", "Модуль тревожных признаков", "скорость, сквозная приёмка, вывод в кабинет врача"],
    ["I кв. 2027", "Перенос сервера на Go", "быстрее ответ, один исполняемый файл, проще установка в клинике"],
    ["II кв. 2027", "Пилот у психиатров", "время подготовки к приёму, доля заполненных анкет, оценка удобства врачами"],
    ["III–IV кв. 2027", "Регистрация медизделия", "клинические испытания; ПО с ИИ — класс риска\u00A03 по\u00A0ПП\u00A0РФ\u00A0№\u00A01684"],
  ];
  const gap = 0.3, qw = (CW - 3 * gap) / 4, ly = 2.3;
  s.addShape(pres.shapes.LINE, { x: X0 + 0.2, y: ly, w: CW - 0.4, h: 0, line: { color: "9FC4B9", width: 1.5 },
    objectName: "Линия времени" });
  q.forEach(([when, what, how], i) => {
    const x = X0 + i * (qw + gap);
    num(s, i + 1, x, ly - 0.21, 0.42, { line: "FFFFFF", lineW: 3 });
    s.addText(when, { x, y: 2.85, w: qw, h: 0.35, fontSize: 14, bold: true, color: C.accent1, margin: 0, isTextBox: true });
    s.addText(what, { x, y: 3.22, w: qw, h: 0.75, fontFace: THEME.headFontFace, fontSize: 19, bold: true,
      color: HEX.ink, margin: 0, valign: "top", isTextBox: true });
    s.addText(how, { x, y: 4.0, w: qw - 0.1, h: 1.2, fontSize: 14, color: HEX.muted, margin: 0, valign: "top", isTextBox: true });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: 5.4, w: CW, h: 1.05, rectRadius: 0.1,
    fill: { color: HEX.ground }, line: { color: HEX.ground }, objectName: "Условия внедрения" });
  const half = (CW - 0.9) / 2;
  s.addText([
    { text: "Данные пациента", options: { bold: true, color: HEX.ink, breakLine: true } },
    { text: "152-ФЗ и 323-ФЗ: согласие, хранение в России, врачебная тайна", options: { color: HEX.muted } },
  ], { x: X0 + 0.3, y: 5.55, w: half, h: 0.8, fontSize: 14, margin: 0, valign: "top", isTextBox: true });
  s.addText([
    { text: "Что нам нужно", options: { bold: true, color: HEX.ink, breakLine: true } },
    { text: "клиническая база для пилота и психиатры-эксперты для приёмки модуля", options: { color: HEX.muted } },
  ], { x: X0 + 0.6 + half, y: 5.55, w: half, h: 0.8, fontSize: 14, margin: 0, valign: "top", isTextBox: true });
  s.addNotes("План на год. До конца года доводим модуль тревожных признаков. В начале двадцать седьмого переносим сервер на Go, весной выходим в пилот к психиатрам. Параллельно готовим регистрацию как медицинского изделия и работу с данными по 152-ФЗ. Нам нужны клиническая база и эксперты.");
}

// ---------- 5. Команда ----------
pres.addSection({ title: "5. Команда" });
{
  const s = S("Четыре медика и разработчик", "5. Команда");
  label(s, "5 · КОМАНДА");
  const team = [
    ["Идиятуллин", "Ильназ Алмазович", "медицина", true],
    ["Сибагатуллин", "Азамат Ильдарович", "разработка"],
    ["Галицкий", "Марк Игоревич", "медицина"],
    ["Мурадисинов", "Мурадисин Идрисович", "медицина"],
    ["Гайнатуллин", "Ильназ Рамилевич", "медицина"],
  ];
  const gap = 0.28, cw = (CW - 4 * gap) / 5, d = 1.85;
  team.forEach(([last, first, role, cap], i) => {
    const x = X0 + i * (cw + gap), cx = x + (cw - d) / 2;
    s.addText("фото", { shape: pres.shapes.OVAL, x: cx, y: 2.0, w: d, h: d, fill: { color: HEX.ground },
      line: { color: HEX.border, width: 1 }, fontSize: 11, color: "9AA5AE", align: "center", valign: "middle",
      margin: 0, objectName: "Фото — " + last });
    if (cap) s.addText("капитан", { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.13, x: cx + d / 2 - 0.55,
      y: 2.0 + d - 0.18, w: 1.1, h: 0.3, fill: { color: HEX.marker }, line: { color: "FFFFFF", width: 1.5 },
      fontSize: 11, bold: true, color: HEX.ink, align: "center", valign: "middle", margin: 0, objectName: "Капитан" });
    s.addText([
      { text: last, options: { bold: true, fontSize: 17, color: HEX.ink, breakLine: true } },
      { text: first, options: { fontSize: 14, color: HEX.ink, breakLine: true } },
      { text: role, options: { fontSize: 13, color: HEX.green } },
    ], { x, y: 4.1, w: cw, h: 1.05, align: "center", margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 2 });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X0, y: 5.45, w: CW, h: 1.05, rectRadius: 0.1,
    fill: { color: HEX.soft }, line: { color: HEX.soft }, objectName: "Благодарности" });
  s.addText([
    { text: "Спасибо ", options: { bold: true, color: HEX.green } },
    { text: "организаторам чемпионата — НМИЦ ПН имени В. П. Сербского и Сеченовскому Университету, партнёру «Авинейро», нашим трекерам и экспертам, а также Казанскому ГМУ.", options: { color: HEX.ink } },
  ], { x: X0 + 0.3, y: 5.55, w: CW - 0.6, h: 0.85, fontSize: 15, margin: 0, valign: "middle", isTextBox: true });
  s.addNotes("Нас пятеро: четыре медика и разработчик. Спасибо организаторам, трекерам и экспертам чемпионата.");
}

// ---------- Финал ----------
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "5. Команда" });
  s.addText("Шаг вперёд", { x: 0.7, y: 1.4, w: 6.4, h: 1.0, fontFace: THEME.headFontFace, fontSize: 48, bold: true,
    color: "FFFFFF", margin: 0, isTextBox: true });
  s.addText("Врач видит, что изменилось между приёмами. Решение остаётся за ним.", {
    x: 0.7, y: 2.55, w: 5.8, h: 1.0, fontSize: 20, color: "E3EEEA", margin: 0, valign: "top", isTextBox: true });
  s.addText("Спасибо! Готовы ответить на вопросы", { x: 0.7, y: 5.4, w: 6.2, h: 0.5, fontSize: 22, bold: true,
    color: HEX.onDark, margin: 0, isTextBox: true });
  const qd = 2.6, gap = 0.45, qx = W - 0.7 - 2 * qd - gap, qy = 1.55;
  [["Код на GitHub", "QR GitHub"], ["Демонстрация", "QR демо"]].forEach(([cap, ph], i) => {
    const x = qx + i * (qd + gap);
    s.addText(ph, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.12, x, y: qy, w: qd, h: qd,
      fill: { color: "FFFFFF" }, line: { color: "FFFFFF" }, fontSize: 12, color: "9AA5AE", align: "center",
      valign: "middle", margin: 0, objectName: ph });
    s.addText(cap, { x, y: qy + qd + 0.18, w: qd, h: 0.35, fontSize: 15, bold: true, color: "FFFFFF",
      align: "center", margin: 0, isTextBox: true });
  });
  s.addNotes("По QR-кодам — код и живая демонстрация. Спасибо! Готовы ответить на вопросы.");
}

// ---------- Приложение ----------
pres.addSection({ title: "Приложение" });
{
  const s = S("Приложение: как измеряли и откуда цифры", "Приложение");
  label(s, "ПРИЛОЖЕНИЕ");
  s.addText(M.appendix.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < M.appendix.length - 1 } })), {
    x: X0, y: 2.05, w: CW, h: 4.4, fontSize: 14, color: HEX.ink, margin: 0, valign: "top", isTextBox: true,
    paraSpaceAfter: 8,
  });
  s.addNotes("Слайд для вопросов жюри, не рассказывается.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");
  await applyTheme(OUT, THEME);
  console.log(OUT);
})();
