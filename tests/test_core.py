import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from AIAssistant.agent import geometry, knowledge, mcp, tools  # noqa: E402
from AIAssistant.agent.agent import Agent  # noqa: E402
from AIAssistant.agent.config import Settings, _FileStore  # noqa: E402
from AIAssistant.agent.events import EventBus  # noqa: E402
from AIAssistant.agent.registry import Registry  # noqa: E402
from AIAssistant.agent.schema import validate  # noqa: E402
from AIAssistant.agent.slicer_fake import FakeSlicer  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
    f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
         (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return np.array([[v[a], v[b], v[c]] for a, b, c in f])


def quad(p0, p1, p2, p3, outward):
    """Two triangles with the winding flipped so the normal points along `outward`."""
    out = []
    for t in ((p0, p1, p2), (p0, p2, p3)):
        t = [np.array(x, float) for x in t]
        if np.dot(np.cross(t[1] - t[0], t[2] - t[0]), outward) < 0:
            t = [t[0], t[2], t[1]]
        out.append(t)
    return np.array(out)


def l_bracket():
    """Solid L profile (y,z): base 40x5 plus wall 5x30, extruded 40 along x. No hidden faces."""
    X = 40
    def q(a, b, outward):  # a,b are (y,z) edge endpoints, extruded along x
        return quad((0, a[0], a[1]), (X, a[0], a[1]), (X, b[0], b[1]), (0, b[0], b[1]), outward)
    faces = [q((0, 0), (40, 0), (0, 0, -1)), q((40, 0), (40, 5), (0, 1, 0)), q((40, 5), (5, 5), (0, 0, 1)),
             q((5, 5), (5, 35), (0, 1, 0)), q((5, 35), (0, 35), (0, 0, 1)), q((0, 35), (0, 0), (0, -1, 0))]
    caps = []
    for x, o in ((0, (-1, 0, 0)), (X, (1, 0, 0))):
        caps.append(quad((x, 0, 0), (x, 40, 0), (x, 40, 5), (x, 0, 5), o))
        caps.append(quad((x, 0, 5), (x, 5, 5), (x, 5, 35), (x, 0, 35), o))
    return np.concatenate(faces + caps)


def write_stl(path, tris):
    import struct
    with open(path, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", 0, 0, 0))
            for p in t:
                f.write(struct.pack("<3f", *p))
            f.write(b"\0\0")


class FakeLLM(object):
    """Scripted model: returns queued messages, records what it was asked."""
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def chat(self, messages, tools=None, tool_choice=None, **kw):
        self.calls.append({"n": len(messages), "tool_choice": tool_choice})
        return self.script.pop(0)


def tc(i, name, args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c%d" % i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def build(tmp, script):
    s = Settings(_FileStore(os.path.join(tmp, "s.json")))
    s.set("output_dir", tmp)
    s.set("max_steps", 6)
    slicer, bus = FakeSlicer(), EventBus()
    reg = tools.build_registry(Registry(), slicer, s)
    return Agent(FakeLLM(script), reg, bus, s), reg, bus, slicer


class SchemaTests(unittest.TestCase):
    def test_enum_required_range(self):
        sch = {"type": "object", "properties": {"m": {"type": "string", "enum": ["a"]},
                                                "n": {"type": "integer", "minimum": 1}}, "required": ["m"]}
        self.assertEqual(validate(sch, {"m": "a", "n": 2}), [])
        self.assertTrue(validate(sch, {"m": "b"}))
        self.assertTrue(validate(sch, {"n": 0, "m": "a"}))
        self.assertTrue(validate(sch, {}))
        self.assertTrue(validate(sch, {"m": "a", "n": True}))


class KnowledgeTests(unittest.TestCase):
    def test_setting_validation(self):
        self.assertTrue(knowledge.check_setting("infill_sparse_density", 40)[0])
        self.assertFalse(knowledge.check_setting("infill_sparse_density", 140)[0])
        self.assertFalse(knowledge.check_setting("made_up_key", 1)[0])
        self.assertFalse(knowledge.check_setting("support_enable", "yes")[0])
        self.assertFalse(knowledge.check_setting("wall_line_count", 2.5)[0])

    def test_recipe_has_nulls_not_inventions(self):
        r = knowledge.material_recipe("PETG", "load_bearing")
        self.assertIsNone(r["purpose"]["recipe"]["infill_sparse_density"])
        self.assertIn("error", knowledge.material_recipe("UNOBTAINIUM"))


class GeometryTests(unittest.TestCase):
    def test_l_bracket_prefers_base_down(self):
        tris = l_bracket()
        top = geometry.rank_orientations(tris)[0]
        self.assertEqual(top["down_vector"], [0.0, 0.0, -1.0])
        self.assertEqual(top["support_proxy_mm3"], 0.0)

    def test_rotation(self):
        r = geometry.rotation_from_to([1, 0, 0], [0, 0, -1])
        self.assertTrue(np.allclose(r.dot([1, 0, 0]), [0, 0, -1]))

    def test_stl_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.stl")
            write_stl(p, box(0, 0, 0, 10, 20, 30))
            self.assertEqual(geometry.bbox(geometry.load_stl(p))["size_mm"], [10, 20, 30])


class AgentTests(unittest.TestCase):
    def test_full_scenario_and_rejected_values(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "bracket.stl")
            write_stl(stl, l_bracket())
            script = [tc(1, "get_state", {}), tc(2, "set_material", {"material": "PETG"}),
                      tc(3, "set_settings", {"settings": {"infill_sparse_density": 400, "support_enable": False}}),
                      tc(4, "load_model", {"path": stl}), tc(5, "slice", {}),
                      {"role": "assistant", "content": "Готово."}]
            agent, reg, bus, slicer = build(d, script)
            agent.handle("кронштейн, PETG")
            evs = [e for e in bus.subscribe(0).queue]
            res = {e["name"]: e["result"] for e in evs if e["type"] == "tool_result"}
            self.assertIn("infill_sparse_density", res["set_settings"]["rejected"])
            self.assertEqual(res["set_settings"]["applied"], {"support_enable": False})
            self.assertIn("reminder", res["set_material"])
            # model forgot to export: the safety net did it
            self.assertTrue(os.path.exists(os.path.join(d, "result.gcode")))
            self.assertTrue(os.path.exists(os.path.join(d, "project.3mf")))
            self.assertIn("Автоматически сохранено", [e for e in evs if e["type"] == "assistant"][-1]["text"])

    def test_cache_dedupes_and_step_limit_forces_text(self):
        with tempfile.TemporaryDirectory() as d:
            script = [tc(i, "search_settings", {"query": "infill"}) for i in range(1, 5)]
            script += [{"role": "assistant", "content": "Итог"}, {"role": "assistant", "content": "x"}]
            agent, reg, bus, _ = build(d, script)
            agent.handle("x")
            choices = [c["tool_choice"] for c in agent._llm.calls]
            self.assertIn("none", choices)
            notes = [e for e in bus.subscribe(0).queue if e["type"] == "tool_result" and "note" in e["result"]]
            self.assertTrue(notes)

    def test_bad_json_arguments_returned_to_model(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "get_state", "arguments": "{oops"}}]}
            agent, reg, bus, _ = build(d, [bad, {"role": "assistant", "content": "ok"}])
            agent.handle("x")
            tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
            self.assertIn("error", json.loads(tool_msgs[0]["content"]))

    def test_export_path_cannot_escape_output_dir(self):
        with tempfile.TemporaryDirectory() as d:
            _, reg, _, slicer = build(d, [])
            slicer.objects["o"] = {"name": "n", "tris": box(0, 0, 0, 1, 1, 1)}
            slicer.slice()
            self.assertIn("error", reg.call("export_gcode", {"name": "../../evil.gcode"}))

    def test_images_only_kept_in_latest_turn(self):
        with tempfile.TemporaryDirectory() as d:
            agent, *_ = build(d, [])
            img = {"kind": "image", "name": "a.png", "mime": "image/png", "b64": "AAAA"}
            agent._user_message("one", [img])
            agent._user_message("two", [img])
            users = [m for m in agent.messages if m["role"] == "user"]
            self.assertEqual(users[0]["content"][1]["text"], "[изображение]")
            self.assertEqual(users[1]["content"][1]["type"], "image_url")


class McpTests(unittest.TestCase):
    def test_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            _, reg, _, _ = build(d, [])
            init = mcp.handle(reg, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "stereotech-ai-assistant")
            self.assertIsNone(mcp.handle(reg, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
            names = [t["name"] for t in mcp.handle(reg, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
            self.assertIn("set_print_mode", names)
            r = mcp.handle(reg, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "set_print_mode", "arguments": {"mode": "cylindrical"}}})
            self.assertFalse(r["result"]["isError"])
            bad = mcp.handle(reg, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                   "params": {"name": "set_print_mode", "arguments": {"mode": "nope"}}})
            self.assertTrue(bad["result"]["isError"])


class ServerTests(unittest.TestCase):
    def test_auth_and_settings_never_leak_key(self):
        import urllib.error
        import urllib.request
        from AIAssistant.agent import bootstrap
        with tempfile.TemporaryDirectory() as d:
            s = Settings(_FileStore(os.path.join(d, "s.json")))
            s.set("output_dir", d)
            s.set("api_key", "SECRET-KEY")
            app = bootstrap.serve(bootstrap.create_app(s))
            base = app.url.split("/?")[0]
            try:
                urllib.request.urlopen(base + "/api/settings")
                self.fail("must require token")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 401)
            body = urllib.request.urlopen(base + "/api/settings?t=" + app.token).read().decode()
            self.assertNotIn("SECRET-KEY", body)
            self.assertIn('"has_key": true', body)
            self.assertEqual(urllib.request.urlopen(base + "/").status, 200)
            app.httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
