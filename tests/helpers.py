"""測試共用工具：在指定環境變數下重新載入 mc_notify"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load(**env):
    for k in list(os.environ):
        if k.startswith("MC_") or k == "STATE_DIRECTORY":
            del os.environ[k]
    os.environ.update(env)
    import mc_notify
    return importlib.reload(mc_notify)


class Recorder:
    """取代 mc_notify.notify，記錄所有通知"""

    def __init__(self, module):
        self.calls = []
        module.notify = self

    def __call__(self, event, title, desc="", color=0, fields=None, attachment=None):
        self.calls.append({"event": event, "title": title, "desc": desc,
                           "fields": fields or [], "attachment": attachment})

    @property
    def events(self):
        return [c["event"] for c in self.calls]
