// app-downloads.js — v8: строго по разметке .row + input.cb-prn / input.cb-scn
(function () {
  const L = (...a)=>{ try{ console.log('[downloads]', ...a); }catch{} };
  const W = (...a)=>{ try{ console.warn('[downloads]', ...a); }catch{} };
  const E = (...a)=>{ try{ console.error('[downloads]', ...a); }catch{} };

  function ready(fn){
    if(document.readyState==='complete'||document.readyState==='interactive') setTimeout(fn,0);
    else document.addEventListener('DOMContentLoaded',fn);
  }

  async function loadFilesDB(){
    const tried=[], tryFetch = async (p)=>{ tried.push(p); try{ const r=await fetch(p,{cache:'no-store'}); if(r.ok) return r.json(); }catch{} return null; };
    for (const p of ['files-db.json','./files-db.json','/files-db.json','/static/files-db.json']) {
      const d = await tryFetch(p); if (d) { L('files-db.json from', p); return d; }
    }
    E('Не удалось загрузить files-db.json'); alert('Не удалось загрузить files-db.json'); return {};
  }

  function getMapping(db, key){
    if (db[key]) return db[key];
    const up = key.toUpperCase();
    for (const k of Object.keys(db)) if (k.toUpperCase()===up) return db[k];
    // мягкое совпадение, если в data-model длинное имя типа "ECOSYS M2040dn"
    for (const k of Object.keys(db)) if (up.includes(k.toUpperCase()) || k.toUpperCase().includes(up)) return db[k];
    return null;
  }

  async function probe(url){
    try{ let r=await fetch(url,{method:'HEAD'}); if(r.ok) return true; r=await fetch(url,{method:'GET'}); return r.ok; }catch{ return false; }
  }

  ready(async function(){
    L('init v8');
    const filesDB = await loadFilesDB();

    document.addEventListener('click', async (ev)=>{
      const btn = ev.target.closest('a.btn.install, .btn.install, [data-action="install"], .btn-install');
      if (!btn) return;

      // Проверяем, есть ли система плагинов
      if (window.PluginSystem && window.PluginSystem.checkStatus) {
        // Если плагин установлен, не обрабатываем здесь - пусть app-plugin.js обработает
        return;
      }

      // отменяем переход по ссылке/submit
      if (btn.tagName === 'A') ev.preventDefault();
      const form = btn.closest('form'); if (form) { ev.preventDefault(); ev.stopPropagation(); }

      // 1) Ровно та строка, где клик
      const row = btn.closest('.row');
      if (!row) { alert('Не нашёл контейнер .row'); return; }
      L('row ok:', row);

      // 2) Чекбоксы в этой строке
      const cbPrn = row.querySelector('input.cb-prn');
      const cbScn = row.querySelector('input.cb-scn');
      L('checkboxes:', { cbPrn, cbScn });

      if (!cbPrn && !cbScn) {
        alert('Не нашёл чекбоксы в этой строке (ищу input.cb-prn и input.cb-scn).');
        return;
      }

      const printerChecked = cbPrn ? !!cbPrn.checked : false;
      const scannerChecked = cbScn ? !!cbScn.checked : false;
      L('states:', { printerChecked, scannerChecked });

      let variant = null;
      if (printerChecked && scannerChecked) variant = 'all';
      else if (printerChecked) variant = 'printer';
      else if (scannerChecked) variant = 'scanner';
      else { alert('Выберите хотя бы один компонент: принтер и/или сканер.'); return; }
      L('variant:', variant);

      // 3) Модель берём из data-model у кнопки ИЛИ у строки
      let modelKey = (btn.dataset && btn.dataset.model) || (row.dataset && row.dataset.model) || '';
      if (!modelKey) {
        alert('Нет data-model ни у кнопки, ни у строки .row — добавь data-model="M2040" при рендере.');
        return;
      }
      L('modelKey:', modelKey);

      const mapping = getMapping(filesDB, modelKey);
      if (!mapping || !mapping[variant]) { alert(`Нет файла для ${modelKey}/${variant} в files-db.json`); return; }
      const fileName = mapping[variant];

      // 4) Куда качать
      const bases = ['/publish/','publish/','./publish/']; // у тебя сейчас работает /publish из static/publish
      let finalUrl = null;
      for (const b of bases) {
        const u = b + encodeURIComponent(fileName);
        const ok = await probe(u);
        L('probe', u, '->', ok);
        if (ok) { finalUrl = u; break; }
      }
      if (!finalUrl) { finalUrl = '/publish/' + encodeURIComponent(fileName); }

      L('download:', { modelKey, variant, fileName, finalUrl });

      // 5) Старт
      try {
        const a = document.createElement('a');
        a.href = finalUrl; a.download = fileName;
        document.body.appendChild(a); a.click(); a.remove();
      } catch {
        window.location.assign(finalUrl);
      }
    });
  });
})();
