# VILAGROTEX — Railway

Готовий проєкт для роботи Telegram-бота 24/7 без відкритого Terminal на Mac.

## Що вже налаштовано

- `bot.py` — VILAGRO PRO PLUS.
- токен береться з Railway Variables, а не з коду;
- `railway.json` запускає `python bot.py`;
- Railway автоматично перезапускає бота;
- `overlapSeconds = 0`, щоб під час нового deploy не працювали одночасно два long-polling процеси;
- SQLite автоматично використовує Railway Volume через `RAILWAY_VOLUME_MOUNT_PATH`;
- Python зафіксовано на 3.13.2;
- `.gitignore` не дає випадково залити токен або локальну SQLite-базу.

## 1. Завантаж файли в GitHub

Створи новий repository, наприклад `vilagro-bot`.

Завантаж у корінь репозиторію:

- `bot.py`
- `requirements.txt`
- `railway.json`
- `.python-version`
- `.gitignore`
- `.env.example`

Не додавай реальний токен у GitHub.

## 2. Створи Railway service

Railway → New Project → Deploy from GitHub repo → вибери `vilagro-bot`.

## 3. Додай Variables

У сервісі Railway відкрий `Variables` і створи:

### Обов'язково
`BOT_TOKEN` = НОВИЙ токен від BotFather

### Уже мають правильні значення за замовчуванням
`ADMIN_ID` = `7097625447`
`CHANNEL` = `@VILAGROTEX`
`SUPPORT_USERNAME` = `@v1vchaaar`
`BOT_USERNAME` = `Vilagreo_bot`

### За бажанням
`OPENAI_API_KEY` = ключ OpenAI для AI-функцій

`OPENAI_MODEL` = модель OpenAI

`PAYMENT_DETAILS` = текст реквізитів для оплати

Після додавання секретного токена можеш використати в Railway опцію Seal.

## 4. ОБОВ'ЯЗКОВО додай Volume для SQLite

У Railway підключи Volume саме до сервісу бота.

Mount Path:
`/data`

Нічого в коді міняти не треба. Railway автоматично передасть шлях у
`RAILWAY_VOLUME_MOUNT_PATH`, а бот створить:

`/data/vilagro.db`

Так користувачі, баланси, оголошення, обране, оплати та інші дані
не повинні зникати після звичайного redeploy.

## 5. Deploy

Railway сам прочитає `railway.json`.

Start command:
`python bot.py`

У Logs після нормального запуску буде приблизно:

`🚜 VILAGROTEX BOT ЗАПУЩЕНИЙ`
`✅ Railway Volume: /data`

Після цього Mac і Terminal можна вимкнути — бот працює на Railway.

## Важливо про стару vilagro.db

Цей архів НЕ містить твою локальну `vilagro.db`, бо її не було серед файлів,
які я отримав у чаті.

Якщо треба перенести старих користувачів, баланси та оголошення,
не запускай надовго нову порожню базу. Надішли мені свій файл `vilagro.db`,
і я підготую його для перенесення без зміни даних.

## Безпека

Токен, який колись був показаний у чаті/на скріншотах, краще не використовувати.
Створи новий у BotFather і збережи тільки в Railway Variables.
