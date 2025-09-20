const qs = s => document.querySelector(s);
const root = document.documentElement;
const tbody = qs('#tbody');
const search = qs('#search');
const summary = qs('#summary');
const splash = qs('#splash');
const bar = qs('#bar');

let DATA = [];

function rowTpl(p) {
  const dotClass = p.online ? 'ok' : 'warn';
  const tip = p.online ? 'Найден в сети' : 'Не найден в текущем сканировании';
  const dl = `/dl/installer?ip=${encodeURIComponent(p.ip||'')}&host=${encodeURIComponent(p.host||'')}&model=${encodeURIComponent(p.model||'')}`;
  return `<div class="row" data-blob="${[p.ip,p.host,p.model,p.desc].join(' ').toLowerCase()}">
    <div class="col status"><span class="badge" title="${tip}"><span class="dot ${dotClass}"></span> ${p.online ? 'Онлайн' : 'Оффлайн'}</span></div>
    <div class="col ip">${p.ip||''}</div>
    <div class="col host">${p.host||''}</div>
    <div class="col model">${p.model||''}</div>
    <div class="col desc">${p.desc||''}</div>
    <div class="col action">
      <a class="btn install" href="${dl}" download>⬇ Скачать установщик</a>
    </div>
  </div>`;
}

function render(list){
  tbody.innerHTML = list.map(rowTpl).join('');
  summary.textContent = `Сохранённых принтеров: ${list.length}`;
}

function filter(){
  const q = search.value.trim().toLowerCase();
  if (!q) return render(DATA);
  render(DATA.filter(p => (`${p.ip} ${p.host} ${p.model} ${p.desc}`).toLowerCase().includes(q)));
}

async function scan(){
  splash.classList.add('visible');
  let progress = 0;
  const t = setInterval(()=>{
    progress = Math.min(98, progress + Math.random()*10);
    bar.style.width = progress + '%';
  }, 200);
  try{
    const r = await fetch('/api/scan?_=' + Date.now());
    const j = await r.json();
    DATA = j.items || [];
    render(DATA);
  } catch(e){
    alert('Не удалось выполнить сканирование: ' + e);
  } finally {
    clearInterval(t);
    bar.style.width = '100%';
    setTimeout(()=>{ splash.classList.remove('visible'); bar.style.width = '0%'; }, 300);
  }
}

function toggleTheme(){ root.classList.toggle('dark'); }
qs('#rescan').addEventListener('click', scan);
qs('#theme').addEventListener('click', toggleTheme);
search.addEventListener('input', filter);

// ——— Подсказка «Откройте установщик в загрузках» ———
const coach = document.getElementById('download-hint');
let coachTimer = null;
function showDownloadHint(ms=6000){
  if(!coach) return;
  coach.classList.remove('hidden');
  if(coachTimer){ clearTimeout(coachTimer); }
  coachTimer = setTimeout(()=> coach.classList.add('hidden'), ms);
}
// Показываем подсказку при клике на кнопку скачивания
tbody.addEventListener('click', (e)=>{
  const a = e.target.closest('a.btn.install');
  if(!a) return;
  showDownloadHint();
});

scan();
