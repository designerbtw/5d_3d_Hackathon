"""Adapter over STE Slicer (Cura 3.6 fork) API.

STATUS: written from the task description (section 4.3), NOT yet verified against
the STE Slicer distribution. Every spot marked VERIFY must be checked in the
installed distribution first. All methods run on the Qt main thread (the
registry wraps them with run_on_main).
"""
import os
import threading

import numpy as np

from . import geometry

# VERIFY: setting key(s) that switch classic / cylindrical / cylindrical_full.
# Look at resources/definitions of Stereotech Hybrid 530 and steslicer/MultiBackend.py.
PRINT_MODE_SETTING = None
PRINT_MODE_VALUES = {"classic": "classic", "cylindrical": "cylindrical", "cylindrical_full": "cylindrical_full"}


def _app():
    from steslicer.SteSlicerApplication import SteSlicerApplication  # VERIFY import path
    return SteSlicerApplication.getInstance()


class RealSlicer(object):
    name = "steslicer"

    def __init__(self):
        self._sliced = None

    # state
    def get_state(self):
        app = _app()
        stack = app.getGlobalContainerStack()
        mm = app.getMachineManager()
        return {"slicer": self.name, "machine": stack.getName() if stack else None,
                "mode": self._read_mode(stack), "material": mm.activeMaterialId,
                "quality": mm.activeQualityType, "objects": self.list_objects()}

    def _read_mode(self, stack):
        if stack is None or PRINT_MODE_SETTING is None:
            return None
        return stack.getProperty(PRINT_MODE_SETTING, "value")

    def set_mode(self, mode):
        if PRINT_MODE_SETTING is None:
            raise RuntimeError("Переключение 3D/5D ещё не настроено: найдите ключ в определении "
                               "Hybrid 530 и задайте PRINT_MODE_SETTING в slicer_real.py")
        stack = _app().getGlobalContainerStack()
        stack.userChanges.setProperty(PRINT_MODE_SETTING, "value", PRINT_MODE_VALUES[mode])
        return {"mode": mode}

    def set_material(self, name):
        _app().getMachineManager().setMaterialById(name)  # VERIFY: expects a material container id
        return {"material": name}

    def set_quality(self, name):
        _app().getMachineManager().setQualityGroupByQualityType(name)  # VERIFY signature
        return {"quality": name}

    def apply_settings(self, values):
        stack = _app().getGlobalContainerStack()
        for k, v in values.items():
            stack.userChanges.setProperty(k, "value", v)
        return {k: stack.getProperty(k, "value") for k in values}   # what was really applied

    # scene
    def _nodes(self):
        from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
        root = _app().getController().getScene().getRoot()
        return [n for n in DepthFirstIterator(root) if n.getMeshData() is not None
                and n.callDecoration("isSliceable")]

    def _node(self, oid):
        for n in self._nodes():
            if str(id(n)) == oid:
                return n
        raise KeyError("Нет объекта " + oid)

    def load_model(self, path):
        from PyQt5.QtCore import QUrl
        before = {id(n) for n in self._nodes()}
        _app().readLocalFile(QUrl.fromLocalFile(path))   # async: the node appears after a job
        return {"requested": os.path.basename(path), "known_before": len(before),
                "note": "Модель загружается асинхронно; вызовите list_objects."}

    def list_objects(self):
        out = []
        for n in self._nodes():
            bb = n.getBoundingBox()
            out.append({"id": str(id(n)), "name": n.getName(),
                        "size_mm": [round(bb.width, 2), round(bb.depth, 2), round(bb.height, 2)]})
        return out

    def get_triangles(self, oid):
        md = self._node(oid).getMeshData()
        v, idx = md.getVertices(), md.getIndices()
        return (v[idx] if idx is not None else v.reshape(-1, 3, 3)).astype(float)  # VERIFY axes (Cura scene is Y-up)

    def rotate_to_down(self, oid, down):
        raise RuntimeError("TODO: RotateOperation по матрице geometry.rotation_from_to (учесть Y-up в сцене Cura)")

    def transform(self, oid, move=None, rotate=None, scale=None):
        raise RuntimeError("TODO: TranslateOperation / RotateOperation / ScaleOperation из UM.Operations")

    def delete(self, oid):
        raise RuntimeError("TODO: RemoveSceneNodeOperation")

    def arrange_all(self):
        _app().arrangeAll()
        return {"arranged": True}

    # slicing / export
    def slice(self, progress=None):
        done = threading.Event()
        backend = _app().getBackend()
        # VERIFY: use backendStateChange / processingProgress signals and BackendState.Done
        raise RuntimeError("TODO: forceSlice() и ожидание сигнала завершения; затем getPrintInformation()")

    def export_gcode(self, path):
        raise RuntimeError("TODO: PluginRegistry.getPluginObject('GCodeWriter').write(stream, None)")

    def save_project(self, path):
        raise RuntimeError("TODO: PluginRegistry.getPluginObject('3MFWriter').write(stream, nodes)")
