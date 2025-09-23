const qs = s => document.querySelector(s);
const tbody = qs('#tbody');
const search = qs('#search');
const summary = qs('#summary');
const splash = qs('#splash');
const bar = qs('#bar');
const coach = qs('#coach');

let DATA = [];

/* Рендер одной строки */

function rowTpl(p) {
  const dotClass = p.online ? 'ok' : 'warn';
  const tip = p.online ? 'Найден в сети' : 'Не найден в текущем сканировании';
  const canScan = !!p.can_scan;
  return `
  <div class="row" data-blob="${[p.ip,p.model,p.desc].join(' ').toLowerCase()}">
    <div class="col status">
      <span class="badge" title="${tip}">
        <span class="dot ${dotClass}"></span>
        ${p.online ? 'Онлайн' : 'Оффлайн'}
      </span>
    </div>
    <div class="col ip">${p.ip||''}</div>
    <div class="col model">${p.model||''}</div>
    <div class="col desc">${p.desc||''}</div>
    <div class="col funcs">
      <label class="chk"><input type="checkbox" class="cb-prn" checked> <span>Принтер</span></label>
      <label class="chk"><input type="checkbox" class="cb-scn" ${canScan ? 'checked' : ''} ${canScan ? '' : 'disabled'}> <span>Сканер</span></label>
    </div>
    <div class="col action">
      <a class="btn install" href="#" data-ip="${p.ip||''}" data-host="${p.host||''}" data-model="${p.model||''}">⬇ Установить</a>
    </div>
  </div>`;
}
/* Плавный вход (сверху вниз) — расставляем задержки по индексу */
function render(list){
  tbody.innerHTML = list.map(rowTpl).join('');
  const rows = Array.from(tbody.querySelectorAll('.row'));
  rows.forEach((r, i) => {
    r.style.setProperty('--i', i); // для delay
  });
  summary.textContent = `Сохранённых принтеров: ${list.length}`;
}

/* Фильтр */
search.addEventListener('input', e=>{
  const q = e.target.value.trim().toLowerCase();
  const rows = Array.from(tbody.querySelectorAll('.row'));
  rows.forEach(r=>{
    const match = r.dataset.blob.includes(q);
    r.style.display = match ? '' : 'none';
  });
});

/* Примитивная имитация сканирования: прогресс-бар */
qs('#rescan')?.addEventListener('click', async ()=>{
  bar.style.width = '0%';
  splash.classList.remove('hidden');
  for (let i=0;i<=100;i+=7){
    await new Promise(r=>setTimeout(r, 40));
    bar.style.width = i+'%';
  }
  splash.classList.add('hidden');
  // заново отрисуем текущие (или перезапросим — тут просто переотрисую для эффекта)
  render(DATA);
});

/* Подсказка: красиво выстреливает снизу вверх */
let coachTimer=null;
function showDownloadHint(ms=12000){
  if(!coach) return;
  coach.classList.remove('hidden');
  // перезапуск анимации: снимем и вернём класс reveal
  coach.classList.remove('reveal');
  // force reflow
  void coach.offsetHeight;
  coach.classList.add('reveal');

  if(coachTimer){ clearTimeout(coachTimer); }
  coachTimer = setTimeout(()=>{
    coach.classList.remove('reveal');
  }, ms);
}
// Показываем подсказку при клике на «Установить»
tbody.addEventListener('click', (e)=>{
  const a = e.target.closest('a.btn.install');
  if(!a) return;
  showDownloadHint();
});

/* Слежение за мышью — для блика на кнопке */
document.addEventListener('pointermove', e=>{
  if(!(e.target instanceof Element)) return;
  const btn = e.target.closest('.btn');
  if(!btn) return;
  const rect = btn.getBoundingClientRect();
  btn.style.setProperty('--mx', (e.clientX - rect.left) + 'px');
  btn.style.setProperty('--my', (e.clientY - rect.top) + 'px');
});

/* ==== ИНИЦИАЛИЗАЦИЯ / ДАННЫЕ ==== */

async function scan() {
  try {
    // показать "прогресс"
    splash.classList.remove('hidden');
    bar.style.width = '0%';

    // фальш-движение прогресса, чтобы UI был «живой»
    let prog = 0;
    const tick = setInterval(() => {
      prog = Math.min(95, prog + 7);
      bar.style.width = prog + '%';
    }, 40);

    const res = await fetch('/api/scan', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { items } = await res.json();

    DATA = Array.isArray(items) ? items : [];
    render(DATA);

    // добиваем прогресс
    bar.style.width = '100%';
    clearInterval(tick);
  } catch (e) {
    console.error('Scan error:', e);
    summary.textContent = 'Ошибка сканирования — проверьте доступность сервера.';
  } finally {
    setTimeout(() => splash.classList.add('hidden'), 250);
  }
}
// === Прицел в фиксированную точку вьюпорта (независимо от монитора) ===
const wrap   = document.querySelector('.wrap');
const coachB = document.querySelector('#coach .bubble');

function aimCoachAtViewportCorner(corner = 'top-right', { offsetX = 24, offsetY = 24 } = {}) {
  if (!wrap || !coachB) return;

  const root     = document.documentElement;
  const wrapRect = wrap.getBoundingClientRect();
  const bubRect  = coachB.getBoundingClientRect();

  // 1) целевая точка в координатах экрана (правый верх с отступами)
  let tX = corner.includes('right') ? window.innerWidth  - offsetX : offsetX;
  let tY = corner.includes('bottom')? window.innerHeight - offsetY : offsetY;

  // 2) конверт в координаты контейнера .wrap
  tX -= wrapRect.left;
  tY -= wrapRect.top;

  // 3) точка старта — из «пузыря» подсказки
  const sX = (bubRect.left + bubRect.width * 0.25) - wrapRect.left; // левее центра — естественнее
  const sY = (bubRect.bottom) - wrapRect.top;

  // 4) вектор, длина и угол
  const dx = tX - sX;
  const dy = tY - sY;
  const len = Math.max(140, Math.min(520, Math.hypot(dx, dy) - 20));
  const angleDeg   = Math.atan2(dy, dx) * 180 / Math.PI;
  const tunedAngle = angleDeg - 8; // слегка «вверх»

  // 5) подстановка в CSS-переменные (которые уже используются в styles.css)
  root.style.setProperty('--coach-len',     `${Math.round(len)}px`);
  root.style.setProperty('--coach-rot',     `${tunedAngle.toFixed(5)}deg`);
  root.style.setProperty('--coach-shift-x', `${Math.round(sX - 10)}px`);     // старт из-под пузыря
  root.style.setProperty('--coach-shift-y', `${Math.round(sY - 440)}px`);    // чуть ниже
}

// наведение при первом показе подсказки
function showDownloadHintFixed() {
  aimCoachAtViewportCorner('top-right', { offsetX: 32, offsetY: 28 }); // ← подстрой тут отступы
  showDownloadHint(); // твоя существующая функция анимации
}

// пере-наведение при ресайзе окна
window.addEventListener('resize', () => {
  aimCoachAtViewportCorner('top-right', { offsetX: 32, offsetY: 28 });
});

// если хочешь — подменить вызов в обработчике клика на кнопку «Установить»:
tbody.addEventListener('click', (e)=>{
  const a = e.target.closest('a.btn.install');
  if(!a) return;
  showDownloadHintFixed();
});

scan();



/* === Coach straight (fixed top-right) === */
function ensureCoachFixed(){
  if(!coach) return;
  coach.classList.add('coach-fixed');
}
function showCoachStraight(){
  ensureCoachFixed();
  coach.classList.remove('hidden');
  // restart reveal transition
  coach.classList.remove('reveal'); void coach.offsetWidth; coach.classList.add('reveal');
  // auto-hide after 12s
  clearTimeout(window.__coachHideT);
  window.__coachHideT = setTimeout(()=>{ coach.classList.add('hidden'); coach.classList.remove('reveal'); }, 12000);
}

// Подсказка должна появляться после клика по "Установить"
document.addEventListener('click', (e)=>{
  const a = e.target.closest && e.target.closest('a.btn.install');
  if(a){ showCoachStraight(); }
});


/* Быстрая подстройка положения стрелки через CSS‑переменные */
function setCoachOffsets(topPx, rightPx){
  const r = document.documentElement;
  if(typeof topPx === 'number')  r.style.setProperty('--coach-top', topPx+'px');
  if(typeof rightPx === 'number') r.style.setProperty('--coach-right', rightPx+'px');
}
