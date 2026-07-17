from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import asyncio
import json
import sqlite3
import urllib.parse
import urllib.request

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from openpyxl import load_workbook

from auth import build_authorize_url, exchange_code, get_profile, new_state, LoginConfigError
from config import settings
from database import (
    init_db,upsert_user,list_shift_types,list_shifts,get_shift,save_shift,delete_shift,
    list_daily_work,toggle_daily_work,list_logistics_settings,save_logistics_setting,
    delete_logistics_setting,list_daily_logistics,logistics_arrive,logistics_complete,
    attendance_for,check_in,check_out,add_reminder,list_reminders,due_reminders,
    mark_reminder_sent,complete_reminder,delete_reminder,add_notification_log,
    list_notification_logs,add_task,list_tasks,toggle_task,delete_task,
    add_work_log,list_work_logs,delete_work_log,dashboard_counts,set_setting,get_setting
)
from line_api import verify_signature,reply_message,work_entry_flex,push_message,reminder_flex

BASE_DIR = Path(__file__).resolve().parent

_WEATHER_CACHE = {"at": None, "data": None}

WEATHER_CODES = {
    0:("☀️","晴朗"),1:("🌤️","大致晴朗"),2:("⛅","局部多雲"),3:("☁️","陰天"),
    45:("🌫️","有霧"),48:("🌫️","霧淞"),51:("🌦️","毛毛雨"),53:("🌦️","毛毛雨"),55:("🌧️","較強毛毛雨"),
    61:("🌦️","小雨"),63:("🌧️","中雨"),65:("🌧️","大雨"),66:("🌨️","凍雨"),67:("🌨️","強凍雨"),
    71:("🌨️","小雪"),73:("🌨️","中雪"),75:("❄️","大雪"),77:("🌨️","霰"),
    80:("🌦️","陣雨"),81:("🌧️","較強陣雨"),82:("⛈️","強陣雨"),85:("🌨️","陣雪"),86:("❄️","強陣雪"),
    95:("⛈️","雷雨"),96:("⛈️","雷雨伴冰雹"),99:("⛈️","強雷雨伴冰雹")
}

def get_taiping_weather():
    now=datetime.now()
    cached_at=_WEATHER_CACHE.get("at")
    if cached_at and _WEATHER_CACHE.get("data") and (now-cached_at).total_seconds()<900:
        return _WEATHER_CACHE["data"]
    params=urllib.parse.urlencode({
        "latitude":24.1271,"longitude":120.7189,"timezone":"Asia/Taipei",
        "current":"temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "hourly":"precipitation_probability","forecast_days":1
    })
    try:
        req=urllib.request.Request("https://api.open-meteo.com/v1/forecast?"+params,headers={"User-Agent":"WorkLife/4.1"})
        with urllib.request.urlopen(req,timeout=4) as response:
            payload=json.load(response)
        current=payload.get("current") or {}
        code=int(current.get("weather_code",3))
        icon,text=WEATHER_CODES.get(code,("🌤️","天氣資訊"))
        probability=0
        hourly=payload.get("hourly") or {}
        times=hourly.get("time") or []
        probs=hourly.get("precipitation_probability") or []
        target=(current.get("time") or "")[:13]
        for i,t in enumerate(times):
            if str(t).startswith(target) and i<len(probs):
                probability=probs[i] or 0; break
        data={"ok":True,"icon":icon,"text":text,"temperature":round(float(current.get("temperature_2m",0))),
              "apparent":round(float(current.get("apparent_temperature",0))),"rain":int(probability),
              "wind":round(float(current.get("wind_speed_10m",0)),1),"location":"台中太平"}
        _WEATHER_CACHE.update(at=now,data=data)
        return data
    except Exception:
        stale=_WEATHER_CACHE.get("data")
        if stale: return stale
        return {"ok":False,"icon":"🌤️","text":"暫時無法取得","temperature":"--","apparent":"--","rain":"--","wind":"--","location":"台中太平"}

def week_schedule(anchor=None):
    anchor=anchor or date.today()
    start=anchor-timedelta(days=anchor.weekday())
    labels="一二三四五六日"
    output=[]
    for i in range(7):
        day=start+timedelta(days=i)
        shift=get_shift(day.isoformat())
        output.append({"date":day.isoformat(),"day":day.day,"weekday":labels[i],"today":day==anchor,"shift":dict(shift) if shift else None})
    return output


app=FastAPI(title="Work Life",version="4.1.1")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60*60*24*30,
    same_site="lax",
    https_only=settings.base_url.startswith("https://")
)
templates=Jinja2Templates(directory=str(BASE_DIR))

@app.middleware("http")
async def disable_dynamic_cache(request: Request, call_next):
    """避免手機瀏覽器重新整理時顯示儲存前的快取頁面。"""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        return response
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/static/style.css")
def static_style(): return FileResponse(BASE_DIR / "style.css",media_type="text/css")
@app.get("/static/app.js")
def static_js(): return FileResponse(BASE_DIR / "app.js",media_type="application/javascript")
@app.get("/static/worklife_mascot.png")
def static_mascot(): return FileResponse(BASE_DIR / "worklife_mascot.png",media_type="image/png")
@app.get("/static/worklife_frame.png")
def static_frame(): return FileResponse(BASE_DIR / "worklife_frame.png",media_type="image/png")

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(reminder_worker())

async def reminder_worker():
    while True:
        try:
            now=datetime.now()
            for item in due_reminders(now.strftime("%Y-%m-%d"),now.strftime("%H:%M")):
                try:
                    content=item["note"] or f'{item["remind_time"]} 提醒'
                    url=f'{settings.base_url}{item["related_url"] or "/dashboard"}'
                    sent=push_message(settings.owner_line_user_id,[reminder_flex(item["title"],content,url)])
                    if sent:
                        mark_reminder_sent(item["id"])
                        add_notification_log(item["title"],content,"已推播")
                except Exception as exc:
                    add_notification_log(item["title"],str(exc),"失敗")
        except Exception:
            pass
        await asyncio.sleep(60)

def current_user(request):
    return request.session.get("user")

def protected(request,path):
    user=current_user(request)
    if not user:
        request.session["login_next"]=path
        return None,RedirectResponse("/login-page",302)
    if settings.owner_line_user_id and user.get("userId")!=settings.owner_line_user_id:
        return None,templates.TemplateResponse("denied.html",{"request":request},status_code=403)
    return user,None

@app.get("/healthz")
def healthz():
    return {"status":"ok","version":"4.1.0","line_login_ready":settings.line_login_ready}

@app.get("/")
def root(request:Request):
    return RedirectResponse("/dashboard" if current_user(request) else "/login-page",302)

@app.get("/login-page",response_class=HTMLResponse)
def login_page(request:Request):
    if current_user(request): return RedirectResponse("/dashboard",302)
    return templates.TemplateResponse("login.html",{"request":request})

@app.get("/login")
def login(request:Request):
    try:
        state=new_state()
        request.session["oauth_state"]=state
        return RedirectResponse(build_authorize_url(state),302)
    except LoginConfigError as exc:
        return templates.TemplateResponse("error.html", {"request":request,"message":str(exc)+" 請在部署環境設定 LINE_LOGIN_CHANNEL_ID、LINE_LOGIN_CHANNEL_SECRET、BASE_URL。"}, status_code=503)

@app.get("/auth/line/callback")
def callback(request:Request,code:str|None=None,state:str|None=None,error:str|None=None):
    if error:
        return templates.TemplateResponse("error.html",{"request":request,"message":"LINE 登入失敗，請重新登入。"},status_code=400)
    expected=request.session.pop("oauth_state",None)
    if not code or not state or state!=expected:
        return templates.TemplateResponse("error.html",{"request":request,"message":"登入驗證失敗，請重新登入。"},status_code=400)
    try:
        token=exchange_code(code)
        profile=get_profile(token["access_token"])
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request":request,"message":f"LINE 登入連線失敗：{exc}"}, status_code=400)
    if settings.owner_line_user_id and profile.get("userId")!=settings.owner_line_user_id:
        return templates.TemplateResponse("denied.html",{"request":request},status_code=403)
    upsert_user(profile["userId"],profile.get("displayName","佑佑"),profile.get("pictureUrl"))
    request.session["user"]=profile
    next_url=request.session.pop("login_next","/dashboard")
    if not isinstance(next_url,str) or not next_url.startswith("/") or next_url.startswith("//"):
        next_url="/dashboard"
    return RedirectResponse(next_url,302)

@app.get("/logout")
def logout(request:Request):
    request.session.clear()
    return RedirectResponse("/login-page",302)

@app.get("/dashboard",response_class=HTMLResponse)
def dashboard(request:Request):
    user,resp=protected(request,"/dashboard")
    if resp:return resp
    today=date.today().isoformat()
    return templates.TemplateResponse("dashboard.html",{
        "request":request,"user":user,"today":today,
        "shift":get_shift(today),
        "daily_work":list_daily_work(today),
        "daily_logistics":list_daily_logistics(today),
        "attendance":attendance_for(today),
        "tasks":list_tasks(False)[:5],
        "reminders":[x for x in list_reminders(False) if x["remind_date"]==today],
        "counts":dashboard_counts(today),
        "weather":get_taiping_weather(),
        "week_days":week_schedule(),
        "now_text":datetime.now().strftime("%Y/%m/%d %H:%M"),
        "today_label":datetime.now().strftime("%m月%d日"),
    })

@app.get("/quick-schedule",response_class=HTMLResponse)
@app.get("/schedule",response_class=HTMLResponse)
def schedule_page(request:Request):
    user,resp=protected(request,request.url.path)
    if resp:return resp
    return templates.TemplateResponse("schedule.html",{
        "request":request,"user":user,
        "shifts":list_shifts(),"shift_types":list_shift_types()
    })

@app.post("/schedule")
def schedule_save(
    request:Request,work_date:str=Form(...),shift_type_id:int=Form(...),
    overtime:str=Form(""),overtime_end:str=Form(""),
    manager_tasks:str=Form(""),note:str=Form("")
):
    user,resp=protected(request,"/quick-schedule")
    if resp:return resp
    try:
        save_shift(work_date,shift_type_id,overtime=="1",overtime_end,manager_tasks=="1",note.strip())
    except (ValueError, OSError) as exc:
        return templates.TemplateResponse("schedule.html",{
            "request":request,"user":user,"shifts":list_shifts(),"shift_types":list_shift_types(),
            "save_error":str(exc)
        },status_code=400)
    except Exception:
        return templates.TemplateResponse("schedule.html",{
            "request":request,"user":user,"shifts":list_shifts(),"shift_types":list_shift_types(),
            "save_error":"儲存失敗，請稍後再試；原本資料沒有被覆蓋。"
        },status_code=500)
    return RedirectResponse("/quick-schedule?saved=1",303)

@app.post("/schedule/delete")
def schedule_delete(request:Request,work_date:str=Form(...)):
    user,resp=protected(request,"/quick-schedule")
    if resp:return resp
    delete_shift(work_date)
    return RedirectResponse("/quick-schedule?deleted=1",303)

def parse_excel(content:bytes, filename:str=""):
    """讀取 Work Life 班表，支援 .xlsx 與含巨集的 .xlsm。"""
    try:
        wb=load_workbook(
            BytesIO(content),
            data_only=True,
            keep_vba=filename.lower().endswith(".xlsm")
        )
    except Exception as exc:
        raise ValueError("Excel 檔案無法開啟，請確認檔案未損壞，且格式為 .xlsx 或 .xlsm。") from exc

    types={str(x["name"]).strip():x for x in list_shift_types()}
    rows=[];errors=[];matched_sheets=0
    for ws in wb.worksheets:
        if "月班表" not in ws.title:
            continue
        matched_sheets+=1
        for row_no in range(5,(ws.max_row or 4)+1):
            raw_date=ws.cell(row_no,1).value
            shift_name=str(ws.cell(row_no,3).value or "").strip()
            if not raw_date or not shift_name:
                continue
            if hasattr(raw_date,"strftime"):
                work_date=raw_date.strftime("%Y-%m-%d")
            else:
                raw_text=str(raw_date).strip().replace("/","-")
                try:
                    work_date=date.fromisoformat(raw_text[:10]).isoformat()
                except Exception:
                    errors.append(f"{ws.title} 第{row_no}列日期無法讀取")
                    continue
            if shift_name not in types:
                errors.append(f"{ws.title} 第{row_no}列班別不存在：{shift_name}")
                continue
            overtime_text=str(ws.cell(row_no,4).value or "否").strip().lower()
            overtime=overtime_text in {"是","yes","y","true","1"}
            overtime_end=str(ws.cell(row_no,5).value or "").strip()
            note=str(ws.cell(row_no,6).value or "").strip()
            rows.append({
                "work_date":work_date,
                "shift_type_id":types[shift_name]["id"],
                "overtime":overtime,
                "overtime_end":overtime_end,
                "note":note
            })
    if matched_sheets==0:
        raise ValueError("找不到『月班表』工作表，請使用 Work Life 班表範本。")
    return rows,errors

@app.post("/quick-schedule/upload",response_class=HTMLResponse)
async def excel_upload(request:Request,file:UploadFile=File(...),overwrite:str=Form("")):
    user,resp=protected(request,"/quick-schedule")
    if resp:return resp
    context={"request":request,"user":user,"shifts":list_shifts(),"shift_types":list_shift_types()}
    filename=(file.filename or "").strip()
    if not filename.lower().endswith((".xlsx",".xlsm")):
        context["upload_error"]="請上傳 .xlsx 或 .xlsm 格式的 Excel 班表。"
        return templates.TemplateResponse("schedule.html",context,status_code=400)
    content=await file.read()
    if not content:
        context["upload_error"]="上傳的 Excel 檔案是空的，請重新選擇檔案。"
        return templates.TemplateResponse("schedule.html",context,status_code=400)
    if len(content)>10*1024*1024:
        context["upload_error"]="Excel 檔案超過 10MB，請縮小檔案後再上傳。"
        return templates.TemplateResponse("schedule.html",context,status_code=400)
    try:
        rows,errors=parse_excel(content,filename)
    except ValueError as exc:
        context["upload_error"]=str(exc)
        return templates.TemplateResponse("schedule.html",context,status_code=400)
    if not rows:
        context["upload_error"]="班表內沒有可匯入的資料，請先在班別欄選擇班別。"
        if errors:
            context["upload_error"] += " " + "、".join(errors[:8])
        return templates.TemplateResponse("schedule.html",context,status_code=400)

    existing={x["work_date"] for x in list_shifts()}
    imported=0;skipped=0
    for row in rows:
        if row["work_date"] in existing and overwrite!="1":
            skipped+=1
            continue
        save_shift(row["work_date"],row["shift_type_id"],row["overtime"],row["overtime_end"],False,row["note"])
        imported+=1
        existing.add(row["work_date"])
    context.update({"shifts":list_shifts(),"upload_result":{"imported":imported,"skipped":skipped,"errors":errors}})
    return templates.TemplateResponse("schedule.html",context)

@app.get("/work-records",response_class=HTMLResponse)
def work_page(request:Request,work_date:str|None=None):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    selected=work_date or date.today().isoformat()
    return templates.TemplateResponse("work_records.html",{
        "request":request,"user":user,"selected_date":selected,
        "shift":get_shift(selected),"daily_work":list_daily_work(selected),
        "daily_logistics":list_daily_logistics(selected),
        "attendance":attendance_for(selected),"logs":list_work_logs()
    })

@app.post("/daily-work/{item_id}/toggle")
def daily_toggle(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    toggle_daily_work(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.post("/attendance/check-in")
def attendance_check_in(request:Request,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    check_in(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.post("/attendance/check-out")
def attendance_check_out(request:Request,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    check_out(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.post("/logistics/{item_id}/arrive")
def logistics_start(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    logistics_arrive(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.post("/logistics/{item_id}/complete")
def logistics_finish(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    logistics_complete(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.post("/work-records")
def log_add(request:Request,work_date:str=Form(...),category:str=Form(...),title:str=Form(...),amount:int=Form(0),note:str=Form("")):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    add_work_log(work_date,category,title,max(amount,0),note)
    return RedirectResponse(f"/work-records?work_date={work_date}",303)

@app.get("/logistics-settings",response_class=HTMLResponse)
def logistics_settings_page(request:Request):
    user,resp=protected(request,"/logistics-settings")
    if resp:return resp
    return templates.TemplateResponse("logistics.html",{
        "request":request,"user":user,"items":list_logistics_settings()
    })

@app.post("/logistics-settings")
def logistics_settings_save(
    request:Request,item_id:str=Form(""),name:str=Form(...),icon:str=Form("🚚"),
    start_time:str=Form(...),end_time:str=Form(...),content:str=Form(""),
    applies_b:str=Form(""),applies_c:str=Form(""),applies_late:str=Form(""),
    applies_night:str=Form(""),remind_minutes:int=Form(10),
    line_push:str=Form(""),show_carousel:str=Form(""),is_active:str=Form("")
):
    user,resp=protected(request,"/logistics-settings")
    if resp:return resp
    try:
        save_logistics_setting(
            int(item_id) if item_id.isdigit() else None,name.strip(),icon.strip() or "🚚",
            start_time,end_time,content.strip(),applies_b=="1",applies_c=="1",
            applies_late=="1",applies_night=="1",max(remind_minutes,0),
            line_push=="1",show_carousel=="1",is_active=="1"
        )
    except (ValueError, sqlite3.DatabaseError) as exc:
        return templates.TemplateResponse("logistics.html", {
            "request":request,"user":user,"items":list_logistics_settings(),"save_error":str(exc)
        }, status_code=400)
    return RedirectResponse("/logistics-settings?saved=1",303)

@app.post("/logistics-settings/{item_id}/delete")
def logistics_settings_delete(request:Request,item_id:int):
    user,resp=protected(request,"/logistics-settings")
    if resp:return resp
    delete_logistics_setting(item_id)
    return RedirectResponse("/logistics-settings?deleted=1",303)

@app.get("/notifications",response_class=HTMLResponse)
def notification_page(request:Request):
    user,resp=protected(request,"/notifications")
    if resp:return resp
    return templates.TemplateResponse("notifications.html",{
        "request":request,"user":user,"today":date.today().isoformat(),
        "reminders":list_reminders(),"logs":list_notification_logs()
    })

@app.post("/reminders")
def reminder_add(
    request:Request,title:str=Form(...),reminder_type:str=Form("自訂"),
    remind_date:str=Form(...),remind_time:str=Form(...),note:str=Form(""),
    related_url:str=Form("/dashboard"),line_push:str=Form(""),show_carousel:str=Form("")
):
    user,resp=protected(request,"/notifications")
    if resp:return resp
    add_reminder(title.strip(),reminder_type,remind_date,remind_time,note.strip(),
                 related_url,line_push=="1",show_carousel=="1")
    return RedirectResponse("/notifications?saved=1",303)

@app.post("/reminders/{item_id}/complete")
def reminder_done(request:Request,item_id:int):
    user,resp=protected(request,"/notifications")
    if resp:return resp
    complete_reminder(item_id)
    return RedirectResponse("/notifications",303)

@app.post("/reminders/{item_id}/delete")
def reminder_remove(request:Request,item_id:int):
    user,resp=protected(request,"/notifications")
    if resp:return resp
    delete_reminder(item_id)
    return RedirectResponse("/notifications",303)

@app.get("/tasks",response_class=HTMLResponse)
def tasks_page(request:Request):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    return templates.TemplateResponse("tasks.html",{"request":request,"user":user,"tasks":list_tasks()})

@app.post("/tasks")
def task_add(request:Request,title:str=Form(...),due_date:str=Form(""),note:str=Form("")):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    try:
        add_task(title,due_date,note)
    except (ValueError, OSError) as exc:
        return templates.TemplateResponse("tasks.html",{
            "request":request,"user":user,"tasks":list_tasks(),"save_error":str(exc)
        },status_code=400)
    except Exception:
        return templates.TemplateResponse("tasks.html",{
            "request":request,"user":user,"tasks":list_tasks(),
            "save_error":"儲存失敗，請稍後再試；原本資料沒有被覆蓋。"
        },status_code=500)
    return RedirectResponse("/tasks?saved=1",303)

@app.post("/tasks/{item_id}/toggle")
def task_toggle(request:Request,item_id:int):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    toggle_task(item_id)
    return RedirectResponse("/tasks",303)

@app.post("/tasks/{item_id}/delete")
def task_remove(request:Request,item_id:int):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    delete_task(item_id)
    return RedirectResponse("/tasks",303)

@app.get("/profile",response_class=HTMLResponse)
def profile_page(request:Request):
    user,resp=protected(request,"/profile")
    if resp:return resp
    return templates.TemplateResponse("profile.html",{
        "request":request,"user":user,
        "line_push":get_setting("line_push","1"),
        "auto_refresh":get_setting("auto_refresh","15")
    })

@app.post("/profile")
def profile_save(request:Request,line_push:str=Form(""),auto_refresh:str=Form("15")):
    user,resp=protected(request,"/profile")
    if resp:return resp
    set_setting("line_push","1" if line_push=="1" else "0")
    set_setting("auto_refresh",auto_refresh)
    return RedirectResponse("/profile?saved=1",303)

@app.get("/api/dashboard-state")
def dashboard_state(request:Request):
    user,resp=protected(request,"/dashboard")
    if resp:return JSONResponse({"ok":False},401)
    today=date.today().isoformat()
    return {
        "ok":True,
        "shift":get_shift(today),
        "daily_work":list_daily_work(today),
        "daily_logistics":list_daily_logistics(today),
        "attendance":attendance_for(today),
        "counts":dashboard_counts(today)
    }

@app.post("/webhook")
async def webhook(request:Request):
    body=(await request.body()).decode("utf-8")
    signature=request.headers.get("X-Line-Signature","")
    if not verify_signature(body,signature):
        return JSONResponse({"ok":False},400)
    data=await request.json()
    for event in data.get("events",[]):
        if event.get("type")=="message" and event.get("message",{}).get("type")=="text":
            text=event["message"]["text"].strip().lower()
            if text in {"/work","work","工作小幫手","班表"}:
                reply_message(event["replyToken"],[work_entry_flex(settings.base_url)])
    return {"ok":True}
