import secrets
from urllib.parse import urlencode
import requests
from config import settings

AUTH_URL = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
PROFILE_URL = "https://api.line.me/v2/profile"

def build_authorize_url(state):
    params = {
        "response_type": "code",
        "client_id": settings.line_login_channel_id,
        "redirect_uri": f"{settings.base_url}/auth/line/callback",
        "state": state,
        "scope": "profile openid",
    }
    return f"{AUTH_URL}?{urlencode(params)}"

def exchange_code(code):
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{settings.base_url}/auth/line/callback",
            "client_id": settings.line_login_channel_id,
            "client_secret": settings.line_login_channel_secret,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def get_profile(access_token):
    r = requests.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def new_state():
    return secrets.token_urlsafe(32)
