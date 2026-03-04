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

# ---- USER STATE ----
# Мы храним состояние теста:
# USER_STATE[user_id] = {
#   "stage": "age" | "gender" | "skin",
#   "age": int,
#   "gender": "Женщина"|"Мужчина",
#   "step": int, "answers": [int]
# }
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
Настоящая политика объясняет, какие данные обрабатываются и зачем.

2) Какие данные могут обрабатываться
• Telegram user_id, имя/никнейм (если доступно)
• ответы на тест по коже (тип кожи, чувствительность, предпочтения)
• история взаимодействия с ботом (рекомендации, выбранные товары)
• данные об оплате подписки (подтверждение/статус). Реквизиты банковской карты я не получаю.

3) Цели обработки
• создание и хранение профиля кожи
• персональные рекомендации и подбор ухода
• предоставление доступа Premium и учёт оплат
• поддержка пользователей и улучшение качества сервиса

4) Срок хранения
Данные хранятся, пока вы пользуетесь сервисом, либо до запроса на удаление.

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
    lines.append("• Профиль + история рекомендаций")
    lines.append("• Поддержка администратора")
    lines.append("")
    lines.append("ℹ️ Важно: вы оплачиваете услугу доступа к сервису. Косметика приобретается отдельно.")
    lines.append("")
    lines.append(f"Ваш статус: {'✅ активен до ' + until if prem else 'не активен'}")
    lines.append(f"Бесплатные проверки использовано: {min(used, 3)}/3")
    return "\n".join(lines)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Пройти тест кожи", callback_data="test:start")],
        [InlineKeyboardButton("🧴 Подобрать уход Atomy (RU)", callback_data="routine:make")],
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


# ---------------- commands ----------------

async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я бот по подбору косметики Атоми (Россия).\n"
        "Сначала я задам возраст и пол, затем 8 вопросов о коже — и подберу уход из каталога atomy.ru + покажу цены.\n\n"
        "ℹ️ Важно: бот не продаёт косметику. Косметика приобретается отдельно.\n"
        f"Premium — услуга доступа ({SUB_PRICE_RUB} ₽ / 30 дней).",
        reply_markup=main_menu_keyboard()
    )


async def cmd_profile(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    prof = db.get_profile(user_id)
    if not prof:
        await update.message.reply_text("Профиля ещё нет. Нажми «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    prem, until = premium_status(user_id)
    age = prof.get("age")
    gender = prof.get("gender")

    await update.message.reply_text(
        "👤 Твой профиль:\n"
        f"• Возраст: {age if age is not None else '—'}\n"
        f"• Пол: {gender or '—'}\n"
        f"• Тип кожи: {prof.get('skin_type') or '—'}\n"
        f"• Барьер: {prof.get('barrier_state') or '—'}\n"
        f"• Чувствительность: {prof.get('sensitivity') or '—'}\n"
        f"• Проблемы: {prof.get('concerns') or '—'}\n\n"
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

async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    db.ensure_user(user_id)

    if q.data == "admin:show":
        if q.message:
            await q.message.reply_text("\n".join(admin_block_lines()), reply_markup=main_menu_keyboard())
        return

    if q.data == "premium:screen":
        if q.message:
            await q.message.reply_text(premium_screen_text(user_id), reply_markup=premium_screen_keyboard())
        return

    if q.data == "premium:terms":
        if q.message:
            await q.message.reply_text(TERMS_TEXT, reply_markup=main_menu_keyboard())
        return

    if q.data == "premium:pdf":
        pdf_bytes = generate_offer_pdf(TERMS_TEXT, title="Условия Premium (публичная оферта)")
        bio = BytesIO(pdf_bytes)
        bio.name = "offer_premium.pdf"
        if q.message:
            await q.message.reply_document(document=InputFile(bio), caption="📄 PDF-оферта Premium")
        return

    if q.data == "privacy:show":
        if PRIVACY_URL:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть политику на сайте", url=PRIVACY_URL)]])
            if q.message:
                await q.message.reply_text("📜 Политика конфиденциальности доступна по ссылке:", reply_markup=kb)
        else:
            if q.message:
                await q.message.reply_text(PRIVACY_TEXT, reply_markup=main_menu_keyboard())
        return

    if q.data == "premium:status":
        prem, until = premium_status(user_id)
        if q.message:
            await q.message.reply_text(
                f"✅ Premium активен до {until}" if prem else f"ℹ️ Premium не активен. Последняя дата: {until}",
                reply_markup=main_menu_keyboard()
            )
        return

    if q.data == "premium:transfer":
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

    if q.data == "premium:send_id":
        if ADMIN_ID == 0:
            if q.message:
                await q.message.reply_text("❌ Администратор не настроен (ADMIN_ID=0).")
            return

        uname = q.from_user.username or "-"
        full_name = (q.from_user.full_name or "-").strip()

        prof = db.get_profile(user_id)
        prof_line = ""
        if prof:
            prof_line = (
                f"\nПрофиль: возраст={prof.get('age') or '-'}, пол={prof.get('gender') or '-'}, "
                f"{prof.get('skin_type') or '-'} | {prof.get('sensitivity') or '-'} | {prof.get('concerns') or '-'}"
            )
        prem, until = premium_status(user_id)

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
                    "❌ Ошибка отправки админу. Проверь ADMIN_ID.\n"
                    f"Ваш user_id: {user_id}",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text("✅ Отправила ваш ID админу. Он активирует Premium.", reply_markup=main_menu_keyboard())
        return

    # --- PROFILE BUTTON ---
    if q.data == "profile:show":
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
                    f"• Тип кожи: {prof.get('skin_type') or '—'}\n"
                    f"• Барьер: {prof.get('barrier_state') or '—'}\n"
                    f"• Чувствительность: {prof.get('sensitivity') or '—'}\n"
                    f"• Проблемы: {prof.get('concerns') or '—'}\n\n"
                    f"Premium: {'✅ до ' + until if prem else 'нет'}",
                    reply_markup=main_menu_keyboard()
                )
        return

    # --- TEST START (NOW ASK AGE FIRST) ---
    if q.data == "test:start":
        USER_STATE[user_id] = {"stage": "age"}
        if q.message:
            await q.message.reply_text("Сколько тебе лет? Напиши числом (например 25).")
        return

    if q.data == "test:cancel":
        USER_STATE.pop(user_id, None)
        if q.message:
            await q.message.reply_text("Тест отменён.", reply_markup=main_menu_keyboard())
        return


async def on_gender_select(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    state = USER_STATE.get(user_id)
    if not state or state.get("stage") != "gender":
        return

    _, _, _, g = q.data.split(":")
    gender = "Женщина" if g == "woman" else "Мужчина"

    state["gender"] = gender
    state["stage"] = "skin"
    state["step"] = 0
    state["answers"] = []
    USER_STATE[user_id] = state

    # сохраняем возраст+пол сразу
    db.set_demographics(user_id, int(state["age"]), gender)

    if q.message:
        await q.message.reply_text("Отлично! Теперь отвечай на вопросы про кожу 👇")
        await q.message.reply_text(QUESTIONS[0]["text"], reply_markup=question_keyboard(0))


async def on_test_answer(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    state = USER_STATE.get(user_id)
    if not state or state.get("stage") != "skin":
        return

    _, _, q_index_str, opt_index_str = q.data.split(":")
    q_index = int(q_index_str)
    opt_index = int(opt_index_str)

    if q_index != state["step"]:
        return

    state["answers"].append(opt_index)
    state["step"] += 1
    USER_STATE[user_id] = state

    if state["step"] < len(QUESTIONS):
        i = state["step"]
        if q.message:
            await q.message.reply_text(QUESTIONS[i]["text"], reply_markup=question_keyboard(i))
        return

    # finish
    prof = calc_profile(state["answers"])
    db.save_profile(user_id, prof["skin_type"], prof["barrier_state"], prof["sensitivity"], prof["concerns"])

    age = state.get("age")
    gender = state.get("gender")
    USER_STATE.pop(user_id, None)

    if q.message:
        await q.message.reply_text(
            "✅ Профиль сохранён!\n\n"
            f"• Возраст: {age if age is not None else '—'}\n"
            f"• Пол: {gender or '—'}\n"
            f"• Тип кожи: {prof['skin_type']}\n"
            f"• Барьер: {prof['barrier_state']}\n"
            f"• Чувствительность: {prof['sensitivity']}\n"
            f"• Проблемы: {prof['concerns']}\n\n"
            "Теперь нажми «🧴 Подобрать уход Atomy (RU)».",
            reply_markup=main_menu_keyboard()
        )


async def handle_message(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    text = (update.message.text or "").strip()
    if not text:
        return

    # ---- If we are in TEST AGE stage ----
    st = USER_STATE.get(user_id)
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

    # ---- INCI checks flow (as before) ----
    prof = db.get_profile(user_id)
    if not prof or not prof.get("skin_type"):
        await update.message.reply_text("Сначала пройди тест: «✅ Пройти тест кожи».", reply_markup=main_menu_keyboard())
        return

    prem, _until = premium_status(user_id)
    if not prem:
        used = db.get_checks_used(user_id)
        if used >= 3:
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
    out.append("ℹ️ Важно: вы оплачиваете услугу доступа к сервису. Косметика приобретается отдельно.")
    out.append("")
    out.extend(admin_block_lines())

    if not prem:
        db.inc_checks_used(user_id)
        used = db.get_checks_used(user_id)
        out.append(f"\nПроверки: {min(used, 3)}/3 (free)")

    await update.message.reply_text("\n".join(out), reply_markup=main_menu_keyboard())


async def on_routine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Этот обработчик оставлен на случай если ты захочешь вынести routine отдельно.
    pass


async def on_routine_make(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # не используется, потому что routine:make обрабатывается в on_menu_click ниже
    pass


async def on_menu_click_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # не используется
    pass


async def on_menu_click_2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # не используется
    pass


async def on_menu_click_3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # не используется
    pass


async def on_menu_click_routine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Этот обработчик уже объявлен выше.
    # Оставлено намеренно пустым, чтобы не было повторного объявления.
    pass


# ---- We need ONE on_menu_click. So we alias the earlier function name ----
# (Python doesn't allow two functions with same name; above we defined it already)
# Nothing to do here.


async def handle_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Единый роутер callback-ов:
    - сначала обрабатываем gender
    - затем test answers
    - затем остальное меню (premium/profile/routine/etc.)
    """
    data = update.callback_query.data

    if data.startswith("test:gender:"):
        return await on_gender_select(update, context)

    if data.startswith("test:answer:"):
        return await on_test_answer(update, context)

    # иначе — в общий обработчик меню
    return await on_menu_click(update, context)


# ---- IMPORTANT: We restore the full original on_menu_click logic by embedding it here ----
# Because above we "overwrote" name conflicts, we must include the real menu logic as a separate function:

async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    db.ensure_user(user_id)

    # admin
    if q.data == "admin:show":
        if q.message:
            await q.message.reply_text("\n".join(admin_block_lines()), reply_markup=main_menu_keyboard())
        return

    # premium
    if q.data == "premium:screen":
        if q.message:
            await q.message.reply_text(premium_screen_text(user_id), reply_markup=premium_screen_keyboard())
        return

    if q.data == "premium:terms":
        if q.message:
            await q.message.reply_text(TERMS_TEXT, reply_markup=main_menu_keyboard())
        return

    if q.data == "premium:pdf":
        pdf_bytes = generate_offer_pdf(TERMS_TEXT, title="Условия Premium (публичная оферта)")
        bio = BytesIO(pdf_bytes)
        bio.name = "offer_premium.pdf"
        if q.message:
            await q.message.reply_document(document=InputFile(bio), caption="📄 PDF-оферта Premium")
        return

    if q.data == "premium:status":
        prem, until = premium_status(user_id)
        if q.message:
            await q.message.reply_text(
                f"✅ Premium активен до {until}" if prem else f"ℹ️ Premium не активен. Последняя дата: {until}",
                reply_markup=main_menu_keyboard()
            )
        return

    if q.data == "premium:transfer":
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

    if q.data == "premium:send_id":
        if ADMIN_ID == 0:
            if q.message:
                await q.message.reply_text("❌ Администратор не настроен (ADMIN_ID=0).")
            return

        uname = q.from_user.username or "-"
        full_name = (q.from_user.full_name or "-").strip()

        prof = db.get_profile(user_id)
        prof_line = ""
        if prof:
            prof_line = (
                f"\nПрофиль: возраст={prof.get('age') or '-'}, пол={prof.get('gender') or '-'}, "
                f"{prof.get('skin_type') or '-'} | {prof.get('sensitivity') or '-'} | {prof.get('concerns') or '-'}"
            )
        prem, until = premium_status(user_id)

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
                    "❌ Ошибка отправки админу. Проверь ADMIN_ID.\n"
                    f"Ваш user_id: {user_id}",
                    reply_markup=main_menu_keyboard()
                )
            return

        if q.message:
            await q.message.reply_text("✅ Отправила ваш ID админу. Он активирует Premium.", reply_markup=main_menu_keyboard())
        return

    # privacy
    if q.data == "privacy:show":
        if PRIVACY_URL:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть политику на сайте", url=PRIVACY_URL)]])
            if q.message:
                await q.message.reply_text("📜 Политика конфиденциальности доступна по ссылке:", reply_markup=kb)
        else:
            if q.message:
                await q.message.reply_text(PRIVACY_TEXT, reply_markup=main_menu_keyboard())
        return

    # profile button
    if q.data == "profile:show":
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
                    f"• Тип кожи: {prof.get('skin_type') or '—'}\n"
                    f"• Барьер: {prof.get('barrier_state') or '—'}\n"
                    f"• Чувствительность: {prof.get('sensitivity') or '—'}\n"
                    f"• Проблемы: {prof.get('concerns') or '—'}\n\n"
                    f"Premium: {'✅ до ' + until if prem else 'нет'}",
                    reply_markup=main_menu_keyboard()
                )
        return

    # routine:make
    if q.data == "routine:make":
        prof = db.get_profile(user_id)
        if not prof or not prof.get("skin_type"):
            if q.message:
                await q.message.reply_text("Сначала пройди тест кожи.", reply_markup=main_menu_keyboard())
            return

        if not CATALOG:
            if q.message:
                await q.message.reply_text(
                    "Каталог не загружен.\n\n"
                    "Обнови catalog_ru.csv в GitHub или запусти update_catalog.py локально и закоммить файл.\n"
                    "Потом Railway перезапустится автоматически.",
                    reply_markup=main_menu_keyboard()
                )
            return

        routine = recommend_routine(CATALOG, prof)

        def fmt_price(item):
            after = item.price_after_rub or "-"
            before = item.price_before_rub or "-"
            return f"{after} ₽ (после регистрации) / {before} ₽ (до регистрации)"

        lines = []
        lines.append("🧴 Подбор ухода Atomy (Россия)")
        lines.append(f"Возраст: {prof.get('age') if prof.get('age') is not None else '—'}")
        lines.append(f"Пол: {prof.get('gender') or '—'}")
        lines.append(f"Тип кожи: {prof.get('skin_type')}")
        lines.append(f"Чувствительность: {prof.get('sensitivity')}")
        lines.append(f"Особенности: {prof.get('concerns')}")
        lines.append("")
        lines.append("ℹ️ Косметика приобретается отдельно на официальном сайте Atomy.")
        lines.append("")

        titles = {"cleanser": "Очищение", "toner": "Тонер", "serum": "Сыворотка", "cream": "Крем", "sunscreen": "SPF"}
        for step, title in titles.items():
            lines.append(f"--- {title} ---")
            items = routine.get(step, [])
            if not items:
                lines.append("Нет подходящих средств в каталоге.")
                lines.append("")
                continue
            for item, score, why in items:
                lines.append(item.name)
                lines.append(f"Цена: {fmt_price(item)}")
                lines.append(f"Комментарий: {why}")
                if item.url:
                    lines.append(f"Ссылка: {item.url}")
                lines.append("")

        lines.append("")
        lines.extend(admin_block_lines())

        if q.message:
            await q.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())
        return

    # test:start handled earlier in the router (it comes here too if clicked)
    if q.data == "test:start":
        USER_STATE[user_id] = {"stage": "age"}
        if q.message:
            await q.message.reply_text("Сколько тебе лет? Напиши числом (например 25).")
        return

    if q.data == "test:cancel":
        USER_STATE.pop(user_id, None)
        if q.message:
            await q.message.reply_text("Тест отменён.", reply_markup=main_menu_keyboard())
        return


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
    app.add_handler(CommandHandler("profile", cmd_profile))  # ✅ added

    # admin
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("receipt", cmd_receipt))

    # callbacks: one router handles everything
    app.add_handler(CallbackQueryHandler(handle_callback_router))

    # messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен ✅")
    app.run_polling()


if __name__ == "__main__":
    main()