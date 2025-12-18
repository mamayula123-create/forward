import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import ChatAdminRequiredError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def load_config(path: str = 'config.json') -> dict:
    p = Path(path)
    if not p.exists():
        logging.error('Config file %s not found', path)
        raise SystemExit(1)
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


async def main():
    cfg = load_config()
    api_id = cfg.get('api_id')
    api_hash = cfg.get('api_hash')
    session = cfg.get('session_name', 'forward_session')
    src = cfg.get('source_bot_username')
    # поддерживаем либо username, либо numeric id через ключ target_channel_id
    dst = cfg.get('target_channel_id') if cfg.get('target_channel_id') is not None else cfg.get('target_channel_username')

    if not all([api_id, api_hash, src, dst]):
        logging.error('Please fill api_id, api_hash, source_bot_username and target_channel_username in config.json')
        raise SystemExit(1)

    # безопасно убираем @ только для строковых значений
    if isinstance(src, str):
        src = src.lstrip('@')
    else:
        src = str(src)

    if isinstance(dst, str):
        dst = dst.lstrip('@')

    # convert api_id to int if it's a string
    try:
        api_id = int(api_id)
    except Exception:
        logging.error('api_id must be an integer in config.json')
        raise SystemExit(1)

    # if target is a numeric id (like -100...), convert to int
    try:
        if isinstance(dst, int):
            pass
        else:
            if isinstance(dst, str) and (dst.startswith('-') or dst.isdigit()):
                dst = int(dst)
    except Exception:
        pass

    client = TelegramClient(session, api_id, api_hash)
    await client.start()

    try:
        src_entity = await client.get_entity(src)
    except Exception as e:
        logging.exception('Не удалось получить сущность источника %s: %s', src, e)
        await client.disconnect()
        raise

    try:
        dst_entity = await client.get_entity(dst)
    except Exception as e:
        logging.exception('Не удалось получить сущность цели %s: %s', dst, e)
        await client.disconnect()
        raise

    # Попробуем заранее получить сущность PriceNFTbot, чтобы корректно ждать его ответ
    pricebot_entity = None
    try:
        pricebot_entity = await client.get_entity('PriceNFTbot')
    except Exception:
        logging.warning('Не удалось получить сущность PriceNFTbot — ответы от него не будут отслеживаться')

    logging.info('Пересылка сообщений от @%s -> @%s', src, dst)

    # --- стартовая тестовая логика для MONK: отправляем username в PriceNFTbot
    # и текст с возможным профитом в канал с пометкой теста
    try:
            if cfg.get('test_monk', True):
                monk = cfg.get('test_monk_username', '@Veisyamegzovich').lstrip('@')
                test_profit = cfg.get('test_profit', '0')
                if pricebot_entity is None:
                    logging.warning('PriceNFTbot не доступен, пропускаю тестовый запрос')
                else:
                    async with client.conversation(pricebot_entity, timeout=8) as conv:
                        try:
                            await conv.send_message(f'@{monk}')
                            logging.info('Отправлен тестовый username в PriceNFTbot: %s', monk)
                            try:
                                resp = await conv.get_response()
                            except asyncio.TimeoutError:
                                logging.warning('Нет ответа от PriceNFTbot на тестовый запрос')
                                resp = None
                        except Exception:
                            logging.exception('Не удалось отправить username в PriceNFTbot (тест)')
                            resp = None

                    if resp:
                        try:
                            # извлекаем часть с TON ≈ $ и отправляем только её
                            resp_text = (getattr(resp, 'message', None) or getattr(resp, 'text', '') or '')
                            m = re.search(r"[\d\.,]+\s*TON\s*≈\s*[\d\.,]+\s*\$", resp_text, re.IGNORECASE)
                            if m:
                                extracted = m.group(0).strip()
                                # форматируем: жирная строка с подчёркнутым словом ПРОФИТ и суммами
                                formatted = f"<b>💸 Возможный <u>ПРОФИТ: {extracted}</u></b>"
                                test_prefix = 'ТЕСТОВАЯ проверка профита\n'
                                try:
                                    await client.send_message(dst_entity, test_prefix + formatted, parse_mode='html')
                                    logging.info('Отправлен извлечённый профит (тест): %s', extracted)
                                except Exception:
                                    logging.exception('Не удалось обработать/отправить ответ PriceNFTbot (тест)')
                            else:
                                logging.warning('Не найден шаблон TON ≈ $ в ответе PriceNFTbot (тест)')
                        except Exception:
                            logging.exception('Не удалось обработать/отправить ответ PriceNFTbot (тест)')
    except Exception:
        logging.exception('Ошибка при выполнении стартовой тестовой логики MONK')

    @client.on(events.NewMessage(from_users=src_entity))
    async def handler(event: events.NewMessage.Event):
        msg = event.message
        text = (getattr(msg, 'message', None) or getattr(msg, 'text', '') or '').strip()
        canon = text.lstrip()
        lower = text.lower()

        # 1) Форматированный переход: пытаемся извлечь username, id и action
        m_user = re.search(r'@[_A-Za-z0-9]{3,}', text)
        username = m_user.group(0) if m_user else None

        m_id = re.search(r'ID[:\s]*([\-\d]{5,})', text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(r'\b(\d{5,})\b', text)
        uid = m_id.group(1) if m_id else None

        m_action = re.search(r'(/[A-Za-z0-9_]+)', text)
        if not m_action:
            m_action = re.search(r'Действие[:\s]*([^\n\r]+)', text, re.IGNORECASE)
        action = m_action.group(1).strip() if m_action else None

        if username and uid and action:
            formatted = (
                '🎯 Новый переход!\n\n'
                f'👤 Пользователь: {username} (ID: {uid})\n'
                f'💻 Действие: {action}'
            )
            try:
                await client.send_message(dst_entity, formatted)
                logging.info('Отправлено форматированное сообщение для %s', username)
            except Exception:
                logging.exception('Ошибка при отправке форматированного сообщения')
            return

        # 2) Точные сообщения, начинающиеся с заданных фраз (учитываем варианты с пробелом)
        if canon.startswith('🎯 Новое действие!'):
            try:
                await client.send_message(dst_entity, text)
                logging.info('Отправлено сообщение: 🎯 Новое действие!')
            except Exception:
                logging.exception('Ошибка при отправке сообщения 🎯 Новое действие!')
            return

        if canon.startswith('🍏УСПЕШНАЯ АВТОРИЗАЦИЯ') or canon.startswith('🍏 УСПЕШНАЯ АВТОРИЗАЦИЯ'):
            # отправляем сам текст в канал
            try:
                await client.send_message(dst_entity, text)
                logging.info('Отправлено сообщение: УСПЕШНАЯ АВТОРИЗАЦИЯ')
            except ChatAdminRequiredError:
                logging.warning('Нет прав отправлять в канал: УСПЕШНАЯ АВТОРИЗАЦИЯ')
            except Exception:
                logging.exception('Ошибка при отправке сообщения УСПЕШНАЯ АВТОРИЗАЦИЯ')

            # извлекаем username из текста и отправляем в @PriceNFTbot
            m_user_auth = re.search(r'@[_A-Za-z0-9]{3,}', text)
            if m_user_auth:
                username_to_send = m_user_auth.group(0)
                try:
                    await client.send_message('PriceNFTbot', username_to_send)
                    logging.info('Отправлен username в PriceNFTbot: %s', username_to_send)
                except Exception:
                    logging.exception('Не удалось отправить username в PriceNFTbot')

            # ждём ответ от PriceNFTbot и пересылаем его сообщение в канал
            try:
                if pricebot_entity is None:
                    logging.warning('PriceNFTbot не доступен, пропускаю ожидание ответа')
                else:
                    async with client.conversation(pricebot_entity, timeout=8) as conv:
                        try:
                            resp = await conv.get_response()
                        except asyncio.TimeoutError:
                            logging.warning('Нет ответа от PriceNFTbot за отведённое время')
                            resp = None

                    if resp:
                        try:
                            # извлекаем только 'TON ≈ $' часть и отправляем её в канал, и делаем reply на сообщение авторизации
                            resp_text = (getattr(resp, 'message', None) or getattr(resp, 'text', '') or '')
                            m = re.search(r"[\d\.,]+\s*TON\s*≈\s*[\d\.,]+\s*\$", resp_text, re.IGNORECASE)
                            if m:
                                extracted = m.group(0).strip()
                                formatted = f"<b>💸 Возможный <u>ПРОФИТ: {extracted}</u></b>"
                                try:
                                    # reply to original authorization message
                                    await event.reply(formatted, parse_mode='html')
                                except Exception:
                                    logging.exception('Не удалось отправить reply с возможным профитом')
                                try:
                                    await client.send_message(dst_entity, formatted, parse_mode='html')
                                    logging.info('Отправлен извлечённый профит: %s', extracted)
                                except ChatAdminRequiredError:
                                    logging.warning('Нет прав отправлять извлечённый профит в канал')
                                except Exception:
                                    logging.exception('Ошибка при отправке извлечённого профита')
                            else:
                                logging.warning('Не найден шаблон TON ≈ $ в ответе PriceNFTbot — ничего не отправляю')
                        except Exception:
                            logging.exception('Ошибка при обработке/отправке ответа PriceNFTbot')
                    else:
                        logging.warning('Ответ PriceNFTbot отсутствует, ничего не пересылаю')
            except Exception:
                logging.exception('Ошибка при ожидании/обработке ответа PriceNFTbot')

            return

        if canon.startswith('💸 УСПЕШНАЯ ОБРАБОТКА МАМОНТА') or canon.startswith('💸УСПЕШНАЯ ОБРАБОТКА МАМОНТА'):
            try:
                await client.send_message(dst_entity, text)
                logging.info('Отправлено сообщение: УСПЕШНАЯ ОБРАБОТКА МАМОНТА')
            except Exception:
                logging.exception('Ошибка при отправке сообщения УСПЕШНАЯ ОБРАБОТКА МАМОНТА')
            return

        # 3) Сообщения про мамонта/ошибки (на случай других вариантов) — отправляем целиком
        if 'мамонт' in lower or 'произошел конфуз' in lower or 'конфуз' in lower or 'доступ к сессии утерян' in lower:
            try:
                await client.send_message(dst_entity, text)
                logging.info('Отправлено сообщение про мамонта/ошибку')
            except Exception:
                logging.exception('Ошибка при отправке сообщения про мамонта/ошибку')
            return

        logging.info('Сообщение от %s пропущено — не соответствует ни одному правилу', src)

    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('Остановлено пользователем')
    except Exception:
        logging.exception('Фатальная ошибка')
        sys.exit(1)
