"""OpenAI-compatible Chat Completions client (stdlib only, Python 3.5 compatible)."""
import json
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class LLMClient(object):
    def __init__(self, settings):
        self._s = settings

    def chat(self, messages, tools=None, tool_choice=None, temperature=0.1, retries=2):
        key = self._s.get("api_key")
        if not key:
            raise LLMError("Не задан API-ключ. Откройте настройки чата и введите ключ.")
        payload = {"model": self._s.get("model"), "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        body = json.dumps(payload).encode("utf-8")
        url = self._s.get("base_url").rstrip("/") + "/chat/completions"
        last = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + key})
            try:
                with urllib.request.urlopen(req, timeout=int(self._s.get("request_timeout"))) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return data["choices"][0]["message"]
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")[:300]
                last = LLMError("LLM вернул HTTP %d: %s" % (e.code, text))
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
                last = LLMError("Ошибка обращения к LLM: %s" % e)
            time.sleep(1.5 * (attempt + 1))
        raise last

    def ping(self):
        self.chat([{"role": "user", "content": "ok"}], retries=0)
        return True
