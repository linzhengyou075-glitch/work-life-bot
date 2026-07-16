(() => {
  const syncText = document.querySelector('[data-sync-time]');
  const updateSyncTime = () => {
    if (!syncText) return;
    const d = new Date();
    syncText.textContent = d.toLocaleTimeString('zh-TW', {hour:'2-digit', minute:'2-digit'});
  };
  updateSyncTime();

  document.querySelectorAll('[data-count]').forEach(el => {
    const target = Number(el.dataset.count || 0);
    const start = performance.now();
    const duration = 800;
    function tick(now){
      const p = Math.min((now-start)/duration,1);
      el.textContent = Math.round(target*p).toLocaleString('zh-TW');
      if(p<1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });

  let editing = false;
  document.querySelectorAll('input,textarea,select').forEach(el => {
    el.addEventListener('focus',()=>editing=true);
    el.addEventListener('blur',()=>editing=false);
  });

  async function refreshState(){
    try{
      const res = await fetch('/api/dashboard-state', {cache:'no-store'});
      if(!res.ok) return;
      const data = await res.json();
      document.querySelectorAll('[data-live="pending"]').forEach(el => el.textContent = data.counts.pending_tasks);
      document.querySelectorAll('[data-live="logs"]').forEach(el => el.textContent = data.counts.work_logs);
      document.querySelectorAll('[data-live="shortage"]').forEach(el => el.textContent = '$' + data.counts.shortage_total);
      updateSyncTime();
      const toast = document.querySelector('[data-sync-toast]');
      if(toast){toast.style.opacity='1';setTimeout(()=>toast.style.opacity='0',1200);}
    }catch(e){}
  }
  setInterval(() => { if(!editing) refreshState(); }, 15000);
})();


(() => {
  const carousel = document.querySelector('[data-carousel]');
  if (carousel) {
    const track = carousel.querySelector('.carousel-track');
    const slides = [...carousel.querySelectorAll('.carousel-slide')];
    const dots = [...carousel.querySelectorAll('.carousel-dots button')];
    let index = 0;
    let timer;

    const show = (next) => {
      index = (next + slides.length) % slides.length;
      track.style.transform = `translateX(-${index * 100}%)`;
      dots.forEach((dot, i) => dot.classList.toggle('is-active', i === index));
    };
    const start = () => {
      clearInterval(timer);
      timer = setInterval(() => show(index + 1), 5000);
    };
    dots.forEach((dot, i) => dot.addEventListener('click', () => { show(i); start(); }));

    let startX = 0;
    carousel.addEventListener('touchstart', e => startX = e.touches[0].clientX, {passive:true});
    carousel.addEventListener('touchend', e => {
      const dx = e.changedTouches[0].clientX - startX;
      if (Math.abs(dx) > 40) show(index + (dx < 0 ? 1 : -1));
      start();
    }, {passive:true});
    start();
  }

  const grid = document.querySelector('[data-calendar-grid]');
  if (!grid) return;

  const rawShifts = Array.isArray(window.__SHIFT_DATA__) ? window.__SHIFT_DATA__ : [];
  const shifts = new Map(rawShifts.map(s => [s.work_date, s]));
  const label = document.querySelector('[data-month-label]');
  const modal = document.querySelector('[data-shift-modal]');
  const dateInput = document.querySelector('[data-shift-date]');
  const batchToggle = document.querySelector('[data-batch-toggle]');
  const overtimeCheck = document.querySelector('[data-overtime-check]');
  const overtimeWrap = document.querySelector('[data-overtime-wrap]');
  let batch = false;
  let selectedDates = new Set();
  let view = new Date();
  view.setDate(1);

  const iso = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    const day = String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
  };

  function shiftChip(s){
    if(!s) return '';
    if(s.shift_type === 'off') return '<span class="shift-chip off">休假</span>';
    const store = s.store_code === 'B' ? '昌' : '洲';
    const time = s.shift_type === 'late' ? '15-23' : '23-07';
    const cls = s.shift_type === 'late' ? 'late' : (s.store_code === 'B' ? 'jc-night' : 'xz-night');
    return `<span class="shift-chip ${cls}">${store}${time}</span>`;
  }

  function render(){
    const y = view.getFullYear(), m = view.getMonth();
    label.textContent = `${y} 年 ${m+1} 月`;
    grid.innerHTML = '';
    const first = new Date(y,m,1);
    const start = new Date(y,m,1-first.getDay());
    const today = iso(new Date());

    for(let i=0;i<42;i++){
      const d = new Date(start); d.setDate(start.getDate()+i);
      const key = iso(d);
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'calendar-cell';
      if(d.getMonth() !== m) cell.classList.add('is-outside');
      if(key === today) cell.classList.add('is-today');
      if(selectedDates.has(key)) cell.classList.add('is-selected');
      cell.innerHTML = `<span class="calendar-daynum">${d.getDate()}</span>${shiftChip(shifts.get(key))}`;
      cell.addEventListener('click', () => {
        if(batch){
          selectedDates.has(key) ? selectedDates.delete(key) : selectedDates.add(key);
          render();
        } else {
          dateInput.value = key;
          modal.hidden = false;
        }
      });
      grid.appendChild(cell);
    }

    const monthShifts = rawShifts.filter(s => s.work_date.startsWith(`${y}-${String(m+1).padStart(2,'0')}`));
    const stats = document.querySelectorAll('.month-stats b');
    if(stats.length >= 4){
      stats[0].textContent = monthShifts.filter(s=>s.shift_type!=='off').length;
      stats[1].textContent = monthShifts.filter(s=>s.shift_type==='off').length;
      stats[2].textContent = monthShifts.filter(s=>s.store_code==='B').length;
      stats[3].textContent = monthShifts.filter(s=>s.store_code==='C').length;
    }
  }

  document.querySelector('[data-prev-month]')?.addEventListener('click',()=>{view.setMonth(view.getMonth()-1);render();});
  document.querySelector('[data-next-month]')?.addEventListener('click',()=>{view.setMonth(view.getMonth()+1);render();});
  document.querySelectorAll('[data-open-shift-modal]').forEach(b=>b.addEventListener('click',()=>{if(!dateInput.value) dateInput.value=iso(new Date());modal.hidden=false;}));
  document.querySelector('[data-close-shift-modal]')?.addEventListener('click',()=>modal.hidden=true);
  batchToggle?.addEventListener('click',()=>{batch=!batch;batchToggle.textContent=batch?'完成批次選取':'批次設定';if(!batch)selectedDates.clear();render();});
  overtimeCheck?.addEventListener('change',()=>{overtimeWrap.hidden=!overtimeCheck.checked;});
  render();
})();

(() => {
  const typeModal=document.querySelector('[data-type-modal]');
  document.querySelector('[data-open-type-modal]')?.addEventListener('click',()=>typeModal.hidden=false);
  document.querySelector('[data-close-type-modal]')?.addEventListener('click',()=>typeModal.hidden=true);
  const del=document.querySelector('[data-delete-date]');
  const date=document.querySelector('[data-shift-date]');
  date?.addEventListener('change',()=>{if(del)del.value=date.value;});
  document.querySelectorAll('[data-shift-id]').forEach(btn=>btn.addEventListener('click',()=>{
    const select=document.querySelector('[data-shift-select]');
    if(select)select.value=btn.dataset.shiftId;
    if(!date.value)date.value=new Date().toISOString().slice(0,10);
    if(del)del.value=date.value;
    document.querySelector('[data-shift-modal]').hidden=false;
  }));
})();


(() => {
  async function updateWeather(){
    const temp = document.querySelector('[data-weather-temp]');
    const rain = document.querySelector('[data-weather-rain]');
    if(!temp && !rain) return;
    try{
      const response = await fetch('/api/weather', {cache:'no-store'});
      if(!response.ok) return;
      const data = await response.json();
      const weather = data.weather || {};
      if(temp) temp.textContent = `${weather.temperature ?? '--'}°C`;
      if(rain) rain.textContent = `${weather.rain_probability ?? '--'}%`;
    }catch(e){}
  }
  updateWeather();
  setInterval(updateWeather, 10 * 60 * 1000);
})();
