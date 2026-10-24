"""Tiny JSON-Schema subset validator: type, enum, min/max, required."""

_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool,
          "object": dict, "array": list}


def validate(schema, value, path="arguments"):
    """Return a list of human-readable problems (empty list = valid)."""
    errs = []
    t = schema.get("type")
    if t:
        ok = isinstance(value, _TYPES[t])
        if t in ("number", "integer") and isinstance(value, bool):
            ok = False
        if not ok:
            return ["%s: ожидался тип %s" % (path, t)]
    if "enum" in schema and value not in schema["enum"]:
        errs.append("%s: допустимы только %s" % (path, ", ".join(map(str, schema["enum"]))))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append("%s: минимум %s" % (path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errs.append("%s: максимум %s" % (path, schema["maximum"]))
    if isinstance(value, dict):
        for r in schema.get("required", []):
            if r not in value:
                errs.append("%s: не хватает поля '%s'" % (path, r))
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                errs.extend(validate(sub, value[k], path + "." + k))
    return errs
