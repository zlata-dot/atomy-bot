import re
from typing import Dict, List, Tuple, Any

# Важно: item должен иметь поля: name, url, price_after_rub, price_before_rub
# Это у тебя уже есть в catalog.py


def _is_men_product(name: str) -> bool:
    n = (name or "").lower()
    # ключевые слова для мужской линейки
    patterns = [
        r"\bmen\b", r"\bman\b", r"\bfor men\b", r"\bmale\b",
        r"\bмуж\b", r"\bдля мужчин\b", r"\bмужской\b"
    ]
    return any(re.search(p, n) for p in patterns)


def _is_45_plus_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [
        r"\b45\+\b", r"\b45 plus\b", r"\banti-?age\b", r"\banti aging\b",
        r"\bлифтинг\b", r"\bвозрастн", r"\bантиэйдж\b", r"\bantiage\b"
    ]
    # 45+ — обычно явно маркируется
    return any(re.search(p, n) for p in patterns)


def _is_teen_young_product(name: str) -> bool:
    n = (name or "").lower()
    patterns = [
        r"\bteen\b", r"\bподрост", r"\bjunior\b", r"\byoung\b", r"\b20\+\b"
    ]
    return any(re.search(p, n) for p in patterns)


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


def _passes_demographic_filters(item, age: int | None, gender: str | None) -> bool:
    name = getattr(item, "name", "") or ""

    # 1) Пол
    if gender:
        if gender.strip().lower() in ("женщина", "female", "woman"):
            # Женщинам исключаем мужские линейки
            if _is_men_product(name):
                return False
        elif gender.strip().lower() in ("мужчина", "male", "man"):
            # Мужчинам можно и унисекс, и мужские (не фильтруем)
            pass

    # 2) Возраст
    grp = _age_group(age)

    # Если возраст < 45 — убираем 45+
    if grp != "45+" and _is_45_plus_product(name):
        return False

    # Если возраст 45+ — можно оставлять 45+, но можно убрать «teen/young»
    if grp == "45+" and _is_teen_young_product(name):
        return False

    return True


def _score_item(item, profile: dict) -> Tuple[int, str]:
    """
    Очень простая логика.
    Возвращает score и короткое объяснение.
    (Ты можешь позже усложнить — это будет точка расширения.)
    """
    skin_type = (profile.get("skin_type") or "").lower()
    sens = (profile.get("sensitivity") or "").lower()
    concerns = (profile.get("concerns") or "").lower()
    name = (getattr(item, "name", "") or "").lower()

    score = 0
    why = []

    # базовые слова
    if skin_type in ("сухая", "dry"):
        if "hydr" in name or "увлаж" in name or "пит" in name:
            score += 2; why.append("увлажнение/питание")
    if skin_type in ("жирная", "oily"):
        if "oil" in name or "sebum" in name or "матир" in name or "pur" in name:
            score += 2; why.append("контроль себума")
    if skin_type in ("комбинированная", "comb"):
        if "balance" in name or "баланс" in name:
            score += 1; why.append("баланс")
    if sens in ("высокая", "high"):
        if "cica" in name or "calm" in name or "успок" in name or "sensitive" in name:
            score += 2; why.append("для чувствительной кожи")

    if "высып" in concerns or "акне" in concerns:
        if "acne" in name or "clear" in name or "blemish" in name or "pur" in name:
            score += 2; why.append("против высыпаний")

    if score == 0:
        score = 1
        why.append("универсальный вариант")

    return score, ", ".join(why)


def recommend_routine(catalog: List[Any], profile: dict) -> Dict[str, List[Tuple[Any, int, str]]]:
    """
    Возвращает подбор по шагам ухода.
    Формат: {"cleanser":[(item,score,why),...], "toner":..., ...}
    """
    age = profile.get("age")
    gender = profile.get("gender")

    # 1) Фильтруем по полу/возрасту
    filtered = [it for it in catalog if _passes_demographic_filters(it, age, gender)]

    # 2) Очень простой маппинг шагов по ключевым словам в названии
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

    # 3) сортировка и топ-3 на шаг
    for step in result:
        result[step].sort(key=lambda x: x[1], reverse=True)
        result[step] = result[step][:3]

    return result