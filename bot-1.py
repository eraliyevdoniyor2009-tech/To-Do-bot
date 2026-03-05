import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Token (Railway sets this as an environment variable) ─────
BOT_TOKEN = os.environ["BOT_TOKEN"]          # crashes early with a clear error if missing

# ── In-memory task storage  { user_id: { task_id: title } } ─
tasks: dict = {}
task_counter: dict = {}

ADD_TASK = 0   # ConversationHandler state


# ── Helpers ───────────────────────────────────────────────────

def get_user_tasks(user_id):
    return tasks.get(user_id, {})


def next_task_id(user_id):
    task_counter[user_id] = task_counter.get(user_id, 0) + 1
    return task_counter[user_id]


def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Vazifa qo'sh", callback_data="add"),
            InlineKeyboardButton("📋 Ro'yxat",      callback_data="list"),
        ],
    ])


# ── /start ────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Salom, *{user.first_name}*!\n\n"
        "Bu *To-Do Bot* — vazifalaringizni boshqarish uchun.\n\n"
        "Quyidagi tugmalardan foydalaning yoki buyruq yozing:\n"
        "`/add` — yangi vazifa\n"
        "`/list` — barcha vazifalar\n"
        "`/help` — yordam",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ── /help ─────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Buyruqlar:*\n\n"
        "/start — bosh menyu\n"
        "/add   — yangi vazifa qo'shish\n"
        "/list  — vazifalar ro'yxati\n"
        "/help  — shu xabar\n\n"
        "Vazifani o'chirish uchun ro'yxatdagi 🗑 tugmasini bosing.",
        parse_mode="Markdown",
    )


# ── ADD TASK (conversation) ───────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "✏️ Vazifa nomini yozing:\n_(Bekor qilish: /cancel)_",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "✏️ Vazifa nomini yozing:\n_(Bekor qilish: /cancel)_",
            parse_mode="Markdown",
        )
    return ADD_TASK


async def add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    title   = update.message.text.strip()

    if not title:
        await update.message.reply_text("❌ Bo'sh vazifa bo'lmaydi. Qaytadan yozing:")
        return ADD_TASK

    if len(title) > 200:
        await update.message.reply_text("❌ Vazifa 200 ta harfdan oshmasin. Qaytadan yozing:")
        return ADD_TASK

    tid = next_task_id(user_id)
    tasks.setdefault(user_id, {})[tid] = title

    await update.message.reply_text(
        f"✅ *Vazifa qo'shildi!*\n\n`#{tid}` {title}",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ── LIST TASKS ────────────────────────────────────────────────

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    user_id    = update.effective_user.id
    user_tasks = get_user_tasks(user_id)

    if not user_tasks:
        await send(
            "📭 Hozircha vazifalar yo'q.\n\n➕ /add buyrug'i bilan qo'shing.",
            reply_markup=main_keyboard(),
        )
        return

    text = f"📋 *Vazifalar ro'yxati* ({len(user_tasks)} ta)\n\n"
    keyboard = []
    for tid, title in sorted(user_tasks.items()):
        text += f"`#{tid}` {title}\n"
        keyboard.append([
            InlineKeyboardButton(f"🗑 #{tid} — {title[:30]}", callback_data=f"del_{tid}")
        ])

    keyboard.append([InlineKeyboardButton("➕ Yangi vazifa", callback_data="add")])

    await send(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ── DELETE TASK ───────────────────────────────────────────────

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    tid     = int(query.data.replace("del_", ""))

    user_tasks = tasks.get(user_id, {})
    if tid in user_tasks:
        title = user_tasks.pop(tid)
        await query.edit_message_text(
            f"🗑 *#{tid} — {title}*\n\nVazifa o'chirildi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Ro'yxat",   callback_data="list"),
                InlineKeyboardButton("➕ Qo'shish",  callback_data="add"),
            ]]),
        )
    else:
        await query.edit_message_text("❌ Vazifa topilmadi.")


# ── MAIN ──────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^add$"),
        ],
        states={
            ADD_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(CommandHandler("list",  list_tasks))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(list_tasks,  pattern="^list$"))
    app.add_handler(CallbackQueryHandler(delete_task, pattern=r"^del_\d+$"))

    logger.info("Bot ishga tushdi (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
