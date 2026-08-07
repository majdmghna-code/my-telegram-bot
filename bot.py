import json
import os
from urllib.parse import quote

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)


TOKEN = os.environ["BOT_TOKEN"]

ADMIN_IDS = [6404738639]


# حالات محادثة الزبون
NAME, PHONE, DETAILS = range(3)

# حالات لوحة التحكم
ADMIN_PASS, ADMIN_MENU, SETTINGS_MENU, SERVICES_MENU, ADMIN_EDIT = range(3, 8)



def load_settings():
    with open("settings.json", "r", encoding="utf-8") as f:
        return json.load(f)



def save_settings():
    with open("settings.json", "w", encoding="utf-8") as f:
        json.dump(
            settings,
            f,
            ensure_ascii=False,
            indent=4
        )


settings = load_settings()



# ========== محادثة الزبون ==========


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    buttons = []

    for i in range(0, len(settings["services"]), 2):

        row = [
            InlineKeyboardButton(
                settings["services"][i],
                callback_data=f"service_{i}"
            )
        ]

        if i + 1 < len(settings["services"]):
            row.append(
                InlineKeyboardButton(
                    settings["services"][i + 1],
                    callback_data=f"service_{i+1}"
                )
            )

        buttons.append(row)

    await update.message.reply_text(
        settings["welcome_message"],
        reply_markup=InlineKeyboardMarkup(buttons)
    )



async def choose_service(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    index = int(query.data.split("_")[1])
    context.user_data["service"] = settings["services"][index]

    await query.message.reply_text("👤 اكتب اسمك:")

    return NAME



async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["name"] = update.message.text
    await update.message.reply_text("📱 اكتب رقم الواتساب:")

    return PHONE



async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["phone"] = update.message.text
    await update.message.reply_text("📝 اكتب تفاصيل الطلب:")

    return DETAILS



async def get_details(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["details"] = update.message.text

    msg = (
        "🔔 طلب جديد\n\n"
        f"👤 الاسم:\n{context.user_data['name']}\n\n"
        f"📱 الرقم:\n{context.user_data['phone']}\n\n"
        f"💻 الخدمة:\n{context.user_data['service']}\n\n"
        f"📝 التفاصيل:\n{context.user_data['details']}"
    )

    link = f"https://wa.me/{settings['whatsapp']}?text={quote(msg)}"

    await update.message.reply_text(
        "✅ تم استلام طلبك",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 فتح واتساب", url=link)]
        ])
    )

    context.user_data.clear()

    return ConversationHandler.END



async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء")

    return ConversationHandler.END



# ========== لوحة التحكم ==========


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ لا تملك صلاحية")
        return ConversationHandler.END

    await update.message.reply_text("🔐 اكتب كلمة مرور لوحة التحكم:")

    return ADMIN_PASS



async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text != settings["admin_password"]:
        await update.message.reply_text("❌ كلمة المرور خاطئة")
        return ConversationHandler.END

    await update.message.reply_text(
        "🔧 لوحة التحكم:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
            [InlineKeyboardButton("📋 الخدمات", callback_data="services")]
        ])
    )

    return ADMIN_MENU



async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "settings":

        await query.message.reply_text(
            "⚙️ الإعدادات:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ تعديل الرسالة", callback_data="welcome")],
                [InlineKeyboardButton("📱 تغيير الواتساب", callback_data="whatsapp")],
                [InlineKeyboardButton("🔑 تغيير كلمة المرور", callback_data="password")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="back")]
            ])
        )

        return SETTINGS_MENU

    elif query.data == "services":

        buttons = [
            [InlineKeyboardButton(f"🗑️ {s}", callback_data=f"del_{i}")]
            for i, s in enumerate(settings["services"])
        ]
        buttons.append([InlineKeyboardButton("➕ إضافة خدمة", callback_data="add")])
        buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data="back")])

        await query.message.reply_text(
            "📋 الخدمات (دوس عالخدمة لحذفها):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        return SERVICES_MENU



async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "🔧 لوحة التحكم:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
            [InlineKeyboardButton("📋 الخدمات", callback_data="services")]
        ])
    )

    return ADMIN_MENU



async def settings_button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    context.user_data["edit"] = query.data

    messages = {
        "welcome": "✏️ اكتب رسالة الترحيب الجديدة:",
        "whatsapp": "📱 اكتب رقم الواتساب الجديد (بدون + وبدون مسافات، مثال: 963912345678):",
        "password": "🔑 اكتب كلمة المرور الجديدة:"
    }

    await query.message.reply_text(messages[query.data])

    return ADMIN_EDIT



async def services_button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "add":
        context.user_data["edit"] = "add"
        await query.message.reply_text("➕ اكتب اسم الخدمة:")
        return ADMIN_EDIT

    elif query.data.startswith("del_"):
        index = int(query.data.split("_")[1])

        if 0 <= index < len(settings["services"]):
            removed = settings["services"].pop(index)
            save_settings()
            await query.message.reply_text(f"🗑️ تم حذف: {removed}")
        else:
            await query.message.reply_text("❌ الخدمة غير موجودة")

        return SERVICES_MENU



async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):

    edit = context.user_data.get("edit")

    if edit == "welcome":
        settings["welcome_message"] = update.message.text

    elif edit == "whatsapp":
        settings["whatsapp"] = update.message.text

    elif edit == "password":
        settings["admin_password"] = update.message.text

    elif edit == "add":
        settings["services"].append(update.message.text)

    save_settings()

    await update.message.reply_text("✅ تم الحفظ بنجاح")

    context.user_data.clear()

    return ConversationHandler.END



async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()
    await update.message.reply_text("❌ تم الخروج من لوحة التحكم")

    return ConversationHandler.END



app = Application.builder().token(TOKEN).build()



customer = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(choose_service, pattern="^service_")
    ],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_details)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)



admin_panel = ConversationHandler(
    entry_points=[
        CommandHandler("admin", admin)
    ],
    states={
        ADMIN_PASS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)
        ],
        ADMIN_MENU: [
            CallbackQueryHandler(admin_menu, pattern="^(settings|services)$")
        ],
        SETTINGS_MENU: [
            CallbackQueryHandler(back_to_admin_menu, pattern="^back$"),
            CallbackQueryHandler(settings_button, pattern="^(welcome|whatsapp|password)$")
        ],
        SERVICES_MENU: [
            CallbackQueryHandler(back_to_admin_menu, pattern="^back$"),
            CallbackQueryHandler(services_button, pattern="^(add|del_\\d+)$")
        ],
        ADMIN_EDIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)
        ]
    },
    fallbacks=[CommandHandler("cancel", admin_cancel)]
)



app.add_handler(CommandHandler("start", start))
app.add_handler(admin_panel)
app.add_handler(customer)


print("البوت يعمل الآن...")


app.run_polling()
