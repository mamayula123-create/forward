# Telethon forwarder

Короткая утилита для пересылки сообщений, которые присылает указанный Telegram-бот, в указанный канал, используя ваш аккаунт (userbot) через Telethon.

Настройка

1. Установите Python 3.9+ и pip.
2. Скопируйте `config.json` и заполните поля `api_id` и `api_hash` (можно получить на https://my.telegram.org), а также `source_bot_username`.

	Для целевого канала можно указать либо `target_channel_username` (например `@mychannel`), либо `target_channel_id` (например `-1001234567890`). Если оба указаны, будет использовано `target_channel_id`.
3. Установите зависимости:

```powershell
pip install -r requirements.txt
```

Запуск

```powershell
python forward_bot.py
```

Примечания

- Убедитесь, что ваш аккаунт уже получал сообщения от бота (или вы добавлены в канал), иначе скрипт может не получать события.
- Если нужно запускать как сервис на Windows, используйте NSSM или планировщик задач.
