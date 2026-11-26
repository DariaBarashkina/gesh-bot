import os
import re
import logging
from dotenv import load_dotenv

from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters,
)
from telegram.error import TimedOut, NetworkError

from texts import (
    WELCOME_CAPTION, MENU_CAPTION, CONTACT_PROMPT, QUESTION_SENT,
    PHOTO_CAPTION, OLD_MESSAGE_HINT,
    RESPONSES,
    PHOTO_MAIN, PHOTO_HOUSE,
    get_main_menu, get_back_menu, get_back_to_menu_kb,
)

# -------- Логирование --------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# -------- Переменные окружения --------
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if not ADMIN_GROUP_ID:
    raise ValueError("ADMIN_GROUP_ID не найден в .env")

WAITING_FOR_QUESTION = 0


# -------- Утилита: обработать ошибку редактирования --------
async def handle_edit_error(query, error: Exception):
    """Разбирает ошибку редактирования и реагирует по-разному."""
    text = str(error).lower()

    if "message is not modified" in text:
        return

    if "message can't be edited" in text or "message to edit not found" in text:
        try:
            await query.message.reply_text(OLD_MESSAGE_HINT)
        except Exception:
            pass
        return

    if "query is too old" in text or "query id is invalid" in text:
        return

    if isinstance(error, (TimedOut, NetworkError)):
        logging.warning("Сетевая ошибка при редактировании: %s", error)
        return

    logging.error("Не удалось отредактировать сообщение: %s", error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with open(PHOTO_MAIN, "rb") as f:
        await update.message.reply_photo(
            photo=f,
            caption=WELCOME_CAPTION,
            reply_markup=get_main_menu(),
        )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with open(PHOTO_MAIN, "rb") as f:
        await update.message.reply_photo(
            photo=f,
            caption=MENU_CAPTION,
            reply_markup=get_main_menu(),
        )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    if query.data == "back_to_menu":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        with open(PHOTO_MAIN, "rb") as f:
            await query.message.reply_photo(
                photo=f,
                caption=WELCOME_CAPTION,
                reply_markup=get_main_menu(),
            )
        return

    if query.data == "back":
        try:
            with open(PHOTO_MAIN, "rb") as f:
                await query.message.edit_media(
                    media=InputMediaPhoto(media=f, caption=WELCOME_CAPTION),
                    reply_markup=get_main_menu(),
                )
        except Exception as e:
            await handle_edit_error(query, e)
        return

    if query.data == "photo":
        try:
            with open(PHOTO_HOUSE, "rb") as f:
                await query.message.edit_media(
                    media=InputMediaPhoto(media=f, caption=PHOTO_CAPTION),
                    reply_markup=get_back_menu(),
                )
        except Exception as e:
            await handle_edit_error(query, e)
        return

    text = RESPONSES.get(query.data, "Не понял 🤔 Выберите пункт меню.")
    try:
        await query.message.edit_caption(
            caption=text,
            reply_markup=get_back_menu(),
        )
    except Exception as e:
        await handle_edit_error(query, e)


async def start_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    try:
        await query.message.edit_caption(
            caption=CONTACT_PROMPT,
            reply_markup=None,
        )
    except Exception as e:
        await handle_edit_error(query, e)
        return ConversationHandler.END
    return WAITING_FOR_QUESTION


async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    question = update.message.text
    username = f"@{user.username}" if user.username else "(без username)"

    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=(
            f"📩 Сообщение от {user.full_name} {username}\n"
            f"ID: {user.id}\n\n{question}"
        ),
    )

    await update.message.reply_text(QUESTION_SENT)
    return ConversationHandler.END


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Сделайте Reply на сообщение с вопросом пользователя."
        )
        return

    quoted = update.message.reply_to_message.text or ""
    match = re.search(r"ID:\s*(\d+)", quoted)
    if not match:
        await update.message.reply_text("Не нашёл ID в исходном сообщении.")
        return

    target_user_id = int(match.group(1))
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"📬 Ответ администратора:\n\n{update.message.text}",
            reply_markup=get_back_to_menu_kb(),
        )
        await update.message.reply_text("✅ Ответ отправлен.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Ошибка при обработке обновления:", exc_info=context.error)


# -------- Запуск --------
def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(30)
        .connect_timeout(30)
        .write_timeout(30)
        .media_write_timeout(180)
        .build()
    )
    app.add_error_handler(error_handler)

    app.add_handler(MessageHandler(
        filters.REPLY & filters.TEXT & filters.Chat(ADMIN_GROUP_ID),
        admin_reply,
    ))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))

    contact_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            start_contact, pattern="^contacts$"
        )],
        states={
            WAITING_FOR_QUESTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, receive_question
                ),
            ],
        },
        fallbacks=[],
    )
    app.add_handler(contact_conv)
    app.add_handler(CallbackQueryHandler(
        on_callback, pattern="^(?!contacts$).*$"
    ))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
