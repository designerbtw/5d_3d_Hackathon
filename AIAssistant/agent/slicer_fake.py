"""In-memory slicer used for development and tests outside STE Slicer.

Implements the same interface as slicer_real.RealSlicer, so the whole stack
(SPA -> agent -> tools) can be exercised without the application.
"""
import os
import time
import zipfile

import numpy as np

from . import geometry

MODES = ("classic", "cylindrical", "cylindrical_full")


class FakeSlicer(object):
    name = "fake"

    def __init__(self):
        self.mode = "classic"
        self.material = "PLA"
        self.quality = "Standard"
        self.settings = {}
        self.objects = {}
        self._next = 1
        self.sliced = None

    # state
    def get_state(self):
        return {"slicer": self.name, "machine": "Stereotech Hybrid 530 (fake)", "mode": self.mode,
                "material": self.material, "quality": self.quality,
                "materials": ["PLA", "PETG", "ABS", "NYLON"], "profiles": ["Draft", "Standard", "Fine"],
                "settings": dict(self.settings),
                "objects": [{"id": k, "name": v["name"]} for k, v in self.objects.items()]}

    def set_mode(self, mode):
        self.mode = mode
        return {"mode": mode}

    def set_material(self, name):
        self.material = name.upper()
        return {"material": self.material}

    def set_quality(self, name):
        self.quality = name
        return {"quality": name}

    def apply_settings(self, values):
        self.settings.update(values)
        return dict(values)

    # scene
    def load_model(self, path):
        tris = geometry.load_stl(path) if path.lower().endswith(".stl") else np.zeros((0, 3, 3))
        oid = "obj%d" % self._next
        self._next += 1
        self.objects[oid] = {"name": os.path.basename(path), "tris": tris}
        return {"id": oid, "name": os.path.basename(path),
                "bbox": geometry.bbox(tris) if len(tris) else None}

    def list_objects(self):
        return [{"id": k, "name": v["name"],
                 "bbox": geometry.bbox(v["tris"]) if len(v["tris"]) else None}
                for k, v in self.objects.items()]

    def get_triangles(self, oid):
        return self.objects[oid]["tris"]

    def rotate_to_down(self, oid, down):
        t = self.objects[oid]["tris"]
        r = geometry.rotation_from_to(down, [0, 0, -1])
        self.objects[oid]["tris"] = np.einsum("ij,nkj->nki", r, t)
        return {"id": oid, "bbox": geometry.bbox(self.objects[oid]["tris"])}

    def transform(self, oid, move=None, rotate=None, scale=None):
        if oid not in self.objects:
            raise KeyError("Нет объекта " + oid)
        return {"id": oid, "applied": {"move": move, "rotate": rotate, "scale": scale}}

    def delete(self, oid):
        self.objects.pop(oid)
        return {"deleted": oid}

    def arrange_all(self):
        return {"arranged": len(self.objects)}

    # slicing / export
    def slice(self, progress=None):
        if not self.objects:
            raise RuntimeError("Сцена пуста: сначала загрузите модель")
        vol = sum(float(np.prod(geometry.bbox(o["tris"])["size_mm"])) for o in self.objects.values() if len(o["tris"]))
        for p in (0.3, 0.7, 1.0):
            if progress:
                progress(p)
            time.sleep(0.05)
        self.sliced = {"print_time_min": int(30 + vol / 500.0), "material_g": round(vol / 1000.0 * 0.4, 1)}
        return dict(self.sliced, state="finished")

    def export_gcode(self, path):
        if not self.sliced:
            raise RuntimeError("Сначала выполните slice")
        with open(path, "w") as f:
            f.write("; FAKE G-CODE (dev mode)\n; mode=%s material=%s\nG28\n" % (self.mode, self.material))
        return {"path": path}

    def save_project(self, path):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("3D/3dmodel.model", "<!-- FAKE 3MF (dev mode) -->")
        return {"path": path}
