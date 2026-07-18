
document.addEventListener("DOMContentLoaded",()=>{
 const car=document.querySelector("[data-carousel]");
 if(car){const track=car.querySelector(".wl-track"),dots=[...car.querySelectorAll(".wl-dots button")];let i=0;setInterval(()=>{i=(i+1)%dots.length;track.style.transform=`translateX(-${i*100}%)`;dots.forEach((d,n)=>d.classList.toggle("active",n===i))},5000)}
 const grid=document.querySelector("[data-calendar]");
 if(grid){const shifts=new Map((window.SHIFTS||[]).map(x=>[x.work_date,x]));let view=new Date();view.setDate(1);const label=document.querySelector("[data-month]"),modal=document.querySelector("[data-modal]"),dateInput=document.querySelector("[data-date]"),del=document.querySelector("[data-delete-date]"),select=document.querySelector("[data-shift-select]");
  const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  function render(){grid.innerHTML="";const y=view.getFullYear(),m=view.getMonth(),first=new Date(y,m,1),start=new Date(y,m,1-first.getDay());label.textContent=`${y} 年 ${m+1} 月`;for(let n=0;n<42;n++){const d=new Date(start);d.setDate(start.getDate()+n);const key=iso(d),s=shifts.get(key),b=document.createElement("button");b.className="day"+(d.getMonth()!=m?" out":"")+(key===iso(new Date())?" today":"");b.innerHTML=`<b>${d.getDate()}</b>${s?`<span class="chip">${s.icon||""} ${s.shift_name}</span>${s.overtime?`<span class="chip ot">加班至 ${s.overtime_end}</span>`:""}`:""}`;b.onclick=()=>{dateInput.value=key;del.value=key;if(s&&s.shift_type_id)select.value=s.shift_type_id;modal.hidden=false};grid.appendChild(b)}}
  document.querySelector("[data-prev]").onclick=()=>{view.setMonth(view.getMonth()-1);render()};document.querySelector("[data-next]").onclick=()=>{view.setMonth(view.getMonth()+1);render()};document.querySelector("[data-open-modal]").onclick=()=>{dateInput.value=iso(new Date());del.value=dateInput.value;modal.hidden=false};document.querySelector("[data-close]").onclick=()=>modal.hidden=true;document.querySelectorAll("[data-shift]").forEach(b=>b.onclick=()=>{select.value=b.dataset.shift;if(!dateInput.value)dateInput.value=iso(new Date());del.value=dateInput.value;modal.hidden=false});const ot=document.querySelector("[data-overtime]"),wrap=document.querySelector("[data-overtime-time]");ot.onchange=()=>wrap.hidden=!ot.checked;render()}
 setInterval(async()=>{if(!document.querySelector(".wl-carousel"))return;try{await fetch("/api/dashboard-state",{cache:"no-store"})}catch(e){}},15000)
});


document.addEventListener("DOMContentLoaded",()=>{
 const modal=document.querySelector("[data-logistics-modal]");
 if(!modal)return;
 const fields={
  id:modal.querySelector("[data-lg-id]"),name:modal.querySelector("[data-lg-name]"),
  icon:modal.querySelector("[data-lg-icon]"),start:modal.querySelector("[data-lg-start]"),
  end:modal.querySelector("[data-lg-end]"),content:modal.querySelector("[data-lg-content]"),
  b:modal.querySelector("[data-lg-b]"),c:modal.querySelector("[data-lg-c]"),
  late:modal.querySelector("[data-lg-late]"),night:modal.querySelector("[data-lg-night]"),
  min:modal.querySelector("[data-lg-min]"),line:modal.querySelector("[data-lg-line]"),
  car:modal.querySelector("[data-lg-car]"),active:modal.querySelector("[data-lg-active]")
 };
 const reset=()=>{fields.id.value="";fields.name.value="";fields.icon.value="🚚";fields.start.value="";fields.end.value="";fields.content.value="";fields.b.checked=true;fields.c.checked=true;fields.late.checked=false;fields.night.checked=false;fields.min.value=10;fields.line.checked=true;fields.car.checked=true;fields.active.checked=true};
 document.querySelector("[data-open-logistics]")?.addEventListener("click",()=>{reset();modal.hidden=false});
 document.querySelector("[data-close-logistics]")?.addEventListener("click",()=>modal.hidden=true);
 document.querySelectorAll("[data-edit-logistics]").forEach(btn=>btn.addEventListener("click",()=>{
   const item=JSON.parse(btn.dataset.item);
   fields.id.value=item.id;fields.name.value=item.name;fields.icon.value=item.icon;
   fields.start.value=item.start_time;fields.end.value=item.end_time;fields.content.value=item.content||"";
   fields.b.checked=!!item.applies_b;fields.c.checked=!!item.applies_c;
   fields.late.checked=!!item.applies_late;fields.night.checked=!!item.applies_night;
   fields.min.value=item.remind_minutes;fields.line.checked=!!item.line_push;
   fields.car.checked=!!item.show_carousel;fields.active.checked=!!item.is_active;
   modal.hidden=false;
 }));
});

// Phase 1：Rainbow Life 首頁輪播與「當天才顯示」動態
 document.addEventListener("DOMContentLoaded",()=>{
  document.body.classList.add("is-today-active");
  const hero=document.querySelector("[data-home-carousel]");
  if(!hero)return;
  const track=hero.querySelector(".rainbow-hero-track");
  const dots=[...hero.querySelectorAll(".rainbow-hero-dots button")];
  let index=0,timer;
  const show=n=>{index=n;track.style.transform=`translateX(-${n*100}%)`;dots.forEach((d,i)=>d.classList.toggle("active",i===n))};
  const start=()=>{clearInterval(timer);timer=setInterval(()=>show((index+1)%dots.length),5200)};
  dots.forEach((dot,i)=>dot.addEventListener("click",()=>{show(i);start()}));
  hero.addEventListener("mouseenter",()=>clearInterval(timer));
  hero.addEventListener("mouseleave",start);
  start();
 });


// Phase 3：智慧生活輪播與首頁即時同步
 document.addEventListener("DOMContentLoaded",()=>{
  const panel=document.querySelector("[data-smart-life]");
  if(!panel)return;
  const track=panel.querySelector("[data-smart-track]");
  const cards=[...track.children];
  const dotsWrap=panel.querySelector("[data-smart-dots]");
  let index=0,timer;
  cards.forEach((_,i)=>{const b=document.createElement("button");b.type="button";b.setAttribute("aria-label",`第 ${i+1} 張`);b.onclick=()=>{show(i);restart()};dotsWrap.appendChild(b)});
  const dots=[...dotsWrap.children];
  const show=i=>{index=(i+cards.length)%cards.length;track.style.transform=`translateX(-${index*100}%)`;dots.forEach((d,n)=>d.classList.toggle("active",n===index))};
  const restart=()=>{clearInterval(timer);timer=setInterval(()=>show(index+1),4600)};
  show(0);restart();
  panel.addEventListener("mouseenter",()=>clearInterval(timer));
  panel.addEventListener("mouseleave",restart);
  let startX=0;
  panel.addEventListener("touchstart",e=>startX=e.touches[0].clientX,{passive:true});
  panel.addEventListener("touchend",e=>{const dx=e.changedTouches[0].clientX-startX;if(Math.abs(dx)>45){show(index+(dx<0?1:-1));restart()}},{passive:true});

  const text=(sel,value)=>{const el=panel.querySelector(sel);if(el&&value!==undefined&&value!==null)el.textContent=value};
  const sync=async()=>{
   try{
    const r=await fetch("/api/dashboard-state",{cache:"no-store"});
    if(!r.ok)return;
    const d=await r.json(); if(!d.ok)return;
    const shift=d.shift,counts=d.counts||{};
    text("[data-smart-shift-title]",shift?`${shift.shift_name}・${shift.store_name||"今日工作地點"}`:"今天沒有排班");
    text("[data-smart-shift-text]",shift?`上班 ${shift.start_time}，目前完成 ${counts.work_done||0}/${counts.work_total||0} 項工作。`:"可以安排生活待辦，或先把接下來的班表補齊。");
    text("[data-smart-reminder-title]",d.reminder?d.reminder.title:"目前沒有急迫提醒");
    text("[data-smart-reminder-text]",d.reminder?`${d.reminder.remind_time}${d.reminder.note?`・${d.reminder.note}`:""}`:"今天可以照自己的步調慢慢完成。");
    text("[data-smart-updated]",`最後同步 ${d.updated_at}`);
   }catch(_){ text("[data-smart-updated]","連線不穩，保留目前資料"); }
  };
  sync();setInterval(sync,15000);
 });


// Phase 4：縮小版首頁輪播＋官方資訊同步
 document.addEventListener("DOMContentLoaded",()=>{
  const box=document.querySelector("[data-compact-carousel]"); if(!box)return;
  const track=box.querySelector("[data-compact-track]"), slides=[...track.children], dotsBox=box.querySelector("[data-compact-dots]");
  let index=0,timer;
  slides.forEach((_,i)=>{const b=document.createElement("button");b.type="button";b.onclick=()=>go(i,true);dotsBox.appendChild(b)});
  const dots=[...dotsBox.children];
  const go=(i,restart=false)=>{index=(i+slides.length)%slides.length;slides[index].scrollIntoView({behavior:"smooth",block:"nearest",inline:"start"});dots.forEach((d,n)=>d.classList.toggle("active",n===index));if(restart)start()};
  const start=()=>{clearInterval(timer);timer=setInterval(()=>go(index+1),5200)};
  box.querySelector(".prev")?.addEventListener("click",()=>go(index-1,true));box.querySelector(".next")?.addEventListener("click",()=>go(index+1,true));
  track.addEventListener("scroll",()=>{const w=slides[0]?.offsetWidth||1;const n=Math.round(track.scrollLeft/(w+16));if(n!==index&&n<slides.length){index=n;dots.forEach((d,j)=>d.classList.toggle("active",j===index))}},{passive:true});
  go(0);start();
  const sync=async()=>{try{const r=await fetch("/api/dashboard-state",{cache:"no-store"});if(!r.ok)return;const d=await r.json();if(!d.ok)return;
    const w=d.weather||{};const we=box.querySelector("[data-mini-weather]");if(we)we.textContent=`${w.temperature??"--"}°C・${w.text||"天氣資訊"}`;
    const rt=box.querySelector("[data-mini-reminder]"),rp=box.querySelector("[data-mini-reminder-text]");if(rt)rt.textContent=d.reminder?.title||"目前沒有急迫提醒";if(rp)rp.textContent=d.reminder?`${d.reminder.remind_time}${d.reminder.note?`・${d.reminder.note}`:""}`:"今天可以照自己的步調慢慢完成。";
    (d.official_info||[]).forEach(x=>{const el=box.querySelector(`[data-official-title="${x.kind}"]`);if(el)el.textContent=x.title});
    const u=box.querySelector("[data-compact-updated]");if(u)u.textContent=`最後更新：${d.updated_at}`;
  }catch(_){const u=box.querySelector("[data-compact-updated]");if(u)u.textContent="官方資料稍後重試"}};
  sync();setInterval(sync,15000);
 });

// Phase 5 Step 1：今日班別智慧卡即時倒數與同步
 document.addEventListener("DOMContentLoaded",()=>{
  const card=document.querySelector("[data-smart-shift-card]"); if(!card)return;
  const q=s=>card.querySelector(s), pad=n=>String(n).padStart(2,"0");
  const parseShiftDate=(dateValue,timeValue,base=new Date())=>{if(!timeValue||!/^[0-2]\d:[0-5]\d$/.test(timeValue))return null;const [h,m]=timeValue.split(":").map(Number);if(dateValue&&/^\d{4}-\d{2}-\d{2}$/.test(dateValue)){const [y,mo,d]=dateValue.split("-").map(Number);return new Date(y,mo-1,d,h,m,0,0)}const result=new Date(base);result.setHours(h,m,0,0);return result};
  const updateCountdown=()=>{
   const start=card.dataset.shiftStart,end=card.dataset.shiftEnd,startDate=card.dataset.shiftStartDate,endDate=card.dataset.shiftEndDate,now=new Date();
   if(!start||!end){q("[data-countdown-label]").textContent="今日狀態";q("[data-shift-countdown]").textContent="自由安排";return}
   let startAt=parseShiftDate(startDate,start,now),endAt=parseShiftDate(endDate,end,now);if(!startAt||!endAt)return;
   if(!endDate&&endAt<=startAt)endAt.setDate(endAt.getDate()+1);
   if(!startDate&&now<startAt && (startAt-now)>12*3600000)startAt.setDate(startAt.getDate()-1);
   if(now<startAt){q("[data-countdown-label]").textContent="距離上班";endAt=startAt}
   else if(now>=endAt){q("[data-countdown-label]").textContent="今日班別";q("[data-shift-countdown]").textContent="已下班";return}
   else q("[data-countdown-label]").textContent="距離下班";
   const total=Math.max(0,Math.floor((endAt-now)/1000)),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;
   q("[data-shift-countdown]").textContent=`${pad(h)}:${pad(m)}:${pad(s)}`;
  };
  const setText=(sel,val)=>{const el=q(sel);if(el&&val!==undefined&&val!==null)el.textContent=val};
  const applyTheme=name=>{card.classList.remove("is-morning","is-evening","is-night","is-off");const n=name||"";card.classList.add(!n?"is-off":n.includes("大夜")?"is-night":n.includes("晚")?"is-evening":"is-morning");setText("[data-shift-icon]",!n?"🫧":n.includes("大夜")?"🌙":n.includes("晚")?"🌆":"☀️")};
  const sync=async()=>{try{const r=await fetch("/api/dashboard-state",{cache:"no-store"});if(!r.ok)return;const d=await r.json();if(!d.ok)return;const s=d.shift,c=d.counts||{},logs=d.daily_logistics||[];
    if(s){const end=s.overtime?s.overtime_end:s.end_time;card.dataset.shiftStart=s.start_time||"";card.dataset.shiftEnd=end||"";card.dataset.shiftStartDate=s.start_date||"";card.dataset.shiftEndDate=s.end_date||"";setText("[data-shift-store]",`🏪 ${s.store_name||"今日店舖"}`);setText("[data-shift-name]",s.shift_name||"今日班別");setText("[data-shift-start-text]",s.start_display||s.start_time||"--:--");setText("[data-shift-end-text]",s.end_display||end||"--:--");applyTheme(s.shift_name)}else{card.dataset.shiftStart="";card.dataset.shiftEnd="";card.dataset.shiftStartDate="";card.dataset.shiftEndDate="";setText("[data-shift-store]","🌈 Rainbow Life");setText("[data-shift-name]","今天沒有排班");setText("[data-shift-start-text]","--:--");setText("[data-shift-end-text]","--:--");applyTheme("")}
    const done=Number(c.work_done||0),total=Number(c.work_total||0),pct=total?Math.round(done/total*100):0;setText("[data-shift-logistics]",logs.length);setText("[data-shift-progress-text]",`${done}/${total}`);const bar=q("[data-shift-progress]");if(bar)bar.style.setProperty("--shift-progress",`${pct}%`);updateCountdown();
   }catch(_){}}
  updateCountdown();setInterval(updateCountdown,1000);setInterval(sync,15000);
 });

// Phase 5 Step 2：官方天氣智慧卡（每 15 分鐘更新）
document.addEventListener("DOMContentLoaded",()=>{
 const card=document.querySelector("[data-smart-weather-card]"); if(!card)return;
 const q=s=>card.querySelector(s);
 const set=(s,v)=>{const el=q(s);if(el&&v!==undefined&&v!==null)el.textContent=v};
 const weatherTip=w=>{
  const rain=Number(w.rain),temp=Number(w.temperature),wind=Number(w.wind);
  if(Number.isFinite(rain)&&rain>=50)return "外出記得攜帶雨具。";
  if(Number.isFinite(temp)&&temp>=30)return "天氣偏熱，記得補充水分。";
  if(Number.isFinite(wind)&&wind>=25)return "風勢較強，外出請留意安全。";
  if(Number.isFinite(temp)&&temp<=18)return "早晚偏涼，建議帶件薄外套。";
  return "出門前再確認即時天氣。";
 };
 const apply=w=>{
  if(!w)return;
  set("[data-weather-icon]",w.icon||"🌤️");set("[data-weather-temperature]",`${w.temperature??"--"}°`);
  set("[data-weather-text]",w.text||"天氣資訊");set("[data-weather-apparent]",w.apparent==="--"?"--":`${w.apparent}°`);
  set("[data-weather-rain]",w.rain==="--"?"--":`${w.rain}%`);set("[data-weather-wind]",w.wind==="--"?"--":`${w.wind} km/h`);
  set("[data-weather-source]",w.source||"天氣服務");set("[data-weather-tip]",weatherTip(w));
  set("[data-weather-updated]",`更新 ${new Date().toLocaleTimeString("zh-TW",{hour:"2-digit",minute:"2-digit"})}`);
 };
 const sync=async()=>{try{const r=await fetch("/api/dashboard-state",{cache:"no-store"});if(!r.ok)throw new Error();const d=await r.json();if(d.ok)apply(d.weather)}catch(_){set("[data-weather-updated]","連線不穩，保留上次資料")}};
 sync();setInterval(sync,15*60*1000);
});


// Phase 5 Step 3：全家官方活動智慧卡（每 30 分鐘更新）
document.addEventListener("DOMContentLoaded",()=>{
 const card=document.querySelector("[data-family-smart-card]"); if(!card)return;
 const q=s=>card.querySelector(s), set=(s,v)=>{const el=q(s);if(el&&v!==undefined&&v!==null)el.textContent=v};
 let items=[],index=0,rotateTimer,progressTimer,progress=0;
 const show=i=>{
  if(!items.length)return;
  index=(i+items.length)%items.length;const item=items[index];
  set("[data-family-category]",item.category||"全家官方");set("[data-family-title]",item.title||"查看全家官方最新活動");
  set("[data-family-period]",item.period||"詳見官方活動頁");set("[data-family-counter]",`${index+1} / ${items.length}`);
  const link=q("[data-family-link]");if(link)link.href=item.url||"https://www.family.com.tw/Marketing/zh/Event";
  progress=0;const bar=q("[data-family-progress]");if(bar)bar.style.width="0%";
 };
 const startRotation=()=>{
  clearInterval(rotateTimer);clearInterval(progressTimer);progress=0;
  rotateTimer=setInterval(()=>show(index+1),7000);
  progressTimer=setInterval(()=>{progress=(progress+2)%102;const bar=q("[data-family-progress]");if(bar)bar.style.width=`${Math.min(progress,100)}%`},140);
 };
 q("[data-family-prev]")?.addEventListener("click",()=>{show(index-1);startRotation()});
 q("[data-family-next]")?.addEventListener("click",()=>{show(index+1);startRotation()});
 const sync=async()=>{try{
   const r=await fetch("/api/dashboard-state",{cache:"no-store"});if(!r.ok)throw new Error();const d=await r.json();
   if(d.ok&&Array.isArray(d.official_info)&&d.official_info.length){items=d.official_info;show(Math.min(index,items.length-1));set("[data-family-updated]",`更新 ${new Date().toLocaleTimeString("zh-TW",{hour:"2-digit",minute:"2-digit"})}`);startRotation()}
  }catch(_){set("[data-family-updated]","連線不穩，保留上次活動")}};
 sync();setInterval(sync,30*60*1000);
});


// 全站統一訊息彈跳視窗
(function(){
  function ensurePopup(){
    let root=document.querySelector('[data-global-popup]');
    if(root) return root;
    root=document.createElement('div');
    root.className='global-popup';
    root.setAttribute('data-global-popup','');
    root.hidden=true;
    root.innerHTML=`<div class="global-popup-backdrop" data-popup-close></div><section class="global-popup-box" role="dialog" aria-modal="true" aria-live="assertive"><div class="global-popup-icon" data-popup-icon>✓</div><h2 data-popup-title>系統訊息</h2><p data-popup-message></p><div class="global-popup-actions"><button type="button" class="wl-btn full" data-popup-ok>確定</button><button type="button" class="wl-btn danger full" data-popup-cancel hidden>取消</button></div></section>`;
    document.body.appendChild(root);
    root.querySelectorAll('[data-popup-close],[data-popup-ok]').forEach(el=>el.addEventListener('click',()=>{root.hidden=true;document.body.classList.remove('popup-open')}));
    return root;
  }
  window.showWorkLifePopup=function(message,type='success',title=''){
    const root=ensurePopup();
    const icon=root.querySelector('[data-popup-icon]');
    const titleEl=root.querySelector('[data-popup-title]');
    const msg=root.querySelector('[data-popup-message]');
    root.className=`global-popup ${type}`;
    icon.textContent=type==='error'?'!':type==='warning'?'?':'✓';
    titleEl.textContent=title || (type==='error'?'操作失敗':type==='warning'?'請確認':'操作完成');
    msg.textContent=String(message||'操作已完成。').trim();
    root.querySelector('[data-popup-cancel]').hidden=true;
    root.querySelector('[data-popup-ok]').onclick=()=>{root.hidden=true;document.body.classList.remove('popup-open')};
    root.hidden=false;document.body.classList.add('popup-open');
  };
  window.confirmWorkLifePopup=function(message,onConfirm,title='請確認'){
    const root=ensurePopup();
    root.className='global-popup warning';
    root.querySelector('[data-popup-icon]').textContent='?';
    root.querySelector('[data-popup-title]').textContent=title;
    root.querySelector('[data-popup-message]').textContent=message;
    const ok=root.querySelector('[data-popup-ok]'),cancel=root.querySelector('[data-popup-cancel]');
    cancel.hidden=false;root.hidden=false;document.body.classList.add('popup-open');
    ok.onclick=()=>{root.hidden=true;document.body.classList.remove('popup-open');cancel.hidden=true;onConfirm()};
    cancel.onclick=()=>{root.hidden=true;document.body.classList.remove('popup-open');cancel.hidden=true};
  };
  document.addEventListener('DOMContentLoaded',()=>{
    ensurePopup();
    const notices=[...document.querySelectorAll('.notice')];
    if(notices.length){
      const isError=notices.some(n=>n.classList.contains('error'));
      const text=notices.map(n=>n.textContent.trim()).filter(Boolean).join('\n');
      notices.forEach(n=>n.remove());
      if(text) setTimeout(()=>showWorkLifePopup(text,isError?'error':'success'),80);
    } else {
      const q=new URLSearchParams(location.search);
      let text='';
      if(q.get('deleted')) text='資料已刪除。';
      else if(q.get('completed')) text='事項已完成。';
      else if(q.get('updated')) text='資料已更新。';
      else if(q.get('checked_in')) text='上班打卡成功。';
      else if(q.get('checked_out')) text='下班打卡成功。';
      else if(q.get('arrived')) text='物流已登記到店。';
      else if(q.get('saved')) text='資料已儲存。';
      if(text) setTimeout(()=>showWorkLifePopup(text,'success'),80);
    }
    document.addEventListener('submit',e=>{
      const form=e.target;
      if(!(form instanceof HTMLFormElement) || form.dataset.confirmed==='1') return;
      const action=(form.getAttribute('action')||'').toLowerCase();
      const danger=action.includes('delete') || form.querySelector('.danger');
      if(danger){
        e.preventDefault();
        confirmWorkLifePopup('確定要刪除這筆資料嗎？此操作無法復原。',()=>{form.dataset.confirmed='1';form.submit()},'刪除確認');
      }
    },true);
  });
})();
