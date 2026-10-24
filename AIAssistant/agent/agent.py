"""Agent loop: LLM <-> tools, with step limit, duplicate cache and a safety net."""
import json
import threading

from . import prompts


class Agent(object):
    def __init__(self, llm, registry, bus, settings):
        self._llm, self._reg, self._bus, self._s = llm, registry, bus, settings
        self.messages = [{"role": "system", "content": prompts.SYSTEM}]
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self._lock.locked()

    def reset(self):
        self.messages = [{"role": "system", "content": prompts.SYSTEM}]
        self._bus.clear()

    def _user_message(self, text, attachments):
        # keep images only in the latest user turn to save tokens
        for m in self.messages:
            if m["role"] == "user" and isinstance(m["content"], list):
                m["content"] = [p if p["type"] == "text" else {"type": "text", "text": "[изображение]"}
                                for p in m["content"]]
        parts, notes = [], []
        for a in attachments:
            if a["kind"] == "image":
                parts.append({"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (a["mime"], a["b64"])}})
            else:
                notes.append("Загружен файл модели: %s, путь: %s" % (a["name"], a["path"]))
        text = "\n".join([text] + notes)
        content = [{"type": "text", "text": text}] + parts if parts else text
        self.messages.append({"role": "user", "content": content})

    def handle(self, text, attachments=None):
        if not self._lock.acquire(False):
            self._bus.emit(type="error", text="Агент ещё обрабатывает предыдущий запрос.")
            return
        try:
            self._bus.emit(type="status", state="working")
            self._user_message(text, attachments or [])
            self._loop()
        except Exception as e:
            self._bus.emit(type="error", text=str(e))
        finally:
            self._bus.emit(type="status", state="idle")
            self._lock.release()

    def _loop(self):
        max_steps = int(self._s.get("max_steps"))
        done, seen = set(), {}
        for step in range(max_steps):
            last = step >= max_steps - 2
            msg = self._llm.chat(self.messages, tools=self._reg.openai_tools(),
                                 tool_choice="none" if last else None)
            self.messages.append(msg)
            calls = msg.get("tool_calls")
            if not calls:
                text = self._safety_net(done, msg.get("content") or "")
                self._bus.emit(type="assistant", text=text)
                return
            for tc in calls:
                self._run_call(tc, done, seen)
        self._bus.emit(type="assistant", text=self._safety_net(done, "Достигнут лимит шагов."))

    def _run_call(self, tc, done, seen):
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"].get("arguments") or "{}")
        except ValueError:
            args = None
        self._bus.emit(type="tool_call", id=tc["id"], name=name, args=args)
        tool = self._reg.get(name)
        key = name + json.dumps(args, sort_keys=True)
        if args is None:
            res = {"error": "Аргументы не являются корректным JSON"}
        elif tool is not None and tool.cacheable and key in seen:
            res = dict(seen[key], note="повторный вызов, возвращён прежний результат")
        else:
            res = self._reg.call(name, args)
            if tool is not None and tool.cacheable and "error" not in res:
                seen[key] = res
        if "error" not in res:
            done.add(name)
        self._bus.emit(type="tool_result", id=tc["id"], name=name, result=res)
        self.messages.append({"role": "tool", "tool_call_id": tc["id"],
                              "content": json.dumps(res, ensure_ascii=False)})

    def _safety_net(self, done, text):
        """If slicing succeeded but the model forgot to export, do it for the user."""
        added = []
        for tool, label in (("export_gcode", "G-code"), ("save_project_3mf", "проект 3MF")):
            if "slice" in done and tool not in done:
                res = self._reg.call(tool, {})
                self._bus.emit(type="tool_call", id="auto-" + tool, name=tool, args={}, auto=True)
                self._bus.emit(type="tool_result", id="auto-" + tool, name=tool, result=res)
                if "error" not in res:
                    added.append("%s: %s" % (label, res.get("path")))
        if added:
            text += "\n\nАвтоматически сохранено — " + "; ".join(added)
        return text
