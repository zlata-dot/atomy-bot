import re
from typing import Dict, Tuple

FRAGRANCE_PATTERNS = [r"\bparfum\b", r"\bfragrance\b", r"\baroma\b"]
ALCOHOL_PATTERNS = [r"\balcohol denat\b", r"\bdenat\.\b"]
IRRITANT_PATTERNS = [r"\bmenthol\b", r"\bpeppermint\b", r"\beucalyptus\b"]
ACID_PATTERNS = [r"\bsalicylic acid\b", r"\bglycolic acid\b", r"\blactic acid\b", r"\bmandelic acid\b", r"\bazelaic acid\b"]
RETINOID_PATTERNS = [r"\bretinol\b", r"\bretinal\b", r"\btretinoin\b", r"\badapalene\b", r"\bretinoate\b"]

def _norm(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[\(\)\[\]\{\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _any_hit(inci: str, patterns: list[str]) -> bool:
    return any(re.search(p, inci) for p in patterns)

def rule_assess(inci_text: str, profile: Dict) -> Tuple[str, list[str]]:
    inci = _norm(inci_text)
    reasons: list[str] = []

    has_fragrance = _any_hit(inci, FRAGRANCE_PATTERNS)
    has_alcohol = _any_hit(inci, ALCOHOL_PATTERNS)
    has_irritants = _any_hit(inci, IRRITANT_PATTERNS)
    has_acids = _any_hit(inci, ACID_PATTERNS)
    has_ret = _any_hit(inci, RETINOID_PATTERNS)

    sensitivity = (profile.get("sensitivity") or "").lower()
    barrier = (profile.get("barrier_state") or "").lower()

    caution = 0
    if has_fragrance and ("высок" in sensitivity or "чувств" in sensitivity):
        reasons.append("Есть отдушка — при чувствительной коже это частый триггер.")
        caution += 1
    if has_alcohol:
        reasons.append("Есть денат. спирт — может сушить/раздражать.")
        caution += 1
    if has_irritants:
        reasons.append("Есть потенциальные раздражители (ментол/эфирные компоненты).")
        caution += 1
    if (has_acids or has_ret) and ("ослаб" in barrier or "обезвож" in barrier):
        reasons.append("Есть активы (кислоты/ретиноиды) — при ослабленном барьере вводить осторожно.")
        caution += 1

    if caution >= 3:
        return "bad", reasons
    if caution >= 1:
        return "caution", reasons
    return "good", reasons