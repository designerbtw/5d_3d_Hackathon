import queue
import threading


class EventBus(object):
    """Fan-out of events to every connected browser tab; keeps history for late joiners."""

    def __init__(self, keep=500):
        self._subs = []
        self._hist = []
        self._keep = keep
        self._lock = threading.Lock()

    def emit(self, **event):
        with self._lock:
            event["seq"] = (self._hist[-1]["seq"] + 1) if self._hist else 1
            self._hist.append(event)
            del self._hist[:-self._keep]
            subs = list(self._subs)
        for q in subs:
            q.put(event)

    def subscribe(self, after=0):
        q = queue.Queue()
        with self._lock:
            for e in self._hist:
                if e["seq"] > after:
                    q.put(e)
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def clear(self):
        with self._lock:
            self._hist = []
