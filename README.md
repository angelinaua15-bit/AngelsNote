# 🪴 Planner Bot

Особистий Telegram-планер: задачі, нотатки, нагадування, ранковий план, вечірній підсумок, автоперенос, статистика.

Стек: Python 3.12 · aiogram 3 · Supabase (Postgres) · Vercel (serverless webhook) · pg_cron для нагадувань.

## Структура
- `api/webhook.py` — приймає апдейти від Telegram
- `api/cron.py` — щохвилини: нагадування, ранковий план, вечірній підсумок, автоперенос
- `api/setup.py` — разово реєструє webhook і меню команд
- `planner/` — логіка бота (handlers, ui, parse, db, jobs)
- `schema.sql` — схема бази (вже застосована в Supabase-проєкті planner-bot)

## Змінні середовища (Vercel → Settings → Environment Variables)
| Ключ | Значення |
|---|---|
| BOT_TOKEN | токен від @BotFather |
| SUPABASE_URL | https://qsjkijfpcouyleeakutq.supabase.co |
| SUPABASE_KEY | anon key проєкту (див. .env) |
| BOT_SECRET | див. .env |
