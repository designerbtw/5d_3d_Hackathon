"""Run the whole stack WITHOUT the slicer (fake slicer backend):  python dev.py
Set LLM_API_KEY in the environment (or enter it in the chat settings)."""
import sys
import time
import webbrowser

sys.path.insert(0, ".")
from AIAssistant.agent.bootstrap import start_server  # noqa: E402

if __name__ == "__main__":
    srv = start_server(8765)
    print("Chat:", srv.url)
    webbrowser.open(srv.url)
    while True:
        time.sleep(3600)
