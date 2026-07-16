from datetime import date
import json

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import build_authorize_url, exchange_code, get_profile, new_state
from config import settings
from database import (
    init_db, upsert_user, list_shifts, upsert_shift, get_today_shift,
    add_work_log, list_work_logs, delete_work_log,
    add_task, list_tasks, toggle_task, delete_task, dashboard_counts,
)
from line_api import verify_signature, reply_message, work_entry_flex

app = FastAPI(title="Work Life", version="2.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.base_url.startswith("https://"),
)
templates = Jinja2Templates(directory=".")

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
def startup():
    init_db()

def require_owner(request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="尚未登入")
    if not settings.owner_line_user_id:
        raise HTTPException(status_code=503, detail="尚未設定管理者 LINE User ID")
    if user.get("userId") != settings.owner_line_user_id:
        raise HTTPException(status_code=403, detail="此系統僅限管理者使用")
    return user

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0"}

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/dashboard" if request.session.get("user") else "/login-page", 302)

@app.get("/login-page", response_class=HTMLResponse)
def login_page(request: Request):
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
    return RedirectResponse("/dashboard", 302)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login-page", 302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_owner(request)
    today = date.today().isoformat()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "today": today,
            "shift": get_today_shift(today),
            "counts": dashboard_counts(),
            "tasks": list_tasks(show_done=False)[:4],
        },
    )

@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("schedule.html", {"request": request, "user": user, "shifts": list_shifts()})

@app.post("/schedule")
def save_shift(
    request: Request,
    work_date: str = Form(...),
    quick_code: str = Form(""),
    store_code: str = Form("C"),
    shift_type: str = Form("night"),
    note: str = Form(""),
):
    require_owner(request)
    code = quick_code.strip().upper()
    if code:
        if code == "X":
            store_code, shift_type = "X", "off"
        else:
            store_code = "C" if "C" in code else "B"
            shift_type = "late" if "15" in code else "night"
    if store_code not in {"B","C","X"} or shift_type not in {"late","night","off"}:
        raise HTTPException(status_code=400, detail="班表資料不正確")
    if shift_type == "off":
        store_code = "X"
    upsert_shift(work_date, store_code, shift_type, note.strip())
    return RedirectResponse("/schedule?saved=1", 303)

@app.get("/work-records", response_class=HTMLResponse)
def work_records_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse(
        "work_records.html",
        {"request": request, "user": user, "logs": list_work_logs()},
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


@app.get("/life", response_class=HTMLResponse)
def life_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("life.html", {"request": request, "user": user})

@app.get("/finance", response_class=HTMLResponse)
def finance_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("finance.html", {"request": request, "user": user})

@app.get("/health", response_class=HTMLResponse)
def health_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("health.html", {"request": request, "user": user})

@app.get("/cards", response_class=HTMLResponse)
def cards_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("cards.html", {"request": request, "user": user})

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@app.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    user = require_owner(request)
    return templates.TemplateResponse("notifications.html", {"request": request, "user": user})

@app.get("/api/dashboard-state")
def dashboard_state(request: Request):
    require_owner(request)
    today = date.today().isoformat()
    shift = get_today_shift(today)
    counts = dashboard_counts()
    return {
        "ok": True,
        "today": today,
        "shift": shift,
        "counts": counts,
    }

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
