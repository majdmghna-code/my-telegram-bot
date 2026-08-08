import os
import sqlite3
import base64
import logging
import secrets
import threading
from datetime import datetime, timedelta

from dotenv import load_dotenv
from anthropic import Anthropic

from dashboard import run_dashboard, get_setting

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- الإعدادات ----------
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "6404738639")  # اختياري: لأمر /gencode من داخل تلغرام
AI_MODEL = "claude-sonnet-5"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

DB_PATH = "students.db"
TELEGRAM_MAX_LEN = 4000

TRIAL_DAYS = 7

PLANS = {
    "شهر": 30,
    "6 أشهر": 182,
    "سنة": 365,
}
# الأسعار هلق تتحدد من لوحة التحكم (dashboard) مش من هون

GRADES = [
    "الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس",
    "السابع", "الثامن", "التاسع", "العاشر", "الحادي عشر", "الثاني عشر",
    "جامعي",
]

SUBJECTS = [
    "رياضيات", "فيزياء", "كيمياء", "علوم/أحياء",
    "لغة عربية", "لغة إنكليزية", "لغة فرنسية",
    "تاريخ", "جغرافيا", "كل المواد",
]


# ---------- قاعدة البيانات ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            chat_id INTEGER PRIMARY KEY,
            grade TEXT,
            subject TEXT,
            trial_start TEXT,
            subscription_end TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            duration_days INTEGER NOT NULL,
            used_by INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_student(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT grade, subject, trial_start, subscription_end FROM students WHERE chat_id=?",
        (chat_id,),
    ).fetchone()
    conn.close()
    return row  # (grade, subject, trial_start, subscription_end) or None


def ensure_student(chat_id: int):
    """يسجل الطالب أول مرة وبيبلش فترة تجربة أسبوع مجاني."""
    if get_student(chat_id) is None:
        now = datetime.utcnow()
        trial_end = now + timedelta(days=TRIAL_DAYS)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO students (chat_id, grade, subject, trial_start, subscription_end) "
            "VALUES (?, NULL, NULL, ?, ?)",
            (chat_id, now.isoformat(), trial_end.isoformat()),
        )
        conn.commit()
        conn.close()


def set_grade(chat_id: int, grade: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE students SET grade=? WHERE chat_id=?", (grade, chat_id))
    conn.commit()
    conn.close()


def set_subject(chat_id: int, subject: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE students SET subject=? WHERE chat_id=?", (subject, chat_id))
    conn.commit()
    conn.close()


def extend_subscription(chat_id: int, days: int):
    grade, subject, trial_start, subscription_end = get_student(chat_id)
    now = datetime.utcnow()
    current_end = datetime.fromisoformat(subscription_end) if subscription_end else now
    base = max(current_end, now)
    new_end = base + timedelta(days=days)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE students SET subscription_end=? WHERE chat_id=?",
        (new_end.isoformat(), chat_id),
    )
    conn.commit()
    conn.close()
    return new_end


def has_access(chat_id: int) -> bool:
    row = get_student(chat_id)
    if not row:
        return False
    _, _, _, subscription_end = row
    if not subscription_end:
        return False
    return datetime.utcnow() <= datetime.fromisoformat(subscription_end)


def remaining_days(chat_id: int) -> int:
    row = get_student(chat_id)
    if not row or not row[3]:
        return 0
    delta = datetime.fromisoformat(row[3]) - datetime.utcnow()
    return max(0, delta.days)


def create_code(duration_days: int) -> str:
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO codes (code, duration_days, used_by, created_at) VALUES (?, ?, NULL, ?)",
        (code, duration_days, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return code


def redeem_code(chat_id: int, code: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT duration_days, used_by FROM codes WHERE code=?", (code,)
    ).fetchone()
    if not row:
        conn.close()
        return None, "كود غير صحيح ❌"
    duration_days, used_by = row
    if used_by is not None:
        conn.close()
        return None, "هاد الكود مستخدم من قبل ❌"
    conn.execute("UPDATE codes SET used_by=? WHERE code=?", (chat_id, code))
    conn.commit()
    conn.close()
    new_end = extend_subscription(chat_id, duration_days)
    return new_end, None


# ---------- لوحات الأزرار ----------
def grade_keyboard():
    buttons, row = [], []
    for g in GRADES:
        row.append(InlineKeyboardButton(g, callback_data=f"grade:{g}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def subject_keyboard():
    buttons, row = [], []
    for s in SUBJECTS:
        row.append(InlineKeyboardButton(s, callback_data=f"subject:{s}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


# ---------- الأوامر ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    is_new = get_student(chat_id) is None
    ensure_student(chat_id)
    intro = (
        f"أهلًا فيك! 👋 عندك أسبوع مجاني تجرب فيه البوت.\n\n"
        if is_new
        else "أهلًا رجعتلك! 👋\n\n"
    )
    await update.message.reply_text(
        intro + "بدايةً، اختار صفك الدراسي:", reply_markup=grade_keyboard()
    )


async def change_grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_student(update.message.chat_id)
    await update.message.reply_text("اختار صفك الدراسي:", reply_markup=grade_keyboard())


async def change_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_student(update.message.chat_id)
    await update.message.reply_text("اختار المادة:", reply_markup=subject_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    ensure_student(chat_id)
    grade, subject, _, sub_end = get_student(chat_id)
    days = remaining_days(chat_id)
    active = has_access(chat_id)
    msg = (
        f"الصف: {grade or 'غير محدد'}\n"
        f"المادة: {subject or 'غير محددة'}\n"
        f"حالة الاشتراك: {'فعّال ✅' if active else 'منتهي ❌'}\n"
    )
    if active:
        msg += f"الأيام المتبقية: {days}"
    await update.message.reply_text(msg)


async def subscribe_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = {
        "شهر": get_setting("price_month", "تواصل معنا لمعرفة السعر"),
        "6 أشهر": get_setting("price_6months", "تواصل معنا لمعرفة السعر"),
        "سنة": get_setting("price_year", "تواصل معنا لمعرفة السعر"),
    }
    lines = ["خطط الاشتراك المتوفرة:\n"]
    for name in PLANS:
        lines.append(f"• {name}: {prices[name]}")
    lines.append(
        "\nللاشتراك: حوّل قيمة الخطة يلي بدك ياها، وبعت إثبات التحويل. "
        "بعد التأكيد رح تستلم كود تفعيل، فعّلو بالأمر:\n/redeem الكود"
    )
    await update.message.reply_text("\n".join(lines))


async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    ensure_student(chat_id)
    if not context.args:
        await update.message.reply_text("استخدم الأمر هيك: /redeem الكود")
        return
    code = context.args[0].strip().upper()
    new_end, error = redeem_code(chat_id, code)
    if error:
        await update.message.reply_text(error)
        return
    await update.message.reply_text(
        f"تم تفعيل الاشتراك بنجاح ✅ ساري لتاريخ {new_end.date().isoformat()}."
    )


async def gencode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للأدمن فقط: /gencode شهر  أو /gencode 6اشهر  أو /gencode سنة  أو /gencode 30 (عدد أيام مباشر)"""
    chat_id = update.message.chat_id
    if not ADMIN_CHAT_ID or str(chat_id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("هاد الأمر للأدمن فقط.")
        return
    if not context.args:
        await update.message.reply_text("استخدم: /gencode شهر  أو  /gencode 6اشهر  أو  /gencode سنة  أو  /gencode <عدد الأيام>")
        return
    arg = context.args[0]
    plan_map = {"شهر": "شهر", "6اشهر": "6 أشهر", "6أشهر": "6 أشهر", "سنة": "سنة"}
    if arg in plan_map:
        days = PLANS[plan_map[arg]]
    elif arg.isdigit():
        days = int(arg)
    else:
        await update.message.reply_text("خطة غير معروفة.")
        return
    code = create_code(days)
    await update.message.reply_text(f"الكود: {code}\nالمدة: {days} يوم")


async def on_grade_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    grade = query.data.split(":", 1)[1]
    set_grade(query.message.chat_id, grade)
    await query.edit_message_text(f"تمام ✅ صفك: {grade}\n\nهلق اختار المادة:")
    await context.bot.send_message(
        chat_id=query.message.chat_id, text="اختار المادة:", reply_markup=subject_keyboard()
    )


async def on_subject_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subject = query.data.split(":", 1)[1]
    set_subject(query.message.chat_id, subject)
    await query.edit_message_text(
        f"تمام ✅ المادة: {subject}\n\n"
        "هلق فيك تبعتلي أي سؤال أو مسألة (نص أو صورة) وبحللها وبشرحلك ياها بالتفصيل.\n"
        "(فيك تغير الصف بـ /grade والمادة بـ /subject بأي وقت)"
    )


# ---------- الذكاء الاصطناعي ----------
def build_system_prompt(grade: str, subject: str) -> str:
    return (
        f"أنت معلم خصوصي محترف وصبور، بتشرح لطالب سوري بالصف {grade} بمادة {subject}. "
        "اعتمد قدر الإمكان على المنهاج السوري الرسمي المستخدم بالمدارس بسوريا، وراعي "
        "المصطلحات والأسلوب المتبع فيه. لما يبعتلك الطالب سؤال أو مسألة (نص أو صورة)، "
        "حللها وجاوب بالعربية بأسلوب مبسّط ومناسب لمستوى هالصف، مع شرح كامل خطوة بخطوة "
        "(مش بس الجواب النهائي)، واستخدم أمثلة لو بتساعد على الفهم. لو السؤال ناقص "
        "معلومات، اطلب التوضيح."
    )


def split_long_text(text: str, limit: int = TELEGRAM_MAX_LEN):
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


async def ask_claude_text(grade: str, subject: str, question: str) -> str:
    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=2000,
        system=build_system_prompt(grade, subject),
        messages=[{"role": "user", "content": question}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def ask_claude_image(grade: str, subject: str, image_bytes: bytes, media_type: str, caption: str) -> str:
    b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")
    user_text = caption.strip() if caption and caption.strip() else "حل هاد السؤال/المسألة وفسرلي ياها بالتفصيل."
    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=2000,
        system=build_system_prompt(grade, subject),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64_image},
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")


# ---------- تحقق الوصول ----------
async def check_access_or_warn(update: Update, chat_id: int) -> bool:
    ensure_student(chat_id)
    if has_access(chat_id):
        return True
    await update.message.reply_text(
        "⛔ خلصت فترتك المجانية/اشتراكك.\n"
        "لتجديد الاشتراك استخدم /subscribe لمعرفة الأسعار، وبعد الدفع رح تستلم كود "
        "تفعيل تدخلو بـ /redeem الكود."
    )
    return False


# ---------- استقبال الأسئلة ----------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not await check_access_or_warn(update, chat_id):
        return

    grade, subject, _, _ = get_student(chat_id)
    if not grade:
        await update.message.reply_text("لسا ما حددت صفك!", reply_markup=grade_keyboard())
        return
    if not subject:
        await update.message.reply_text("لسا ما حددت المادة!", reply_markup=subject_keyboard())
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        answer = await ask_claude_text(grade, subject, update.message.text)
    except Exception:
        logger.exception("خطأ بمعالجة النص")
        await update.message.reply_text("صار في خطأ وأنا بحاول حل السؤال، جرب كمان مرة 🙏")
        return

    for chunk in split_long_text(answer):
        await update.message.reply_text(chunk)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not await check_access_or_warn(update, chat_id):
        return

    grade, subject, _, _ = get_student(chat_id)
    if not grade:
        await update.message.reply_text("لسا ما حددت صفك!", reply_markup=grade_keyboard())
        return
    if not subject:
        await update.message.reply_text("لسا ما حددت المادة!", reply_markup=subject_keyboard())
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    image_bytes = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption or ""

    try:
        answer = await ask_claude_image(grade, subject, image_bytes, "image/jpeg", caption)
    except Exception:
        logger.exception("خطأ بمعالجة الصورة")
        await update.message.reply_text("صار في خطأ وأنا بحاول حل الصورة، جرب كمان مرة 🙏")
        return

    for chunk in split_long_text(answer):
        await update.message.reply_text(chunk)


# ---------- تشغيل البوت ----------
def main():
    if not TELEGRAM_BOT_TOKEN or not ANTHROPIC_API_KEY:
        raise SystemExit("لازم تحط TELEGRAM_BOT_TOKEN و ANTHROPIC_API_KEY بملف .env قبل ما تشغل البوت.")

    init_db()

    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grade", change_grade))
    app.add_handler(CommandHandler("subject", change_subject))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("subscribe", subscribe_info))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("gencode", gencode))
    app.add_handler(CallbackQueryHandler(on_grade_selected, pattern=r"^grade:"))
    app.add_handler(CallbackQueryHandler(on_subject_selected, pattern=r"^subject:"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("البوت شغال...")
    app.run_polling()


if __name__ == "__main__":
    main()
