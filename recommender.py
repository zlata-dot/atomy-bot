import re
from typing import Dict, List, Tuple, Any


# ---------------- normalize ----------------

def _norm_gender(gender: str | None) -> str | None:
    if not gender:
        return None
    g = gender.strip().lower()
    if g in ("ж", "жен", "женщина", "female", "woman", "w"):
        return "female"
    if g in ("м", "муж", "мужчина", "male", "man", "m"):
        return "male"
    return None


def _norm_age(age: Any) -> int | None:
    if age is None:
        return None
    try:
        a = int(str(age).strip())
        if a <= 0 or a > 120:
            return None
        return a
    except Exception:
        return None


def _age_group(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 18:
        return "teen"
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    return "45+"


# ---------------- product tags ----------------

def _is_men_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [
        r"\bfor men\b",
        r"\bmen\b",
        r"\bman\b",
        r"\bmale\b",
        r"\bмужск(?:ой|ая|ое|ие)\b",
        r"\bдля мужчин\b",
        r"\bмужчин\b",
    ]
    return any(re.search(p, n) for p in patterns)


def _is_45_plus_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [
        r"\b45\+\b", r"\b50\+\b", r"\b60\+\b",
        r"\b45 plus\b", r"\b50 plus\b", r"\b60 plus\b",
        r"\bage\s*45\+\b",
    ]
    return any(re.search(p, n) for p in patterns)


def _is_teen_young_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [r"\bteen\b", r"\bподрост", r"\bjunior\b", r"\byoung\b"]
    return any(re.search(p, n) for p in patterns)


def _passes_demographic_filters(item, age: Any, gender: Any) -> bool:
    name = getattr(item, "name", "") or ""

    age_i = _norm_age(age)
    gender_n = _norm_gender(gender)

    # female -> exclude men lines
    if gender_n == "female":
        if _is_men_product(name):
            return False

    grp = _age_group(age_i)

    if grp != "45+" and _is_45_plus_product(name):
        return False

    if grp == "45+" and _is_teen_young_product(name):
        return False

    return True


# ---------------- scoring ----------------

def _score_item(item, profile: dict) -> Tuple[int, str]:
    skin_type = (profile.get("skin_type") or "").lower()
    sens = (profile.get("sensitivity") or "").lower()
    concerns = (profile.get("concerns") or "").lower()
    name = (getattr(item, "name", "") or "").lower()

    score = 0
    why = []

    if skin_type in ("сухая", "dry"):
        if ("hydr" in name) or ("увлаж" in name) or ("пит" in name):
            score += 2
            why.append("увлажнение/питание")

    if skin_type in ("жирная", "oily"):
        if ("oil" in name) or ("sebum" in name) or ("матир" in name) or ("pur" in name):
            score += 2
            why.append("контроль себума")

    if skin_type in ("комбинированная", "comb"):
        if ("balance" in name) or ("баланс" in name):
            score += 1
            why.append("баланс")

    if sens in ("высокая", "high"):
        if ("cica" in name) or ("calm" in name) or ("успок" in name) or ("sensitive" in name):
            score += 2
            why.append("для чувствительной кожи")

    if ("высып" in concerns) or ("акне" in concerns):
        if ("acne" in name) or ("clear" in name) or ("blemish" in name) or ("pur" in name):
            score += 2
            why.append("против высыпаний")

    if score == 0:
        score = 1
        why.append("универсальный вариант")

    return score, ", ".join(why)


# ---------------- main API ----------------

def recommend_routine(catalog: List[Any], profile: dict) -> Dict[str, List[Tuple[Any, int, str]]]:
    age = profile.get("age")
    gender = profile.get("gender")
    filtered = [it for it in catalog if _passes_demographic_filters(it, age, gender)]

    steps = {
        "cleanser": ["clean", "cleansing", "foam", "пенк", "гель", "умыван", "клинз"],
        "toner": ["toner", "tonic", "тонер", "тоник"],
        "serum": ["serum", "ampoule", "эссенц", "сывор", "ампул"],
        "cream": ["cream", "крем", "emulsion", "эмульс"],
        "sunscreen": ["spf", "sun", "sunscreen", "солнеч", "защит", "uv"],
    }

    result: Dict[str, List[Tuple[Any, int, str]]] = {k: [] for k in steps.keys()}

    for it in filtered:
        name = (getattr(it, "name", "") or "").lower()
        for step, keys in steps.items():
            if any(k in name for k in keys):
                score, why = _score_item(it, profile)
                result[step].append((it, score, why))
                break

    for step in result:
        result[step].sort(key=lambda x: x[1], reverse=True)
        result[step] = result[step][:3]

    return result


# ---------------- 30 days plan by favorites ----------------

def _pick(items: list[str], prefer: list[str], avoid: list[str]) -> str | None:
    if not items:
        return None
    # 1) prefer and not avoid
    for it in items:
        s = it.lower()
        if any(p in s for p in prefer) and not any(a in s for a in avoid):
            return it
    # 2) not avoid
    for it in items:
        s = it.lower()
        if not any(a in s for a in avoid):
            return it
    return items[0]


def build_plan_30(profile: dict, favorites: list[dict]) -> str:
    """
    Подробный план на 30 дней на основе "Моего набора".
    favorites: список dict из db.list_favorites(user_id)
    dict содержит: step, name, url, price_after_rub, price_before_rub (url/price optional)
    """

    if not favorites:
        return (
            "📅 План на 30 дней\n\n"
            "У тебя пока пустой ⭐ Мой набор.\n"
            "Сначала добавь туда средства из «🧴 Подобрать уход», и я составлю план под твои продукты."
        )

    skin = (profile.get("skin_type") or "—")
    sens = (profile.get("sensitivity") or "—")
    concerns = (profile.get("concerns") or "—")

    # соберём набор по шагам
    steps = {"cleanser": [], "toner": [], "serum": [], "cream": [], "sunscreen": []}
    for f in favorites:
        step = (f.get("step") or "").strip()
        name = (f.get("name") or "").strip()
        if step in steps and name:
            steps[step].append(name)

    # ключи для утро/вечер
    morning_prefer = ["morning", "day", "daily", "днев", "утрен", "spf", "sun", "uv"]
    morning_avoid = ["evening", "night", "pm", "sleep", "overnight", "вечер", "ноч"]

    evening_prefer = ["evening", "night", "pm", "sleep", "overnight", "вечер", "ноч"]
    evening_avoid = []

    # выбор для AM/PM
    am = {}
    pm = {}
    for step in ["cleanser", "toner", "serum", "cream"]:
        am[step] = _pick(steps[step], prefer=morning_prefer, avoid=morning_avoid)
        pm[step] = _pick(steps[step], prefer=evening_prefer, avoid=evening_avoid)

    # SPF только утром
    am["sunscreen"] = _pick(steps["sunscreen"], prefer=["spf", "sun", "uv", "солн", "spf"], avoid=[])
    pm["sunscreen"] = None

    # полезные подсказки по профилю
    tips = []
    skin_l = (skin or "").lower()
    sens_l = (sens or "").lower()
    conc_l = (concerns or "").lower()

    if "сух" in skin_l:
        tips += [
            "• Для сухой кожи: делай акцент на увлажнение/питание, не пересушивай очищением.",
            "• Вечером крем можно наносить плотнее (особенно в холодный сезон).",
        ]
    if "жир" in skin_l:
        tips += [
            "• Для жирной кожи: выбирай лёгкие текстуры, избегай очень плотных слоёв крема.",
            "• Если появляется блеск — уменьшай количество крема утром.",
        ]
    if "комб" in skin_l:
        tips += [
            "• Для комбинированной кожи: на T-зону меньше крема, на сухие зоны — чуть больше.",
        ]
    if "высок" in sens_l:
        tips += [
            "• Чувствительная кожа: вводи любые новые средства постепенно и делай паузы при раздражении.",
        ]
    if ("высып" in conc_l) or ("акне" in conc_l):
        tips += [
            "• При высыпаниях: не перегружай кожу слоями, следи за реакцией на плотные кремы.",
        ]
    if "пигмент" in conc_l:
        tips += [
            "• При пигментации: SPF обязателен каждый день, иначе эффект ухода будет слабее.",
        ]
    if ("раздраж" in conc_l) or ("покрас" in conc_l):
        tips += [
            "• При раздражении: держи уход минималистичным, без частой смены средств.",
        ]

    # сборка текста плана
    lines = []
    lines.append("📅 Персональный план ухода на 30 дней (по твоему набору)")
    lines.append("")
    lines.append(f"Профиль: {skin} | чувствительность: {sens}")
    lines.append(f"Особенности: {concerns}")
    lines.append("")
    lines.append("⭐ Твой набор (что будет использоваться):")

    def title(step: str) -> str:
        return {
            "cleanser": "Очищение",
            "toner": "Тонер",
            "serum": "Сыворотка",
            "cream": "Крем",
            "sunscreen": "SPF",
        }.get(step, step)

    for step in ["cleanser", "toner", "serum", "cream", "sunscreen"]:
        if steps[step]:
            lines.append(f"\n{title(step)}:")
            for n in steps[step]:
                lines.append(f"• {n}")

    # ежедневная схема
    lines.append("\n────────────")
    lines.append("🌞 УТРО (каждый день)")
    i = 1
    for step in ["cleanser", "toner", "serum", "cream"]:
        if am.get(step):
            lines.append(f"{i}️⃣ {am[step]}")
            i += 1
    if am.get("sunscreen"):
        lines.append(f"{i}️⃣ {am['sunscreen']}  (SPF)")
        i += 1
    else:
        lines.append(f"{i}️⃣ SPF (добавь в набор средство с SPF)")

    lines.append("\n🌙 ВЕЧЕР (каждый день)")
    i = 1
    for step in ["cleanser", "toner", "serum", "cream"]:
        if pm.get(step):
            lines.append(f"{i}️⃣ {pm[step]}")
            i += 1

    # недельный план (реально полезный)
    lines.append("\n────────────")
    lines.append("📆 ПЛАН ПО НЕДЕЛЯМ (30 дней)")
    lines.append("")
    lines.append("1️⃣ Неделя 1 (Дни 1–7) — адаптация")
    lines.append("• Используй только базовую схему утром/вечером.")
    lines.append("• Если есть чувствительность — не добавляй новые продукты в эти 7 дней.")
    lines.append("• Оцени реакцию кожи: стянутость/покраснение/блеск.")

    lines.append("\n2️⃣ Неделя 2 (Дни 8–14) — закрепление")
    lines.append("• Сохраняй схему.")
    lines.append("• 1 раз за неделю сделай «спокойный день»: меньше слоёв (тонер + крем).")
    lines.append("• Если кожа жирная — утром уменьши крем; если сухая — добавь слой крема вечером.")

    lines.append("\n3️⃣ Неделя 3 (Дни 15–21) — усиление результата")
    lines.append("• Сохраняй схему.")
    lines.append("• В 2 дня недели сделай «восстановительные вечера»: тонер + крем (без сыворотки), если есть раздражение.")
    lines.append("• Если всё комфортно — оставь сыворотку ежедневно.")

    lines.append("\n4️⃣ Неделя 4 (Дни 22–30) — стабилизация")
    lines.append("• Сохраняй схему без резких изменений.")
    lines.append("• В конце недели оцени: стало ли меньше сухости/блеска/раздражения, как держится макияж/ощущение кожи.")
    lines.append("• При необходимости — скорректируем набор под результат.")

    # советы
    lines.append("\n────────────")
    lines.append("💡 Важные правила (чтобы реально был результат)")
    lines.append("• Новые продукты вводи раз в 5–7 дней (если будешь добавлять новые).")
    lines.append("• Если жжение/сильное покраснение — сделай паузу 2–3 дня и вернись к минимальному уходу.")
    lines.append("• SPF — каждый день (даже зимой), если есть риск пигментации/постакне.")
    if tips:
        lines.append("\n📝 Под твой профиль:")
        lines.extend(tips)

    lines.append("\nℹ️ План — информационный. Косметика приобретается отдельно.")
    return "\n".join(lines)