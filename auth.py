import secrets
from urllib.parse import urlencode
import requests
from config import settings


class LoginConfigError(RuntimeError):
    pass


def new_state():
    return secrets.token_urlsafe(24)


def build_authorize_url(state):
    if not settings.line_login_ready:
        raise LoginConfigError("尚未設定 LINE Login Channel ID 或 Channel Secret。")
    params = {
        "response_type": "code",
        "client_id": settings.line_login_channel_id,
        "redirect_uri": f"{settings.base_url}/auth/line/callback",
        "state": state,
        "scope": "profile openid",
    }
    return "https://access.line.me/oauth2/v2.1/authorize?" + urlencode(params)


def exchange_code(code):
    try:
        response = requests.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{settings.base_url}/auth/line/callback",
                "client_id": settings.line_login_channel_id,
                "client_secret": settings.line_login_channel_secret,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = exc.response.text[:300]
        raise RuntimeError(f"LINE 權杖交換失敗：{detail or exc}") from exc


def get_profile(access_token):
    try:
        response = requests.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError("無法取得 LINE 使用者資料。") from exc
