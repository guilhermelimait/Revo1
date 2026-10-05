"""Local app targets and their Windows shell icons; paths never go to the knob."""

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np
from PIL import Image

SLOTS = 7
ICON_SIZE = 64
ICON_BYTES = ICON_SIZE * ICON_SIZE * 3
TARGET_TYPES = (".exe", ".lnk", ".appref-ms")
SHELL_PREFIX = "shell:AppsFolder\\"
TECHNICAL_WORDS = (
    "administrative", "application verifier", "command prompt", "component services",
    "computer management", "control panel", "cross tools", "debuggable", "debugger",
    "developer command", "developer powershell", "device manager", "disk cleanup",
    "documentation", "event viewer", "faq", "help", "hyper-v", "inno setup",
    "license", "manuals", "memory diagnostic", "odbc", "performance monitor",
    "powershell", "registry", "release notes", "resource monitor", "revision history",
    "system configuration", "system information", "task scheduler", "uninstall",
    "windows kits", "windows sdk", "windows update", "support center",
    "defragment", "disk clean", "install additional tools", "diagnostics",
    "language preferences", "report a problem", "visual studio installer",
    "reset preferences", "windows app cert", "windows software development kit",
    "firewall with advanced",
)
TECHNICAL_NAMES = ("administrative tools", "character map", "dfrgui", "disk defragmenter",
                   "nvm", "settings", "terminal", "windows terminal", "windows security")
TECHNICAL_NAMES += ("git bash", "git cmd", "git gui", "pageant", "psftp", "puttygen",
                    "recovery drive", "recoverydrive", "run", "services",
                    "steps recorder", "windows tools", "vlc media player skinned")


@dataclass(frozen=True)
class AppChoice:
    name: str
    path: str
    store: bool = False
    technical: bool = False


def valid_shell_target(value):
    return (isinstance(value, str) and value.startswith(SHELL_PREFIX)
            and 0 < len(value[len(SHELL_PREFIX):]) <= 1024
            and all(ord(ch) >= 32 for ch in value))


def valid_target(value):
    return (valid_shell_target(value) or
            (isinstance(value, str) and Path(value).is_absolute()
             and Path(value).suffix.lower() in TARGET_TYPES))


def technical_app(name, path=""):
    name = name.casefold()
    return (name in TECHNICAL_NAMES or any(word in name for word in TECHNICAL_WORDS)
            or name.startswith(("python ", "idle ", "pydoc ", "node.js", "msbuild "))
            or Path(path).suffix.lower() in (".chm", ".htm", ".html", ".url"))


def _apps_folder():
    from comtypes import COMError
    from comtypes.client import CreateObject
    try:
        folder = CreateObject("Shell.Application", dynamic=True).NameSpace("shell:AppsFolder")
        if not folder:
            raise OSError("Windows could not open its installed-app catalog.")
        return folder
    except COMError as exc:
        raise OSError(f"Windows could not read its installed-app catalog: {exc}") from exc


def valid_slots(value):
    return (isinstance(value, list) and len(value) == SLOTS
            and all(item is None or
                    (isinstance(item, dict) and set(item) == {"name", "path"}
                     and isinstance(item["name"], str) and 0 < len(item["name"]) <= 80
                     and valid_target(item["path"]))
                    for item in value))


def target(path):
    if valid_shell_target(path):
        from comtypes import COMError
        try:
            item = _apps_folder().ParseName(path[len(SHELL_PREFIX):])
            if not item:
                raise FileNotFoundError("This app is no longer installed. Choose another app.")
            return {"name": str(item.Name)[:80], "path": path}
        except COMError as exc:
            raise OSError(f"Windows could not find this installed app: {exc}") from exc
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in TARGET_TYPES:
        raise ValueError("Choose an application (.exe) or a Windows app shortcut (.lnk).")
    return {"name": path.stem[:80], "path": str(path)}


def start_menu_apps():
    roots = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
             Path(os.environ["PROGRAMDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    found = {}
    for root in roots:
        if root.exists():
            for path in root.rglob("*.lnk"):
                found[str(path).casefold()] = (path.stem, str(path))
    return sorted(found.values(), key=lambda item: (item[0].casefold(), item[1].casefold()))


def installed_apps():
    """AppsFolder includes Store apps, desktop apps and installed browser apps."""
    from comtypes import COMError
    found = {}
    try:
        items = _apps_folder().Items()
        for index in range(items.Count):
            item = items.Item(index)
            name = str(item.Name)
            identifier = item.ExtendedProperty("System.AppUserModel.ID")
            if not name or not isinstance(identifier, str) or not identifier:
                continue
            path = SHELL_PREFIX + identifier
            if valid_shell_target(path):
                found[name.casefold()] = AppChoice(name, path, "!" in identifier,
                                                   technical_app(name, str(item.Path)))
    except COMError as exc:
        raise OSError(f"Windows could not list its installed apps: {exc}") from exc
    for name, path in start_menu_apps():
        found.setdefault(name.casefold(), AppChoice(name, path, False, technical_app(name, path)))
    return sorted(found.values(), key=lambda item: item.name.casefold())


def launch(item):
    checked = target(item["path"])
    os.startfile(checked["path"])


def shell_icon(path):
    """Draw the shell's icon into a top-down DIB, releasing every GDI handle."""
    class SHFILEINFO(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                    ("dwAttributes", wintypes.DWORD), ("szDisplayName", wintypes.WCHAR * 260),
                    ("szTypeName", wintypes.WCHAR * 80)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    common = ctypes.WinDLL("comctl32", use_last_error=True)
    shell.SHGetFileInfoW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(SHFILEINFO), wintypes.UINT, wintypes.UINT]
    shell.SHGetFileInfoW.restype = ctypes.c_size_t
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER),
                                   wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    user.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT,
                               wintypes.HBRUSH, wintypes.UINT]
    user.DestroyIcon.argtypes = [wintypes.HICON]
    common.ImageList_GetIcon.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.UINT]
    common.ImageList_GetIcon.restype = wintypes.HICON
    info = SHFILEINFO()
    shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    shell.SHParseDisplayName.restype = ctypes.c_long
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    pidl = ctypes.c_void_p()
    result = shell.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
    if result < 0 or not pidl.value:
        raise OSError(f"Windows could not locate the app icon (HRESULT {result:#x}).")
    try:
        image_list = shell.SHGetFileInfoW(pidl, 0, ctypes.byref(info), ctypes.sizeof(info), 0x4008)
    finally:
        ole.CoTaskMemFree(pidl)
    if not image_list:
        raise OSError(f"Windows could not read the icon for {Path(path).name}")
    info.hIcon = common.ImageList_GetIcon(image_list, info.iIcon, 1)
    if not info.hIcon:
        raise OSError(f"Windows could not draw the icon for {Path(path).name}")
    dc = bitmap = previous = None
    try:
        dc = gdi.CreateCompatibleDC(None)
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), ICON_SIZE, -ICON_SIZE,
                                  1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0)
        if not dc or not bitmap or not pixels.value:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = gdi.SelectObject(dc, bitmap)
        composites = []
        for value in (0, 255):
            background = bytes((value, value, value, 255)) * (ICON_SIZE * ICON_SIZE)
            ctypes.memmove(pixels, background, len(background))
            if not user.DrawIconEx(dc, 0, 0, info.hIcon, ICON_SIZE, ICON_SIZE, 0, None, 3):
                raise ctypes.WinError(ctypes.get_last_error())
            raw = ctypes.string_at(pixels, len(background))
            composites.append(Image.frombytes("RGB", (ICON_SIZE, ICON_SIZE), raw, "raw", "BGRX"))
        return transparent_icon(*composites)
    finally:
        if previous:
            gdi.SelectObject(dc, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        user.DestroyIcon(info.hIcon)


def transparent_icon(black, white):
    """Recover coverage from two shell composites, including legacy mask-only icons."""
    dark = np.asarray(black, dtype=np.float32)
    light = np.asarray(white, dtype=np.float32)
    alpha = np.clip(255 - np.max(light - dark, axis=2), 0, 255)
    rgb = np.divide(dark * 255, alpha[:, :, None],
                    out=np.zeros_like(dark), where=alpha[:, :, None] > 0)
    rgba = np.dstack((np.clip(np.rint(rgb), 0, 255), np.rint(alpha))).astype(np.uint8)
    return Image.fromarray(rgba)


def icon_bytes(image):
    rgba = np.asarray(image.convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS),
                      dtype=np.uint16)
    rgb = rgba[:, :, :3]
    packed = ((rgb[:, :, 0] >> 3) << 11) | ((rgb[:, :, 1] >> 2) << 5) | (rgb[:, :, 2] >> 3)
    wire = np.empty((ICON_SIZE, ICON_SIZE, 3), dtype=np.uint8)
    wire[:, :, 0] = packed >> 8
    wire[:, :, 1] = packed & 255
    wire[:, :, 2] = rgba[:, :, 3]
    return wire.tobytes()


def wire_name(name):
    text = name.encode("ascii", errors="replace")[:40]
    text = bytes(byte if 32 <= byte <= 126 else 32 for byte in text)
    return base64.b64encode(text).decode("ascii")
