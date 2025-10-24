# src/lm/utils/debounce.py
class Debouncer:
    """Coalesce multiple UI events and run the action once after delay."""
    def __init__(self, tk_root):
        self.tk_root = tk_root
        self._handles = {}
    def schedule(self, key: str, delay_ms: int, func, *args, **kwargs):
        h = self._handles.get(key)
        if h is not None:
            try:
                self.tk_root.after_cancel(h)
            except Exception:
                pass
        self._handles[key] = self.tk_root.after(delay_ms, lambda: func(*args, **kwargs))
