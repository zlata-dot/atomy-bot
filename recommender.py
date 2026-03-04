import re
from typing import Dict, List, Tuple, Any


# ---------------- helpers: normalize ----------------

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
        # иногда из БД возраст приходит строкой "23"
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


# ---------------- helpers: product tags ----------------

def _is_men_product(name: str) -> bool:
    """
    Детектор мужских продуктов. Сделан более строгим,
    чтобы не ловить случайные совпадения.
    """
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
    """
    ВАЖНО: чтобы не выкидывать половину каталога,
    считаем 45+ только если есть явные метки возраста.
    """
    n = (name or "").lower()
    patterns = [
        r"\b45\+\b",
        r"\b50\+\b",
        r"\b60\+\b",
        r"\b45 plus\b",
        r"\b50 plus\b",
        r"\b60 plus\b",
        r"\bage\s*45\+\b",
    ]
    return any(re.search(p, n) for p in patterns)


def _is_teen_young_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [
        r"\bteen\b", r"\bподрост", r"\bjunior\b", r"\byoung\b"
    ]
    return any(re.search(p, n) for p in patterns)


def _passes_demographic_filters(item, age: Any, gender: Any) -> bool:
    name = getattr(item, "name", "") or ""

    age_i = _norm_age(age)
    gender_n = _norm_gender(gender)

    # 1) Пол
    if gender_n == "female":
        # женщинам исключаем мужские линейки
        if _is_men_product(name):
            return False
    # male -> не фильтруем (унисекс + мужские ок)

    # 2) Возраст
    grp = _age_group(age_i)

    # если возраст не 45+, убираем явные 45+ продукты
    if grp != "45+" and _is_45_plus_product(name):
        return False

    # если 45+, можно убрать подростковые
    if grp == "45+" and _is_teen_young_product(name):
        return False

    return True


# ---------------- scoring ----------------

def _score_item(item, profile: dict) -> Tuple[int, str]:
    """
    Простая логика для ранжирования.
    """
    skin_type = (profile.get("skin_type") or "").lower()
    sens = (profile.get("sensitivity") or "").lower()
    concerns = (profile.get("concerns") or "").lower()
    name = (getattr(item, "name", "") or "").lower()

    score = 0
    why = []

    # сухая
    if skin_type in ("сухая", "dry"):
        if ("hydr" in name) or ("увлаж" in name) or ("пит" in name):
            score += 2
            why.append("увлажнение/питание")

    # жирная
    if skin_type in ("жирная", "oily"):
        if ("oil" in name) or ("sebum" in name) or ("матир" in name) or ("pur" in name):
            score += 2
            why.append("контроль себума")

    # комбинированная
    if skin_type in ("комбинированная", "comb"):
        if ("balance" in name) or ("баланс" in name):
            score += 1
            why.append("баланс")

    # чувствительная
    if sens in ("высокая", "high"):
        if ("cica" in name) or ("calm" in name) or ("успок" in name) or ("sensitive" in name):
            score += 2
            why.append("для чувствительной кожи")

    # высыпания
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
    """
    Возвращает подбор по шагам ухода.
    Формат: {"cleanser":[(item,score,why),...], "toner":..., ...}
    """
    age = profile.get("age")
    gender = profile.get("gender")

    filtered = [it for it in catalog if _passes_demographic_filters(it, age, gender)]

    steps = {
        "cleanser": ["clean", "cleansing", "foam", "пенк", "гель", "умыван"],
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


def build_plan_30(profile: dict) -> str:
    """
    План ухода на 30 дней (для Premium).
    """
    age_i = _norm_age(profile.get("age"))
    gender_n = _norm_gender(profile.get("gender"))

    skin_type = (profile.get("skin_type") or "—")
    sens = (profile.get("sensitivity") or "—")
    concerns = (profile.get("concerns") or "—")

    g_text = "—"
    if gender_n == "female":
        g_text = "женщина"
    elif gender_n == "male":
        g_text = "мужчина"

    text = []
    text.append("🗓 План ухода на 30 дней")
    text.append("")
    text.append(f"Возраст: {age_i if age_i is not None else '—'} | Пол: {g_text}")
    text.append(f"Тип кожи: {skin_type}")
    text.append(f"Чувствительность: {sens}")
    text.append(f"Цели/особенности: {concerns}")
    text.append("")
    text.append("🌞 Утро (каждый день):")
    text.append("1) Очищение")
    text.append("2) Тонер/эссенция")
    text.append("3) Сыворотка по цели")
    text.append("4) Крем")
    text.append("5) SPF")
    text.append("")
    text.append("🌙 Вечер (каждый день):")
    text.append("1) Очищение")
    text.append("2) Тонер/эссенция")
    text.append("3) Сыворотка по цели")
    text.append("4) Крем (плотнее/питательнее)")
    text.append("")
    text.append("📌 По неделям:")
    text.append("Неделя 1 — адаптация (без резких активов).")
    text.append("Неделя 2 — добавляем 1 актив по цели (если нет раздражения).")
    text.append("Неделя 3 — маска 1–2 раза/нед + закрепляем режим.")
    text.append("Неделя 4 — поддержание и оценка результата.")
    text.append("")
    text.append("⚠️ Если есть жжение/сильное покраснение — отменяем новое средство на 3–5 дней.")
    return "\n".join(text)