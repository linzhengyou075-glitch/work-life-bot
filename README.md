# Work Life Bot 第一包（手機平面上傳版）

這一包特別適合使用 GitHub 手機版上傳：所有檔案都放在同一層，不需要保留資料夾結構。

Render 設定：
- Build Command：`pip install -r requirements.txt`
- Start Command：`uvicorn main:app --host 0.0.0.0 --port $PORT`
- Instance Type：Free

已完成：
- `/work` LINE 入口卡片
- LINE Login
- 僅指定管理者可登入
- 粉藍／粉紫動態首頁
- 建昌／溪洲班表
- 快速代碼：15B、15C、B、C、X
- 隱私權政策與使用條款

部署後網址：
- Webhook：`https://你的網址/webhook`
- Callback：`https://你的網址/auth/line/callback`
- Privacy：`https://你的網址/privacy`
- Terms：`https://你的網址/terms`
