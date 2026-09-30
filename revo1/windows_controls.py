import ctypes
from ctypes import wintypes
import threading

import comtypes
import comtypes.client
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class INPUT_DATA(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_DATA)]


def _volume():
    device = AudioUtilities.GetSpeakers()
    return device.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None
    ).QueryInterface(IAudioEndpointVolume)


def _microphone():
    device = AudioUtilities.GetMicrophone()
    return device.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None
    ).QueryInterface(IAudioEndpointVolume)


def microphone_level():
    return round(_microphone().GetMasterVolumeLevelScalar() * 100)


def change_microphone(steps):
    audio = _microphone()
    level = max(0, min(100, round(audio.GetMasterVolumeLevelScalar() * 100) + steps * 2))
    audio.SetMasterVolumeLevelScalar(level / 100, None)
    return level


def volume_level():
    return round(_volume().GetMasterVolumeLevelScalar() * 100)


def change_volume(steps):
    audio = _volume()
    level = max(0, min(100, round(audio.GetMasterVolumeLevelScalar() * 100) + steps * 2))
    audio.SetMasterVolumeLevelScalar(level / 100, None)
    return level


_wmi_local = threading.local()


def _wmi():
    """A root/wmi connection for the calling thread. COM objects belong to
    the apartment that created them, so each thread keeps its own."""
    service = getattr(_wmi_local, "service", None)
    if service is None:
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        locator = comtypes.client.CreateObject("WbemScripting.SWbemLocator", dynamic=True)
        service = locator.ConnectServer(".", "root\\wmi")
        _wmi_local.service = service
    return service


def _first(query):
    for item in _wmi().ExecQuery(query):
        return item
    return None


def brightness_level():
    monitor = _first("SELECT CurrentBrightness FROM WmiMonitorBrightness")
    if monitor is None:
        raise RuntimeError("This display does not expose Windows WMI brightness controls")
    return int(monitor.Properties_.Item("CurrentBrightness").Value)


def _set_brightness(level):
    monitor = _first("SELECT * FROM WmiMonitorBrightnessMethods")
    if monitor is None:
        raise RuntimeError("Brightness control is unavailable")
    params = monitor.Methods_.Item("WmiSetBrightness").InParameters.SpawnInstance_()
    params.Properties_.Item("Timeout").Value = 0
    params.Properties_.Item("Brightness").Value = level
    monitor.ExecMethod_("WmiSetBrightness", params)


def change_brightness(steps):
    level = max(0, min(100, brightness_level() + steps * 5))
    _set_brightness(level)
    return level


def _send_input(event):
    ctypes.set_last_error(0)
    if ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def scroll(steps):
    event = INPUT(0, INPUT_DATA(mi=MOUSEINPUT(
        0, 0, (steps * 120) & 0xFFFFFFFF, 0x0800, 0, 0)))
    _send_input(event)


def _key(key, flags=0):
    _send_input(INPUT(1, INPUT_DATA(ki=KEYBDINPUT(key, 0, flags, 0, 0))))


def key_press(key, control=False):
    if control:
        _key(0x11)
    try:
        _key(key)
        _key(key, 0x0002)
    finally:
        if control:
            _key(0x11, 0x0002)


def zoom(steps):
    for _ in range(min(abs(steps), 20)):
        key_press(0xBB if steps > 0 else 0xBD, control=True)


def media(steps):
    for _ in range(min(abs(steps), 20)):
        key_press(0xB0 if steps > 0 else 0xB1)
