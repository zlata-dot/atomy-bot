# app.py
import os
from datetime import datetime, timezone, timedelta
from io import BytesIO

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.error import Forbidden
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from db import DB
from catalog import load_catalog_ru
from recommender import recommend_routine, build_plan_30
from rules import rule_assess
from pdf_offer import generate_offer_pdf

load_dotenv()

# ---------------- ENV ----------------
BOT_TOKEN = (os.getenv("BOT_TOKEN", "") or "").strip()
DB_PATH = (os.getenv("DB_PATH", "cosmo.sqlite3") or "").strip()
CATALOG_PATH = (os.getenv("CATALOG_PATH", "catalog_ru.csv") or "").strip()

ADMIN_NAME = (os.getenv("ADMIN_NAME", "Злата, @zkaflu") or "").strip()
ADMIN_TG = (os.getenv("ADMIN_TG", "") or "").strip()
ADMIN_PHONE = (os.getenv("ADMIN_PHONE", "") or "").strip()
ADMIN_NOTE = (os.getenv("ADMIN_NOTE", "") or "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

REGION = (os.getenv("REGION", "RU") or "").strip()
SUB_PRICE_RUB = int(os.getenv("SUB_PRICE_RUB", "99") or "99")
PRIVACY_URL = (os.getenv("PRIVACY_URL", "") or "").strip()

# Перевод по реквизитам
PAYMENT_RECIPIENT = (os.getenv("PAYMENT_RECIPIENT", "") or "").strip()
PAYMENT_BANK = (os.getenv("PAYMENT_BANK", "") or "").strip()
PAYMENT_CARD = (os.getenv("PAYMENT_CARD", "") or "").strip()
PAYMENT_PHONE = (os.getenv("PAYMENT_PHONE", "") or "").strip()
PAYMENT_COMMENT = (os.getenv("PAYMENT_COMMENT", "") or "").strip()

# Лимиты
FREE_INCI_CHECKS = 1  # 1 проверка составов бесплатно, дальше Premium

if not BOT_TOKEN:
    raise RuntimeError("В .env не указан BOT_TOKEN")

# ---------------- DB + CATALOG ----------------
db = DB(DB_PATH)
db.init()

CATALOG = []
try:
    CATALOG = load_catalog_ru(CATALOG_PATH)
except Exception as e:
    print(f"Каталог не загружен: {e}")

# ---------------- TEXTS ----------------
TERMS_TEXT = """
📄 УСЛОВИЯ PREMIUM (ПУБЛИЧНАЯ ОФЕРТА)

1. Premium — это услуга предоставления доступа к сервису персонального подбора ухода
и анализа составов косметики сроком на 30 дней с момента активации.

2. Стоимость Premium: 99 ₽ за 30 дней.

3. Услуга включает:
• персональный подбор ухода (безлимит)
• сохранение профиля и истории рекомендаций
• избранное/мой набор
• план на 30 дней
• поддержку администратора по подбору и оформлению заказа

4. Услуга НЕ включает продажу товаров.
Косметические продукты приобретаются пользователем отдельно
на официальном сайте или через консультанта.

5. Доступ активируется после подтверждения оплаты.

6. Возврат возможен в случае технической ошибки до момента использования сервиса.
Если доступ активирован и сервис использовался — возврат рассматривается индивидуально.

7. По вопросам работы сервиса можно обратиться к администратору.
""".strip()

PRIVACY_TEXT = """
📜 ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ (обработка персональных данных)

1) Какие данные обрабатываются
• Telegram user_id, имя/никнейм (если доступно)
• ответы на тест по коже (тип кожи, чувствительность, предпочтения)
• возраст и пол (если вы указали)
• история взаимодействия с ботом (рекомендации, избранное)
• статус Premium. Банковские данные карты я не получаю.

2) Цели обработки
• создание и хранение профиля кожи
• персональные рекомендации и подбор ухода
• предоставление доступа Premium и учёт оплат
• поддержка пользователей и улучшение сервиса

3) Срок хранения
Данные хранятся, пока вы пользуетесь сервисом, либо до запроса на удаление.

4) Передача третьим лицам
Данные не продаются и не передаются третьим лицам для рекламы.

5) Контакты
По вопросам конфиденциальности обратитесь к администратору сервиса.
""".strip()

# ---------------- TEST QUESTIONS ----------------
QUESTIONS = [
    {"text": "1) Через 2–3 часа после умывания без крема кожа:", "options": ["Стянута", "Комфорт", "Блестит", "И стянута и блестит местами"]},
    {"text": "2) Поры:", "options": ["Почти не видны", "Заметны в T-зоне", "Заметны везде", "Не знаю"]},
    {"text": "3) Шелушения бывают?", "options": ["Часто", "Иногда", "Редко", "Почти никогда"]},
    {"text": "4) Прыщи/комедоны:", "options": ["Часто", "Иногда", "Редко", "Почти никогда"]},
    {"text": "5) Реакция на новые средства:", "options": ["Часто жжёт/краснеет", "Иногда", "Редко", "Почти никогда"]},
    {"text": "6) К вечеру кожа чаще:", "options": ["Сухость", "Норм", "Жирный блеск", "Блеск в T-зоне"]},
    {"text": "7) После крема чаще:", "options": ["Комфорт", "Тяжесть/плёнка", "Блеск", "Зависит от зоны"]},
    {"text": "8) Главная проблема сейчас:", "options": ["Сухость/стянутость", "Жирность/блеск", "Высыпания", "Покраснение/раздражение", "Пигментация", "Просто базовый уход"]},
]

# ---------------- STATE ----------------
# state example:
# USER_STATE[user_id] = {"mode":"test","phase":"age"/"gender"/"q", "age":None, "gender":None, "step":0, "answers":[]}
USER_STATE: dict[int, dict] = {}

# ---------------- HELPERS ----------------
def _is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID

def admin_block_lines() -> list[str]:
    lines = [f"👤 Администратор: {ADMIN_NAME}"]
    if ADMIN_TG:
        lines.append(f"Telegram: {ADMIN_TG}")
    if ADMIN_PHONE:
        lines.append(f"Телефон: {ADMIN_PHONE}")
    if ADMIN_NOTE:
        lines.append(ADMIN_NOTE)
    return lines

def parse_iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None

def premium_status(user_id: int) -> tuple[bool, str]:
    sub = db.get_subscription(user_id)
    until = parse_iso(sub.get("premium_until"))
    if sub.get("is_premium") == 1 and until and until > datetime.now(timezone.utc):
        return True, until.strftime("%Y-%m-%d")
    return False, (until.strftime("%Y-%m-%d") if until else "—")

def can_use_premium_feature(user_id: int) -> bool:
    prem, _ = premium_status(user_id)
    return prem

def can_check_inci(user_id: int) -> tuple[bool, str]:
    """Premium = безлимит. Без Premium = 1 проверка."""
    prem, _ = premium_status(user_id)
    if prem:
        return True, ""

    used = db.get_checks_used(user_id)
    if used >= FREE_INCI_CHECKS:
        return False, (
            f"🚫 Бесплатная проверка составов исчерпана ({FREE_INCI_CHECKS}/{FREE_INCI_CHECKS}).\n\n"
            f"💎 Premium — {SUB_PRICE_RUB} ₽ / 30 дней (услуга доступа).\n"
            "В Premium:\n"
            "• ⭐ Избранное / Мой набор\n"
            "• 📅 План на 30 дней\n"
            "• ✅ Безлимитные проверки составов\n\n"
            "Нажми «💳 Premium»."
        )
    return True, ""

def premium_screen_text(user_id: int) -> str:
    prem, until = premium_status(user_id)
    used = db.get_checks_used(user_id)

    lines = []
    lines.append(f"💎 Premium-доступ (услуга) — {SUB_PRICE_RUB} ₽ / 30 дней")
    lines.append("")
    lines.append("Что даёт Premium:")
    lines.append("• ⭐ Избранное / Мой набор")
    lines.append("• 📅 План на 30 дней по твоему набору")
    lines.append("• ✅ Безлимитные проверки составов")
    lines.append("• Поддержка администратора")
    lines.append("")
    lines.append("ℹ️ Важно: вы оплачиваете услугу доступа к сервису. Косметика приобретается отдельно.")
    lines.append("")
    lines.append(f"Ваш статус: {'✅ активен до ' + until if prem else 'не активен'}")
    if not prem:
        lines.append(f"Бесплатная проверка составов: {min(used, FREE_INCI_CHECKS)}/{FREE_INCI_CHECKS}")
    return "\n".join(lines)

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Пройти тест кожи", callback_data="test:start")],
        [InlineKeyboardButton("🧴 Подобрать уход Atomy (RU)", callback_data="routine:make")],
        [InlineKeyboardButton("⭐ Избранное / Мой набор (Premium)", callback_data="favorites:show")],
        [InlineKeyboardButton("📅 План на 30 дней (Premium)", callback_data="plan:30")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile:show")],
        [InlineKeyboardButton("💳 Premium", callback_data="premium:screen")],
        [InlineKeyboardButton("📄 Условия Premium", callback_data="premium:terms")],
        [InlineKeyboardButton("📜 Политика конфиденциальности", callback_data="privacy:show")],
        [InlineKeyboardButton("💬 Написать администратору", callback_data="admin:show")],
    ])

def premium_screen_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Перевод по реквизитам", callback_data="premium:transfer")],
        [InlineKeyboardButton("📩 Я оплатил(а) — отправить ID админу", callback_data="premium:send_id")],
        [InlineKeyboardButton("📄 Условия Premium", callback_data="premium:terms")],
        [InlineKeyboardButton("📄 PDF-оферта", callback_data="premium:pdf")],
        [InlineKeyboardButton("📜 Политика конфиденциальности", callback_data="privacy:show")],
        [InlineKeyboardButton("📌 Мой статус Premium", callback_data="premium:status")],
    ])

def question_keyboard(q_index: int) -> InlineKeyboardMarkup:
    buttons = []
    for i, opt in enumerate(QUESTIONS[q_index]["options"]):
        buttons.append([InlineKeyboardButton(opt, callback_data=f"test:answer:{q_index}:{i}")])
    buttons.append([InlineKeyboardButton("⛔️ Отменить тест", callback_data="test:cancel")])
    return InlineKeyboardMarkup(buttons)

def age_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("18–24", callback_data="test:age:21")],
        [InlineKeyboardButton("25–34", callback_data="test:age:30")],
        [InlineKeyboardButton("35–44", callback_data="test:age:40")],
        [InlineKeyboardButton("45+", callback_data="test:age:50")],
        [InlineKeyboardButton("Пропустить", callback_data="test:age:0")],
        [InlineKeyboardButton("⛔️ Отменить тест", callback_data="test:cancel")],
    ])

def gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Женщина", callback_data="test:gender:f")],
        [InlineKeyboardButton("Мужчина", callback_data="test:gender:m")],
        [InlineKeyboardButton("Пропустить", callback_data="test:gender:x")],
        [InlineKeyboardButton("⛔️ Отменить тест", callback_data="test:cancel")],
    ])

def favs_keyboard_for_item(product_id: str, step: str, is_fav: bool) -> InlineKeyboardMarkup:
    if is_fav:
        btn = InlineKeyboardButton("✅ В наборе (убрать)", callback_data=f"fav:remove:{product_id}")
    else:
        btn = InlineKeyboardButton("⭐ Добавить в мой набор", callback_data=f"fav:add:{product_id}:{step}")
    return InlineKeyboardMarkup([[btn]])

def calc_profile(answers: list[int]) -> dict:
    dry = oil = sens = acne = 0
    concerns = []

    q1 = answers[0]
    if q1 == 0: dry += 2
    if q1 == 2: oil += 2
    if q1 == 3: dry += 1; oil += 1

    q2 = answers[1]
    if q2 == 2: oil += 2
    elif q2 == 1: oil += 1

    q3 = answers[2]
    if q3 == 0: dry += 2
    elif q3 == 1: dry += 1

    q4 = answers[3]
    if q4 == 0: acne += 2
    elif q4 == 1: acne += 1

    q5 = answers[4]
    if q5 == 0: sens += 2
    elif q5 == 1: sens += 1

    q6 = answers[5]
    if q6 == 0: dry += 1
    elif q6 == 2: oil += 2
    elif q6 == 3: oil += 1

    q7 = answers[6]
    if q7 == 1: oil += 1
    if q7 == 2: oil += 2

    q8 = answers[7]
    if q8 == 0: concerns.append("сухость")
    if q8 == 1: concerns.append("жирность")
    if q8 == 2: concerns.append("высыпания")
    if q8 == 3: concerns.append("покраснение/раздражение"); sens += 1
    if q8 == 4: concerns.append("пигментация")
    if q8 == 5: concerns.append("базовый уход")

    if dry >= 3 and oil <= 1: skin_type = "сухая"
    elif oil >= 3 and dry <= 1: skin_type = "жирная"
    elif oil >= 3 and dry >= 2: skin_type = "комбинированная"
    else: skin_type = "нормальная"

    if sens >= 3: sensitivity = "высокая"
    elif sens == 2: sensitivity = "средняя"
    else: sensitivity = "низкая"

    if dry >= 4 or sens >= 3: barrier_state = "барьер ослаблен/есть обезвоженность"
    elif dry >= 2: barrier_state = "есть обезвоженность"
    else: barrier_state = "норма"

    if acne >= 2 and "высыпания" not in concerns:
        concerns.append("высыпания")

    return {
        "skin_type": skin_type,
        "barrier_state": barrier_state,
        "sensitivity": sensitivity,
        "concerns": ", ".join(concerns) if concerns else "нет выраженных",
    }

def fmt_price(item) -> str:
    after = getattr(item, "price_after_rub", None)
    before = getattr(item, "price_before_rub", None)
    a = f"{after} ₽" if after else "—"
    b = f"{before} ₽" if before else "—"
    return f"{a} (после регистрации) / {b} (до регистрации)"

def safe_product_id(item) -> str:
    pid = getattr(item, "product_id", None) or getattr(item, "code", None) or getattr(item, "sku", None)
    if pid:
        return str(pid)[:32]
    # fallback: short hash-ish
    return str(abs(hash(getattr(item, "url", "") or getattr(item, "name", "") or "item")))[:12]

# ---------------- COMMANDS ----------------
async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я бот по подбору косметики Атоми (Россия).\n"
        "Ответь на несколько вопросов — и я подберу тебе подходящие средства.\n\n"
        f"✅ 1 проверка состава бесплатно. Premium — {SUB_PRICE_RUB} ₽ / 30 дней.\n"
        "ℹ️ Косметика покупается отдельно.",
        reply_markup=main_menu_keyboard()
    )

async def cmd_terms(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TERMS_TEXT, reply_markup=main_menu_keyboard())

async def cmd_privacy(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if PRIVACY_URL:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть политику на сайте", url=PRIVACY_URL)]])
        await update.message.reply_text("📜 Политика конфиденциальности доступна по ссылке:", reply_markup=kb)
    else:
        await update.message.reply_text(PRIVACY_TEXT, reply_markup=main_menu_keyboard())

async def cmd_offer_pdf(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    pdf_bytes = generate_offer_pdf(TERMS_TEXT, title="Условия Premium (публичная оферта)")
    bio = BytesIO(pdf_bytes)
    bio.name = "offer_premium.pdf"
    await update.message.reply_document(document=InputFile(bio), caption="📄 PDF-оферта Premium")

async def cmd_myid(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш user_id: {update.effective_user.id}")

async def cmd_status(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    prem, until = premium_status(user_id)
    await update.message.reply_text(
        f"✅ Premium активен до {until}" if prem else f"ℹ️ Premium не активен. Последняя дата: {until}",
        reply_markup=main_menu_keyboard()
    )

async def cmd_profile(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    prof = db.get_profile(user_id)
    prem, until = premium_status(user_id)

    if not prof or not prof.get("skin_type"):
        await update.message.reply_text("Профиля ещё нет. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    gender = prof.get("gender") or "—"
    age = prof.get("age") or "—"

    await update.message.reply_text(
        "👤 Твой профиль:\n"
        f"• Возраст: {age}\n"
        f"• Пол: {gender}\n"
        f"• Тип кожи: {prof.get('skin_type')}\n"
        f"• Барьер: {prof.get('barrier_state')}\n"
        f"• Чувствительность: {prof.get('sensitivity')}\n"
        f"• Проблемы: {prof.get('concerns')}\n\n"
        f"Premium: {'✅ до ' + until if prem else 'нет'}",
        reply_markup=main_menu_keyboard()
    )

# --- ADMIN COMMANDS ---
async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /grant <user_id> [days]")
        return
    target_id = int(context.args[0])
    days = int(context.args[1]) if len(context.args) > 1 else 30
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    db.set_premium(target_id, until, payment_method_id=None, last_payment_id=None)
    await update.message.reply_text(f"✅ Premium выдан user_id={target_id} на {days} дней")

async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    target_id = int(context.args[0])
    db.disable_premium(target_id)
    await update.message.reply_text(f"✅ Premium отключён для user_id={target_id}")

async def cmd_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /receipt <user_id>")
        return
    target_id = int(context.args[0])
    db.mark_receipt_issued(target_id, yk_payment_id=None, amount_rub=SUB_PRICE_RUB)
    await update.message.reply_text(f"✅ Отмечено: чек сформирован для user_id={target_id}")

# ---------------- CALLBACKS ----------------
async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    db.ensure_user(user_id)
    data = q.data

    # ---- Premium gate for Favorites / Plan 30 ----
    if data.startswith("favorites:") or data.startswith("fav:"):
        if not can_use_premium_feature(user_id):
            if q.message:
                await q.message.reply_text(
                    "⭐ Избранное / Мой набор доступно только в Premium.\n\n"
                    "В Premium:\n"
                    "• ⭐ Избранное / Мой набор\n"
                    "• 📅 План на 30 дней\n"
                    "• ✅ Безлимитные проверки составов\n\n"
                    "Нажми «💳 Premium».",
                    reply_markup=main_menu_keyboard()
                )
            return

    if data == "plan:30":
        prem, until = premium_status(user_id)
        if not prem:
            if q.message:
                await q.message.reply_text(
                    "📅 План на 30 дней доступен только в Premium.\n\n"
                    "Premium даёт:\n"
                    "• ⭐ Избранное / Мой набор\n"
                    "• 📅 План на 30 дней по твоим продуктам\n"
                    "• ✅ Безлимитные проверки составов\n\n"
                    f"Стоимость: {SUB_PRICE_RUB} ₽ / 30 дней (услуга доступа).\n"
                    "Нажми «💳 Premium».",
                    reply_markup=main_menu_keyboard()
                )
            return

        prof = db.get_profile(user_id)
        if not prof or not prof.get("skin_type"):
            if q.message:
                await q.message.reply_text(
                    "Сначала пройди тест кожи — тогда я составлю план под твой профиль.",
                    reply_markup=main_menu_keyboard()
                )
            return

        favs = db.list_favorites(user_id)

        try:
            plan_text = build_plan_30(prof, favs)
        except Exception as e:
            if ADMIN_ID:
                try:
                    await context.application.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"❌ Ошибка plan:30 для user_id={user_id}\n{type(e).__name__}: {e}"
                    )
                except Exception:
                    pass
            if q.message:
                await q.message.reply_text(
                    "❌ План временно недоступен (ошибка). Я отправила детали админу.",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text(plan_text, reply_markup=main_menu_keyboard())
        return

    # ---- Favorites UI ----
    if data == "favorites:show":
        favs = db.list_favorites(user_id)
        if q.message:
            if not favs:
                await q.message.reply_text("⭐ В избранном пока пусто. Добавь товары из рекомендаций.", reply_markup=main_menu_keyboard())
            else:
                lines = ["⭐ Твой набор:"]
                for f in favs[:50]:
                    lines.append(f"• {f.get('name')} ({f.get('step')})")
                    if f.get("url"):
                        lines.append(f"  {f.get('url')}")
                await q.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())
        return

    if data.startswith("fav:add:"):
        # fav:add:<product_id>:<step>
        try:
            _, _, pid, step = data.split(":", 3)
        except Exception:
            return

        # Найдём в каталоге
        item = None
        for it in CATALOG:
            if safe_product_id(it) == pid:
                item = it
                break

        if not item:
            if q.message:
                await q.message.reply_text("Не нашла товар в каталоге. Обнови каталог и попробуй снова.", reply_markup=main_menu_keyboard())
            return

        db.add_favorite(
            user_id=user_id,
            product_id=pid,
            step=step,
            name=getattr(item, "name", "Товар"),
            url=getattr(item, "url", None),
            price_after_rub=getattr(item, "price_after_rub", None),
            price_before_rub=getattr(item, "price_before_rub", None),
        )
        if q.message:
            await q.message.reply_text("✅ Добавлено в твой набор.", reply_markup=main_menu_keyboard())
        return

    if data.startswith("fav:remove:"):
        # fav:remove:<product_id>
        try:
            _, _, pid = data.split(":", 2)
        except Exception:
            return
        db.remove_favorite(user_id, pid)
        if q.message:
            await q.message.reply_text("🗑 Убрала из набора.", reply_markup=main_menu_keyboard())
        return

    # ---- Admin / Premium / Policy ----
    if data == "admin:show":
        if q.message:
            await q.message.reply_text("\n".join(admin_block_lines()), reply_markup=main_menu_keyboard())
        return

    if data == "premium:screen":
        if q.message:
            await q.message.reply_text(premium_screen_text(user_id), reply_markup=premium_screen_keyboard())
        return

    if data == "premium:terms":
        if q.message:
            await q.message.reply_text(TERMS_TEXT, reply_markup=main_menu_keyboard())
        return

    if data == "premium:pdf":
        pdf_bytes = generate_offer_pdf(TERMS_TEXT, title="Условия Premium (публичная оферта)")
        bio = BytesIO(pdf_bytes)
        bio.name = "offer_premium.pdf"
        if q.message:
            await q.message.reply_document(document=InputFile(bio), caption="📄 PDF-оферта Premium")
        return

    if data == "privacy:show":
        if PRIVACY_URL:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть политику на сайте", url=PRIVACY_URL)]])
            if q.message:
                await q.message.reply_text("📜 Политика конфиденциальности доступна по ссылке:", reply_markup=kb)
        else:
            if q.message:
                await q.message.reply_text(PRIVACY_TEXT, reply_markup=main_menu_keyboard())
        return

    if data == "premium:status":
        prem, until = premium_status(user_id)
        if q.message:
            await q.message.reply_text(
                f"✅ Premium активен до {until}" if prem else f"ℹ️ Premium не активен. Последняя дата: {until}",
                reply_markup=main_menu_keyboard()
            )
        return

    if data == "premium:transfer":
        lines = []
        lines.append(f"💸 Перевод по реквизитам: {SUB_PRICE_RUB} ₽")
        lines.append("")
        if PAYMENT_RECIPIENT:
            lines.append(f"Получатель: {PAYMENT_RECIPIENT}")
        if PAYMENT_BANK:
            lines.append(f"Банк: {PAYMENT_BANK}")
        if PAYMENT_PHONE:
            lines.append(f"СБП (телефон): {PAYMENT_PHONE}")
        if PAYMENT_CARD:
            lines.append(f"Карта: {PAYMENT_CARD}")
        lines.append("")
        lines.append(f"Назначение: {PAYMENT_COMMENT or 'Premium (услуга доступа к сервису на 30 дней)'}")
        lines.append("")
        lines.append("После оплаты нажмите: «📩 Я оплатил(а) — отправить ID админу».")
        lines.append("ℹ️ Косметика приобретается отдельно.")
        if q.message:
            await q.message.reply_text("\n".join(lines), reply_markup=premium_screen_keyboard())
        return

    if data == "premium:send_id":
        if ADMIN_ID == 0:
            if q.message:
                await q.message.reply_text("❌ Администратор не настроен (ADMIN_ID=0).")
            return

        uname = q.from_user.username or "-"
        full_name = (q.from_user.full_name or "-").strip()
        prof = db.get_profile(user_id)
        prem, until = premium_status(user_id)

        prof_line = ""
        if prof and prof.get("skin_type"):
            prof_line = (
                f"\nПрофиль: {prof.get('skin_type')} | {prof.get('sensitivity')} | {prof.get('concerns')}"
                f"\nВозраст: {prof.get('age') or '-'} | Пол: {prof.get('gender') or '-'}"
            )

        text_to_admin = (
            "📩 Пользователь сообщил об оплате Premium\n\n"
            f"user_id: {user_id}\n"
            f"username: @{uname}\n"
            f"имя: {full_name}\n"
            f"Premium: {'активен до ' + until if prem else 'не активен'}"
            f"{prof_line}\n\n"
            "Команды:\n"
            f"/grant {user_id} 30\n"
            f"/receipt {user_id}\n"
        )

        try:
            await context.application.bot.send_message(chat_id=ADMIN_ID, text=text_to_admin)
        except Forbidden:
            if q.message:
                await q.message.reply_text(
                    "❌ Не могу написать админу (Telegram запретил).\n\n"
                    "✅ Решение:\n"
                    "1) Админ должен открыть этого бота и нажать Start\n"
                    "2) Повторите кнопку «Отправить ID админу»\n\n"
                    f"Ваш user_id: {user_id}\n"
                    f"Админ: {ADMIN_TG or '(укажи ADMIN_TG в .env)'}",
                    reply_markup=main_menu_keyboard()
                )
            return
        except Exception:
            if q.message:
                await q.message.reply_text(
                    "❌ Ошибка отправки админу. Проверь ADMIN_ID в .env.\n"
                    f"Ваш user_id: {user_id}",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text("✅ Отправила ваш ID админу. Он активирует Premium.", reply_markup=main_menu_keyboard())
        return

    # ---- Profile show ----
    if data == "profile:show":
        prof = db.get_profile(user_id)
        prem, until = premium_status(user_id)

        if q.message:
            if not prof or not prof.get("skin_type"):
                await q.message.reply_text("Профиля ещё нет. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
            else:
                await q.message.reply_text(
                    "👤 Твой профиль:\n"
                    f"• Возраст: {prof.get('age') or '—'}\n"
                    f"• Пол: {prof.get('gender') or '—'}\n"
                    f"• Тип кожи: {prof.get('skin_type')}\n"
                    f"• Барьер: {prof.get('barrier_state')}\n"
                    f"• Чувствительность: {prof.get('sensitivity')}\n"
                    f"• Проблемы: {prof.get('concerns')}\n\n"
                    f"Premium: {'✅ до ' + until if prem else 'нет'}",
                    reply_markup=main_menu_keyboard()
                )
        return

    # ---- Test start ----
    if data == "test:start":
        USER_STATE[user_id] = {"mode": "test", "phase": "age", "age": None, "gender": None, "step": 0, "answers": []}
        if q.message:
            await q.message.reply_text("Перед тестом укажи возраст:", reply_markup=age_keyboard())
        return

    if data == "test:cancel":
        USER_STATE.pop(user_id, None)
        if q.message:
            await q.message.reply_text("Тест отменён.", reply_markup=main_menu_keyboard())
        return

    # ---- Age / Gender steps ----
    if data.startswith("test:age:"):
        st = USER_STATE.get(user_id)
        if not st or st.get("mode") != "test":
            return
        try:
            age_val = int(data.split(":")[-1])
        except Exception:
            age_val = 0
        st["age"] = age_val if age_val > 0 else None
        st["phase"] = "gender"
        if q.message:
            await q.message.reply_text("Теперь укажи пол:", reply_markup=gender_keyboard())
        return

    if data.startswith("test:gender:"):
        st = USER_STATE.get(user_id)
        if not st or st.get("mode") != "test":
            return
        g = data.split(":")[-1]
        gender_val = "женщина" if g == "f" else "мужчина" if g == "m" else None
        st["gender"] = gender_val
        st["phase"] = "q"
        if q.message:
            await q.message.reply_text(QUESTIONS[0]["text"], reply_markup=question_keyboard(0))
        return

    # ---- Routine ----
    if data == "routine:make":
        prof = db.get_profile(user_id)
        if not prof or not prof.get("skin_type"):
            if q.message:
                await q.message.reply_text("Сначала пройди тест кожи.", reply_markup=main_menu_keyboard())
            return

        if not CATALOG:
            if q.message:
                await q.message.reply_text(
                    "Каталог не загружен.\n\n"
                    "1) Выполни: python update_catalog.py\n"
                    "2) Перезапусти бота: python app.py",
                    reply_markup=main_menu_keyboard()
                )
            return

        routine = recommend_routine(CATALOG, prof)

        lines = []
        lines.append("🧴 Подбор ухода Atomy (Россия)")
        lines.append(f"Тип кожи: {prof.get('skin_type')}")
        lines.append(f"Чувствительность: {prof.get('sensitivity')}")
        lines.append(f"Особенности: {prof.get('concerns')}")
        lines.append(f"Возраст: {prof.get('age') or '—'} | Пол: {prof.get('gender') or '—'}")
        lines.append("")
        lines.append("ℹ️ Косметика приобретается отдельно на официальном сайте Atomy.")
        lines.append("")

        titles = {"cleanser": "Очищение", "toner": "Тонер", "serum": "Сыворотка", "cream": "Крем", "sunscreen": "SPF"}
        if q.message:
            # 1) сначала общий текст
            await q.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())

            # 2) потом карточки с кнопкой "в набор"
            for step, title in titles.items():
                items = routine.get(step, [])
                if not items:
                    await q.message.reply_text(f"--- {title} ---\nНет подходящих средств в каталоге.")
                    continue

                await q.message.reply_text(f"--- {title} ---")
                for item, score, why in items[:3]:
                    pid = safe_product_id(item)
                    is_f = db.is_favorite(user_id, pid)

                    msg_lines = [
                        getattr(item, "name", "Товар"),
                        f"Цена: {fmt_price(item)}",
                        f"Комментарий: {why}",
                    ]
                    if getattr(item, "url", None):
                        msg_lines.append(f"Ссылка: {item.url}")

                    # Кнопка "в набор" только Premium, иначе покажем подсказку
                    if can_use_premium_feature(user_id):
                        kb = favs_keyboard_for_item(pid, step, is_f)
                    else:
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Избранное в Premium", callback_data="premium:screen")]])

                    await q.message.reply_text("\n".join(msg_lines), reply_markup=kb)

            # 3) админ в конце
            await q.message.reply_text("\n".join(admin_block_lines()), reply_markup=main_menu_keyboard())
        return


async def on_test_answer(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    st = USER_STATE.get(user_id)
    if not st or st.get("mode") != "test" or st.get("phase") != "q":
        if q.message:
            await q.message.reply_text("Тест не запущен. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    # test:answer:q_index:opt_index
    try:
        _, _, q_index_str, opt_index_str = q.data.split(":")
        q_index = int(q_index_str)
        opt_index = int(opt_index_str)
    except Exception:
        return

    if q_index != st["step"]:
        return

    st["answers"].append(opt_index)
    st["step"] += 1

    if st["step"] < len(QUESTIONS):
        i = st["step"]
        if q.message:
            await q.message.reply_text(QUESTIONS[i]["text"], reply_markup=question_keyboard(i))
        return

    prof_calc = calc_profile(st["answers"])

    # сохраняем возраст/пол + профиль
    db.save_profile(
        user_id=user_id,
        age=st.get("age"),
        gender=st.get("gender"),
        skin_type=prof_calc["skin_type"],
        barrier_state=prof_calc["barrier_state"],
        sensitivity=prof_calc["sensitivity"],
        concerns=prof_calc["concerns"],
    )

    USER_STATE.pop(user_id, None)

    if q.message:
        await q.message.reply_text(
            "✅ Профиль сохранён!\n\n"
            f"• Возраст: {db.get_profile(user_id).get('age') or '—'}\n"
            f"• Пол: {db.get_profile(user_id).get('gender') or '—'}\n"
            f"• Тип кожи: {prof_calc['skin_type']}\n"
            f"• Барьер: {prof_calc['barrier_state']}\n"
            f"• Чувствительность: {prof_calc['sensitivity']}\n"
            f"• Проблемы: {prof_calc['concerns']}\n\n"
            "Теперь нажми «🧴 Подобрать уход Atomy (RU)».",
            reply_markup=main_menu_keyboard()
        )


async def handle_message(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    text = (update.message.text or "").strip()
    if not text:
        return

    prof = db.get_profile(user_id)
    if not prof or not prof.get("skin_type"):
        await update.message.reply_text("Сначала пройди тест: «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    # 1 бесплатная проверка, далее Premium. Premium = безлимит.
    ok, reason = can_check_inci(user_id)
    if not ok:
        await update.message.reply_text(reason, reply_markup=main_menu_keyboard())
        return

    verdict, reasons = rule_assess(text, prof)

    out = []
    out.append(
        "✅ Вердикт: подходит" if verdict == "good"
        else "⚠️ Вердикт: с осторожностью" if verdict == "caution"
        else "❌ Вердикт: скорее не подходит"
    )
    if reasons:
        out.append("Причины:")
        out.extend([f"• {r}" for r in reasons])

    out.append("")
    out.append("ℹ️ Важно: вы оплачиваете услугу доступа к сервису. Косметика приобретается отдельно.")
    out.append("")
    out.extend(admin_block_lines())

    prem, _ = premium_status(user_id)
    if not prem:
        db.inc_checks_used(user_id)
        used = db.get_checks_used(user_id)
        out.append(f"\nПроверка составов: {min(used, FREE_INCI_CHECKS)}/{FREE_INCI_CHECKS} (free)")

    await update.message.reply_text("\n".join(out), reply_markup=main_menu_keyboard())


# ---------------- MAIN ----------------
def main():
    print("Бот запускается...")
    print(f"REGION={REGION}")
    print(f"CATALOG_PATH={CATALOG_PATH}")
    print(f"Товаров в каталоге: {len(CATALOG)}")
    print(f"ADMIN_ID={ADMIN_ID}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("terms", cmd_terms))
    app.add_handler(CommandHandler("privacy", cmd_privacy))
    app.add_handler(CommandHandler("offer_pdf", cmd_offer_pdf))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("profile", cmd_profile))

    # admin commands
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("receipt", cmd_receipt))

    # callbacks
    app.add_handler(CallbackQueryHandler(on_test_answer, pattern=r"^test:answer:"))
    app.add_handler(CallbackQueryHandler(on_menu_click))

    # text messages (INCI check)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен ✅")
    app.run_polling()


if __name__ == "__main__":
    main()