"""Tool definitions. Every handler validates input, applies it through the slicer
adapter and returns what was ACTUALLY applied so the model never has to guess."""
import os

import numpy as np

from . import geometry, knowledge

MODES = ["classic", "cylindrical", "cylindrical_full"]
S = {"type": "string"}
N = {"type": "number"}


def _inside(base, path):
    base = os.path.realpath(base)
    p = os.path.realpath(os.path.join(base, path))
    if p != base and not p.startswith(base + os.sep):
        raise ValueError("Путь вне папки результатов: %s" % base)
    return p


def build_registry(registry, slicer, settings, progress=None):
    r = registry
    out_dir = settings.output_dir()

    def get_state(a):
        st = slicer.get_state()
        st["tunable_settings"] = {k: v["label"] for k, v in knowledge.WHITELIST.items()}
        return st

    def set_print_mode(a):
        return slicer.set_mode(a["mode"])

    def set_material(a):
        res = slicer.set_material(a["material"])
        rec = knowledge.MATERIALS.get(a["material"].upper())
        if rec and rec.get("dry_before_print"):
            res["reminder"] = "Материал гигроскопичен: перед печатью его нужно просушить."
        return res

    def set_quality(a):
        return slicer.set_quality(a["profile"])

    def search_settings(a):
        return {"matches": knowledge.search_settings(a["query"])}

    def set_settings(a):
        applied, rejected = {}, {}
        for k, v in a["settings"].items():
            ok, res = knowledge.check_setting(k, v)
            if ok:
                applied[k] = res
            else:
                rejected[k] = res
        actual = slicer.apply_settings(applied) if applied else {}
        return {"applied": actual, "rejected": rejected}

    def load_model(a):
        path = a["path"]
        if not os.path.isfile(path):
            raise ValueError("Файл не найден: %s" % path)
        if os.path.splitext(path)[1].lower() not in (".stl", ".obj", ".3mf"):
            raise ValueError("Поддерживаются STL, OBJ, 3MF")
        return slicer.load_model(path)

    def list_objects(a):
        return {"objects": slicer.list_objects()}

    def transform(a):
        return slicer.transform(a["id"], a.get("move"), a.get("rotate"), a.get("scale"))

    def delete_model(a):
        return slicer.delete(a["id"])

    def arrange_all(a):
        return slicer.arrange_all()

    def analyze_orientation(a):
        tris = slicer.get_triangles(a["id"])
        variants = geometry.rank_orientations(tris)
        return {"id": a["id"], "bbox": geometry.bbox(tris), "variants": variants,
                "how_to_read": "down_vector - куда смотрит стол; layers_stack_along - вдоль какой оси лягут слои "
                               "(вдоль неё деталь слабее). Меньше score - меньше поддержек и ниже высота.",
                "recommended_variant": variants[0]["variant_id"] if variants else None}

    def apply_orientation(a):
        tris = slicer.get_triangles(a["id"])
        variants = {v["variant_id"]: v for v in geometry.rank_orientations(tris)}
        v = variants.get(a["variant_id"])
        if v is None:
            raise ValueError("Нет варианта %s. Сначала вызовите analyze_orientation" % a["variant_id"])
        return slicer.rotate_to_down(a["id"], v["down_vector"])

    def slice_(a):
        return slicer.slice(progress)

    def export_gcode(a):
        return slicer.export_gcode(_inside(out_dir, a.get("name", "result.gcode")))

    def save_project(a):
        return slicer.save_project(_inside(out_dir, a.get("name", "project.3mf")))

    def get_material_recipe(a):
        return knowledge.material_recipe(a["material"], a.get("purpose"))

    r.add("get_state", "Текущее состояние: принтер, режим, материал, профиль, объекты и список настраиваемых параметров. Вызывай первым.", handler=get_state)
    r.add("set_print_mode", "Режим печати: classic (3D), cylindrical (5D Spiral), cylindrical_full (5D).",
          {"mode": {"type": "string", "enum": MODES}}, ["mode"], set_print_mode)
    r.add("set_material", "Выбрать материал (например PLA, PETG, ABS, NYLON).", {"material": S}, ["material"], set_material)
    r.add("set_quality", "Выбрать профиль качества (Draft, Standard, Fine).", {"profile": S}, ["profile"], set_quality)
    r.add("search_settings", "Найти параметры по слову; возвращает ключи, которые можно менять.", {"query": S}, ["query"], search_settings, cacheable=True)
    r.add("set_settings", "Изменить параметры печати. Значения проверяются; в ответе видно, что применено и что отклонено.",
          {"settings": {"type": "object"}}, ["settings"], set_settings)
    r.add("get_material_recipe", "Рецепт материала и цели печати (load_bearing, fast, visual). null = значение не задано.",
          {"material": S, "purpose": {"type": "string", "enum": ["load_bearing", "fast", "visual"]}}, ["material"],
          get_material_recipe, cacheable=True)
    r.add("load_model", "Загрузить STL/OBJ/3MF по пути.", {"path": S}, ["path"], load_model)
    r.add("list_objects", "Список объектов на столе с габаритами.", handler=list_objects)
    r.add("transform_model", "Сдвиг (мм), поворот (градусы), масштаб объекта.",
          {"id": S, "move": {"type": "object"}, "rotate": {"type": "object"}, "scale": N}, ["id"], transform)
    r.add("delete_model", "Удалить объект со стола.", {"id": S}, ["id"], delete_model)
    r.add("arrange_all", "Автоматическая расстановка объектов на столе.", handler=arrange_all)
    r.add("analyze_orientation", "Геометрический анализ: варианты ориентации с метриками поддержек, высоты и площади контакта.",
          {"id": S}, ["id"], analyze_orientation, cacheable=True)
    r.add("apply_orientation", "Повернуть модель в выбранный вариант ориентации.",
          {"id": S, "variant_id": {"type": "integer", "minimum": 1}}, ["id", "variant_id"], apply_orientation)
    r.add("slice", "Нарезать сцену. Возвращает время печати и расход материала.", handler=slice_)
    r.add("export_gcode", "Сохранить G-code в папку результатов.", {"name": S}, [], export_gcode)
    r.add("save_project_3mf", "Сохранить проект 3MF в папку результатов.", {"name": S}, [], save_project)
    return r
