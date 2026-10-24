"""Single tool registry shared by the agent loop and the MCP endpoint."""
import json

from .schema import validate


class Tool(object):
    def __init__(self, name, description, parameters, handler, cacheable=False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.cacheable = cacheable


class Registry(object):
    def __init__(self, runner=None):
        self._tools = {}
        self._order = []
        self._runner = runner or (lambda f, *a: f(*a))

    def add(self, name, description, properties=None, required=None, handler=None, cacheable=False):
        schema = {"type": "object", "properties": properties or {}, "required": required or []}
        self._tools[name] = Tool(name, description, schema, handler, cacheable)
        self._order.append(name)

    def get(self, name):
        return self._tools.get(name)

    def openai_tools(self):
        return [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in (self._tools[n] for n in self._order)]

    def mcp_tools(self):
        return [{"name": t.name, "description": t.description, "inputSchema": t.parameters}
                for t in (self._tools[n] for n in self._order)]

    def call(self, name, args):
        """Validate, run on the slicer main thread, never raise: errors go back to the model."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": "Неизвестный инструмент '%s'" % name}
        if not isinstance(args, dict):
            return {"error": "Аргументы должны быть JSON-объектом"}
        problems = validate(tool.parameters, args)
        if problems:
            return {"error": "Некорректные аргументы", "details": problems}
        try:
            result = self._runner(tool.handler, args)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def dumps(result):
        return json.dumps(result, ensure_ascii=False)
