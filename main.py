import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    ReactionTypeEmoji,
)

# ───────────── ENV ─────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPPORT_ID = int(os.getenv("SUPPORT_ID", "8620034545"))  # сюда приходят вопросы
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "8620034545,8830973658").split(",") if x.strip()
}
SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", "settings.json"))

HEART_EFFECT_ID = "5159385139981059251"  # эффект сообщения ❤️

DEFAULTS = {
    "greeting": {
        "text": "Здравствуйте! Вас приветствует тех. поддержка Gold Visuals. "
        "Задайте свой вопрос и ожидайте ответ в течение 24 часов.",
        "entities": [],
    },
    "btn_text": "Написать в тех/поддержку",
    "btn_emoji": "",
    "ask": {"text": "Задайте свой вопрос", "entities": []},
    "sent": {"text": "✅ Ваш вопрос отправлен. Ожидайте ответ в течение 24 часов.", "entities": []},
}


# ───────────── Настройки ─────────────
def load_settings() -> dict:
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    merged = json.loads(json.dumps(DEFAULTS))
    merged.update(data)
    return merged


def save_settings(s: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def ents(block: dict) -> list[MessageEntity]:
    return [MessageEntity(**e) for e in block.get("entities", [])]


def pack(message: Message) -> dict:
    return {
        "text": message.text or "",
        "entities": [e.model_dump(exclude_none=True) for e in (message.entities or [])],
    }


def user_kb() -> InlineKeyboardMarkup:
    s = load_settings()
    extra = {"style": "success"}  # зелёная кнопка (Bot API 9.4+)
    if s.get("btn_emoji"):
        extra["icon_custom_emoji_id"] = s["btn_emoji"]  # премиум эмодзи на кнопке
    btn = InlineKeyboardButton(text=s["btn_text"], callback_data="ask", **extra)
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


# ───────────── FSM ─────────────
class Ask(StatesGroup):
    question = State()


class Edit(StatesGroup):
    greeting = State()
    btn_text = State()
    btn_emoji = State()
    ask = State()
    sent = State()
    reply = State()


router = Router()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


# ───────────── Пользователь ─────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    s = load_settings()
    try:
        await message.react([ReactionTypeEmoji(emoji="❤")])  # маленькое сердечко
    except Exception:
        pass
    kwargs = dict(
        chat_id=message.chat.id,
        text=s["greeting"]["text"],
        entities=ents(s["greeting"]) or None,
        reply_markup=user_kb(),
    )
    try:
        await bot.send_message(**kwargs, message_effect_id=HEART_EFFECT_ID)  # анимация сердечка
    except Exception:
        await bot.send_message(**kwargs)


@router.callback_query(F.data == "ask")
async def cb_ask(call: CallbackQuery, state: FSMContext):
    s = load_settings()
    await state.set_state(Ask.question)
    await call.message.answer(s["ask"]["text"], entities=ents(s["ask"]) or None)
    await call.answer()


@router.message(Ask.question)
async def got_question(message: Message, state: FSMContext, bot: Bot):
    u = message.from_user
    name = u.full_name
    uname = f"@{u.username}" if u.username else "без username"
    header = f"📩 Новый вопрос\n👤 {name} ({uname})\n🆔 {u.id}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply:{u.id}")]]
    )
    await bot.send_message(SUPPORT_ID, header, reply_markup=kb)
    await message.copy_to(SUPPORT_ID)
    s = load_settings()
    await message.answer(s["sent"]["text"], entities=ents(s["sent"]) or None)
    await state.clear()


# ───────────── Ответ админа пользователю ─────────────
@router.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    uid = int(call.data.split(":")[1])
    await state.set_state(Edit.reply)
    await state.update_data(target=uid)
    await call.message.answer(f"Напишите ответ для пользователя {uid} (/cancel — отмена):")
    await call.answer()


@router.message(Edit.reply)
async def send_reply(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Отменено.")
    uid = (await state.get_data())["target"]
    try:
        await bot.send_message(uid, "💬 Ответ тех. поддержки Gold Visuals:")
        await message.copy_to(uid)
        await message.answer("✅ Ответ отправлен.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")
    await state.clear()


# ───────────── Админ-панель ─────────────
def admin_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏️ Текст приветствия", callback_data="adm:greeting")],
        [InlineKeyboardButton(text="🔘 Текст кнопки", callback_data="adm:btn_text")],
        [InlineKeyboardButton(text="✨ Премиум эмодзи на кнопке", callback_data="adm:btn_emoji")],
        [InlineKeyboardButton(text="💬 Текст «Задайте свой вопрос»", callback_data="adm:ask")],
        [InlineKeyboardButton(text="✅ Текст «Вопрос отправлен»", callback_data="adm:sent")],
        [InlineKeyboardButton(text="👁 Предпросмотр", callback_data="adm:preview")],
        [InlineKeyboardButton(text="♻️ Сбросить всё", callback_data="adm:reset")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return  # молча игнорируем
    await state.clear()
    await message.answer("🛠 Админ-панель Gold Visuals", reply_markup=admin_kb())


PROMPTS = {
    "greeting": ("Отправьте новый текст приветствия. Можно вставлять премиум эмодзи 💎", Edit.greeting),
    "btn_text": ("Отправьте новый текст кнопки (обычный текст):", Edit.btn_text),
    "btn_emoji": (
        "Отправьте ОДНО премиум эмодзи — оно появится слева на кнопке.\n"
        "Отправьте «-» чтобы убрать эмодзи.",
        Edit.btn_emoji,
    ),
    "ask": ("Отправьте новый текст «Задайте свой вопрос» (можно с премиум эмодзи):", Edit.ask),
    "sent": ("Отправьте новый текст «Вопрос отправлен» (можно с премиум эмодзи):", Edit.sent),
}


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    action = call.data.split(":")[1]

    if action in PROMPTS:
        text, st = PROMPTS[action]
        await state.set_state(st)
        await call.message.answer(text + "\n\n/cancel — отмена")
    elif action == "preview":
        s = load_settings()
        await call.message.answer(
            s["greeting"]["text"], entities=ents(s["greeting"]) or None, reply_markup=user_kb()
        )
    elif action == "reset":
        save_settings(json.loads(json.dumps(DEFAULTS)))
        await call.message.answer("♻️ Настройки сброшены.")
    await call.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


async def _save_block(message: Message, state: FSMContext, key: str):
    if not is_admin(message.from_user.id) or not message.text:
        return
    s = load_settings()
    s[key] = pack(message)
    save_settings(s)
    await state.clear()
    await message.answer("✅ Сохранено. Проверьте через /admin → Предпросмотр.")


@router.message(Edit.greeting)
async def set_greeting(message: Message, state: FSMContext):
    await _save_block(message, state, "greeting")


@router.message(Edit.ask)
async def set_ask(message: Message, state: FSMContext):
    await _save_block(message, state, "ask")


@router.message(Edit.sent)
async def set_sent(message: Message, state: FSMContext):
    await _save_block(message, state, "sent")


@router.message(Edit.btn_text)
async def set_btn_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or not message.text:
        return
    s = load_settings()
    s["btn_text"] = message.text[:64]
    save_settings(s)
    await state.clear()
    await message.answer("✅ Текст кнопки сохранён.")


@router.message(Edit.btn_emoji)
async def set_btn_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or not message.text:
        return
    s = load_settings()
    if message.text.strip() == "-":
        s["btn_emoji"] = ""
    else:
        custom = [e for e in (message.entities or []) if e.type == "custom_emoji"]
        if not custom:
            return await message.answer("❌ Это не премиум эмодзи. Отправьте именно премиум эмодзи.")
        s["btn_emoji"] = custom[0].custom_emoji_id
    save_settings(s)
    await state.clear()
    await message.answer("✅ Эмодзи кнопки сохранено.")


# ───────────── Запуск ─────────────
async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("Укажите переменную окружения BOT_TOKEN")
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())