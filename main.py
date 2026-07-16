from datetime import date
import json

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import build_authorize_url, exchange_code, get_profile, new_state
from .config import settings
from .database import init_db, upsert_user, list_shifts, upsert_shift, get_today_shift
from .line_api import verify_signature, reply_message, work_entry_flex

app = FastAPI(title="Work Life", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.base_url.startswith("https://"),
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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
    return {"status": "ok"}

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
        {"request": request, "user": user, "today": today, "shift": get_today_shift(today)},
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
