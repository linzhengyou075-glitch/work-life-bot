
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
