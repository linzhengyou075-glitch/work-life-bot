from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    base_url: str
    session_secret: str
    line_channel_secret: str
    line_channel_access_token: str
    line_login_channel_id: str
    line_login_channel_secret: str
    owner_line_user_id: str

    @classmethod
    def from_env(cls):
        return cls(
            base_url=os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"),
            session_secret=os.getenv("SESSION_SECRET", "dev-only-change-me"),
            line_channel_secret=os.getenv("LINE_CHANNEL_SECRET", ""),
            line_channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_login_channel_id=os.getenv("LINE_LOGIN_CHANNEL_ID", ""),
            line_login_channel_secret=os.getenv("LINE_LOGIN_CHANNEL_SECRET", ""),
            owner_line_user_id=os.getenv("WORK_OWNER_LINE_USER_ID", ""),
        )

settings = Settings.from_env()
