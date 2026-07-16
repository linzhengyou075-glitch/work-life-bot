from datetime import date, datetime
import asyncio
import json
import requests

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import build_authorize_url, exchange_code, get_profile, new_state
from config import settings
from database import (
    init_db, upsert_user, list_shift_types, add_shift_type,
    list_shifts, get_shift, get_today_shift, save_shift, delete_shift,
    list_templates, get_template, add_template_item, delete_template_item,
    list_daily_work, toggle_daily_work,
    attendance_for, check_in, check_out,
    inventory_for, inventory_arrive, inventory_complete,
    add_work_log, list_work_logs, delete_work_log,
    add_task, list_tasks, toggle_task, delete_task, dashboard_counts,
    add_reminder, list_reminders, list_today_carousel_reminders, due_reminders,
    mark_reminder_sent, complete_reminder, delete_reminder,
    add_notification_log, list_notification_logs,
    upsert_health_record, get_health_record, list_health_records,
    add_finance_record, delete_finance_record, list_finance_records, finance_summary,
    upsert_card, list_cards, set_app_setting, get_app_setting,
)
from line_api import verify_signature, reply_message, work_entry_flex, push_message, reminder_flex

app = FastAPI(title="Work Life", version="2.1.0")
templates = Jinja2Templates(directory=".")
templates_engine = templates

PUBLIC_PATHS = {
    "/",
    "/login-page",
    "/login",
    "/auth/line/callback",
    "/logout",
    "/privacy",
    "/terms",
    "/webhook",
    "/healthz",
}
PUBLIC_PREFIXES = ("/static/",)

@app.middleware("http")
async def browser_login_guard(request: Request, call_next):
    """
    Browser pages automatically return to LINE Login instead of exposing
    a JSON 401 error. Static files, OAuth callback, legal pages, webhook,
    and health checks remain public.
    """
    path = request.url.path
    is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

    if not is_public and not request.session.get("user"):
        # Preserve the page the user originally wanted to open.
        if request.method == "GET" and not path.startswith("/api/"):
            next_path = path
            if request.url.query:
                next_path += f"?{request.url.query}"
            request.session["login_next"] = next_path
            return RedirectResponse("/login-page", status_code=302)

        if path.startswith("/api/"):
            return JSONResponse({"ok": False, "detail": "尚未登入"}, status_code=401)

        request.session["login_next"] = "/dashboard"
        return RedirectResponse("/login-page", status_code=303)

    return await call_next(request)

# Session 必須包在登入攔截器外層，網頁才能正常讀取登入狀態。
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.base_url.startswith("https://"),
)

@app.get("/static/style.css")
def static_style():
    return FileResponse("style.css", media_type="text/css")


@app.get("/static/app.js")
def static_js():
    return FileResponse("app.js", media_type="application/javascript")

@app.get("/static/worklife_mascot.png")
def static_mascot():
    return FileResponse("worklife_mascot.png", media_type="image/png")

@app.get("/static/worklife_frame.png")
def static_frame():
    return FileResponse("worklife_frame.png", media_type="image/png")

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(reminder_worker())

async def reminder_worker():
    while True:
        try:
            now = datetime.now()
            for reminder in due_reminders(now.strftime("%Y-%m-%d"), now.strftime("%H:%M")):
                title = reminder["title"]
                content = reminder["note"] or f'{reminder["remind_time"]} 的提醒'
                url = f'{settings.base_url}{reminder["related_url"] or "/dashboard"}'
                try:
                    sent = push_message(
                        settings.owner_line_user_id,
                        [reminder_flex(title, content, url)],
                    )
                    if sent:
                        mark_reminder_sent(reminder["id"])
                        add_notification_log(title, content, reminder["reminder_type"], "sent")
                except Exception as exc:
                    add_notification_log(title, str(exc), reminder["reminder_type"], "failed")
        except Exception:
            pass
        await asyncio.sleep(60)

def fetch_weather():
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 24.127,
                "longitude": 120.718,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "hourly": "precipitation_probability",
                "timezone": "Asia/Taipei",
                "forecast_days": 1,
            },
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        current = data.get("current", {})
        hourly = data.get("hourly", {})
        probs = hourly.get("precipitation_probability", [])
        return {
            "temperature": current.get("temperature_2m"),
            "apparent": current.get("apparent_temperature"),
            "wind": current.get("wind_speed_10m"),
            "rain_probability": max(probs) if probs else 0,
            "code": current.get("weather_code"),
            "updated_at": current.get("time"),
        }
    except Exception:
        return {
            "temperature": None,
            "apparent": None,
            "wind": None,
            "rain_probability": None,
            "code": None,
            "updated_at": None,
        }

def require_owner(request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="尚未登入")
    if not settings.owner_line_user_id:
        raise HTTPException(status_code=503, detail="尚未設定管理者 LINE User ID")
    if user.get("userId") != settings.owner_line_user_id:
        raise HTTPException(status_code=403, detail="此系統僅限管理者使用")
    return user

@app.get("/healthz")
def health_check():
    return {"status": "ok", "version": "2.1.1"}

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", 302)
    request.session["login_next"] = "/dashboard"
    return RedirectResponse("/login-page", 302)

@app.get("/login-page", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", 302)
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
def login(request: Request):
    state = new_state()
    request.session["oauth_state"] = state
    return RedirectResponse(build_authorize_url(state), 302)

@app.get("/auth/line/callback")
def line_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return templates.TemplateResponse("error.html", {"request": request, "message": f"LINE Login 失敗：{error}"}, status_code=400)
    expected = request.session.pop("oauth_state", None)
    if not code or not state or not expected or state != expected:
        return templates.TemplateResponse("error.html", {"request": request, "message": "登入驗證失敗，請重新登入。"}, status_code=400)

    token = exchange_code(code)
    profile = get_profile(token["access_token"])

    if not settings.owner_line_user_id:
        return templates.TemplateResponse("error.html", {"request": request, "message": "尚未設定管理者 LINE User ID。"}, status_code=503)
    if profile.get("userId") != settings.owner_line_user_id:
        return templates.TemplateResponse("denied.html", {"request": request}, status_code=403)

    upsert_user(profile["userId"], profile.get("displayName", "佑佑"), profile.get("pictureUrl"))
    request.session["user"] = profile
    next_url = request.session.pop("login_next", "/dashboard")
    if not isinstance(next_url, str) or not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/dashboard"
    return RedirectResponse(next_url, 302)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login-page", 302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_owner(request)
    today = date.today().isoformat()
    shift = get_today_shift(today)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "today": today,
            "shift": shift,
            "counts": dashboard_counts(today),
            "tasks": list_tasks(show_done=False)[:5],
            "daily_work": list_daily_work(today),
            "attendance": attendance_for(today),
            "inventory": inventory_for(today),
            "reminders": list_today_carousel_reminders(today),
            "weather": fetch_weather(),
            "health": get_health_record(today),
        },
    )

@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "user": user,
            "shifts": list_shifts(),
            "shift_types": list_shift_types(active_only=True),
            "templates": list_templates(),
        },
    )

@app.post("/schedule")
def schedule_save(
    request: Request,
    work_date: str = Form(...),
    shift_type_id: int = Form(...),
    overtime: str = Form(""),
    overtime_end: str = Form(""),
    note: str = Form(""),
):
    require_owner(request)
    save_shift(work_date, shift_type_id, overtime == "1", overtime_end, note.strip())
    return RedirectResponse("/schedule?saved=1", 303)

@app.post("/schedule/delete")
def schedule_delete(request: Request, work_date: str = Form(...)):
    require_owner(request)
    delete_shift(work_date)
    return RedirectResponse("/schedule?deleted=1", 303)

@app.post("/shift-types")
def shift_type_create(
    request: Request,
    name: str = Form(...),
    store_code: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    color: str = Form("#8f7aea"),
    icon: str = Form("🌙"),
    template_id: str = Form(""),
):
    require_owner(request)
    add_shift_type(name.strip(), store_code, start_time, end_time, color, icon, int(template_id) if template_id else None)
    return RedirectResponse("/schedule?shift_type_saved=1", 303)

@app.get("/work-records", response_class=HTMLResponse)
def work_records_page(request: Request, work_date: str | None = None, template_id: int | None = None):
    user = require_owner(request)
    selected_date = work_date or date.today().isoformat()
    templates = list_templates()
    selected_template = get_template(template_id or (templates[0]["id"] if templates else 0)) if templates else None
    return templates_engine.TemplateResponse(
        "work_records.html",
        {
            "request": request,
            "user": user,
            "selected_date": selected_date,
            "daily_work": list_daily_work(selected_date),
            "logs": list_work_logs(),
            "templates": templates,
            "selected_template": selected_template,
            "attendance": attendance_for(selected_date),
            "inventory": inventory_for(selected_date),
            "shift": get_shift(selected_date),
        },
    )

@app.post("/work-records")
def save_work_record(
    request: Request,
    work_date: str = Form(...),
    store_code: str = Form(...),
    category: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    amount: int = Form(0),
):
    require_owner(request)
    if store_code not in {"B", "C"}:
        raise HTTPException(status_code=400, detail="店舖資料不正確")
    if category not in {"handover", "shortage", "note"}:
        raise HTTPException(status_code=400, detail="紀錄類型不正確")
    add_work_log(work_date, store_code, category, title.strip(), content.strip(), max(amount, 0))
    return RedirectResponse("/work-records?saved=1", 303)

@app.post("/work-records/{log_id}/delete")
def remove_work_record(request: Request, log_id: int):
    require_owner(request)
    delete_work_log(log_id)
    return RedirectResponse("/work-records?deleted=1", 303)

@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "tasks.html",
        {"request": request, "user": user, "tasks": list_tasks()},
    )

@app.post("/tasks")
def save_task(
    request: Request,
    title: str = Form(...),
    due_date: str = Form(""),
    note: str = Form(""),
):
    require_owner(request)
    add_task(title.strip(), due_date.strip() or None, note.strip())
    return RedirectResponse("/tasks?saved=1", 303)

@app.post("/tasks/{task_id}/toggle")
def task_toggle(request: Request, task_id: int):
    require_owner(request)
    toggle_task(task_id)
    return RedirectResponse("/tasks", 303)

@app.post("/tasks/{task_id}/delete")
def task_delete(request: Request, task_id: int):
    require_owner(request)
    delete_task(task_id)
    return RedirectResponse("/tasks?deleted=1", 303)


@app.post("/daily-work/{item_id}/toggle")
def daily_work_toggle(request: Request, item_id: int, work_date: str = Form(...)):
    require_owner(request)
    toggle_daily_work(item_id)
    return RedirectResponse(f"/work-records?work_date={work_date}", 303)

@app.post("/templates/{template_id}/items")
def template_item_add(
    request: Request,
    template_id: int,
    title: str = Form(...),
    scheduled_time: str = Form(""),
    category: str = Form("work"),
):
    require_owner(request)
    add_template_item(template_id, title.strip(), scheduled_time, category)
    return RedirectResponse(f"/work-records?template_id={template_id}", 303)

@app.post("/template-items/{item_id}/delete")
def template_item_remove(request: Request, item_id: int, template_id: int = Form(...)):
    require_owner(request)
    delete_template_item(item_id)
    return RedirectResponse(f"/work-records?template_id={template_id}", 303)

@app.post("/attendance/check-in")
def attendance_check_in(request: Request, work_date: str = Form(...)):
    require_owner(request)
    shift = get_shift(work_date)
    check_in(work_date, shift["id"] if shift else None)
    return RedirectResponse("/dashboard", 303)

@app.post("/attendance/check-out")
def attendance_check_out(request: Request, work_date: str = Form(...)):
    require_owner(request)
    check_out(work_date)
    return RedirectResponse("/dashboard", 303)

@app.post("/inventory/arrive")
def inventory_arrived(request: Request, work_date: str = Form(...)):
    require_owner(request)
    inventory_arrive(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}", 303)

@app.post("/inventory/complete")
def inventory_completed(request: Request, work_date: str = Form(...)):
    require_owner(request)
    inventory_complete(work_date)
    return RedirectResponse(f"/work-records?work_date={work_date}", 303)

@app.get("/life", response_class=HTMLResponse)
def life_page(request: Request):
    user = require_owner(request)
    today = date.today().isoformat()
    return templates.TemplateResponse(
        "life.html",
        {
            "request": request,
            "user": user,
            "today": today,
            "reminders": list_reminders(include_done=False),
            "tasks": list_tasks(show_done=False),
        },
    )

@app.get("/finance", response_class=HTMLResponse)
def finance_page(request: Request):
    user = require_owner(request)
    month = date.today().strftime("%Y-%m")
    return templates.TemplateResponse(
        "finance.html",
        {
            "request": request,
            "user": user,
            "today": date.today().isoformat(),
            "records": list_finance_records(),
            "summary": finance_summary(month),
        },
    )

@app.post("/finance")
def finance_add(
    request: Request,
    record_date: str = Form(...),
    record_type: str = Form(...),
    category: str = Form("其他"),
    title: str = Form(...),
    amount: int = Form(...),
    note: str = Form(""),
):
    require_owner(request)
    add_finance_record(record_date, record_type, category, title.strip(), max(amount, 0), note.strip())
    return RedirectResponse("/finance?saved=1", 303)

@app.post("/finance/{record_id}/delete")
def finance_remove(request: Request, record_id: int):
    require_owner(request)
    delete_finance_record(record_id)
    return RedirectResponse("/finance?deleted=1", 303)

@app.get("/health", response_class=HTMLResponse)
def health_page(request: Request):
    user = require_owner(request)
    today = date.today().isoformat()
    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "user": user,
            "today": today,
            "record": get_health_record(today),
            "history": list_health_records(),
        },
    )

@app.post("/health")
def health_save(
    request: Request,
    record_date: str = Form(...),
    steps: int = Form(0),
    heart_rate: int = Form(0),
    sleep_hours: int = Form(0),
    sleep_minutes: int = Form(0),
    calories: int = Form(0),
    water_ml: int = Form(0),
    weight: float = Form(0),
    note: str = Form(""),
):
    require_owner(request)
    total_sleep = max(sleep_hours, 0) * 60 + max(sleep_minutes, 0)
    upsert_health_record(
        record_date, max(steps,0), max(heart_rate,0), total_sleep,
        max(calories,0), max(water_ml,0), max(weight,0), note.strip()
    )
    return RedirectResponse("/health?saved=1", 303)

@app.get("/cards", response_class=HTMLResponse)
def cards_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "cards.html",
        {"request": request, "user": user, "cards": list_cards()},
    )

@app.post("/cards")
def cards_save(
    request: Request,
    card_type: str = Form(...),
    label: str = Form(...),
    barcode_value: str = Form(...),
    note: str = Form(""),
):
    require_owner(request)
    upsert_card(card_type, label.strip(), barcode_value.strip(), note.strip())
    return RedirectResponse("/cards?saved=1", 303)

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "weather_enabled": get_app_setting("weather_enabled", "1"),
            "line_push_enabled": get_app_setting("line_push_enabled", "1"),
            "auto_refresh_seconds": get_app_setting("auto_refresh_seconds", "15"),
        },
    )

@app.post("/profile/settings")
def profile_settings(
    request: Request,
    weather_enabled: str = Form("0"),
    line_push_enabled: str = Form("0"),
    auto_refresh_seconds: str = Form("15"),
):
    require_owner(request)
    set_app_setting("weather_enabled", weather_enabled)
    set_app_setting("line_push_enabled", line_push_enabled)
    set_app_setting("auto_refresh_seconds", auto_refresh_seconds)
    return RedirectResponse("/profile?saved=1", 303)

@app.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "notifications.html",
        {
            "request": request,
            "user": user,
            "reminders": list_reminders(),
            "logs": list_notification_logs(),
            "today": date.today().isoformat(),
        },
    )

@app.post("/reminders")
def reminder_add(
    request: Request,
    title: str = Form(...),
    reminder_type: str = Form("custom"),
    remind_date: str = Form(...),
    remind_time: str = Form(...),
    related_url: str = Form("/dashboard"),
    note: str = Form(""),
    line_push: str = Form(""),
    show_carousel: str = Form(""),
):
    require_owner(request)
    add_reminder(
        title.strip(), reminder_type, remind_date, remind_time,
        related_url, note.strip(), line_push == "1", show_carousel == "1"
    )
    return RedirectResponse("/notifications?saved=1", 303)

@app.post("/reminders/{reminder_id}/complete")
def reminder_complete(request: Request, reminder_id: int):
    require_owner(request)
    complete_reminder(reminder_id)
    return RedirectResponse("/notifications", 303)

@app.post("/reminders/{reminder_id}/delete")
def reminder_remove(request: Request, reminder_id: int):
    require_owner(request)
    delete_reminder(reminder_id)
    return RedirectResponse("/notifications?deleted=1", 303)

@app.get("/api/weather")
def weather_api(request: Request):
    require_owner(request)
    return {"ok": True, "weather": fetch_weather()}


@app.get("/api/dashboard-state")
def dashboard_state(request: Request):
    require_owner(request)
    today = date.today().isoformat()
    return {
        "ok": True,
        "today": today,
        "shift": get_today_shift(today),
        "counts": dashboard_counts(today),
        "daily_work": list_daily_work(today),
        "attendance": attendance_for(today),
        "inventory": inventory_for(today),
        "reminders": list_today_carousel_reminders(today),
        "weather": fetch_weather(),
        "health": get_health_record(today),
    }

@app.get("/api/schedule-state")
def schedule_state(request: Request):
    require_owner(request)
    return {"ok": True, "shifts": list_shifts()}

@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("x-line-signature", "")):
        raise HTTPException(status_code=400, detail="Invalid signature")
    payload = json.loads(raw.decode())
    for event in payload.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            if event["message"]["text"].strip().lower() == "/work":
                reply_message(event["replyToken"], [work_entry_flex()])
    return JSONResponse({"ok": True})
