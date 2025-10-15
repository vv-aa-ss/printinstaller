const qs = s => document.querySelector(s);
const tbody = qs('#tbody');
const search = qs('#search');
const summary = qs('#summary');
const splash = qs('#splash');
const bar = qs('#bar');

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
      <a class="btn install" href="#" data-ip="${p.ip||''}" data-host="${p.host||''}" data-model="${p.model||''}" data-desc="${p.desc||''}">Установить</a>
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
scan();
