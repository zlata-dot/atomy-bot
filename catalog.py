import csv
from dataclasses import dataclass
from typing import List

@dataclass
class CatalogItem:
    sku: str
    name: str
    step: str
    price_before_rub: str
    price_after_rub: str
    pv: str
    inci: str
    url: str

def load_catalog_ru(path: str) -> List[CatalogItem]:
    items: List[CatalogItem] = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            items.append(CatalogItem(
                sku=(row.get("sku") or "").strip(),
                name=(row.get("name") or "").strip(),
                step=(row.get("step") or "").strip(),
                price_before_rub=(row.get("price_before_rub") or "").strip(),
                price_after_rub=(row.get("price_after_rub") or "").strip(),
                pv=(row.get("pv") or "").strip(),
                inci=(row.get("inci") or "").strip(),
                url=(row.get("url") or "").strip(),
            ))
    return items