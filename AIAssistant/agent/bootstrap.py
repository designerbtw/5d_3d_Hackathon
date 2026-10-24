"""Wires settings, LLM, tools, agent and server together."""
import binascii
import os

from . import tools
from .agent import Agent
from .config import Settings
from .events import EventBus
from .llm import LLMClient
from .registry import Registry
from .server import App, serve


def _pick_slicer():
    try:
        import steslicer  # noqa: F401  (only importable inside STE Slicer)
        from .slicer_real import RealSlicer
        return RealSlicer(), _main_runner()
    except ImportError:
        from .slicer_fake import FakeSlicer
        return FakeSlicer(), None


def _main_runner():
    """Run a function on the Qt main thread and wait for its result."""
    import threading
    from UM.Application import Application

    def run(func, *args, **kw):
        timeout = kw.pop("timeout", 120)
        done, box = threading.Event(), {}

        def call():
            try:
                box["r"] = func(*args)
            except Exception as e:
                box["e"] = e
            finally:
                done.set()
        Application.getInstance().callLater(call)
        if not done.wait(timeout):
            raise TimeoutError("Слайсер не ответил за %d с" % timeout)
        if "e" in box:
            raise box["e"]
        return box["r"]
    return run


def create_app(settings=None):
    settings = settings or Settings()
    bus = EventBus()
    slicer, runner = _pick_slicer()
    registry = Registry(runner)
    tools.build_registry(registry, slicer, settings,
                         progress=lambda p: bus.emit(type="progress", value=p))
    llm = LLMClient(settings)
    agent = Agent(llm, registry, bus, settings)
    token = binascii.hexlify(os.urandom(16)).decode("ascii")
    return App(settings, llm, agent, registry, bus, token)


def start_server(port=0):
    return serve(create_app(), port)
