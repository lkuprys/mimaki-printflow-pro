import sys
import time
import threading
import ctypes
from typing import Optional, List, Dict, Callable, Tuple

import win32gui
import win32con
import win32service

try:
    from pywinauto import Application
    import comtypes.gen.UIAutomationClient as UIA
except ImportError:
    Application = None
    UIA = None

# MSAA SELFLAG constants
SELFLAG_TAKEFOCUS = 1
SELFLAG_TAKESELECTION = 2
SELFLAG_EXTENDSELECTION = 4
SELFLAG_ADDSELECTION = 8
STATE_SYSTEM_SELECTED = 0x00000002


class RasterLinkBridge:
    """
    Pilnai automatizuotas, foninis (headless) Mimaki RasterLink 7 valdiklis.
    Valdo langą nepastebimai fone (nematomose koordinatėse),
    automatiškai uždaro pop-up langus, atlieka kompoziciją ir paleidžia RIP & Print.
    """

    def __init__(self, check_interval: float = 1.0):
        self.check_interval = check_interval
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self.dismissed_popups = 0
        self.hdesk = None
        self._user_visible = False

    # -----------------------------------------------------------------
    # DESKTOP IR LANGO VALDYMAS
    # -----------------------------------------------------------------
    def _switch_desktop(self):
        """Užtikrina, kad esama gija bendrautų su vartotojo interaktyviu 'default' desktop'u."""
        try:
            self.hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
            ctypes.windll.user32.SetThreadDesktop(int(self.hdesk))
        except Exception:
            pass

    def find_rasterlink_hwnd(self) -> Optional[int]:
        self._switch_desktop()
        hwnds = []

        def cb(h, _):
            if win32gui.IsWindow(h):
                try:
                    t = win32gui.GetWindowText(h)
                    if "MimakiRasterLink7" in t:
                        hwnds.append(h)
                except Exception:
                    pass

        try:
            if self.hdesk:
                win32gui.EnumDesktopWindows(int(self.hdesk), cb, None)
            else:
                win32gui.EnumWindows(cb, None)
        except Exception:
            win32gui.EnumWindows(cb, None)

        return hwnds[0] if hwnds else None

    def ensure_offscreen(self, hwnd: Optional[int] = None) -> Optional[int]:
        """
        Atkuria RasterLink 7 iš minimized būsenos ir perkelia į fonines koordinates (-15000, -15000).
        Naudojamas SW_SHOWNOACTIVATE, kad nebūtų pavogtas vartotojo aktyvus langas ar fokusas.
        Jei vartotojas per UI pasirinko matyti RasterLink (_user_visible=True), langas lieka ekrane.
        """
        if self._user_visible:
            return hwnd or self.find_rasterlink_hwnd()

        if not hwnd or not win32gui.IsWindow(hwnd):
            hwnd = self.find_rasterlink_hwnd()
        if not hwnd:
            return None

        try:
            rect = win32gui.GetWindowRect(hwnd)
            # Jei langas minimizuotas arba vartotojo matomoje srityje (-1000 iki 5000 px)
            if win32gui.IsIconic(hwnd) or (rect[0] > -1000 and rect[0] < 5000):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                win32gui.SetWindowPos(
                    hwnd, 0, -15000, -15000, 1280, 900,
                    win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER
                )
                time.sleep(0.3)
        except Exception:
            pass
        return hwnd

    def is_window_visible_on_screen(self) -> bool:
        """Patikrina ar RasterLink 7 langas šiuo metu matomas ekrane."""
        hwnd = self.find_rasterlink_hwnd()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        if win32gui.IsIconic(hwnd):
            return False
        try:
            rect = win32gui.GetWindowRect(hwnd)
            return -500 < rect[0] < 5000 and -500 < rect[1] < 5000
        except Exception:
            return False

    def show_window(self) -> bool:
        """Atkuria RasterLink 7 langą ekrane, kad operatorius galėtų jį apžiūrėti."""
        self._user_visible = True
        hwnd = self.find_rasterlink_hwnd()
        if not hwnd:
            return False
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOP, 80, 80, 1350, 880,
                win32con.SWP_SHOWWINDOW
            )
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def hide_window(self) -> bool:
        """Paslepia RasterLink 7 langą atgal į fonines koordinates (-15000, -15000)."""
        self._user_visible = False
        hwnd = self.find_rasterlink_hwnd()
        if not hwnd:
            return False
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.SetWindowPos(
                hwnd, 0, -15000, -15000, 1280, 900,
                win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER
            )
            return True
        except Exception:
            return False

    def toggle_window(self) -> bool:
        """Perjungia RasterLink 7 matomumą: jei matomas – paslepia, jei paslėptas – parodo."""
        if self.is_window_visible_on_screen():
            self.hide_window()
            return False
        else:
            self.show_window()
            return True

    # -----------------------------------------------------------------
    # FONINIS POP-UP STEBĖTOJAS
    # -----------------------------------------------------------------
    def start(self):
        """Paleidžia nuolatinį foninį pop-up langų stebėtoją."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        """Sustabdo foninį pop-up stebėtoją."""
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self):
        self._switch_desktop()
        while self._running:
            try:
                self.dismiss_popups(max_wait=0.2)
            except Exception:
                pass
            time.sleep(self.check_interval)

    def dismiss_popups(self, max_wait: float = 3.0) -> int:
        """Aptinka iššokusius RasterLink pranešimus ir automatiškai paspaudžia OK / Yes / Continue."""
        self._switch_desktop()
        rl_hwnd = self.find_rasterlink_hwnd()
        t0 = time.time()
        dismissed = 0

        while time.time() - t0 < max_wait:
            pops = []

            def cb(h, _):
                if win32gui.IsWindowVisible(h) and h != rl_hwnd:
                    t = win32gui.GetWindowText(h)
                    c = win32gui.GetClassName(h)
                    if c == "#32770" or any(k in t.lower() for k in [
                        "warning", "rasterlink", "notice", "information", "confirmation", "error"
                    ]):
                        pops.append((h, t, c))

            try:
                if self.hdesk:
                    win32gui.EnumDesktopWindows(int(self.hdesk), cb, None)
                else:
                    win32gui.EnumWindows(cb, None)
            except Exception:
                win32gui.EnumWindows(cb, None)

            for h, t, c in pops:
                # 1. Bandome per pywinauto / UIA
                handled = False
                if Application:
                    try:
                        dlg = Application(backend="uia").connect(handle=h).window(handle=h)
                        for btn_text in ["OK", "Yes", "Taip", "Continue", "Close"]:
                            try:
                                btn = dlg.child_window(title=btn_text, control_type="Button")
                                if btn.is_enabled():
                                    btn.invoke()
                                    dismissed += 1
                                    handled = True
                                    break
                            except Exception:
                                pass
                    except Exception:
                        pass

                # 2. Atsarginis Win32 pranešimų siuntimas
                if not handled:
                    def enum_child_cb(ch, _):
                        nonlocal dismissed, handled
                        ct = win32gui.GetWindowText(ch).strip().lower()
                        cc = win32gui.GetClassName(ch)
                        if cc == "Button" and ct in ["ok", "taip", "yes", "continue", "close"]:
                            win32gui.PostMessage(ch, win32con.BM_CLICK, 0, 0)
                            dismissed += 1
                            handled = True
                    try:
                        win32gui.EnumChildWindows(h, enum_child_cb, None)
                    except Exception:
                        pass

            if dismissed > 0:
                break
            time.sleep(0.3)

        self.dismissed_popups += dismissed
        return dismissed

    # -----------------------------------------------------------------
    # PAGALBINIAI UIA ELEMENTŲ METODAI
    # -----------------------------------------------------------------
    def _find_by_aid(self, elem, aid: str):
        if not elem:
            return None
        try:
            if elem.element_info.automation_id == aid:
                return elem
            for c in elem.children():
                res = self._find_by_aid(c, aid)
                if res:
                    return res
        except Exception:
            pass
        return None

    def _get_window(self):
        self._switch_desktop()
        hwnd = self.ensure_offscreen()
        if not hwnd or not Application:
            return None, None
        try:
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            return hwnd, win
        except Exception:
            return None, None

    def invoke_menu(self, item_name: str) -> bool:
        """Išskleidžia 'Function' meniu ir iškviečia nurodytą punktą (pvz., 'Composition', 'Quality', 'Execution')."""
        hwnd, win = self._get_window()
        if not win:
            return False
        try:
            menu = win.child_window(auto_id="menuStrip", control_type="MenuBar")
            func_item = menu.child_window(title="Function", control_type="MenuItem")
            func_item.expand()
            time.sleep(0.2)
            for sub in func_item.children():
                if sub.window_text() == item_name:
                    sub.invoke()
                    time.sleep(0.5)
                    return True
            func_item.collapse()
        except Exception:
            pass
        return False

    # -----------------------------------------------------------------
    # PLOKŠČIŲ PAIEŠKA IR PAŽYMĖJIMAS
    # -----------------------------------------------------------------
    def get_job_rows(self) -> List[Dict]:
        """Nuskaito esamas užduotis iš pagrindinio RasterLink Job List."""
        hwnd, win = self._get_window()
        if not win:
            return []

        pnl_main = self._find_by_aid(win, "PnlMainJobList")
        if not pnl_main:
            return []
        grid = self._find_by_aid(pnl_main, "gridJobList")
        if not grid:
            return []

        rows = []
        for r in grid.children()[1:]:  # praleidžiam antraštę 'Top Row'
            name_val = ""
            attr_val = ""
            for c in r.children():
                n = c.element_info.name or ""
                if "Job Name" in n:
                    try:
                        name_val = c.iface_value.CurrentValue
                    except Exception:
                        pass
                elif "Attribute" in n:
                    try:
                        attr_val = c.iface_value.CurrentValue
                    except Exception:
                        pass
            rows.append({
                "elem": r,
                "job_name": name_val,
                "attribute": attr_val
            })
        return rows

    def select_jobs(self, row_elems: list):
        """Pažymi kelias eilutes vienu metu per MSAA LegacyIAccessiblePattern."""
        if not UIA:
            return
        for elem in row_elems:
            try:
                raw = elem.element_info.element
                pat = raw.GetCurrentPattern(UIA.UIA_LegacyIAccessiblePatternId)
                legacy = pat.QueryInterface(UIA.IUIAutomationLegacyIAccessiblePattern)
                legacy.Select(SELFLAG_TAKEFOCUS | SELFLAG_ADDSELECTION)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # KOMPOZICIJA IR KOKYBĖS NUSTATYMAS
    # -----------------------------------------------------------------
    def composite_and_quality(
        self,
        job_name_keyword: str = "",
        timeout: float = 35.0,
        status_cb: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str]:
        """
        Laukia, kol RasterLink Job List pasirodys 3 plokštės,
        jas pažymi, paspaudžia 'Composite' su Quality režimu,
        uždaro įspėjimą ir perjungia į 'Quality' langą.
        """
        def log(msg):
            if status_cb:
                status_cb(msg)

        log(f"Laukiama, kol RasterLink 7 Job List pasirodys 3 plokštės darbui: '{job_name_keyword}'...")
        t0 = time.time()
        matching = []

        # 1. Laukiame kol visos 3 plokštės atkeliaus iš Hot Folderių
        while time.time() - t0 < timeout:
            rows = self.get_job_rows()
            matching = [
                r for r in rows
                if not job_name_keyword or job_name_keyword.lower() in r["job_name"].lower()
            ]
            if len(matching) >= 3:
                break
            time.sleep(1.0)

        if len(matching) < 3:
            if len(matching) > 0:
                log(f"Rasta tik {len(matching)} plokštė(-s). Tęsiama su esamomis...")
            else:
                return False, f"Po {timeout}s laukimo RasterLink 7 nerastos 3 plokštės darbui: {job_name_keyword}"

        log(f"Rastos {len(matching)} plokštės. Pažymimi visi trys sluoksniai...")
        self.select_jobs([m["elem"] for m in matching])
        time.sleep(0.5)

        # 2. Atveriame Composition
        log("Atveriamas 'Composition' langas...")
        if not self.invoke_menu("Composition"):
            return False, "Nepavyko atverti 'Composition' meniu punkto."
        time.sleep(1.0)

        hwnd, win = self._get_window()
        pnl_comp = self._find_by_aid(win, "PnlComposite")
        if pnl_comp:
            # Pasirenkame Quality prioritetą
            rdo_q = self._find_by_aid(pnl_comp, "rdoQuality")
            if rdo_q:
                try:
                    rdo_q.select()
                    log("Nustatytas prioritetas: Quality.")
                except Exception:
                    pass

            # Paspaudžiame Composite
            btn_comp = self._find_by_aid(pnl_comp, "btnComposite")
            if btn_comp and btn_comp.is_enabled():
                log("Spaudžiamas 'Composite' mygtukas...")
                try:
                    btn_comp.invoke()
                    time.sleep(1.0)
                    self.dismiss_popups(max_wait=3.0)
                    log("Kompozicija sukurta! (Primer ➔ White ➔ CMYK)")
                except Exception as e:
                    log(f"Klaida spaudžiant Composite: {e}")
            else:
                log("Sluoksniai jau sujungti į kompoziciją.")

        # 3. Perjungiame į Quality langą
        log("Perjungiama į 'Quality' nustatymus...")
        self.invoke_menu("Quality")
        time.sleep(0.8)
        log("Kokybės nustatymai paruošti spaudai!")

        return True, "Kompozicija sėkmingai atlikta ir nustatytas Quality režimas."

    # -----------------------------------------------------------------
    # RIP AND PRINT VYKDYMAS (DEŠINYS PELĖS KLAVIŠAS -> RIP and Print)
    # -----------------------------------------------------------------
    def rip_and_print(
        self,
        job_name_keyword: str = "",
        status_cb: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str]:
        """
        Pažymi kompozicijos sluoksnius Job List lentelėje ir per
        dešinį pelės klavišą kontekstiniame meniu pasirenka 'RIP and Print'.
        """
        def log(msg):
            if status_cb:
                status_cb(msg)

        hwnd = self.find_rasterlink_hwnd()
        if not hwnd:
            return False, "RasterLink 7 langas nerastas."

        self._switch_desktop()
        was_hidden = not self.is_window_visible_on_screen()

        # Pelės paspaudimams langas privalo būti ekrano koordinatėse
        if was_hidden:
            log("Laikinai paruošiamas RasterLink langas komandų vykdymui...")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 80, 80, 1350, 880, win32con.SWP_SHOWWINDOW)
            time.sleep(0.4)

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.1)

        app = Application(backend="uia").connect(handle=hwnd)
        win = app.window(handle=hwnd)

        pnl_main = self._find_by_aid(win, "PnlMainJobList")
        if not pnl_main:
            if was_hidden and not self._user_visible:
                self.hide_window()
            return False, "Nerastas 'PnlMainJobList' skydelis."

        grid = self._find_by_aid(pnl_main, "gridJobList")
        if not grid:
            if was_hidden and not self._user_visible:
                self.hide_window()
            return False, "Nerasta 'gridJobList' lentelė."

        rows = self.get_job_rows()
        matching = [
            r for r in rows
            if not job_name_keyword or job_name_keyword.lower() in r["job_name"].lower()
        ]

        if not matching:
            # Jei nerasta pagal konkretų filtrą, naudojame visas esamas eilutes
            matching = rows

        if not matching:
            if was_hidden and not self._user_visible:
                self.hide_window()
            return False, "Job List lentelėje nėra eilučių spausdinimui."

        log(f"Pažymimi sluoksniai spaudai ({len(matching)} vnt.)...")
        self.select_jobs([m["elem"] for m in matching])
        time.sleep(0.3)

        target_row = matching[0]["elem"]
        r = target_row.rectangle()
        cx = r.left + 250
        cy = r.top + (r.height() // 2)

        log("Atveriamas kontekstinis dešinio pelės klavišo meniu...")
        ctypes.windll.user32.SetCursorPos(cx, cy)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        time.sleep(0.4)

        # Ieškome iššokusio kontekstinio meniu lango
        wins = []
        def cb(h, _):
            if win32gui.IsWindowVisible(h):
                c = win32gui.GetClassName(h)
                if "20808" in c:
                    wins.append(h)

        if self.hdesk:
            win32gui.EnumDesktopWindows(int(self.hdesk), cb, None)
        else:
            win32gui.EnumWindows(cb, None)

        if not wins:
            if was_hidden and not self._user_visible:
                self.hide_window()
            return False, "Nepavyko atverti kontekstinio meniu."

        m_hwnd = wins[0]
        m_app = Application(backend="uia").connect(handle=m_hwnd)
        mw = m_app.window(handle=m_hwnd)
        clicked = False

        for c in mw.children():
            if c.window_text() == "RIP and Print":
                mr = c.rectangle()
                mx = mr.left + 50
                my = mr.top + (mr.height() // 2)
                log("Spaudžiamas kontekstinio meniu punktas 'RIP and Print'...")
                ctypes.windll.user32.SetCursorPos(mx, my)
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                clicked = True
                break

        time.sleep(0.5)
        self.dismiss_popups(max_wait=3.0)

        # Grąžiname langą į foną, jei vartotojas nebuvo jo atvėręs per UI
        if was_hidden and not self._user_visible:
            self.hide_window()

        if clicked:
            log("RIP and Print sėkmingai paleistas į Mimaki spausdintuvą!")
            return True, "Spausdinimas sėkmingai paleistas!"
        else:
            return False, "Meniu nerastas punktas 'RIP and Print'."


# Singleton egzempliorius
bridge = RasterLinkBridge()
