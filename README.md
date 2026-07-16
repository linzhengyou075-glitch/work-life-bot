# Work Life Bot 第一包

已完成：
- 獨立 FastAPI 專案
- `/work` LINE 入口卡片
- LINE Login
- 僅指定管理者可登入
- 粉藍／粉紫動態首頁
- 班表新增、修改與列表
- 代碼：15B、15C、B、C、X
- 隱私權政策與使用條款
- Render 部署設定

部署後需設定：
- Webhook URL：`https://你的網址/webhook`
- Callback URL：`https://你的網址/auth/line/callback`
- Privacy URL：`https://你的網址/privacy`
- Terms URL：`https://你的網址/terms`

密鑰只放 Render 環境變數，不要再貼到聊天室。
