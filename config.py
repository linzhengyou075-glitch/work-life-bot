from dataclasses import dataclass
import os


def _base_url() -> str:
    value = (os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000").strip()
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    base_url: str = _base_url()
    session_secret: str = os.getenv("SESSION_SECRET", "work-life-stable-session-secret-v1")
    line_login_channel_id: str = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
    line_login_channel_secret: str = os.getenv("LINE_LOGIN_CHANNEL_SECRET", "").strip()
    line_channel_secret: str = os.getenv("LINE_CHANNEL_SECRET", "").strip()
    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    owner_line_user_id: str = os.getenv("OWNER_LINE_USER_ID", "").strip()

    @property
    def line_login_ready(self) -> bool:
        return bool(self.line_login_channel_id and self.line_login_channel_secret and self.base_url)

settings = Settings()
