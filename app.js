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
