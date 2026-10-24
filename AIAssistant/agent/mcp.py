"""Minimal MCP server over JSON-RPC 2.0: initialize, tools/list, tools/call, ping."""
import json

PROTOCOL = "2024-11-05"


def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(registry, request):
    """Return a response dict, or None for notifications."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _err(None, -32600, "Invalid Request")
    rid, method = request.get("id"), request.get("method")
    params = request.get("params") or {}
    if rid is None:  # notification, e.g. notifications/initialized
        return None
    if method == "initialize":
        return _ok(rid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "stereotech-ai-assistant", "version": "1.0.0"}})
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": registry.mcp_tools()})
    if method == "tools/call":
        name = params.get("name")
        if registry.get(name) is None:
            return _err(rid, -32602, "Unknown tool: %s" % name)
        result = registry.call(name, params.get("arguments") or {})
        return _ok(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                         "isError": "error" in result})
    return _err(rid, -32601, "Method not found: %s" % str(method))
