from typing import Dict, List, Tuple
from catalog import CatalogItem
from rules import rule_assess

# Базовые шаги ухода
STEPS = ["cleanser", "toner", "serum", "cream", "sunscreen"]

# Слова, которые считаем косметикой (можно дополнять)
COSMETIC_INCLUDE = [
    "крем", "тонер", "сывор", "серум", "эссен", "эмульс",
    "пен", "очищ", "гель", "маска", "пилинг", "скраб",
    "spf", "солнц", "лосьон", "мицел", "молочк",
    "ампул", "патч", "бальзам", "пудра", "шампун", "кондиц", "туш",
]

# Слова, которые точно НЕ косметика (исключаем)
NON_COSMETIC_EXCLUDE = [
    "пакет", "стирк", "капсул", "порошок", "моющ", "чистящ", "уборк",
    "посуда", "перчат", "губк", "салфет", "тряпк",
    "зубн", "паста", "щетк", "ополаск",
    "витамин", "бада", "капсулы", "таблет", "добавк",
]

def _low(s: str) -> str:
    return (s or "").lower()

def guess_step(name: str) -> str:
    n = _low(name)
    # cleanser
    if "пен" in n or "очищ" in n or "гель" in n or "клин" in n or "мицел" in n:
        return "cleanser"
    # toner
    if "тонер" in n or "тоник" in n:
        return "toner"
    # serum
    if "сывор" in n or "серум" in n or "ампул" in n or "эссен" in n:
        return "serum"
    # sunscreen
    if "spf" in n or "солнц" in n:
        return "sunscreen"
    # cream
    if "крем" in n:
        return "cream"
    return ""

def is_cosmetic(item: CatalogItem) -> bool:
    """
    Возвращает True, если это похоже на косметику.
    Фильтр: исключаем бытовое/прочее, допускаем косметику даже без INCI,
    но приоритет будет ниже.
    """
    name = _low(item.name)

    # Жёсткое исключение по словам
    if any(bad in name for bad in NON_COSMETIC_EXCLUDE):
        return False

    # Если есть INCI — почти наверняка косметика (или средство ухода)
    if item.inci and len(item.inci) > 30:
        return True

    # Если по названию похоже на косметику
    if any(good in name for good in COSMETIC_INCLUDE):
        return True

    return False

def score_item(item: CatalogItem, profile: Dict) -> Tuple[int, str]:
    step = item.step or guess_step(item.name)
    if step not in STEPS:
        return 0, "Не относится к базовым шагам ухода"

    # INCI нет — всё равно можно предложить, но ниже
    if not item.inci or len(item.inci) < 30:
        return 35, "Нет полного состава INCI — лучше уточнить состав перед покупкой"

    verdict, reasons = rule_assess(item.inci, profile)
    if verdict == "good":
        return 90, "Подходит по базовым правилам"
    if verdict == "caution":
        return 60, "Нюансы: " + "; ".join(reasons[:2]) if reasons else "Нюансы по составу"
    return 20, "Скорее не подходит: " + "; ".join(reasons[:2]) if reasons else "Скорее не подходит"

def recommend_routine(items: List[CatalogItem], profile: Dict) -> Dict[str, List[Tuple[CatalogItem, int, str]]]:
    """
    Возвращает топ-3 на каждый шаг ухода.
    Здесь же фильтруем каталог, чтобы не попадало бытовое.
    """
    result = {s: [] for s in STEPS}

    for item in items:
        if not is_cosmetic(item):
            continue

        step = item.step or guess_step(item.name)
        if step not in result:
            continue

        sc, why = score_item(item, profile)
        if sc > 0:
            result[step].append((item, sc, why))

    for step in result:
        result[step].sort(key=lambda x: x[1], reverse=True)
        result[step] = result[step][:3]

    return result