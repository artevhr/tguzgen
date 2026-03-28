# TG Username Generator Bot

Telegram-бот для генерации редких юзернеймов с двумя тарифами.

## Возможности

| Функция | Free | Premium (89⭐/мес) |
|---|---|---|
| Длина юзернейма | 2–32 | 2–32 |
| Генераций в день | 30 | ∞ |
| Точность результатов | ~30% свободны | 100% свободны (API check) |
| Реферальная программа | ✅ | ✅ |

## Реферальная программа

- Пригласил 1 человека → **−5⭐** от цены Premium
- Максимальная скидка: **49⭐** (т.е. минимум 40⭐)
- ~9–10 рефералов для максимальной скидки

## Команды бота

- `/start` — главное меню
- `/start ref_<ID>` — вход по реферальной ссылке
- `/admin` — панель администратора (только для ADMIN_IDS)

## Установка локально

```bash
git clone <repo>
cd tg-username-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Отредактируй .env: вставь BOT_TOKEN и ADMIN_IDS
python main.py
```

## Деплой на Railway

1. Создай новый проект на [railway.app](https://railway.app)
2. Выбери **Deploy from GitHub** → подключи репозиторий
3. Добавь **Variables** в разделе настроек сервиса:
   - `BOT_TOKEN` — токен бота от @BotFather
   - `ADMIN_IDS` — твой Telegram ID (узнать у @userinfobot)
   - `DATABASE_PATH` — `bot.db` (или `/data/bot.db` если добавишь Volume)
4. *(Опционально)* Добавь **Volume** → смонтируй в `/data` → поставь `DATABASE_PATH=/data/bot.db`
5. Railway сам подберёт `Procfile` и задеплоит бота

> ⚠️ Без Volume база данных сбрасывается при каждом редеплое. Для продакшна рекомендуется добавить Volume.

## Структура проекта

```
tg-username-bot/
├── main.py           # Точка входа
├── config.py         # Конфиг из .env
├── database.py       # Все операции с БД (aiosqlite)
├── scheduler.py      # APScheduler — напоминания об окончании подписки
├── handlers/
│   ├── start.py      # /start, главное меню, реферальная ссылка
│   ├── generate.py   # FSM генерации юзернеймов
│   ├── profile.py    # Личный кабинет
│   ├── payment.py    # Оплата через Telegram Stars
│   └── admin.py      # Панель администратора
└── utils/
    ├── generator.py  # Генерация юзернеймов
    └── checker.py    # Проверка доступности через Telegram API
```

## Заметки

- **Проверка юзернеймов**: бот использует `getChat` API. Приватные аккаунты могут отображаться как "свободные" — это ограничение Telegram API.
- **Скорость Premium**: проверка каждого юзернейма занимает ~350мс (rate limit). 20 юзернеймов ≈ 7 сек.
- **Короткие юзернеймы** (2–4 символа): почти всегда заняты — это нормально.
