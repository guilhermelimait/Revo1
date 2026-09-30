"""A notification-area (system tray) icon, using the Win32 API directly.

A hidden window on its own thread owns the icon and receives its clicks. It
also lets a second launch of the app ask this one to show itself, even while
the main window is hidden in the tray.
"""

import ctypes
import threading
from ctypes import wintypes

WINDOW_CLASS = "RoundScreenTray"
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_SET_VISIBLE = WM_APP + 2
# Posted by a second instance of the app: "show the window".
WM_ACTIVATE_APP = WM_APP + 3
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
NOTIFYICON_VERSION_4 = 4
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
LR_DEFAULTSIZE = 0x40
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
MENU_OPEN, MENU_QUIT = 1, 2

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                  wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                               wintypes.LPCWSTR]
user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                               wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def activate_running_instance():
    """Asks an already running RoundScreen to show its window. Returns False
    when there is none to ask."""
    window = user32.FindWindowW(WINDOW_CLASS, None)
    # Lets the running copy take the foreground, which this launch owns.
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    return bool(window) and bool(user32.PostMessageW(window, WM_ACTIVATE_APP, 0, 0))


class TrayIcon:
    """`on_open` and `on_quit` are called on the tray thread, so they should
    only hand the request over (e.g. put it on a queue)."""

    def __init__(self, tooltip, icon_path, on_open, on_quit):
        self.tooltip = tooltip[:127]
        self.icon_path = str(icon_path)
        self.on_open = on_open
        self.on_quit = on_quit
        self.window = None
        self.icon = None
        self.visible = False
        self.ready = threading.Event()
        self._proc = WNDPROC(self._window_proc)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.thread = threading.Thread(target=self._run, name="tray", daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(5)

    def show(self):
        self._post(WM_SET_VISIBLE, 1)

    def hide(self):
        self._post(WM_SET_VISIBLE, 0)

    def stop(self):
        if self._post(WM_CLOSE, 0):
            self.thread.join(timeout=3)

    def _post(self, message, wparam):
        return bool(self.window) and bool(user32.PostMessageW(self.window, message, wparam, 0))

    def _data(self):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.window
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self.icon
        data.szTip = self.tooltip
        return data

    def _add(self):
        data = self._data()
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            data.uVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(data))

    def _set_visible(self, visible):
        if visible == self.visible:
            return
        self.visible = visible
        if visible:
            self._add()
        else:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data()))

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, MENU_OPEN, "Open RoundScreen")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, MENU_QUIT, "Quit")
        user32.SetMenuDefaultItem(menu, MENU_OPEN, 0)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # Without this the menu doesn't close when clicking elsewhere.
        user32.SetForegroundWindow(self.window)
        choice = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                       point.x, point.y, 0, self.window, None)
        user32.PostMessageW(self.window, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if choice == MENU_OPEN:
            self.on_open()
        elif choice == MENU_QUIT:
            self.on_quit()

    def _window_proc(self, window, message, wparam, lparam):
        if message == WM_TRAY:
            # NOTIFYICON_VERSION_4 puts the mouse message in the low word.
            event = lparam & 0xFFFF
            if event in (NIN_SELECT, NIN_KEYSELECT):
                self.on_open()
            elif event == WM_CONTEXTMENU:
                self._menu()
            return 0
        if message == WM_SET_VISIBLE:
            self._set_visible(bool(wparam))
            return 0
        if message == WM_ACTIVATE_APP:
            self.on_open()
            return 0
        if message == self._taskbar_created and self.visible:
            # Explorer restarted: put the icon back.
            self._add()
            return 0
        if message == WM_CLOSE:
            self._set_visible(False)
            user32.DestroyWindow(window)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(window, message, wparam, lparam)

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._proc
        window_class.hInstance = instance
        window_class.lpszClassName = WINDOW_CLASS
        user32.RegisterClassW(ctypes.byref(window_class))
        # A hidden top-level window (not message-only), so it also receives
        # Explorer's "TaskbarCreated" broadcast.
        self.window = user32.CreateWindowExW(0, WINDOW_CLASS, "RoundScreen tray", 0, 0, 0, 0, 0,
                                             None, None, instance, None)
        size = user32.GetSystemMetrics(49)  # SM_CXSMICON
        self.icon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size,
                                      LR_LOADFROMFILE)
        self.ready.set()
        if not self.window:
            return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        self.window = None
        if self.icon:
            user32.DestroyIcon(self.icon)
