#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import logging
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus, ParseMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN_V2)
dp = Dispatcher()

# Хранилище активных голосований
active_votes = {}

# Глобальные настройки по чатам
chat_settings = {}

# Администраторы по чатам (помимо владельца)
chat_admins = {}

# Дефолтные значения
DEFAULT_SETTINGS = {
    'vote_duration': 300,
    'mute_duration': 300,
    'ban_duration': 0,
    'votes_needed_mute': 3,
    'votes_needed_ban': 5,
    'auto_delete_timeout': 300
}

AUTO_DELETE_TIMEOUT = 300


def escape_markdown(text: str) -> str:
    """Экранирование спецсимволов для MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def get_chat_settings(chat_id: int):
    """Получить настройки для чата, если нет - создать дефолтные"""
    if chat_id not in chat_settings:
        chat_settings[chat_id] = DEFAULT_SETTINGS.copy()
    return chat_settings[chat_id]


def get_chat_admins(chat_id: int) -> set:
    """Получить список администраторов чата"""
    if chat_id not in chat_admins:
        chat_admins[chat_id] = set()
    return chat_admins[chat_id]


async def auto_delete_message(chat_id: int, message_id: int, delay: int):
    """Автоматически удаляет сообщение через delay секунд"""
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Сообщение {message_id} удалено из чата {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")


async def delete_user_command(message: types.Message):
    """Удалить команду пользователя сразу"""
    try:
        await message.delete()
        logger.info(f"Команда пользователя {message.message_id} удалена из чата {message.chat.id}")
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")


async def is_owner(chat_id: int, user_id: int) -> bool:
    """Проверить, является ли пользователь владельцем чата"""
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status == ChatMemberStatus.CREATOR
    except Exception as e:
        logger.error(f"Ошибка при проверке владельца: {e}")
        return False


async def is_admin(chat_id: int, user_id: int) -> bool:
    """Проверить, является ли пользователь администратором (владельцем или назначенным админом)"""
    try:
        # Проверяем владельца
        if await is_owner(chat_id, user_id):
            return True

        # Проверяем назначенных админов
        if user_id in get_chat_admins(chat_id):
            return True

        # Проверяем Telegram администраторов
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status == ChatMemberStatus.ADMINISTRATOR
    except Exception as e:
        logger.error(f"Ошибка при проверке админа: {e}")
        return False


async def get_user_mention(user_id: int, first_name: str) -> str:
    """Получить упоминание пользователя"""
    return f"[{escape_markdown(first_name or f'user_{user_id}')}](tg://user?id={user_id})"


async def find_user_by_username(chat_id: int, username: str) -> dict:
    """Найти пользователя по username в чате"""
    try:
        # Убираем @ если есть
        username = username.lstrip('@').lower()

        # На деле нужно использовать username через @username
        # Telegram API требует ID, но мы можем попробовать через mention
        member = await bot.get_chat_member(chat_id, f"@{username}")
        return {"success": True, "user_id": member.user.id, "first_name": member.user.first_name}
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователя {username}: {e}")
        return {"success": False, "error": str(e)}


async def extract_username_from_text(text: str) -> str:
    """Извлечь username из текста команды"""
    # Ищем все упоминания (@username)
    matches = re.findall(r'@[\w_]+', text)
    if matches:
        return matches[0]  # Возвращаем первое найденное упоминание
    return None


@dp.message(Command(commands=['start']))
async def cmd_start(message: types.Message):
    """Команда /start - приветствие и основная информация"""
    welcome_text = (
        "👋 *Добро пожаловать в бота модерации\\!*\n\n"
        "Я помогаю поддерживать порядок в чате через **демократичное голосование**\\.\n\n"
        "🎯 *Основной функционал:*\n"
        "• 🔇 **Мьют** \\- временная блокировка сообщений\n"
        "• 🚫 **Бан** \\- удаление из чата\n"
        "• ⚙️ **Настройки** \\- управление параметрами \\(для админов\\)\n\n"
        "📖 *Как использовать:*\n"
        "`/vote_mute` \\- голосование о мьюте \\(ответьте на сообщение\\)\n"
        "`/vote_ban` \\- голосование о бане \\(ответьте на сообщение\\)\n"
        "`/help` \\- полная справка\n"
        "`/settings` \\- параметры чата \\(админы\\)\n\n"
        "💡 *Или используйте inline\\-режим:*\n"
        "`@ботник mute` или `@ботник ban` \\(после ответа на сообщение\\)"
    )

    response = await message.answer(welcome_text)
    asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, AUTO_DELETE_TIMEOUT))
    asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['help']))
async def cmd_help(message: types.Message):
    """Команда /help - полная справка"""
    settings = get_chat_settings(message.chat.id)

    ban_duration_text = (
        "♾️ *Вечный*" if settings['ban_duration'] == 0 
        else f"{settings['ban_duration'] // 60} *мин*"
    )

    help_text = (
        "📚 *Полная справка по боту*\n\n"
        "🔇 *МЬЮТ \\(временная блокировка\\):*\n"
        "1️⃣ Ответьте на сообщение пользователя\n"
        "2️⃣ Напишите `/vote_mute` или `@ботник mute`\n"
        "3️⃣ Участники голосуют кнопками 👍 / 👎\n"
        "4️⃣ Если голосов хватает \\- пользователь замьючивается\n\n"
        "🚫 *БАН \\(удаление из чата\\):*\n"
        "1️⃣ Ответьте на сообщение пользователя\n"
        "2️⃣ Напишите `/vote_ban` или `@ботник ban`\n"
        "3️⃣ Участники голосуют кнопками 👍 / 👎\n"
        "4️⃣ Если голосов хватает \\- пользователь удаляется\n\n"
        "⚙️ *Текущие параметры:*\n"
        f"• ⏱️ Время голосования: *{settings['vote_duration'] // 60} мин*\n"
        f"• 📊 Голосов для мьюта: *{settings['votes_needed_mute']}*\n"
        f"• 📊 Голосов для бана: *{settings['votes_needed_ban']}*\n"
        f"• ⏳ Длительность мьюта: *{settings['mute_duration'] // 60} мин*\n"
        f"• ⏳ Длительность бана: {ban_duration_text}\n\n"
        "⚡ *Команды администраторов:*\n"
        "`/settings` \\- просмотр настроек\n"
        "`/set_vote_time <сек>` \\- время голосования\n"
        "`/set_mute_time <сек>` \\- время мьюта\n"
        "`/set_ban_time <сек>` \\- время бана \\(0 \\= вечный\\)\n"
        "`/add_admin @username` \\- назначить администратора\n"
        "`/remove_admin @username` \\- убрать администратора"
    )

    response = await message.answer(help_text)
    asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, AUTO_DELETE_TIMEOUT))
    asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['settings']))
async def cmd_settings(message: types.Message):
    """Команда /settings - просмотр настроек"""
    if not await is_admin(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эта команда доступна только администраторам\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    settings = get_chat_settings(message.chat.id)
    admins = get_chat_admins(message.chat.id)

    settings_text = (
        "⚙️ *Текущие параметры чата:*\n\n"
        "⏱️ *Время голосования:*\n"
        f"`{settings['vote_duration']}` сек \\(`{settings['vote_duration'] // 60}` мин\\)\n\n"
        "🔇 *Время мьюта:*\n"
        f"`{settings['mute_duration']}` сек \\(`{settings['mute_duration'] // 60}` мин\\)\n\n"
        "🚫 *Время бана:*\n"
        f"`{settings['ban_duration']}` сек "
        f"\\(`0` \\= вечный, `{settings['ban_duration'] // 60}` мин\\)\n\n"
        "📊 *Голоса для мьюта:* `" + str(settings['votes_needed_mute']) + "`\n"
        "📊 *Голоса для бана:* `" + str(settings['votes_needed_ban']) + "`\n\n"
        f"👥 *Назначенные администраторы:* `{len(admins)}`\n\n"
        "✏️ *Команды для изменения:*\n"
        "`/set_vote_time <число>` \\- время голосования\n"
        "`/set_mute_time <число>` \\- время мьюта\n"
        "`/set_ban_time <число>` \\- время бана\n"
        "`/add_admin @username` \\- добавить админа\n"
        "`/remove_admin @username` \\- убрать админа"
    )

    response = await message.answer(settings_text)
    asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, AUTO_DELETE_TIMEOUT))
    asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['set_vote_time']))
async def cmd_set_vote_time(message: types.Message):
    """Команда /set_vote_time - установка времени голосования"""
    if not await is_admin(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эта команда доступна только администраторам\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            response = await message.answer(
                "❌ *Ошибка:* Укажите время в секундах\\.\n\n"
                "Пример: `/set_vote_time 300`"
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        seconds = int(parts[1])
        if seconds < 30 or seconds > 3600:
            response = await message.answer(
                "❌ *Ошибка:* Время должно быть от `30` до `3600` секунд \\("
                "`0,5` мин \\- `60` мин\\)\\."
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        chat_settings[message.chat.id]['vote_duration'] = seconds
        response = await message.answer(
            f"✅ *Успешно\\!* Время голосования установлено на "
            f"`{seconds}` сек \\(`{seconds // 60}` мин\\)\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))

    except ValueError:
        response = await message.answer(
            "❌ *Ошибка:* Необходимо указать число\\.\n\n"
            "Пример: `/set_vote_time 300`"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['set_mute_time']))
async def cmd_set_mute_time(message: types.Message):
    """Команда /set_mute_time - установка времени мьюта"""
    if not await is_admin(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эта команда доступна только администраторам\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            response = await message.answer(
                "❌ *Ошибка:* Укажите время в секундах\\.\n\n"
                "Пример: `/set_mute_time 300`"
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        seconds = int(parts[1])
        if seconds < 30 or seconds > 86400:
            response = await message.answer(
                "❌ *Ошибка:* Время должно быть от `30` до `86400` секунд "
                "\\(`0,5` мин \\- `24` часа\\)\\."
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        chat_settings[message.chat.id]['mute_duration'] = seconds
        response = await message.answer(
            f"✅ *Успешно\\!* Время мьюта установлено на "
            f"`{seconds}` сек \\(`{seconds // 60}` мин\\)\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))

    except ValueError:
        response = await message.answer(
            "❌ *Ошибка:* Необходимо указать число\\.\n\n"
            "Пример: `/set_mute_time 300`"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['set_ban_time']))
async def cmd_set_ban_time(message: types.Message):
    """Команда /set_ban_time - установка времени бана"""
    if not await is_admin(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эта команда доступна только администраторам\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            response = await message.answer(
                "❌ *Ошибка:* Укажите время в секундах или `0` для вечного бана\\.\n\n"
                "Пример: `/set_ban_time 0`"
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        seconds = int(parts[1])
        if seconds != 0 and (seconds < 30 or seconds > 86400):
            response = await message.answer(
                "❌ *Ошибка:* Время должно быть от `30` до `86400` секунд "
                "или `0` для вечного бана\\."
            )
            asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return

        chat_settings[message.chat.id]['ban_duration'] = seconds
        time_text = "♾️ *Вечный*" if seconds == 0 else f"`{seconds // 60}` *мин*"
        response = await message.answer(
            f"✅ *Успешно\\!* Время бана установлено на {time_text}\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))

    except ValueError:
        response = await message.answer(
            "❌ *Ошибка:* Необходимо указать число\\.\n\n"
            "Пример: `/set_ban_time 0` \\(вечный\\)"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['add_admin']))
async def cmd_add_admin(message: types.Message):
    """Команда /add_admin @username - назначение администратора (только владелец)"""
    if not await is_owner(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эту команду может использовать только **владелец чата**\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Извлекаем username из текста команды
    username = await extract_username_from_text(message.text)

    if not username:
        response = await message.answer(
            "❌ *Ошибка:* Укажите username пользователя\\.\n\n"
            "Пример: `/add_admin @username`"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Пытаемся найти пользователя по username
    user_result = await find_user_by_username(message.chat.id, username)

    if not user_result['success']:
        response = await message.answer(
            f"❌ *Ошибка:* Не удалось найти пользователя `{username}`\\.\n\n"
            "Убедитесь, что пользователь есть в чате и username написан правильно\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    target_user_id = user_result['user_id']
    target_user_name = user_result['first_name']

    # Проверка, не администратор ли уже
    if await is_admin(message.chat.id, target_user_id):
        response = await message.answer(
            "⚠️ *Этот пользователь уже администратор\\.*"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Добавляем в администраторы
    get_chat_admins(message.chat.id).add(target_user_id)

    user_mention = await get_user_mention(target_user_id, target_user_name)
    response = await message.answer(
        f"✅ *Успешно\\!* {user_mention} назначен администратором\\."
    )
    asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
    asyncio.create_task(delete_user_command(message))


@dp.message(Command(commands=['remove_admin']))
async def cmd_remove_admin(message: types.Message):
    """Команда /remove_admin @username - удаление администратора (только владелец)"""
    if not await is_owner(message.chat.id, message.from_user.id):
        response = await message.answer(
            "⚠️ *Ошибка:* Эту команду может использовать только **владелец чата**\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Извлекаем username из текста команды
    username = await extract_username_from_text(message.text)

    if not username:
        response = await message.answer(
            "❌ *Ошибка:* Укажите username пользователя\\.\n\n"
            "Пример: `/remove_admin @username`"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Пытаемся найти пользователя по username
    user_result = await find_user_by_username(message.chat.id, username)

    if not user_result['success']:
        response = await message.answer(
            f"❌ *Ошибка:* Не удалось найти пользователя `{username}`\\.\n\n"
            "Убедитесь, что пользователь есть в чате и username написан правильно\\."
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    target_user_id = user_result['user_id']
    target_user_name = user_result['first_name']

    admins = get_chat_admins(message.chat.id)

    if target_user_id not in admins:
        response = await message.answer(
            "⚠️ *Этот пользователь не является назначенным администратором\\.*"
        )
        asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    # Удаляем из администраторов
    admins.discard(target_user_id)

    user_mention = await get_user_mention(target_user_id, target_user_name)
    response = await message.answer(
        f"✅ *Успешно\\!* {user_mention} лишен прав администратора\\."
    )
    asyncio.create_task(auto_delete_message(message.chat.id, response.message_id, 30))
    asyncio.create_task(delete_user_command(message))


async def start_vote(message: types.Message, vote_type: str):
    """Запуск голосования"""
    chat_id = message.chat.id
    settings = get_chat_settings(chat_id)

    if chat_id in active_votes:
        response = await message.answer(
            "⏳ *Погодите\\!* Голосование уже идёт\\. Дождитесь его завершения\\."
        )
        asyncio.create_task(auto_delete_message(chat_id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    if not message.reply_to_message:
        cmd_name = "`/vote_mute`" if vote_type == "mute" else "`/vote_ban`"
        response = await message.answer(
            f"❌ *Ошибка:* Ответьте на сообщение пользователя и напишите {cmd_name}"
        )
        asyncio.create_task(auto_delete_message(chat_id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    target_user = message.reply_to_message.from_user
    target_user_id = target_user.id
    target_user_name = target_user.first_name or f"user_{target_user_id}"

    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=target_user_id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            response = await message.answer(
                "🛡️ *Нельзя голосовать против администраторов\\.*"
            )
            asyncio.create_task(auto_delete_message(chat_id, response.message_id, 30))
            asyncio.create_task(delete_user_command(message))
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса: {e}")

    if target_user_id == message.from_user.id:
        response = await message.answer(
            "🙅 *Нельзя голосовать против себя\\!*"
        )
        asyncio.create_task(auto_delete_message(chat_id, response.message_id, 30))
        asyncio.create_task(delete_user_command(message))
        return

    if vote_type == "mute":
        votes_needed = settings['votes_needed_mute']
        title = "🗳️ *ГОЛОСОВАНИЕ О МЬЮТЕ*"
    else:
        votes_needed = settings['votes_needed_ban']
        title = "🗳️ *ГОЛОСОВАНИЕ О БАНЕ*"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍 За", callback_data=f"vote_yes_{vote_type}_{target_user_id}")],
        [InlineKeyboardButton(text="👎 Против", callback_data=f"vote_no_{vote_type}_{target_user_id}")]
    ])

    user_mention = await get_user_mention(target_user_id, target_user_name)

    vote_text = (
        f"{title}\n\n"
        f"👤 *Пользователь:* {user_mention}\n"
        f"⏱️ *Время на голос:* `{settings['vote_duration'] // 60}` мин\n"
        f"📊 *Нужно голосов:* `{votes_needed}`\n\n"
        f"🎯 *Голосуйте честно\\:*"
    )

    sent_message = await message.answer(vote_text, reply_markup=keyboard)

    # Удаляем команду пользователя
    asyncio.create_task(delete_user_command(message))

    active_votes[chat_id] = {
        'type': vote_type,
        'target_user_id': target_user_id,
        'target_user_name': target_user_name,
        'votes_yes': 0,
        'votes_no': 0,
        'voters': set(),
        'message_id': sent_message.message_id,
        'end_time': datetime.now() + timedelta(seconds=settings['vote_duration']),
        'votes_needed': votes_needed
    }

    asyncio.create_task(end_vote_timer(chat_id))


@dp.message(Command(commands=['vote_mute']))
async def cmd_vote_mute(message: types.Message):
    """Команда /vote_mute - голосование о мьюте"""
    await start_vote(message, "mute")


@dp.message(Command(commands=['vote_ban']))
async def cmd_vote_ban(message: types.Message):
    """Команда /vote_ban - голосование о бане"""
    await start_vote(message, "ban")


@dp.message(F.text)
async def handle_inline_mention(message: types.Message):
    """Обработка сообщений вида '@бот mute' или '@бот ban'"""
    if not message.text:
        return

    text = message.text.strip().lower()

    # Проверяем, упомянут ли бот в сообщении
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username.lower()

        # Ищем упоминание бота
        if bot_username not in text:
            return
    except Exception as e:
        logger.error(f"Ошибка при получении информации бота: {e}")
        return

    # Проверяем, содержит ли сообщение 'mute' или 'ban'
    if 'mute' in text:
        vote_type = "mute"
    elif 'ban' in text:
        vote_type = "ban"
    else:
        return

    # Запускаем голосование
    await start_vote(message, vote_type)


@dp.callback_query(F.data.startswith('vote_'))
async def process_vote(callback: types.CallbackQuery):
    """Обработка голосования"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    if chat_id not in active_votes:
        await callback.answer(
            "⏳ Голосование уже завершилось",
            show_alert=True
        )
        return

    vote_data = active_votes[chat_id]

    if user_id in vote_data['voters']:
        await callback.answer(
            "ℹ️ Вы уже проголосовали",
            show_alert=False
        )
        return

    parts = callback.data.split('_')
    vote_option = parts[1]
    vote_type = parts[2]
    target_user_id = int(parts[3])

    if target_user_id != vote_data['target_user_id'] or vote_type != vote_data['type']:
        await callback.answer(
            "⚠️ Это голосование неактуально",
            show_alert=True
        )
        return

    if vote_option == 'yes':
        vote_data['votes_yes'] += 1
    elif vote_option == 'no':
        vote_data['votes_no'] += 1

    vote_data['voters'].add(user_id)

    type_name = "мьюте" if vote_data['type'] == 'mute' else "бане"

    current_text = (
        f"🗳️ *Голосование о {type_name}*\n\n"
        f"👤 *Пользователь:* `{vote_data['target_user_name']}`\n\n"
        f"👍 *За:* `{vote_data['votes_yes']}`\n"
        f"👎 *Против:* `{vote_data['votes_no']}`\n"
        f"📊 *Всего голосов:* `{len(vote_data['voters'])}`\n"
        f"🎯 *Нужно:* `{vote_data['votes_needed']}`"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍 За", callback_data=f"vote_yes_{vote_data['type']}_{target_user_id}")],
        [InlineKeyboardButton(text="👎 Против", callback_data=f"vote_no_{vote_data['type']}_{target_user_id}")]
    ])

    await callback.message.edit_text(current_text, reply_markup=keyboard)
    await callback.answer("✅ Голос принят")


async def end_vote_timer(chat_id: int):
    """Таймер завершения голосования"""
    settings = get_chat_settings(chat_id)
    await asyncio.sleep(settings['vote_duration'])

    if chat_id in active_votes:
        await finalize_vote(chat_id)


async def finalize_vote(chat_id: int):
    """Завершение голосования и выполнение действия"""
    if chat_id not in active_votes:
        return

    settings = get_chat_settings(chat_id)
    vote_data = active_votes.pop(chat_id)
    target_user_id = vote_data['target_user_id']
    target_user_name = vote_data['target_user_name']
    vote_type = vote_data['type']

    votes_yes = vote_data['votes_yes']
    votes_no = vote_data['votes_no']
    total_votes = len(vote_data['voters'])
    votes_needed = vote_data['votes_needed']

    type_action = "мьют" if vote_type == 'mute' else "бан"

    result_text = (
        "✅ *Голосование завершено*\n\n"
        f"👤 *Пользователь:* `{target_user_name}`\n\n"
        f"👍 *За:* `{votes_yes}`\n"
        f"👎 *Против:* `{votes_no}`\n"
        f"📊 *Итого голосов:* `{total_votes}`"
    )

    if votes_yes >= votes_needed:
        if vote_type == 'mute':
            result_text += (
                f"\n\n🔇 *Решение: МЬЮТ АКТИВИРОВАН*\n"
                f"`{target_user_name}` отправляется в тихий режим на "
                f"`{settings['mute_duration'] // 60}` минут\\."
            )

            try:
                until_date = datetime.now() + timedelta(seconds=settings['mute_duration'])
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target_user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                logger.info(f"Пользователь {target_user_id} замьючен в чате {chat_id}")
            except Exception as e:
                result_text += f"\n\n⚠️ *Ошибка при мьюте:* `{str(e)}`"
                logger.error(f"Не удалось замьютить пользователя {target_user_id}: {e}")
        else:
            time_text = "♾️ *вечный*" if settings['ban_duration'] == 0 else f"`{settings['ban_duration'] // 60}` *мин*"
            result_text += (
                f"\n\n🚫 *Решение: БАН АКТИВИРОВАН*\n"
                f"`{target_user_name}` удалён из чата на {time_text}\\."
            )

            try:
                if settings['ban_duration'] == 0:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=target_user_id)
                else:
                    until_date = datetime.now() + timedelta(seconds=settings['ban_duration'])
                    await bot.ban_chat_member(chat_id=chat_id, user_id=target_user_id, until_date=until_date)
                logger.info(f"Пользователь {target_user_id} забанен в чате {chat_id}")
            except Exception as e:
                result_text += f"\n\n⚠️ *Ошибка при бане:* `{str(e)}`"
                logger.error(f"Не удалось забанить пользователя {target_user_id}: {e}")
    else:
        result_text += (
            f"\n\n❌ *Решение: {type_action.upper()} НЕ АКТИВИРОВАН*\n"
            f"Недостаточно голосов: `{votes_yes}` из `{votes_needed}`\\."
        )

    response = await bot.send_message(chat_id, result_text)
    asyncio.create_task(auto_delete_message(chat_id, response.message_id, AUTO_DELETE_TIMEOUT))


async def main():
    """Запуск диспетчера"""
    logger.info("🚀 Бот запущен")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
