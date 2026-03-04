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
from recommender import recommend_routine
from rules import rule_assess
from pdf_offer import generate_offer_pdf

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "cosmo.sqlite3").strip()
CATALOG_PATH = os.getenv("CATALOG_PATH", "catalog_ru.csv").strip()

ADMIN_NAME = os.getenv("ADMIN_NAME", "Администратор").strip()
ADMIN_TG = os.getenv("ADMIN_TG", "").strip()
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").strip()
ADMIN_NOTE = os.getenv("ADMIN_NOTE", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

REGION = os.getenv("REGION", "RU").strip()
SUB_PRICE_RUB = int(os.getenv("SUB_PRICE_RUB", "99") or "99")
PRIVACY_URL = (os.getenv("PRIVACY_URL", "") or "").strip()

# реквизиты (перевод)
PAYMENT_RECIPIENT = (os.getenv("PAYMENT_RECIPIENT", "") or "").strip()
PAYMENT_BANK = (os.getenv("PAYMENT_BANK", "") or "").strip()
PAYMENT_CARD = (os.getenv("PAYMENT_CARD", "") or "").strip()
PAYMENT_PHONE = (os.getenv("PAYMENT_PHONE", "") or "").strip()
PAYMENT_COMMENT = (os.getenv("PAYMENT_COMMENT", "") or "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. На Railway добавь BOT_TOKEN в Variables.")

db = DB(DB_PATH)
db.init()

# Каталог
CATALOG = []
try:
    CATALOG = load_catalog_ru(CATALOG_PATH)
except Exception as e:
    print(f"Каталог не загружен: {e}")

# USER_STATE:
# - test stages: age -> gender -> skin
# - inci stage: inci
USER_STATE = {}

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

TERMS_TEXT = """
📄 УСЛОВИЯ PREMIUM (ПУБЛИЧНАЯ ОФЕРТА)

1. Premium — это услуга предоставления доступа к сервису персонального подбора ухода 
и анализа составов косметики сроком на 30 дней с момента активации.

2. Стоимость Premium: 99 ₽ за 30 дней.

3. Услуга включает:
• персональный подбор ухода(безлимит)
• сохранение профиля и истории рекомендаций
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

1) Общие положения
Я (самозанятая/самозанятый) предоставляю доступ к сервису подбора косметики и анализа составов.

2) Какие данные могут обрабатываться
• Telegram user_id, имя/никнейм (если доступно)
• ответы на тест по коже (тип кожи, чувствительность, предпочтения)
• история взаимодействия с ботом (рекомендации, выбранные товары)
• данные об оплате подписки (подтверждение/статус)

3) Цели обработки
• создание и хранение профиля кожи
• персональные рекомендации и подбор ухода
• доступ Premium и учёт оплат
• поддержка пользователей

4) Срок хранения
Пока вы пользуетесь сервисом, либо до запроса на удаление.

5) Передача третьим лицам
Данные не продаются и не передаются третьим лицам для рекламы.

6) Контакты
По вопросам конфиденциальности обратитесь к администратору сервиса.
""".strip()


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


def premium_screen_text(user_id: int) -> str:
    prem, until = premium_status(user_id)
    used = db.get_checks_used(user_id)
    lines = []
    lines.append(f"💎 Premium-доступ (услуга) — {SUB_PRICE_RUB} ₽ / 30 дней")
    lines.append("")
    lines.append("Что даёт Premium:")
    lines.append("• Безлимитные проверки составов (INCI)")
    lines.append("• Расширенный подбор ухода под тип кожи и цели")
    lines.append("• Профиль + избранное/набор")
    lines.append("• План на 30 дней")
    lines.append("• Поддержка администратора")
    lines.append("")
    lines.append("ℹ️ Важно: вы оплачиваете услугу доступа. Косметика приобретается отдельно.")
    lines.append("")
    lines.append(f"Ваш статус: {'✅ активен до ' + until if prem else 'не активен'}")
    lines.append(f"Бесплатные проверки использовано: {min(used, 3)}/3")
    return "\n".join(lines)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Пройти тест кожи", callback_data="test:start")],
        [InlineKeyboardButton("🧴 Подобрать уход Atomy (RU)", callback_data="routine:make")],
        [InlineKeyboardButton("⭐ Мой набор", callback_data="fav:show")],
        [InlineKeyboardButton("📅 План на 30 дней", callback_data="plan:30")],
        [InlineKeyboardButton("🔎 Проверка состава (INCI)", callback_data="inci:start")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile:show")],
        [InlineKeyboardButton("💳 Premium", callback_data="premium:screen")],
        [InlineKeyboardButton("📄 Условия Premium", callback_data="premium:terms")],
        [InlineKeyboardButton("📜 Политика конфиденциальности", callback_data="privacy:show")],
        [InlineKeyboardButton("💬 Написать администратору", callback_data="admin:show")],
    ])


def premium_screen_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💸 Перевод по реквизитам", callback_data="premium:transfer")],
        [InlineKeyboardButton("📩 Я оплатил(а) — отправить ID админу", callback_data="premium:send_id")],
        [InlineKeyboardButton("📄 Условия Premium", callback_data="premium:terms")],
        [InlineKeyboardButton("📄 PDF-оферта", callback_data="premium:pdf")],
        [InlineKeyboardButton("📜 Политика конфиденциальности", callback_data="privacy:show")],
        [InlineKeyboardButton("📌 Мой статус Premium", callback_data="premium:status")],
    ]
    return InlineKeyboardMarkup(rows)


def question_keyboard(q_index: int) -> InlineKeyboardMarkup:
    buttons = []
    for i, opt in enumerate(QUESTIONS[q_index]["options"]):
        buttons.append([InlineKeyboardButton(opt, callback_data=f"test:answer:{q_index}:{i}")])
    buttons.append([InlineKeyboardButton("⛔️ Отменить тест", callback_data="test:cancel")])
    return InlineKeyboardMarkup(buttons)


def gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Женщина", callback_data="test:gender:woman")],
        [InlineKeyboardButton("Мужчина", callback_data="test:gender:man")],
        [InlineKeyboardButton("⛔️ Отменить тест", callback_data="test:cancel")],
    ])


def _fav_item_keyboard(step: str, idx: int, url: str | None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("⭐ Добавить в набор", callback_data=f"fav:add:{step}:{idx}")]]
    if url:
        rows.append([InlineKeyboardButton("🔗 Открыть на сайте", url=url)])
    return InlineKeyboardMarkup(rows)


def _myset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 Оформить через администратора", callback_data="lead:send")],
        [InlineKeyboardButton("🗑 Очистить набор", callback_data="fav:clear")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="menu:home")],
    ])


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


import re

def _pick_item(items: list[str], prefer: list[str], avoid: list[str]) -> str | None:
    """
    Выбирает 1 лучшее средство из списка по ключевым словам.
    prefer — слова, которые хотим найти
    avoid — слова, которых хотим избегать
    """
    if not items:
        return None

    # 1) Prefer + not avoid
    for it in items:
        s = it.lower()
        if any(p in s for p in prefer) and not any(a in s for a in avoid):
            return it

    # 2) Not avoid
    for it in items:
        s = it.lower()
        if not any(a in s for a in avoid):
            return it

    # 3) fallback
    return items[0]


def build_plan_30(profile: dict, favorites: list) -> str:
    """
    План ухода на основе выбранного набора.
    Утро и вечер отличаются:
    - утром избегаем evening/night
    - вечером предпочитаем evening/night
    - SPF только утром
    """
    if not favorites:
        return (
            "📅 План на 30 дней\n\n"
            "Сначала добавь средства в ⭐ Мой набор.\n"
            "Это можно сделать в разделе «🧴 Подобрать уход»."
        )

    steps = {
        "cleanser": [],
        "toner": [],
        "serum": [],
        "cream": [],
        "sunscreen": [],
    }

    for f in favorites:
        step = f.get("step")
        name = f.get("name")
        if step in steps and name:
            steps[step].append(name)

    # Ключевые слова
    morning_prefer = ["morning", "day", "daily", "днев", "утрен", "spf", "sun", "uv"]
    morning_avoid = ["evening", "night", "pm", "sleep", "overnight", "вечер", "ноч"]

    evening_prefer = ["evening", "night", "pm", "sleep", "overnight", "вечер", "ноч"]
    evening_avoid = []  # вечером не избегаем

    # Выбор средств для утра/вечера по каждому шагу
    am = {}
    pm = {}

    for step in ["cleanser", "toner", "serum", "cream"]:
        am[step] = _pick_item(steps[step], prefer=morning_prefer, avoid=morning_avoid)
        pm[step] = _pick_item(steps[step], prefer=evening_prefer, avoid=evening_avoid)

    # SPF — только утром
    am["sunscreen"] = _pick_item(steps["sunscreen"], prefer=["spf", "sun", "uv", "солн", "spf"], avoid=[])
    pm["sunscreen"] = None

    # Заголовок и список набора
    lines = []
    lines.append("📅 План ухода на 30 дней")
    lines.append("")
    lines.append("Ваш набор:")

    def _step_title(step: str) -> str:
        return {
            "cleanser": "Очищение",
            "toner": "Тонер",
            "serum": "Сыворотка",
            "cream": "Крем",
            "sunscreen": "SPF",
        }.get(step, step)

    for step, items in steps.items():
        if not items:
            continue
        lines.append("")
        lines.append(_step_title(step))
        for it in items:
            lines.append(f"• {it}")

    lines.append("")
    lines.append("────")
    lines.append("")
    lines.append("🌅 Утро")

    n = 1
    for step in ["cleanser", "toner", "serum", "cream", "sunscreen"]:
        if am.get(step):
            lines.append(f"{n}️⃣ {am[step]}")
            n += 1

    lines.append("")
    lines.append("🌙 Вечер")

    n = 1
    for step in ["cleanser", "toner", "serum", "cream"]:
        if pm.get(step):
            lines.append(f"{n}️⃣ {pm[step]}")
            n += 1

    lines.append("")
    lines.append("💡 Подсказка")
    lines.append("• Если средство содержит слова Evening/Night — используйте его вечером.")
    lines.append("• SPF используется только утром.")
    lines.append("")
    lines.append("ℹ️ План — информационный. Косметика приобретается отдельно.")

    return "\n".join(lines)


# ---------------- commands ----------------
async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я бот по подбору косметики Атоми (Россия).\n"
        "Пройди тест (возраст → пол → кожа) — и я подберу уход из каталога atomy.ru + покажу цены.\n\n"
        "ℹ️ Важно: бот не продаёт косметику. Косметика приобретается отдельно.\n"
        f"Premium — услуга доступа ({SUB_PRICE_RUB} ₽ / 30 дней).",
        reply_markup=main_menu_keyboard()
    )


async def cmd_profile(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    prof = db.get_profile(user_id)
    if not prof or not prof.get("skin_type"):
        await update.message.reply_text("Профиля ещё нет. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    prem, until = premium_status(user_id)

    await update.message.reply_text(
        "👤 Твой профиль:\n"
        f"• Возраст: {prof.get('age') if prof.get('age') is not None else '—'}\n"
        f"• Пол: {prof.get('gender') or '—'}\n"
        f"• Тип кожи: {prof.get('skin_type')}\n"
        f"• Барьер: {prof.get('barrier_state')}\n"
        f"• Чувствительность: {prof.get('sensitivity')}\n"
        f"• Проблемы: {prof.get('concerns')}\n\n"
        f"Premium: {'✅ до ' + until if prem else 'нет'}",
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


# --- admin commands ---
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


# ---------------- callbacks ----------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    db.ensure_user(user_id)

    data = q.data

    # ---- MENU ----
    if data == "menu:home":
        if q.message:
            await q.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return

    # ---- ADMIN ----
    if data == "admin:show":
        if q.message:
            await q.message.reply_text("\n".join(admin_block_lines()), reply_markup=main_menu_keyboard())
        return

    # ---- PRIVACY ----
    if data == "privacy:show":
        if PRIVACY_URL:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть политику на сайте", url=PRIVACY_URL)]])
            if q.message:
                await q.message.reply_text("📜 Политика конфиденциальности доступна по ссылке:", reply_markup=kb)
        else:
            if q.message:
                await q.message.reply_text(PRIVACY_TEXT, reply_markup=main_menu_keyboard())
        return

    # ---- PREMIUM ----
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

        prof = db.get_profile(user_id) or {}
        prem, until = premium_status(user_id)

        text_to_admin = (
            "📩 Пользователь сообщил об оплате Premium\n\n"
            f"user_id: {user_id}\n"
            f"username: @{uname}\n"
            f"имя: {full_name}\n"
            f"Premium: {'активен до ' + until if prem else 'не активен'}\n"
            f"Профиль: возраст={prof.get('age') or '-'}, пол={prof.get('gender') or '-'}, "
            f"{prof.get('skin_type') or '-'} | {prof.get('sensitivity') or '-'} | {prof.get('concerns') or '-'}\n\n"
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
                    "✅ Решение: админ должен открыть бота и нажать Start.\n\n"
                    f"Ваш user_id: {user_id}",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text("✅ Отправила ваш ID админу.", reply_markup=main_menu_keyboard())
        return

    # ---- PROFILE ----
    if data == "profile:show":
        prof = db.get_profile(user_id)
        prem, until = premium_status(user_id)
        if q.message:
            if not prof or not prof.get("skin_type"):
                await q.message.reply_text("Профиля ещё нет. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
            else:
                await q.message.reply_text(
                    "👤 Твой профиль:\n"
                    f"• Возраст: {prof.get('age') if prof.get('age') is not None else '—'}\n"
                    f"• Пол: {prof.get('gender') or '—'}\n"
                    f"• Тип кожи: {prof.get('skin_type')}\n"
                    f"• Барьер: {prof.get('barrier_state')}\n"
                    f"• Чувствительность: {prof.get('sensitivity')}\n"
                    f"• Проблемы: {prof.get('concerns')}\n\n"
                    f"Premium: {'✅ до ' + until if prem else 'нет'}",
                    reply_markup=main_menu_keyboard()
                )
        return

    # ---- TEST START: AGE ----
    if data == "test:start":
        USER_STATE[user_id] = {"stage": "age"}
        if q.message:
            await q.message.reply_text("Сколько тебе лет? Напиши числом (например 25).")
        return

    # ---- TEST CANCEL ----
    if data == "test:cancel":
        USER_STATE.pop(user_id, None)
        if q.message:
            await q.message.reply_text("Тест отменён.", reply_markup=main_menu_keyboard())
        return

    # ---- TEST GENDER ----
    if data.startswith("test:gender:"):
        st = USER_STATE.get(user_id)
        if not st or st.get("stage") != "gender":
            return
        g = data.split(":")[2]
        gender = "Женщина" if g == "woman" else "Мужчина"
        st["gender"] = gender
        st["stage"] = "skin"
        st["step"] = 0
        st["answers"] = []
        USER_STATE[user_id] = st

        db.set_demographics(user_id, int(st["age"]), gender)

        if q.message:
            await q.message.reply_text("Отлично! Теперь отвечай на вопросы про кожу 👇")
            await q.message.reply_text(QUESTIONS[0]["text"], reply_markup=question_keyboard(0))
        return

    # ---- TEST ANSWER ----
    if data.startswith("test:answer:"):
        st = USER_STATE.get(user_id)
        if not st or st.get("stage") != "skin":
            return

        _, _, q_index_str, opt_index_str = data.split(":")
        q_index = int(q_index_str)
        opt_index = int(opt_index_str)

        if q_index != st["step"]:
            return

        st["answers"].append(opt_index)
        st["step"] += 1
        USER_STATE[user_id] = st

        if st["step"] < len(QUESTIONS):
            i = st["step"]
            if q.message:
                await q.message.reply_text(QUESTIONS[i]["text"], reply_markup=question_keyboard(i))
            return

        prof = calc_profile(st["answers"])
        db.save_profile(user_id, prof["skin_type"], prof["barrier_state"], prof["sensitivity"], prof["concerns"])
        age = st.get("age")
        gender = st.get("gender")
        USER_STATE.pop(user_id, None)

        if q.message:
            await q.message.reply_text(
                "✅ Профиль сохранён!\n\n"
                f"• Возраст: {age}\n"
                f"• Пол: {gender}\n"
                f"• Тип кожи: {prof['skin_type']}\n"
                f"• Барьер: {prof['barrier_state']}\n"
                f"• Чувствительность: {prof['sensitivity']}\n"
                f"• Проблемы: {prof['concerns']}\n\n"
                "Теперь нажми «🧴 Подобрать уход Atomy (RU)».",
                reply_markup=main_menu_keyboard()
            )
        return

    # ---- INCI START ----
    if data == "inci:start":
        USER_STATE[user_id] = {"stage": "inci"}
        if q.message:
            await q.message.reply_text(
                "🔎 Проверка состава (INCI)\n\n"
                "Вставь состав одним сообщением (например: Water, Glycerin, Niacinamide...)\n"
                "Я скажу подходит ли твоему типу кожи.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⛔️ Отмена", callback_data="inci:cancel")]])
            )
        return

    if data == "inci:cancel":
        st = USER_STATE.get(user_id)
        if st and st.get("stage") == "inci":
            USER_STATE.pop(user_id, None)
        if q.message:
            await q.message.reply_text("Ок, отменено.", reply_markup=main_menu_keyboard())
        return

    # ---- FAVORITES: SHOW ----
    if data == "fav:show":
        favs = db.list_favorites(user_id)
        if q.message:
            if not favs:
                await q.message.reply_text("⭐ Набор пуст. Добавь средства из рекомендаций.", reply_markup=main_menu_keyboard())
            else:
                lines = ["⭐ Ваш набор:"]
                for i, f in enumerate(favs, 1):
                    step = f.get("step") or "-"
                    lines.append(f"{i}. [{step}] {f.get('name')}")
                lines.append("")
                lines.append("Нажми «Оформить через администратора» — админ поможет с заказом.")
                await q.message.reply_text("\n".join(lines), reply_markup=_myset_keyboard())
        return

    # ---- FAVORITES: CLEAR ----
    if data == "fav:clear":
        db.clear_favorites(user_id)
        if q.message:
            await q.message.reply_text("🗑 Набор очищен.", reply_markup=main_menu_keyboard())
        return

    # ---- FAVORITES: ADD ----
    if data.startswith("fav:add:"):
        # callback_data: fav:add:<step>:<idx>
        parts = data.split(":")
        if len(parts) != 4:
            return
        step = parts[2]
        idx = int(parts[3])

        prof = db.get_profile(user_id) or {}
        routine = recommend_routine(CATALOG, prof)
        items = routine.get(step, [])
        if idx < 0 or idx >= len(items):
            if q.message:
                await q.message.reply_text("Не нашла это средство. Нажми «Подобрать уход» ещё раз.", reply_markup=main_menu_keyboard())
            return

        item, score, why = items[idx]
        db.add_favorite(
            user_id=user_id,
            name=item.name,
            url=getattr(item, "url", "") or "",
            step=step,
            price_after_rub=getattr(item, "price_after_rub", None),
            price_before_rub=getattr(item, "price_before_rub", None),
        )
        if q.message:
            await q.message.reply_text(f"✅ Добавила в набор: {item.name}", reply_markup=main_menu_keyboard())
        return

    # ---- PLAN 30 ----
    if data == "plan:30":

        prof = db.get_profile(user_id)
        favs = db.list_favorites(user_id)

        if not prof or not prof.get("skin_type"):
            if q.message:
                await q.message.reply_text(
                    "Сначала пройди тест кожи.",
                    reply_markup=main_menu_keyboard()
                )
            return

        plan = build_plan_30(prof, favs)

        if q.message:
            await q.message.reply_text(
                plan,
                reply_markup=main_menu_keyboard()
            )

        return
    # ---- LEAD SEND (to admin) ----
    if data == "lead:send":
        if ADMIN_ID == 0:
            if q.message:
                await q.message.reply_text("❌ Администратор не настроен (ADMIN_ID=0).", reply_markup=main_menu_keyboard())
            return

        prof = db.get_profile(user_id) or {}
        favs = db.list_favorites(user_id)

        uname = q.from_user.username or "-"
        full_name = (q.from_user.full_name or "-").strip()

        lines = []
        lines.append("🧾 ЛИД: пользователь хочет оформить заказ")
        lines.append("")
        lines.append(f"user_id: {user_id}")
        lines.append(f"username: @{uname}")
        lines.append(f"имя: {full_name}")
        lines.append("")
        lines.append(f"Возраст: {prof.get('age') or '—'}")
        lines.append(f"Пол: {prof.get('gender') or '—'}")
        lines.append(f"Тип кожи: {prof.get('skin_type') or '—'}")
        lines.append(f"Чувствительность: {prof.get('sensitivity') or '—'}")
        lines.append(f"Проблемы: {prof.get('concerns') or '—'}")
        lines.append("")
        lines.append("⭐ Набор пользователя:")
        if not favs:
            lines.append("— Пусто (попросите выбрать средства из рекомендаций)")
        else:
            for i, f in enumerate(favs, 1):
                step = f.get("step") or "-"
                pa = f.get("price_after_rub")
                pb = f.get("price_before_rub")
                price = f"{pa} ₽ / {pb} ₽" if (pa or pb) else "-"
                lines.append(f"{i}. [{step}] {f.get('name')} | {price}")
                if f.get("url"):
                    lines.append(f"   {f.get('url')}")
        lines.append("")
        lines.append("Команды:")
        lines.append(f"/grant {user_id} 30")
        lines.append(f"/receipt {user_id}")

        try:
            await context.application.bot.send_message(chat_id=ADMIN_ID, text="\n".join(lines))
        except Forbidden:
            if q.message:
                await q.message.reply_text(
                    "❌ Не могу написать админу (Telegram запретил).\n"
                    "Админ должен открыть бота и нажать Start.",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text("✅ Отправила заявку админу. Он напишет тебе и поможет оформить заказ.", reply_markup=main_menu_keyboard())
        return

    # ---- ROUTINE MAKE (send items with favorite buttons) ----
    if data == "routine:make":
        prof = db.get_profile(user_id)
        if not prof or not prof.get("skin_type"):
            if q.message:
                await q.message.reply_text("Сначала пройди тест кожи.", reply_markup=main_menu_keyboard())
            return
        if not CATALOG:
            if q.message:
                await q.message.reply_text("Каталог не загружен. Проверь catalog_ru.csv.", reply_markup=main_menu_keyboard())
            return

        routine = recommend_routine(CATALOG, prof)

        # Короткое вступление
        if q.message:
            await q.message.reply_text(
                "🧴 Подбор ухода готов!\n"
                "Ниже я пришлю средства по шагам. Под каждым можно нажать ⭐ чтобы добавить в набор.\n\n"
                "ℹ️ Косметика приобретается отдельно.",
                reply_markup=main_menu_keyboard()
            )

        def fmt_price(it):
            after = getattr(it, "price_after_rub", None) or "-"
            before = getattr(it, "price_before_rub", None) or "-"
            return f"{after} ₽ (после регистрации) / {before} ₽ (до регистрации)"

        titles = {"cleanser": "Очищение", "toner": "Тонер", "serum": "Сыворотка", "cream": "Крем", "sunscreen": "SPF"}

        for step, title in titles.items():
            items = routine.get(step, [])
            if not items:
                await q.message.reply_text(f"--- {title} ---\nНет подходящих средств в каталоге.")
                continue

            await q.message.reply_text(f"--- {title} ---")
            for idx, (item, score, why) in enumerate(items):
                text_out = (
                    f"{item.name}\n"
                    f"Цена: {fmt_price(item)}\n"
                    f"Комментарий: {why}"
                )
                await q.message.reply_text(
                    text_out,
                    reply_markup=_fav_item_keyboard(step, idx, getattr(item, "url", None))
                )

        # В конце — быстрые кнопки
        await q.message.reply_text(
            "Готово ✅\n\n"
            "Открой ⭐ Мой набор, чтобы увидеть выбранные средства и отправить заявку админу.\n"
            "Или получи 📅 План на 30 дней.",
            reply_markup=main_menu_keyboard()
        )
        return

    # если ничего не совпало
    if q.message:
        await q.message.reply_text("Не поняла действие. Открой меню:", reply_markup=main_menu_keyboard())


async def handle_message(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    text = (update.message.text or "").strip()
    if not text:
        return

    st = USER_STATE.get(user_id)

    # --- TEST AGE ---
    if st and st.get("stage") == "age":
        try:
            age = int(text)
        except ValueError:
            await update.message.reply_text("Пожалуйста, введи возраст числом 🙂 Например: 25")
            return
        if age < 10 or age > 100:
            await update.message.reply_text("Укажи реальный возраст (от 10 до 100) 🙂")
            return
        st["age"] = age
        st["stage"] = "gender"
        USER_STATE[user_id] = st
        await update.message.reply_text("Теперь выбери пол:", reply_markup=gender_keyboard())
        return

    # --- INCI MODE ---
    if st and st.get("stage") == "inci":
        prof = db.get_profile(user_id)
        if not prof or not prof.get("skin_type"):
            USER_STATE.pop(user_id, None)
            await update.message.reply_text("Сначала пройди тест кожи.", reply_markup=main_menu_keyboard())
            return

        prem, _until = premium_status(user_id)
        if not prem:
            used = db.get_checks_used(user_id)
            if used >= 3:
                USER_STATE.pop(user_id, None)
                await update.message.reply_text(
                    "🚫 Лимит бесплатных проверок исчерпан (3/3).\n\n"
                    f"💎 Premium — {SUB_PRICE_RUB} ₽ / 30 дней (услуга доступа).\n"
                    "Нажми «💳 Premium».",
                    reply_markup=main_menu_keyboard()
                )
                return

        verdict, reasons = rule_assess(text, prof)

        out = []
        out.append("✅ Вердикт: подходит" if verdict == "good" else "⚠️ Вердикт: с осторожностью" if verdict == "caution" else "❌ Вердикт: скорее не подходит")
        if reasons:
            out.append("Причины:")
            out.extend([f"• {r}" for r in reasons])

        out.append("")
        out.append("ℹ️ Важно: это информационная рекомендация. Косметика приобретается отдельно.")
        out.append("")
        out.extend(admin_block_lines())

        if not prem:
            db.inc_checks_used(user_id)
            used = db.get_checks_used(user_id)
            out.append(f"\nПроверки: {min(used, 3)}/3 (free)")

        USER_STATE.pop(user_id, None)
        await update.message.reply_text("\n".join(out), reply_markup=main_menu_keyboard())
        return

    # обычный текст вне режимов — мягко направляем
    await update.message.reply_text(
        "Выбери действие в меню 👇\n"
        "• Пройти тест\n"
        "• Подобрать уход\n"
        "• Проверить состав (INCI)",
        reply_markup=main_menu_keyboard()
    )


def main():
    print("Бот запускается...")
    print(f"REGION={REGION}")
    print(f"CATALOG_PATH={CATALOG_PATH}")
    print(f"Товаров в каталоге: {len(CATALOG)}")
    print(f"ADMIN_ID={ADMIN_ID}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("terms", cmd_terms))
    app.add_handler(CommandHandler("privacy", cmd_privacy))
    app.add_handler(CommandHandler("offer_pdf", cmd_offer_pdf))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("myid", cmd_myid))

    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("receipt", cmd_receipt))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен ✅")
    app.run_polling()


if __name__ == "__main__":
    main()