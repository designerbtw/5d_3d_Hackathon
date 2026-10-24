"""Deterministic geometry analysis: ranks candidate print orientations.

The LLM never computes geometry; it receives this table and chooses from it.
Coordinates: model space, "down" is the unit vector pointing to the build plate.
"""
import struct

import numpy as np


def load_stl(path):
    """Return triangles as an (N, 3, 3) float array (binary or ASCII STL)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 == len(data):
            dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return np.frombuffer(data[84:], dtype=dt)["v"].astype(np.float64)
    pts = []
    for line in data.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "vertex":
            pts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if not pts or len(pts) % 3:
        raise ValueError("Не удалось прочитать STL")
    return np.array(pts, dtype=np.float64).reshape(-1, 3, 3)


def bbox(tris):
    v = tris.reshape(-1, 3)
    lo, hi = v.min(axis=0), v.max(axis=0)
    return {"min": lo.round(3).tolist(), "max": hi.round(3).tolist(),
            "size_mm": (hi - lo).round(3).tolist()}


def _normals_areas(tris):
    c = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(c, axis=1)
    area = ln / 2.0
    n = np.zeros_like(c)
    ok = ln > 1e-12
    n[ok] = c[ok] / ln[ok][:, None]
    return n, area


def rotation_from_to(a, b):
    """3x3 rotation matrix turning unit vector a into unit vector b."""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k.dot(k) * (1.0 / (1.0 + c))


def _candidates(n, area, top=6):
    cands = [np.array(v, float) for v in
             ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0])]
    keys = {}
    for ni, ai in zip(n, area):
        k = tuple(np.round(ni, 2))
        keys[k] = keys.get(k, 0.0) + ai
    for k, _ in sorted(keys.items(), key=lambda kv: -kv[1])[:top]:
        v = np.array(k, float)
        if np.linalg.norm(v) > 0.5 and not any(np.allclose(v, c, atol=0.03) for c in cands):
            cands.append(v / np.linalg.norm(v))
    return cands


def rank_orientations(tris, overhang_deg=45.0, max_results=6):
    n, area = _normals_areas(tris)
    cos_thr = np.cos(np.radians(overhang_deg))
    cent = tris.mean(axis=1)
    rows = []
    for d in _candidates(n, area):
        s_vert = tris.reshape(-1, 3).dot(d)
        plate, top = s_vert.max(), s_vert.min()
        height = plate - top
        nd = n.dot(d)
        depth = plate - cent.dot(d)               # distance above the plate
        on_plate = (nd > 0.999) & (depth < 0.2)
        overhang = (nd > cos_thr) & ~on_plate
        rows.append({
            "down_vector": [round(float(x), 4) for x in d],
            "height_mm": round(float(height), 2),
            "contact_area_mm2": round(float(area[on_plate].sum()), 1),
            "overhang_area_mm2": round(float(area[overhang].sum()), 1),
            "support_proxy_mm3": round(float((area[overhang] * nd[overhang] * depth[overhang]).sum()), 1),
        })
    sup = max(r["support_proxy_mm3"] for r in rows) or 1.0
    hgt = max(r["height_mm"] for r in rows) or 1.0
    con = max(r["contact_area_mm2"] for r in rows) or 1.0
    for r in rows:
        r["score"] = round(0.6 * r["support_proxy_mm3"] / sup + 0.2 * r["height_mm"] / hgt
                           + 0.2 * (1 - r["contact_area_mm2"] / con), 4)
    rows.sort(key=lambda r: r["score"])
    out = []
    for r in rows:
        if any(np.allclose(r["down_vector"], o["down_vector"], atol=0.03) for o in out):
            continue
        out.append(r)
    out = out[:max_results]
    for i, r in enumerate(out):
        r["variant_id"] = i + 1
        r["layers_stack_along"] = [-x for x in r["down_vector"]]
    return out
