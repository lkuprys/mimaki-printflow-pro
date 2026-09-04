import time
import threading
import win32gui
import win32con


class RasterLinkBridge:
    def __init__(self, check_interval: float = 1.5):
        self.check_interval = check_interval
        self._running = False
        self._thread: threading.Thread = None
        self.dismissed_popups = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print("[BRIDGE] RasterLink foninis stebetojas paleistas.")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        print("[BRIDGE] RasterLink foninis stebetojas sustabdytas.")

    def _monitor_loop(self):
        while self._running:
            try:
                self._check_and_dismiss_popups()
            except Exception as e:
                pass
            time.sleep(self.check_interval)

    def _check_and_dismiss_popups(self):
        """Suranda isokusius RasterLink pranesimu langus ir paspaudzia OK."""
        def enum_windows_callback(hwnd, extra):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            
            # Tipiniai Mimaki / RasterLink isokantys langai
            popup_keywords = [
                "RasterLink", "Warning", "Error", "Notice", "Information",
                "Media Width", "Profile", "Device", "Confirmation"
            ]
            
            # Tikriname ar langas yra dialogas / pop-up
            if any(k.lower() in title.lower() for k in popup_keywords) and class_name == "#32770":
                # Iesko mygtuko 'OK', 'Continue', 'Yes'
                def enum_child_callback(child_hwnd, _):
                    c_text = win32gui.GetWindowText(child_hwnd).strip().lower()
                    c_class = win32gui.GetClassName(child_hwnd)
                    if c_class == "Button" and c_text in ["ok", "taip", "yes", "continue", "teskite"]:
                        # Paspaudziame mygtuka
                        win32gui.PostMessage(child_hwnd, win32con.BM_CLICK, 0, 0)
                        self.dismissed_popups += 1
                        print(f"[BRIDGE] Uzdarytas pranesimo langas: '{title}' per mygtuka '{c_text}'")
                
                win32gui.EnumChildWindows(hwnd, enum_child_callback, None)
                
        win32gui.EnumWindows(enum_windows_callback, None)


# Singleton instance
bridge = RasterLinkBridge()
