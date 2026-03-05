import logging
import os
import enum
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Text, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

# ============================================================
#  LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)

# ============================================================
#  CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8661236146:AAHbkGO1SAQy9KThfAVH4a5OCa_z5vMqQw4")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot_data.db")

EXPENSE_CATEGORIES = [
    ("🍔 Ovqat", "food"),
    ("🚗 Transport", "transport"),
    ("🏠 Uy-joy", "housing"),
    ("👗 Kiyim", "clothing"),
    ("💊 Salomatlik", "health"),
    ("📚 Ta'lim", "education"),
    ("🎭 Ko'ngil ochar", "entertainment"),
    ("📱 Texnologiya", "technology"),
    ("💡 Kommunal", "utilities"),
    ("🎁 Sovg'a", "gifts"),
    ("💰 Jamg'arma", "savings"),
    ("❓ Boshqa", "other"),
]

CATEGORY_NAMES = {
    "food": "🍔 Ovqat",
    "transport": "🚗 Transport",
    "housing": "🏠 Uy-joy",
    "clothing": "👗 Kiyim",
    "health": "💊 Salomatlik",
    "education": "📚 Ta'lim",
    "entertainment": "🎭 Ko'ngil ochar",
    "technology": "📱 Texnologiya",
    "utilities": "💡 Kommunal",
    "gifts": "🎁 Sovg'a",
    "savings": "💰 Jamg'arma",
    "other": "❓ Boshqa",
}

CATEGORY_EMOJI = {
    "food": "🍔", "transport": "🚗", "housing": "🏠",
    "clothing": "👗", "health": "💊", "education": "📚",
    "entertainment": "🎭", "technology": "📱", "utilities": "💡",
    "gifts": "🎁", "savings": "💰", "other": "❓",
}

PRIORITY_NAMES = {"high": "🔴 Yuqori", "medium": "🟡 O'rta", "low": "🟢 Past"}
STATUS_NAMES = {"pending": "⏳ Kutilmoqda", "in_progress": "🔄 Jarayonda", "completed": "✅ Bajarilgan"}

# Conversation states
(
    TODO_TITLE, TODO_DESC, TODO_PRIORITY, TODO_DUE_DATE,
    EXPENSE_AMOUNT, EXPENSE_CATEGORY, EXPENSE_DESC,
) = range(7)

TASKS_PER_PAGE = 5
EXPENSES_PER_PAGE = 8

# ============================================================
#  DATABASE
# ============================================================
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, nullable=False, index=True)
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    priority    = Column(String(10), default="medium")
    status      = Column(String(20), default="pending")
    due_date    = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def priority_emoji(self):
        return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(self.priority, "⚪")

    def status_emoji(self):
        return {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}.get(self.status, "❓")


class Expense(Base):
    __tablename__ = "expenses"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, nullable=False, index=True)
    amount      = Column(Float, nullable=False)
    category    = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    currency    = Column(String(10), default="UZS")
    created_at  = Column(DateTime, default=datetime.utcnow)

    def category_emoji(self):
        return CATEGORY_EMOJI.get(self.category, "💸")

    def formatted_amount(self):
        if self.amount >= 1_000_000:
            return f"{self.amount / 1_000_000:.1f}M {self.currency}"
        elif self.amount >= 1_000:
            return f"{self.amount / 1_000:.0f}K {self.currency}"
        return f"{self.amount:,.0f} {self.currency}"


def init_db():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


SessionLocal = init_db()


def get_session():
    return SessionLocal()


# ============================================================
#  HELPERS
# ============================================================

def fmt(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")


def progress_bar(percent: int, length: int = 10) -> str:
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


def mini_bar(percent: int, length: int = 8) -> str:
    filled = max(1, int(length * percent / 100))
    return "█" * filled + "░" * (length - filled)


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ To-Do", callback_data="todo_menu"),
            InlineKeyboardButton("💰 Xarajat", callback_data="expense_menu"),
        ],
    ])


# ============================================================
#  START HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 Salom, *{user.first_name}*!\n\n"
        "🚀 *Professional Life Manager Bot*ga xush kelibsiz!\n\n"
        "Bu bot sizga:\n"
        "✅ *To-Do* — vazifalaringizni boshqarish\n"
        "💰 *Xarajat* — moliyaviy hisobingizni yuritish\n\n"
        "Quyidagi menyudan boshlang 👇"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Barcha buyruqlar:*\n\n"
        "🗂 *To-Do:*\n"
        "/add\\_task — yangi vazifa qo'shish\n"
        "/tasks — barcha vazifalar\n"
        "/stats — vazifalar statistikasi\n\n"
        "💸 *Xarajat:*\n"
        "/add\\_expense — xarajat qo'shish\n"
        "/expenses — xarajatlar ro'yxati\n"
        "/summary — xarajat xulosasi\n\n"
        "⚙️ *Boshqa:*\n"
        "/menu — asosiy menyu\n"
        "/help — yordam\n"
        "/cancel — bekor qilish"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 *Asosiy Menyu*\n\nQaysi bo'limga o'tmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 *Asosiy Menyu*\n\nQaysi bo'limga o'tmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
#  TODO — MENU
# ============================================================

async def todo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    session = get_session()
    try:
        total    = session.query(Task).filter_by(user_id=user_id).count()
        pending  = session.query(Task).filter_by(user_id=user_id, status="pending").count()
        done     = session.query(Task).filter_by(user_id=user_id, status="completed").count()
    finally:
        session.close()

    text = (
        "✅ *To-Do Boshqaruvi*\n\n"
        f"📋 Jami vazifalar: *{total}*\n"
        f"⏳ Kutilayotgan: *{pending}*\n"
        f"✅ Bajarilgan: *{done}*\n\n"
        "Quyidan tanlang:"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Yangi vazifa", callback_data="todo_add")],
        [
            InlineKeyboardButton("📋 Barchasi", callback_data="todo_list"),
            InlineKeyboardButton("⏳ Kutilmoqda", callback_data="todo_filter_pending"),
        ],
        [
            InlineKeyboardButton("🔄 Jarayonda", callback_data="todo_filter_in_progress"),
            InlineKeyboardButton("✅ Bajarilgan", callback_data="todo_filter_completed"),
        ],
        [InlineKeyboardButton("📊 Statistika", callback_data="todo_stats")],
        [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  TODO — ADD (ConversationHandler)
# ============================================================

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📝 *Yangi vazifa qo'shish*\n\n"
        "Vazifa sarlavhasini kiriting:\n\n"
        "_Bekor qilish uchun /cancel_"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    return TODO_TITLE


async def todo_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if len(title) < 2:
        await update.message.reply_text("❌ Sarlavha kamida 2 ta harf bo'lishi kerak.")
        return TODO_TITLE
    if len(title) > 200:
        await update.message.reply_text("❌ Sarlavha 200 ta harfdan oshmasin.")
        return TODO_TITLE
    context.user_data["task_title"] = title
    keyboard = [[InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_desc")]]
    await update.message.reply_text(
        f"✅ Sarlavha: *{title}*\n\n📄 Tavsif kiriting _(ixtiyoriy)_:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TODO_DESC


async def todo_get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_desc"] = update.message.text.strip()
    return await _ask_priority(update.message)


async def todo_skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["task_desc"] = None
    return await _ask_priority(update.callback_query.message, edit=True)


async def _ask_priority(message, edit=False):
    keyboard = [
        [InlineKeyboardButton("🔴 Yuqori", callback_data="priority_high")],
        [InlineKeyboardButton("🟡 O'rta",  callback_data="priority_medium")],
        [InlineKeyboardButton("🟢 Past",   callback_data="priority_low")],
    ]
    text = "⚡ *Muhimlik darajasini tanlang:*"
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return TODO_PRIORITY


async def todo_get_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["task_priority"] = query.data.replace("priority_", "")
    keyboard = [[InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_date")]]
    await query.edit_message_text(
        "📅 *Muddat kiriting* _(DD.MM.YYYY formatida)_\n\nMisol: `25.12.2025`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TODO_DUE_DATE


async def todo_get_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        due_date = datetime.strptime(text, "%d.%m.%Y")
        if due_date < datetime.now():
            await update.message.reply_text("❌ Muddat o'tib ketgan sana bo'lishi mumkin emas!")
            return TODO_DUE_DATE
        context.user_data["task_due_date"] = due_date
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format! `DD.MM.YYYY` ko'rinishida yozing.")
        return TODO_DUE_DATE
    return await _save_task(update.message, context)


async def todo_skip_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["task_due_date"] = None
    return await _save_task(update.callback_query.message, context, edit=True)


async def _save_task(message, context, edit=False):
    user_id = message.chat.id
    data = context.user_data

    task = Task(
        user_id=user_id,
        title=data.get("task_title"),
        description=data.get("task_desc"),
        priority=data.get("task_priority", "medium"),
        due_date=data.get("task_due_date"),
        status="pending",
    )

    session = get_session()
    try:
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
    finally:
        session.close()

    due_str = data.get("task_due_date").strftime("%d.%m.%Y") if data.get("task_due_date") else "Ko'rsatilmagan"
    text = (
        "✅ *Vazifa muvaffaqiyatli qo'shildi!*\n\n"
        f"📌 *Sarlavha:* {data.get('task_title')}\n"
        f"📄 *Tavsif:* {data.get('task_desc') or 'Yoq'}\n"
        f"⚡ *Muhimlik:* {PRIORITY_NAMES.get(data.get('task_priority', 'medium'))}\n"
        f"📅 *Muddat:* {due_str}\n"
        f"🆔 ID: #{task_id}"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Barcha vazifalar", callback_data="todo_list")],
        [InlineKeyboardButton("➕ Yana qo'shish",   callback_data="todo_add")],
        [InlineKeyboardButton("🏠 Asosiy menyu",    callback_data="main_menu")],
    ]
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    context.user_data.clear()
    return ConversationHandler.END


# ============================================================
#  TODO — LIST / FILTER
# ============================================================

async def cb_todo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _display_tasks(query.message, query.from_user.id, status_filter=None, edit=True)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _display_tasks(update.message, update.effective_user.id, status_filter=None)


async def cb_todo_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.replace("todo_filter_", "")
    await _display_tasks(query.message, query.from_user.id, status_filter=status, edit=True)


async def _display_tasks(message, user_id, status_filter=None, edit=False):
    session = get_session()
    try:
        q = session.query(Task).filter_by(user_id=user_id)
        if status_filter:
            q = q.filter_by(status=status_filter)
        q = q.order_by(Task.priority.asc(), Task.created_at.desc())
        total = q.count()
        tasks = q.limit(TASKS_PER_PAGE).all()
    finally:
        session.close()

    if not tasks:
        text = "📭 *Vazifalar topilmadi.*\n\n➕ Yangi vazifa qo'shing!"
        keyboard = [
            [InlineKeyboardButton("➕ Yangi vazifa", callback_data="todo_add")],
            [InlineKeyboardButton("🔙 Orqaga",       callback_data="todo_menu")],
        ]
    else:
        filter_label = f" — {STATUS_NAMES.get(status_filter, '')}" if status_filter else ""
        text = f"📋 *Vazifalar{filter_label}* _{total} ta_\n\n"
        for t in tasks:
            due = f" 📅 {t.due_date.strftime('%d.%m')}" if t.due_date else ""
            text += f"{t.priority_emoji()} {t.status_emoji()} *{t.title}*{due}\n"

        keyboard = []
        for t in tasks:
            keyboard.append([
                InlineKeyboardButton(f"👁 #{t.id} {t.title[:22]}", callback_data=f"task_view_{t.id}")
            ])
        keyboard.append([
            InlineKeyboardButton("➕ Qo'shish", callback_data="todo_add"),
            InlineKeyboardButton("🔙 Orqaga",  callback_data="todo_menu"),
        ])

    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  TODO — DETAIL / COMPLETE / DELETE
# ============================================================

async def cb_task_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("task_view_", ""))
    user_id = query.from_user.id

    session = get_session()
    try:
        task = session.query(Task).filter_by(id=task_id, user_id=user_id).first()
        if not task:
            await query.edit_message_text("❌ Vazifa topilmadi.")
            return

        due_str     = task.due_date.strftime("%d.%m.%Y") if task.due_date else "Ko'rsatilmagan"
        created_str = task.created_at.strftime("%d.%m.%Y %H:%M")
        done_str    = task.completed_at.strftime("%d.%m.%Y") if task.completed_at else "—"
        desc        = task.description or "Yoq"
        status      = task.status
        title       = task.title

        text = (
            f"📌 *{title}*\n\n"
            f"📄 *Tavsif:* {desc}\n"
            f"⚡ *Muhimlik:* {PRIORITY_NAMES.get(task.priority)}\n"
            f"🔄 *Holat:* {STATUS_NAMES.get(task.status)}\n"
            f"📅 *Muddat:* {due_str}\n"
            f"🗓 *Yaratilgan:* {created_str}\n"
            f"✅ *Bajarilgan:* {done_str}\n"
            f"🆔 ID: #{task.id}"
        )
    finally:
        session.close()

    keyboard = []
    if status != "completed":
        keyboard.append([InlineKeyboardButton("✅ Bajarildi", callback_data=f"task_done_{task_id}")])
    keyboard.append([InlineKeyboardButton("🗑 O'chirish", callback_data=f"task_del_{task_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga",   callback_data="todo_list")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def cb_task_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("task_done_", ""))
    user_id = query.from_user.id

    session = get_session()
    try:
        task = session.query(Task).filter_by(id=task_id, user_id=user_id).first()
        if task:
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            session.commit()
            title = task.title
    finally:
        session.close()

    await query.edit_message_text(
        f"🎉 *'{title}'* muvaffaqiyatli bajarildi!\n\nAjoyib ish, davom eting! 💪",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Vazifalar",  callback_data="todo_list")],
            [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")],
        ]),
    )


async def cb_task_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("task_del_", ""))
    user_id = query.from_user.id

    session = get_session()
    try:
        task = session.query(Task).filter_by(id=task_id, user_id=user_id).first()
        if task:
            title = task.title
            session.delete(task)
            session.commit()
    finally:
        session.close()

    await query.edit_message_text(
        f"🗑 *'{title}'* o'chirildi.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Vazifalar",  callback_data="todo_list")],
            [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")],
        ]),
    )


# ============================================================
#  TODO — STATS
# ============================================================

async def cb_todo_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_todo_stats(query.message, query.from_user.id, edit=True)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_todo_stats(update.message, update.effective_user.id)


async def _show_todo_stats(message, user_id, edit=False):
    session = get_session()
    try:
        total       = session.query(Task).filter_by(user_id=user_id).count()
        pending     = session.query(Task).filter_by(user_id=user_id, status="pending").count()
        in_progress = session.query(Task).filter_by(user_id=user_id, status="in_progress").count()
        completed   = session.query(Task).filter_by(user_id=user_id, status="completed").count()
        high        = session.query(Task).filter_by(user_id=user_id, priority="high",   status="pending").count()
        medium      = session.query(Task).filter_by(user_id=user_id, priority="medium", status="pending").count()
        low         = session.query(Task).filter_by(user_id=user_id, priority="low",    status="pending").count()
    finally:
        session.close()

    rate = round((completed / total * 100) if total > 0 else 0)
    bar  = progress_bar(rate)
    text = (
        "📊 *To-Do Statistikasi*\n\n"
        f"📋 Jami: *{total}* vazifa\n\n"
        "📈 *Holat bo'yicha:*\n"
        f"  ⏳ Kutilmoqda: *{pending}*\n"
        f"  🔄 Jarayonda: *{in_progress}*\n"
        f"  ✅ Bajarilgan: *{completed}*\n\n"
        f"🎯 *Bajarish darajasi:*\n"
        f"  {bar} {rate}%\n\n"
        "⚡ *Kutilayotgan (muhimlik):*\n"
        f"  🔴 Yuqori: *{high}*\n"
        f"  🟡 O'rta: *{medium}*\n"
        f"  🟢 Past: *{low}*"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Orqaga", callback_data="todo_menu"),
        InlineKeyboardButton("🏠 Menyu",  callback_data="main_menu"),
    ]])
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ============================================================
#  EXPENSE — MENU
# ============================================================

async def expense_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    session = get_session()
    try:
        now         = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total_all   = session.query(func.sum(Expense.amount)).filter_by(user_id=user_id).scalar() or 0
        total_month = (
            session.query(func.sum(Expense.amount))
            .filter(Expense.user_id == user_id, Expense.created_at >= month_start)
            .scalar() or 0
        )
        count_month = (
            session.query(func.count(Expense.id))
            .filter(Expense.user_id == user_id, Expense.created_at >= month_start)
            .scalar() or 0
        )
    finally:
        session.close()

    text = (
        "💰 *Xarajat Boshqaruvi*\n\n"
        f"📅 *Bu oy:* {fmt(total_month)} UZS\n"
        f"📊 *Tranzaksiyalar:* {count_month} ta\n"
        f"💼 *Jami (hammasi):* {fmt(total_all)} UZS\n\n"
        "Quyidan tanlang:"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Xarajat qo'shish", callback_data="expense_add")],
        [
            InlineKeyboardButton("📋 Ro'yxat", callback_data="expense_list"),
            InlineKeyboardButton("📊 Xulosa",  callback_data="expense_summary"),
        ],
        [InlineKeyboardButton("📈 Grafik", callback_data="expense_chart")],
        [
            InlineKeyboardButton("📅 Bugun", callback_data="exp_period_today"),
            InlineKeyboardButton("📅 Hafta", callback_data="exp_period_week"),
            InlineKeyboardButton("📅 Oy",    callback_data="exp_period_month"),
        ],
        [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  EXPENSE — ADD (ConversationHandler)
# ============================================================

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💸 *Xarajat qo'shish*\n\n"
        "Miqdorni kiriting _(so'mda)_:\n\n"
        "Misol: `50000` yoki `1500000`\n\n"
        "_Bekor qilish uchun /cancel_"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    return EXPENSE_AMOUNT


async def expense_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(" ", "").replace(",", "").replace(".", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
        if amount > 1_000_000_000:
            await update.message.reply_text("❌ Juda katta miqdor! 1 milliarddan kam bo'lsin.")
            return EXPENSE_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri miqdor! Faqat raqam kiriting.\nMisol: `50000`", parse_mode="Markdown")
        return EXPENSE_AMOUNT

    context.user_data["expense_amount"] = amount
    return await _ask_category(update.message)


async def _ask_category(message, edit=False):
    keyboard = []
    cats = EXPENSE_CATEGORIES
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(cats[i][0], callback_data=f"cat_{cats[i][1]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(cats[i + 1][0], callback_data=f"cat_{cats[i + 1][1]}"))
        keyboard.append(row)

    text = "📂 *Toifani tanlang:*"
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return EXPENSE_CATEGORY


async def expense_get_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat_", "")
    context.user_data["expense_category"] = category
    keyboard = [[InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_exp_desc")]]
    await query.edit_message_text(
        f"✅ Toifa: *{CATEGORY_NAMES.get(category)}*\n\n📝 Tavsif kiriting _(ixtiyoriy)_:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EXPENSE_DESC


async def expense_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["expense_desc"] = update.message.text.strip()
    return await _save_expense(update.message, context)


async def expense_skip_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["expense_desc"] = None
    return await _save_expense(update.callback_query.message, context, edit=True)


async def _save_expense(message, context, edit=False):
    user_id = message.chat.id
    data    = context.user_data

    expense = Expense(
        user_id=user_id,
        amount=data.get("expense_amount"),
        category=data.get("expense_category"),
        description=data.get("expense_desc"),
    )

    session = get_session()
    try:
        session.add(expense)
        session.commit()
        session.refresh(expense)
        exp_id = expense.id
    finally:
        session.close()

    cat_name = CATEGORY_NAMES.get(data.get("expense_category"), "❓ Boshqa")
    text = (
        "✅ *Xarajat muvaffaqiyatli saqlandi!*\n\n"
        f"💰 *Miqdor:* {fmt(data.get('expense_amount'))} UZS\n"
        f"📂 *Toifa:* {cat_name}\n"
        f"📝 *Tavsif:* {data.get('expense_desc') or 'Yoq'}\n"
        f"🆔 ID: #{exp_id}"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Yana qo'shish", callback_data="expense_add")],
        [InlineKeyboardButton("📊 Xulosa",        callback_data="expense_summary")],
        [InlineKeyboardButton("🏠 Asosiy menyu",  callback_data="main_menu")],
    ]
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    context.user_data.clear()
    return ConversationHandler.END


# ============================================================
#  EXPENSE — LIST
# ============================================================

async def cb_expense_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _display_expenses(query.message, query.from_user.id, edit=True)


async def cmd_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _display_expenses(update.message, update.effective_user.id)


async def _display_expenses(message, user_id, edit=False):
    session = get_session()
    try:
        expenses = (
            session.query(Expense)
            .filter_by(user_id=user_id)
            .order_by(Expense.created_at.desc())
            .limit(EXPENSES_PER_PAGE)
            .all()
        )
        total_count = session.query(func.count(Expense.id)).filter_by(user_id=user_id).scalar() or 0
    finally:
        session.close()

    if not expenses:
        text = "📭 *Xarajatlar topilmadi.*\n\n➕ Birinchi xarajatni qo'shing!"
        keyboard = [
            [InlineKeyboardButton("➕ Qo'shish", callback_data="expense_add")],
            [InlineKeyboardButton("🔙 Orqaga",   callback_data="expense_menu")],
        ]
    else:
        text = f"📋 *So'nggi xarajatlar* _(jami: {total_count})_\n\n"
        for e in expenses:
            date_str = e.created_at.strftime("%d.%m")
            text += f"{e.category_emoji()} `{date_str}` *{fmt(e.amount)}* — {CATEGORY_NAMES.get(e.category, e.category)}\n"

        keyboard = []
        for e in expenses:
            short = f" ({e.description[:15]})" if e.description else ""
            keyboard.append([
                InlineKeyboardButton(f"🗑 #{e.id} {fmt(e.amount)} UZS{short}", callback_data=f"exp_del_{e.id}")
            ])
        keyboard.append([
            InlineKeyboardButton("➕ Qo'shish", callback_data="expense_add"),
            InlineKeyboardButton("🔙 Orqaga",   callback_data="expense_menu"),
        ])

    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  EXPENSE — SUMMARY
# ============================================================

async def cb_expense_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_summary(query.message, query.from_user.id, edit=True)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_summary(update.message, update.effective_user.id)


async def _show_summary(message, user_id, edit=False):
    now         = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start  = now - timedelta(days=now.weekday())
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    session = get_session()
    try:
        def get_total(start):
            return session.query(func.sum(Expense.amount)).filter(
                Expense.user_id == user_id, Expense.created_at >= start
            ).scalar() or 0

        today_total = get_total(today_start)
        week_total  = get_total(week_start)
        month_total = get_total(month_start)
        all_total   = session.query(func.sum(Expense.amount)).filter_by(user_id=user_id).scalar() or 0

        cat_data = (
            session.query(Expense.category, func.sum(Expense.amount).label("total"))
            .filter(Expense.user_id == user_id, Expense.created_at >= month_start)
            .group_by(Expense.category)
            .order_by(func.sum(Expense.amount).desc())
            .all()
        )
    finally:
        session.close()

    text = (
        "📊 *Xarajat Xulosasi*\n\n"
        f"📅 *Bugun:*    {fmt(today_total)} UZS\n"
        f"📅 *Bu hafta:* {fmt(week_total)} UZS\n"
        f"📅 *Bu oy:*    {fmt(month_total)} UZS\n"
        f"💼 *Jami:*     {fmt(all_total)} UZS\n\n"
    )

    if cat_data:
        text += "📂 *Bu oy — toifa bo'yicha:*\n"
        for cat, amount in cat_data:
            name    = CATEGORY_NAMES.get(cat, "❓ Boshqa")
            percent = round(amount / month_total * 100) if month_total > 0 else 0
            bar     = mini_bar(percent)
            text   += f"{name}: {fmt(amount)} `{bar}` {percent}%\n"

    keyboard = [
        [
            InlineKeyboardButton("📈 Grafik",   callback_data="expense_chart"),
            InlineKeyboardButton("📋 Ro'yxat",  callback_data="expense_list"),
        ],
        [
            InlineKeyboardButton("📅 Bugun", callback_data="exp_period_today"),
            InlineKeyboardButton("📅 Hafta", callback_data="exp_period_week"),
            InlineKeyboardButton("📅 Oy",    callback_data="exp_period_month"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="expense_menu")],
    ]
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  EXPENSE — CHART (text-based)
# ============================================================

async def cb_expense_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    now         = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    session = get_session()
    try:
        cat_data = (
            session.query(Expense.category, func.sum(Expense.amount).label("total"))
            .filter(Expense.user_id == user_id, Expense.created_at >= month_start)
            .group_by(Expense.category)
            .order_by(func.sum(Expense.amount).desc())
            .all()
        )
    finally:
        session.close()

    if not cat_data:
        await query.edit_message_text(
            "📭 Bu oy xarajat yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="expense_menu")]]),
        )
        return

    total      = sum(a for _, a in cat_data)
    month_name = now.strftime("%B %Y")
    text       = f"📈 *{month_name} — Toifa Grafiği*\n\n"

    for cat, amount in cat_data:
        name    = CATEGORY_NAMES.get(cat, "❓ Boshqa")
        percent = round(amount / total * 100) if total > 0 else 0
        bar_len = max(1, int(percent / 5))
        bar     = "█" * bar_len + "░" * (20 - bar_len)
        text   += f"{name}\n`{bar}` {percent}%\n_{fmt(amount)} UZS_\n\n"

    text += f"💼 *Jami: {fmt(total)} UZS*"

    keyboard = [
        [InlineKeyboardButton("📊 Xulosa",  callback_data="expense_summary")],
        [InlineKeyboardButton("🔙 Orqaga",  callback_data="expense_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  EXPENSE — FILTER BY PERIOD
# ============================================================

async def cb_exp_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    period  = query.data.replace("exp_period_", "")
    user_id = query.from_user.id
    now     = datetime.utcnow()

    if period == "today":
        start       = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_name = "Bugun"
    elif period == "week":
        start       = now - timedelta(days=now.weekday())
        period_name = "Bu hafta"
    else:
        start       = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_name = "Bu oy"

    session = get_session()
    try:
        expenses = (
            session.query(Expense)
            .filter(Expense.user_id == user_id, Expense.created_at >= start)
            .order_by(Expense.created_at.desc())
            .all()
        )
        total = session.query(func.sum(Expense.amount)).filter(
            Expense.user_id == user_id, Expense.created_at >= start
        ).scalar() or 0
    finally:
        session.close()

    if not expenses:
        text = f"📭 *{period_name}* uchun xarajat topilmadi."
    else:
        text = f"📋 *{period_name}* xarajatlari\n💰 *Jami: {fmt(total)} UZS*\n\n"
        for e in expenses:
            time_str = e.created_at.strftime("%d.%m %H:%M")
            text    += f"{e.category_emoji()} `{time_str}` *{fmt(e.amount)} UZS*\n"
            if e.description:
                text += f"   _{e.description}_\n"

    keyboard = [
        [
            InlineKeyboardButton("📅 Bugun", callback_data="exp_period_today"),
            InlineKeyboardButton("📅 Hafta", callback_data="exp_period_week"),
            InlineKeyboardButton("📅 Oy",    callback_data="exp_period_month"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="expense_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  EXPENSE — DELETE
# ============================================================

async def cb_exp_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    exp_id  = int(query.data.replace("exp_del_", ""))
    user_id = query.from_user.id

    session = get_session()
    try:
        expense = session.query(Expense).filter_by(id=exp_id, user_id=user_id).first()
        if expense:
            amount = expense.amount
            session.delete(expense)
            session.commit()
            text = f"🗑 *#{exp_id}* — {fmt(amount)} UZS o'chirildi."
        else:
            text = "❌ Xarajat topilmadi."
    finally:
        session.close()

    keyboard = [
        [InlineKeyboardButton("📋 Ro'yxat",     callback_data="expense_list")],
        [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ============================================================
#  CANCEL (shared)
# ============================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text    = "❌ Bekor qilindi."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Asosiy menyu", callback_data="main_menu")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)
    return ConversationHandler.END


# ============================================================
#  MAIN
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # --- TODO conversation ---
    todo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_task", add_task_start),
            CallbackQueryHandler(add_task_start, pattern="^todo_add$"),
        ],
        states={
            TODO_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, todo_get_title)],
            TODO_DESC:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, todo_get_description),
                CallbackQueryHandler(todo_skip_description, pattern="^skip_desc$"),
            ],
            TODO_PRIORITY: [CallbackQueryHandler(todo_get_priority, pattern="^priority_")],
            TODO_DUE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, todo_get_due_date),
                CallbackQueryHandler(todo_skip_due_date, pattern="^skip_date$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
    )

    # --- EXPENSE conversation ---
    expense_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_expense", add_expense_start),
            CallbackQueryHandler(add_expense_start, pattern="^expense_add$"),
        ],
        states={
            EXPENSE_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_get_amount)],
            EXPENSE_CATEGORY: [CallbackQueryHandler(expense_get_category, pattern="^cat_")],
            EXPENSE_DESC:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_get_desc),
                CallbackQueryHandler(expense_skip_desc, pattern="^skip_exp_desc$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
    )

    # Commands
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("menu",    menu_command))
    app.add_handler(CommandHandler("tasks",   cmd_tasks))
    app.add_handler(CommandHandler("expenses", cmd_expenses))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("stats",   cmd_stats))

    # Conversations
    app.add_handler(todo_conv)
    app.add_handler(expense_conv)

    # Todo callbacks
    app.add_handler(CallbackQueryHandler(todo_menu,         pattern="^todo_menu$"))
    app.add_handler(CallbackQueryHandler(cb_todo_list,      pattern="^todo_list$"))
    app.add_handler(CallbackQueryHandler(cb_todo_filter,    pattern="^todo_filter_"))
    app.add_handler(CallbackQueryHandler(cb_task_detail,    pattern="^task_view_"))
    app.add_handler(CallbackQueryHandler(cb_task_complete,  pattern="^task_done_"))
    app.add_handler(CallbackQueryHandler(cb_task_delete,    pattern="^task_del_"))
    app.add_handler(CallbackQueryHandler(cb_todo_stats,     pattern="^todo_stats$"))

    # Expense callbacks
    app.add_handler(CallbackQueryHandler(expense_menu,       pattern="^expense_menu$"))
    app.add_handler(CallbackQueryHandler(cb_expense_list,    pattern="^expense_list$"))
    app.add_handler(CallbackQueryHandler(cb_expense_summary, pattern="^expense_summary$"))
    app.add_handler(CallbackQueryHandler(cb_expense_chart,   pattern="^expense_chart$"))
    app.add_handler(CallbackQueryHandler(cb_exp_period,      pattern="^exp_period_"))
    app.add_handler(CallbackQueryHandler(cb_exp_delete,      pattern="^exp_del_"))

    # General
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"))

    logger.info("✅ Bot ishga tushdi!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
