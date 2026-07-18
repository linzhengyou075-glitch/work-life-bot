from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import asyncio
import json
import sqlite3
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

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
    delete_logistics_setting,list_daily_logistics,logistics_arrive,logistics_complete,mark_logistics_reminded,
    attendance_for,check_in,check_out,add_reminder,list_reminders,due_reminders,
    mark_reminder_sent,complete_reminder,delete_reminder,add_notification_log,
    list_notification_logs,add_task,list_tasks,toggle_task,delete_task,
    add_work_log,list_work_logs,delete_work_log,dashboard_counts,set_setting,get_setting,
    database_status
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

def get_open_meteo_weather():
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


def get_cwa_taiping_weather():
    """中央氣象署官方鄉鎮預報；需在部署環境設定 CWA_API_KEY。"""
    if not settings.cwa_api_key:
        return None
    params=urllib.parse.urlencode({
        "Authorization":settings.cwa_api_key,
        "LocationName":"太平區",
        "ElementName":"天氣現象,平均溫度,體感溫度,12小時降雨機率,風速"
    })
    req=urllib.request.Request(
        "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-073?"+params,
        headers={"User-Agent":"WorkLife/4.2"}
    )
    with urllib.request.urlopen(req,timeout=6) as response:
        payload=json.load(response)
    locations=((payload.get("records") or {}).get("Locations") or (payload.get("records") or {}).get("locations") or [])
    if not locations:
        return None
    towns=locations[0].get("Location") or locations[0].get("location") or []
    town=next((x for x in towns if (x.get("LocationName") or x.get("locationName"))=="太平區"), towns[0] if towns else None)
    if not town:
        return None
    elements=town.get("WeatherElement") or town.get("weatherElement") or []
    values={}
    for element in elements:
        name=element.get("ElementName") or element.get("elementName") or ""
        periods=element.get("Time") or element.get("time") or []
        if not periods:
            continue
        period=periods[0]
        item=(period.get("ElementValue") or period.get("elementValue") or [{}])[0]
        values[name]=item.get("Weather") or item.get("Temperature") or item.get("ProbabilityOfPrecipitation") or item.get("WindSpeed") or item.get("value")
    text=str(values.get("天氣現象") or "天氣資訊")
    icon="☀️" if "晴" in text else "⛈️" if "雷" in text else "🌧️" if "雨" in text else "☁️" if "陰" in text else "⛅"
    def number(value, default="--"):
        try:return round(float(value))
        except:return default
    return {
        "ok":True,"icon":icon,"text":text,
        "temperature":number(values.get("平均溫度")),
        "apparent":number(values.get("體感溫度")),
        "rain":number(values.get("12小時降雨機率")),
        "wind":number(values.get("風速")),
        "location":"台中太平",
        "source":"中央氣象署",
        "source_url":"https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=6602700"
    }

def get_taiping_weather():
    now=datetime.now()
    cached_at=_WEATHER_CACHE.get("at")
    if cached_at and _WEATHER_CACHE.get("data") and (now-cached_at).total_seconds()<900:
        return _WEATHER_CACHE["data"]
    try:
        official=get_cwa_taiping_weather()
        if official:
            _WEATHER_CACHE.update(at=now,data=official)
            return official
    except Exception:
        pass
    fallback=get_open_meteo_weather()
    fallback["source"]="備援天氣服務"
    fallback["source_url"]="https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=6602700"
    return fallback


_OFFICIAL_INFO_CACHE = {"at": None, "items": None}

class _FamilyEventParser(HTMLParser):
    """擷取全家官方活動頁可閱讀文字，不使用非官方活動來源。"""
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.texts = []
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if self.skip:
            return
        value = " ".join(data.split()).strip()
        if 2 <= len(value) <= 90:
            self.texts.append(value)

def _clean_family_events(texts):
    date_pattern = re.compile(r"^(20\d{2}/\d{2}/\d{2})\s*[-–－~～]\s*(20\d{2}/\d{2}/\d{2})$")
    category_names = {"主題活動", "會員優惠", "支付優惠", "鮮食優惠", "抽獎活動", "長期活動"}
    ignored = {
        "最新活動", "便利快訊", "商品情報", "各項查詢", "便利服務", "全家相關網站",
        "全家便利商店", "Image", "上一頁", "下一頁", "更多活動"
    }
    events=[]
    pending_category="官方活動"
    pending_period=""
    for value in texts:
        if value in ignored:
            continue
        if value in category_names:
            if value != "長期活動": pending_category=value
            else: pending_period="長期活動"
            continue
        match=date_pattern.match(value)
        if match:
            pending_period=f"{match.group(1)}－{match.group(2)}"
            continue
        if len(value)<5 or value.startswith("http"):
            continue
        if any(word in value for word in ("活動", "優惠", "加購", "回饋", "咖啡", "點數", "集章", "折", "贈", "買", "兌")):
            if value not in {x["title"] for x in events}:
                events.append({
                    "title":value[:58],
                    "period":pending_period or "詳見官方活動頁",
                    "category":pending_category,
                    "url":"https://www.family.com.tw/Marketing/zh/Event"
                })
                pending_period=""
            if len(events)>=6:
                break
    return events

def _fetch_family_events():
    url="https://www.family.com.tw/Marketing/zh/Event"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 WorkLife/5.0"})
    with urllib.request.urlopen(req,timeout=7) as response:
        html=response.read().decode("utf-8","ignore")
    parser=_FamilyEventParser(); parser.feed(html)
    return _clean_family_events(parser.texts)

def get_official_info():
    """全家官方活動推播；失敗時保留上次成功資料。"""
    now=datetime.now()
    cached_at=_OFFICIAL_INFO_CACHE.get("at")
    cached=_OFFICIAL_INFO_CACHE.get("items") or []
    if cached_at and cached and (now-cached_at).total_seconds()<1800:
        return cached
    try:
        events=_fetch_family_events()
        if not events:
            raise ValueError("no family events parsed")
        _OFFICIAL_INFO_CACHE.update(at=now,items=events)
        return events
    except Exception:
        if cached:
            return cached
        return [{
            "title":"查看全家官方最新活動",
            "period":"官方資料稍後自動重試",
            "category":"全家官方",
            "url":"https://www.family.com.tw/Marketing/zh/Event"
        }]


def _time_minutes(value):
    try:
        h,m=str(value or "").split(":")[:2]
        return int(h)*60+int(m)
    except Exception:
        return 0

def _is_overnight_shift(shift):
    return bool(shift) and _time_minutes(shift.get("end_time")) <= _time_minutes(shift.get("start_time"))

def _shift_end_value(shift):
    return (shift.get("overtime_end") if shift and shift.get("overtime") else shift.get("end_time")) if shift else ""

def _display_md(value):
    return value.strftime("%m/%d")

def decorate_shift_dates(work_date, shift):
    if not shift:
        return None
    item=dict(shift)
    start_day=datetime.strptime(work_date,"%Y-%m-%d").date()
    end_day=start_day+timedelta(days=1) if _time_minutes(_shift_end_value(item)) <= _time_minutes(item.get("start_time")) else start_day
    item.update({
        "work_date":work_date,
        "start_date":start_day.isoformat(),
        "end_date":end_day.isoformat(),
        "start_display":f"{_display_md(start_day)} {item.get('start_time') or '--:--'}",
        "end_display":f"{_display_md(end_day)} {_shift_end_value(item) or '--:--'}",
        "range_display":f"{_display_md(start_day)} {item.get('start_time') or '--:--'} ～ {_display_md(end_day)} {_shift_end_value(item) or '--:--'}",
        "is_overnight":end_day!=start_day,
    })
    return item

def decorate_timed_rows(work_date, shift, rows, time_key="scheduled_time"):
    start_day=datetime.strptime(work_date,"%Y-%m-%d").date()
    overnight=_is_overnight_shift(shift)
    start_minutes=_time_minutes(shift.get("start_time")) if shift else 0
    output=[]
    for row in rows:
        item=dict(row)
        raw=item.get(time_key) or ""
        item_minutes=_time_minutes(raw)
        item_day=start_day+timedelta(days=1) if overnight and item_minutes < start_minutes else start_day
        item["display_date"]=item_day.isoformat()
        item["display_md"]=_display_md(item_day)
        item["datetime_display"]=f"{_display_md(item_day)} {raw or '--:--'}"
        item["sort_datetime"]=f"{item_day.isoformat()} {raw or '23:59'}"
        output.append(item)
    return sorted(output,key=lambda x:(x["sort_datetime"],x.get("id",0)))

def resolve_active_work_date(now=None):
    now=now or datetime.now()
    today=now.date()
    previous=today-timedelta(days=1)
    previous_shift=get_shift(previous.isoformat())
    if previous_shift and _is_overnight_shift(previous_shift):
        end_value=_shift_end_value(previous_shift)
        end_at=datetime.combine(today,datetime.strptime(end_value,"%H:%M").time())
        if now <= end_at:
            return previous.isoformat()
    return today.isoformat()

def dashboard_work_context(now=None):
    now=now or datetime.now()
    work_date=resolve_active_work_date(now)
    raw_shift=get_shift(work_date)
    shift=decorate_shift_dates(work_date,raw_shift)
    work=decorate_timed_rows(work_date,raw_shift,list_daily_work(work_date),"scheduled_time")
    logistics=decorate_timed_rows(work_date,raw_shift,list_daily_logistics(work_date),"start_time")
    next_item=None
    for item in work:
        try:
            at=datetime.strptime(f"{item['display_date']} {item.get('scheduled_time')}","%Y-%m-%d %H:%M")
        except Exception:
            continue
        if not item.get("is_done") and at>=now:
            next_item=item
            break
    return work_date,shift,work,logistics,next_item

def get_next_shift(after_date=None):
    after_date=after_date or date.today().isoformat()
    for item in list_shifts():
        if item.get("work_date", "") < after_date:
            continue
        if item.get("store_code") == "X":
            continue
        return decorate_shift_dates(item["work_date"], item)
    return None


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


app=FastAPI(title="Work Life",version="4.2.1")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60*60*24*30,
    same_site="lax",
    https_only=settings.base_url.startswith("https://")
)
templates=Jinja2Templates(directory=str(BASE_DIR))

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

            # Phase 2：依班表自動推播物流提醒。大夜班凌晨時段會套用前一天班表。
            for work_date in ((now.date()-timedelta(days=1)).isoformat(), now.date().isoformat()):
                raw_shift=get_shift(work_date)
                if not raw_shift or raw_shift.get("store_code")=="X":
                    continue
                for item in decorate_timed_rows(work_date,raw_shift,list_daily_logistics(work_date),"start_time"):
                    if item.get("reminded_at") or item.get("completed_at") or not item.get("line_push"):
                        continue
                    try:
                        event_at=datetime.strptime(f"{item['display_date']} {item['start_time']}","%Y-%m-%d %H:%M")
                        remind_at=event_at-timedelta(minutes=int(item.get("remind_minutes") or 10))
                    except Exception:
                        continue
                    if remind_at <= now < event_at+timedelta(minutes=5):
                        title=f"{item.get('icon') or '🚚'} {item.get('name')}即將到店"
                        content=f"預計 {item['datetime_display']} 到店"
                        if item.get("content"):
                            content += f"｜{item['content']}"
                        url=f"{settings.base_url}/work-records?work_date={work_date}"
                        sent=push_message(settings.owner_line_user_id,[reminder_flex(title,content,url)])
                        if sent:
                            mark_logistics_reminded(item["id"])
                            add_notification_log(title,content,"已推播")
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
    return {"status":"ok","version":"4.2.1-render-connect-fix","line_login_ready":settings.line_login_ready,"database":database_status()}

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
    now=datetime.now()
    work_date,shift,daily_work,daily_logistics,next_work_item=dashboard_work_context(now)
    today=date.today().isoformat()
    return templates.TemplateResponse("dashboard.html",{
        "request":request,"user":user,"today":today,"active_work_date":work_date,
        "shift":shift,
        "daily_work":daily_work,
        "daily_logistics":daily_logistics,
        "next_work_item":next_work_item,
        "attendance":attendance_for(work_date),
        "tasks":list_tasks(False)[:5],
        "reminders":[x for x in list_reminders(False) if x["remind_date"]==today],
        "counts":dashboard_counts(work_date),
        "weather":get_taiping_weather(),
        "official_info":get_official_info(),
        "week_days":week_schedule(),
        "next_shift":get_next_shift(today),
        "now_text":datetime.now().strftime("%Y/%m/%d %H:%M"),
        "today_label":datetime.now().strftime("%m月%d日"),
        "life_links":[
            {"icon":"🏪","title":"全家最新活動","text":"查看全家官方最新優惠與主題活動","url":"https://www.family.com.tw/Marketing/zh/Event","tag":"官方"},
            {"icon":"🎫","title":"會員優惠","text":"會員點數、兌換與 APP 優惠資訊","url":"https://www.family.com.tw/Marketing/zh/Member","tag":"官方"},
        ],
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

def _excel_text(value):
    if value is None:
        return ""
    if hasattr(value, "strftime") and not isinstance(value, str):
        try:
            return value.strftime("%H:%M")
        except Exception:
            pass
    return str(value).strip()


def _normalise_header(value):
    return re.sub(r"[\s_／/()（）]+", "", _excel_text(value)).lower()


def _normalise_store(value):
    text=_excel_text(value).replace(" ", "")
    if "溪洲" in text or text.upper()=="C":
        return "溪洲"
    if "建昌" in text or text.upper()=="B":
        return "建昌"
    return ""


def _normalise_shift_name(store_value, shift_value):
    shift=_excel_text(shift_value).replace(" ", "")
    if not shift:
        return ""
    if "休" in shift:
        return "休假"
    store=_normalise_store(store_value)
    if "大夜" in shift or shift in {"夜班", "night"}:
        return f"{store}大夜" if store else ""
    if "晚班" in shift or shift in {"晚", "late"}:
        return f"{store}晚班" if store else ""
    # 兼容舊範本直接填入完整班別名稱。
    return shift


def _parse_work_date(raw_date):
    if raw_date is None or raw_date == "":
        return None
    if hasattr(raw_date, "strftime"):
        return raw_date.strftime("%Y-%m-%d")
    text=_excel_text(raw_date).replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(text[:19], fmt).date().isoformat()
        except Exception:
            pass
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except Exception:
        return None


def _parse_overtime(value):
    text=_excel_text(value)
    compact=text.replace(" ", "").replace("：", ":")
    if not compact or compact.lower() in {"否", "no", "n", "false", "0", "-", "無"}:
        return False, ""
    match=re.search(r"([01]?\d|2[0-3]):([0-5]\d)", compact)
    if match:
        return True, f"{int(match.group(1)):02d}:{match.group(2)}"
    return compact.lower() in {"是", "yes", "y", "true", "1", "加班"}, ""


def _header_map(ws):
    aliases={
        "date":{"日期", "工作日期", "上班日期"},
        "store":{"店名", "店舖", "店鋪", "門市", "工作店舖"},
        "shift":{"班別", "班次", "班別名稱"},
        "start":{"上班時間", "開始時間", "上班"},
        "end":{"下班時間", "結束時間", "下班"},
        "overtime":{"加班", "加班時間", "加班至"},
        "note":{"備註", "說明"},
    }
    normalised={key:{_normalise_header(v) for v in values} for key,values in aliases.items()}
    for row_no in range(1, min(ws.max_row or 1, 12)+1):
        mapping={}
        for col_no in range(1, (ws.max_column or 1)+1):
            header=_normalise_header(ws.cell(row_no,col_no).value)
            for key,values in normalised.items():
                if header in values:
                    mapping[key]=col_no
        if "date" in mapping and "shift" in mapping:
            return row_no,mapping
    return None,{}


def parse_excel(content:bytes, filename:str=""):
    """讀取 Work Life 班表，支援新版直式表格與舊版月班表範本。"""
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
    seen_dates=set()
    for ws in wb.worksheets:
        header_row,columns=_header_map(ws)
        if header_row:
            matched_sheets+=1
            for row_no in range(header_row+1,(ws.max_row or header_row)+1):
                raw_date=ws.cell(row_no,columns["date"]).value
                raw_shift=ws.cell(row_no,columns["shift"]).value
                raw_store=ws.cell(row_no,columns.get("store",0)).value if columns.get("store") else ""
                if not raw_date and not raw_shift:
                    continue
                work_date=_parse_work_date(raw_date)
                if not work_date:
                    errors.append(f"{ws.title} 第{row_no}列日期無法讀取")
                    continue
                shift_name=_normalise_shift_name(raw_store,raw_shift)
                if not shift_name:
                    errors.append(f"{ws.title} 第{row_no}列缺少店名或班別")
                    continue
                if shift_name not in types:
                    errors.append(f"{ws.title} 第{row_no}列班別不存在：{shift_name}")
                    continue
                overtime,overtime_end=_parse_overtime(ws.cell(row_no,columns.get("overtime",0)).value if columns.get("overtime") else "")
                note=_excel_text(ws.cell(row_no,columns.get("note",0)).value) if columns.get("note") else ""
                if work_date in seen_dates:
                    errors.append(f"{ws.title} 第{row_no}列日期重複：{work_date}")
                    continue
                rows.append({
                    "work_date":work_date,
                    "shift_type_id":types[shift_name]["id"],
                    "overtime":overtime,
                    "overtime_end":overtime_end or ("08:00" if overtime else ""),
                    "note":note
                })
                seen_dates.add(work_date)
            continue

        # 舊版 Work Life 月班表：A 日期、C 班別、D 是否加班、E 加班時間、F 備註。
        if "月班表" not in ws.title:
            continue
        matched_sheets+=1
        for row_no in range(5,(ws.max_row or 4)+1):
            work_date=_parse_work_date(ws.cell(row_no,1).value)
            shift_name=_excel_text(ws.cell(row_no,3).value)
            if not work_date or not shift_name:
                continue
            if shift_name not in types:
                errors.append(f"{ws.title} 第{row_no}列班別不存在：{shift_name}")
                continue
            overtime_text=_excel_text(ws.cell(row_no,4).value)
            overtime,overtime_from_text=_parse_overtime(overtime_text)
            overtime_end=_excel_text(ws.cell(row_no,5).value) or overtime_from_text
            note=_excel_text(ws.cell(row_no,6).value)
            if work_date in seen_dates:
                errors.append(f"{ws.title} 第{row_no}列日期重複：{work_date}")
                continue
            rows.append({
                "work_date":work_date,
                "shift_type_id":types[shift_name]["id"],
                "overtime":overtime,
                "overtime_end":overtime_end or ("08:00" if overtime else ""),
                "note":note
            })
            seen_dates.add(work_date)
    if matched_sheets==0:
        raise ValueError("找不到班表欄位。請確認第一列包含：日期、店名、班別、上班時間、下班時間、加班。")
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
    selected=work_date or resolve_active_work_date()
    raw_shift=get_shift(selected)
    return templates.TemplateResponse("work_records.html",{
        "request":request,"user":user,"selected_date":selected,
        "shift":decorate_shift_dates(selected,raw_shift),
        "daily_work":decorate_timed_rows(selected,raw_shift,list_daily_work(selected),"scheduled_time"),
        "daily_logistics":decorate_timed_rows(selected,raw_shift,list_daily_logistics(selected),"start_time"),
        "attendance":attendance_for(selected),"logs":list_work_logs()
    })

@app.post("/daily-work/{item_id}/toggle")
def daily_toggle(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    toggle_daily_work(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

@app.post("/attendance/check-in")
def attendance_check_in(request:Request,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    check_in(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

@app.post("/attendance/check-out")
def attendance_check_out(request:Request,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    check_out(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

@app.post("/logistics/{item_id}/arrive")
def logistics_start(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    logistics_arrive(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

@app.post("/logistics/{item_id}/complete")
def logistics_finish(request:Request,item_id:int,work_date:str=Form(...)):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    logistics_complete(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

@app.post("/work-records")
def log_add(request:Request,work_date:str=Form(...),category:str=Form(...),title:str=Form(...),amount:int=Form(0),note:str=Form("")):
    user,resp=protected(request,"/work-records")
    if resp:return resp
    add_work_log(work_date,category,title,max(amount,0),note)
    return RedirectResponse(f"/work-records?work_date={work_date}&updated=1",303)

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
    return RedirectResponse("/notifications?completed=1",303)

@app.post("/reminders/{item_id}/delete")
def reminder_remove(request:Request,item_id:int):
    user,resp=protected(request,"/notifications")
    if resp:return resp
    delete_reminder(item_id)
    return RedirectResponse("/notifications?deleted=1",303)

@app.get("/tasks",response_class=HTMLResponse)
def tasks_page(request:Request):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    return templates.TemplateResponse("tasks.html",{"request":request,"user":user,"tasks":list_tasks()})

@app.post("/tasks")
def task_add(request:Request,title:str=Form(...),due_date:str=Form(""),note:str=Form("")):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    add_task(title,due_date,note)
    return RedirectResponse("/tasks?saved=1",303)

@app.post("/tasks/{item_id}/toggle")
def task_toggle(request:Request,item_id:int):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    toggle_task(item_id)
    return RedirectResponse("/tasks?updated=1",303)

@app.post("/tasks/{item_id}/delete")
def task_remove(request:Request,item_id:int):
    user,resp=protected(request,"/tasks")
    if resp:return resp
    delete_task(item_id)
    return RedirectResponse("/tasks?deleted=1",303)

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
    now=datetime.now()
    today=date.today().isoformat()
    work_date,shift,daily_work,daily_logistics,next_work_item=dashboard_work_context(now)
    reminders=[x for x in list_reminders(False) if x["remind_date"]==today]
    return {
        "ok":True,"active_work_date":work_date,
        "shift":shift,
        "daily_work":daily_work,
        "daily_logistics":daily_logistics,
        "next_work_item":next_work_item,
        "attendance":attendance_for(work_date),
        "counts":dashboard_counts(work_date),
        "weather":get_taiping_weather(),
        "official_info":get_official_info(),
        "next_shift":get_next_shift(today),
        "reminder":reminders[0] if reminders else None,
        "updated_at":datetime.now().strftime("%H:%M:%S")
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
