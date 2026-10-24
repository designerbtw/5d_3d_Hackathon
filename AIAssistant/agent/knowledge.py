import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def _load(name):
    with open(os.path.join(_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


MATERIALS = _load("materials.json")
WHITELIST = {k: v for k, v in _load("settings_whitelist.json").items() if not k.startswith("_")}


def material_recipe(material, purpose=None):
    key = (material or "").upper()
    base = MATERIALS.get(key)
    if base is None:
        return {"error": "Нет рецепта для материала '%s'. Известны: %s" % (
            material, ", ".join(k for k in MATERIALS if not k.startswith("_")))}
    out = {"material": key, "recipe": base}
    if purpose:
        p = MATERIALS["_purposes"].get(purpose)
        out["purpose"] = {"name": purpose, "recipe": p} if p else {
            "error": "Неизвестная цель. Доступны: " + ", ".join(MATERIALS["_purposes"])}
    out["warning"] = "null означает 'значение не задано': не придумывай число, спроси пользователя или оставь профиль."
    return out


def check_setting(key, value):
    """Return (ok, value_or_message). Clamps nothing: out-of-range values are rejected."""
    spec = WHITELIST.get(key)
    if spec is None:
        return False, "Параметр '%s' не в белом списке (см. search_settings)" % key
    t = spec["type"]
    if t == "boolean":
        return (True, value) if isinstance(value, bool) else (False, "ожидался true/false")
    if t == "string":
        if value in spec.get("enum", [value]):
            return True, value
        return False, "допустимы: " + ", ".join(spec["enum"])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, "ожидалось число"
    if t == "integer" and int(value) != value:
        return False, "ожидалось целое число"
    if value < spec["min"] or value > spec["max"]:
        return False, "вне диапазона %s..%s" % (spec["min"], spec["max"])
    return True, int(value) if t == "integer" else value


def search_settings(query, limit=8):
    q = (query or "").lower()
    hits = [{"key": k, "label": v["label"]} for k, v in WHITELIST.items()
            if q in k.lower() or q in v["label"].lower()]
    return hits[:limit] or [{"key": k, "label": v["label"]} for k, v in list(WHITELIST.items())[:limit]]
