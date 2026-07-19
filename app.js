
document.addEventListener("DOMContentLoaded",()=>{
 const car=document.querySelector("[data-carousel]");
 if(car){const track=car.querySelector(".wl-track"),dots=[...car.querySelectorAll(".wl-dots button")];let i=0;setInterval(()=>{i=(i+1)%dots.length;track.style.transform=`translateX(-${i*100}%)`;dots.forEach((d,n)=>d.classList.toggle("active",n===i))},5000)}
 const grid=document.querySelector("[data-calendar]");
 if(grid){const shifts=new Map((window.SHIFTS||[]).map(x=>[x.work_date,x]));let view=new Date();view.setDate(1);const label=document.querySelector("[data-month]"),modal=document.querySelector("[data-modal]"),dateInput=document.querySelector("[data-date]"),del=document.querySelector("[data-delete-date]"),select=document.querySelector("[data-shift-select]");
  const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  function render(){grid.innerHTML="";const y=view.getFullYear(),m=view.getMonth(),first=new Date(y,m,1),start=new Date(y,m,1-first.getDay());label.textContent=`${y} 年 ${m+1} 月`;for(let n=0;n<42;n++){const d=new Date(start);d.setDate(start.getDate()+n);const key=iso(d),s=shifts.get(key),b=document.createElement("button");b.className="day"+(d.getMonth()!=m?" out":"")+(key===iso(new Date())?" today":"");b.innerHTML=`<b>${d.getDate()}</b>${s?`<span class="chip">${s.icon||""} ${s.shift_name}</span>${s.overtime?`<span class="chip ot">加班至 ${s.overtime_end}</span>`:""}`:""}`;b.onclick=()=>{dateInput.value=key;del.value=key;if(s&&s.shift_type_id)select.value=s.shift_type_id;modal.hidden=false};grid.appendChild(b)}}
  document.querySelector("[data-prev]").onclick=()=>{view.setMonth(view.getMonth()-1);render()};document.querySelector("[data-next]").onclick=()=>{view.setMonth(view.getMonth()+1);render()};document.querySelector("[data-open-modal]").onclick=()=>{dateInput.value=iso(new Date());del.value=dateInput.value;modal.hidden=false};document.querySelector("[data-close]").onclick=()=>modal.hidden=true;document.querySelectorAll("[data-shift]").forEach(b=>b.onclick=()=>{select.value=b.dataset.shift;if(!dateInput.value)dateInput.value=iso(new Date());del.value=dateInput.value;modal.hidden=false});const ot=document.querySelector("[data-overtime]"),wrap=document.querySelector("[data-overtime-time]");ot.onchange=()=>wrap.hidden=!ot.checked;render()}
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
  updateCountdown();setInterval(updateCountdown,1000);
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

// 首頁改版第一包：公告輪播（純前端，不增加 Render 請求）
document.addEventListener("DOMContentLoaded",()=>{
  const root=document.querySelector("[data-dashboard-carousel]");
  if(!root)return;
  const track=root.querySelector("[data-dashboard-track]");
  const slides=[...track.children];
  const dots=root.querySelector("[data-dashboard-dots]");
  if(slides.length<2)return;
  let index=0,timer=null;
  const buttons=slides.map((_,i)=>{
    const button=document.createElement("button");
    button.type="button";
    button.setAttribute("aria-label",`顯示第 ${i+1} 則資訊`);
    button.addEventListener("click",()=>show(i,true));
    dots.appendChild(button);
    return button;
  });
  function show(next,restart=false){
    index=(next+slides.length)%slides.length;
    track.style.transform=`translateX(-${index*100}%)`;
    buttons.forEach((button,i)=>button.classList.toggle("active",i===index));
    if(restart)start();
  }
  function start(){clearInterval(timer);timer=setInterval(()=>show(index+1),6500)}
  root.addEventListener("mouseenter",()=>clearInterval(timer));
  root.addEventListener("mouseleave",start);
  root.addEventListener("focusin",()=>clearInterval(timer));
  root.addEventListener("focusout",start);
  show(0);start();
});
