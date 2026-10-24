"""Extension entry point: adds a menu item that starts the local chat server."""
import webbrowser

from UM.Extension import Extension
from UM.Logger import Logger


class AIAssistant(Extension):
    def __init__(self):
        super().__init__()
        self.setMenuName("AI Assistant")
        self.addMenuItem("Open chat", self.showChat)
        self._server = None

    def showChat(self):
        try:
            if self._server is None:
                from .agent.bootstrap import start_server
                self._server = start_server()
            webbrowser.open(self._server.url)
        except Exception as e:  # never crash the slicer from a menu click
            Logger.log("e", "AI Assistant failed to start: %s" % e)
