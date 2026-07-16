import base64, hashlib, hmac, requests
from config import settings

def verify_signature(raw_body, signature):
    if not settings.line_channel_secret or not signature:
        return False
    digest = hmac.new(settings.line_channel_secret.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)

def reply_message(reply_token, messages):
    if not settings.line_channel_access_token:
        return
    r = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"replyToken": reply_token, "messages": messages},
        timeout=15,
    )
    r.raise_for_status()

def work_entry_flex(base_url=None):
    return {
        "type": "flex",
        "altText": "Work Life 網頁入口",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#E9E5FF",
                "contents": [{"type": "text", "text": "🤖 Work Life 助手", "weight": "bold", "size": "lg", "color": "#5548A9"}],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#FAF9FF",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "歡迎回來，佑佑", "weight": "bold", "size": "xl", "color": "#2D2851"},
                    {"type": "text", "text": "班表與生活管理，都在這裡。", "wrap": True, "color": "#69627E"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#FAF9FF",
                "contents": [{
                    "type": "button",
                    "style": "primary",
                    "color": "#8B73E8",
                    "action": {"type": "uri", "label": "進入 Work Life", "uri": f"{(base_url or settings.base_url)}/login"},
                }],
            },
        },
    }


def push_message(user_id, messages):
    if not settings.line_channel_access_token or not user_id:
        return False
    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"to": user_id, "messages": messages},
        timeout=15,
    )
    response.raise_for_status()
    return True

def reminder_flex(title, content, url):
    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#EAE6FF",
                "contents": [
                    {"type": "text", "text": "🤖 Work Life 提醒", "weight": "bold", "color": "#5649A8"}
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold", "size": "xl", "wrap": True, "color": "#2D2851"},
                    {"type": "text", "text": content or "請查看 Work Life。", "wrap": True, "color": "#6C657E"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#8069E7",
                        "action": {"type": "uri", "label": "開啟 Work Life", "uri": url},
                    }
                ],
            },
        },
    }
