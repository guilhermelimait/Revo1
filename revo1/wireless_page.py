"""Settings > Wireless: pair the knob once over USB, then use it over Wi-Fi or
Bluetooth whenever the cable is unplugged. The link is end-to-end encrypted
with a key only this PC and the knob hold."""

import re
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

from revo1 import config, secure, ui
from revo1.layout import CARD_WIDTH, PANEL_BG

LINKS = (("usb", "Usb", "USB cable"), ("wifi", "Wifi", "Wi-Fi"),
         ("ble", "Bluetooth", "Bluetooth"))
LINK_GAP = 12
LINK_W = (CARD_WIDTH - 2 * LINK_GAP) // 3
LINK_H = 72
FIELD_GAP = 12
# One short of half, so rounding at any display scale keeps both borders.
FIELD_W = (CARD_WIDTH - FIELD_GAP) // 2 - 1
WIFI_TEXT = {"off": "Off", "connecting": "Joining {ssid}\u2026",
             "connected": "On {ssid}", "bad_password": "Wrong password",
             "not_found": "Can't find {ssid}"}
ERROR_RED = "#C8373D"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def link_kind(label):
    """"usb", "wifi" or "ble" for the label a bridge connection reports."""
    if label.startswith("Wi-Fi"):
        return "wifi"
    if label == "Bluetooth":
        return "ble"
    return "usb"


def current_ssid():
    """The Wi-Fi network this PC is on, or "" (wired, or Wi-Fi is off)."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=5, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.MULTILINE)
    return match.group(1) if match else ""


class WirelessTab:
    def init_wireless(self):
        """Before the bridge starts: hands it the stored key."""
        self.link_key = secure.unprotect_key(self.settings["link_key"])
        if self.settings["link_key"] and not self.link_key:
            # Stored by another Windows user or machine; it can't be used here.
            self.settings["link_key"] = ""
        self.link_kind = None
        self.knob_net = None
        self.pairing = None
        self.wireless_note = None
        self.bridge.set_wireless(self.link_key, self.settings["wireless"],
                                 self.settings["knob_ip"], self.settings["knob_ble"])

    def build_wireless_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        self.caption(body, "CONNECTION").pack(anchor="w")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        self.link_tiles = []
        for key, icon, title in LINKS:
            tile = ui.Picture(row, PANEL_BG)
            tile.pack(side="left", padx=(0, 0 if key == "ble" else k.px(LINK_GAP)))
            self.link_tiles.append((tile, key, icon, title))
        self.wireless_summary = ui.Picture(body, PANEL_BG)
        self.wireless_summary.pack(anchor="w", pady=(k.px(10), 0))
        self.wireless_toggle = ui.Button(
            body, PANEL_BG,
            lambda hover: self.paint_toggle(
                self.settings["wireless"], "Use wireless when the cable is unplugged",
                "USB always takes over as soon as it is plugged in", hover),
            self.toggle_wireless)
        self.wireless_toggle.pack(anchor="w", pady=(k.px(12), 0))

        body = self.section(tab)
        self.caption(body, "PAIR OVER USB").pack(anchor="w")
        fields = tk.Frame(body, bg=PANEL_BG)
        fields.pack(anchor="w", pady=(k.px(6), 0))
        self.ssid_entry = self.wireless_field(fields, "Wi-Fi network", 0)
        self.password_entry = self.wireless_field(fields, "Password", 1, secret=True)
        self.ssid_entry.insert(0, self.settings["wifi_ssid"])
        self.password_entry.bind("<Return>", lambda event: self.pair_knob())
        hint = ui.Picture(body, PANEL_BG)
        image = k.canvas(CARD_WIDTH, 34, PANEL_BG)
        k.text(image, 0, 9, "Leave the network empty to use Bluetooth only. The knob "
               "needs a 2.4 GHz network.", "regular", 8.5, ui.MUTED_INK, width=CARD_WIDTH)
        k.text(image, 0, 26, "The password goes to the knob over the cable and is never "
               "saved on this PC.", "regular", 8.5, ui.MUTED_INK, width=CARD_WIDTH)
        hint.show(image)
        hint.pack(anchor="w", pady=(k.px(8), 0))
        self.pair_actions = tk.Frame(body, bg=PANEL_BG)
        self.pair_actions.pack(anchor="w", pady=(k.px(12), 0))
        self.pair_note = ui.Picture(body, PANEL_BG)
        self.pair_note.pack(anchor="w", pady=(k.px(8), 0))
        if not self.settings["wifi_ssid"]:
            threading.Thread(target=self.detect_ssid, name="ssid", daemon=True).start()
        self.refresh_wireless()

    def wireless_field(self, parent, label, column, secret=False):
        k = self.kit
        cell = tk.Frame(parent, bg=PANEL_BG)
        cell.grid(row=0, column=column, padx=(0, k.px(FIELD_GAP)) if column == 0 else 0)
        title = ui.Picture(cell, PANEL_BG)
        image = k.canvas(FIELD_W, 18, PANEL_BG)
        k.text(image, 0, 9, label, "semibold", 9, ui.SUBTLE_INK)
        title.show(image)
        title.pack(anchor="w")
        # The white box carries the border so the text can sit inset from it.
        box = tk.Frame(cell, bg="#FFFFFF", width=k.px(FIELD_W), height=k.px(34),
                       highlightthickness=1, highlightbackground=ui.CARD_EDGE)
        box.pack_propagate(False)
        box.pack(anchor="w", pady=(k.px(4), 0))
        entry = tk.Entry(box, font=(ui.TK_FAMILY, 11), bg="#FFFFFF", fg=ui.INK,
                         relief="flat", highlightthickness=0, insertbackground=ui.INK,
                         show="\u2022" if secret else "")
        entry.pack(fill="both", expand=True, padx=k.px(10))
        entry.bind("<FocusIn>", lambda event: box.config(highlightbackground=ui.SUBTLE_INK))
        entry.bind("<FocusOut>", lambda event: box.config(highlightbackground=ui.CARD_EDGE))
        return entry

    def detect_ssid(self):
        ssid = current_ssid()
        if ssid:
            self.events.put(("ssid", ssid))

    # ----- state ------------------------------------------------------------

    def knob_key_id(self):
        return self.knob_net["key_id"] if self.knob_net else None

    def pair_state(self):
        """"paired", "mismatch" (the knob holds another key), "knob_only",
        or "none"."""
        ours = secure.key_id(self.link_key) if self.link_key else ""
        theirs = self.knob_key_id()
        if theirs is None:
            return "paired" if ours else "none"
        if ours and theirs == ours:
            return "paired"
        if theirs:
            return "mismatch"
        return "knob_only" if ours else "none"

    def link_detail(self, key):
        """(state line, ready) for one of the three link tiles."""
        active = self.connected and self.link_kind == key
        paired = self.pair_state() == "paired"
        if key == "usb":
            return ("In use" if active else "Unplugged"), active
        if not paired:
            return "Not set up", False
        if key == "ble":
            return ("In use" if active else "Ready"), True
        ssid = self.settings["wifi_ssid"]
        if not ssid:
            return "Not set up", False
        if active:
            return f"In use \u00b7 {self.settings['knob_ip']}", True
        if self.knob_net and self.connected:
            text = WIFI_TEXT[self.knob_net["wifi"]].format(ssid=ssid)
            return text, self.knob_net["wifi"] == "connected"
        return "Ready", True

    def paint_link_tile(self, key, icon, title):
        k = self.kit
        image = k.canvas(LINK_W, LINK_H, PANEL_BG)
        active = self.connected and self.link_kind == key
        detail, ready = self.link_detail(key)
        if active:
            k.rounded(image, (0, 0, LINK_W, LINK_H), 12, ui.INK)
            ink, sub = "#FFFFFF", "#C8C8D2"
        else:
            k.rounded(image, (0, 0, LINK_W, LINK_H), 12, ui.CARD_BG, ui.CARD_EDGE)
            ink, sub = ui.INK, ui.MUTED_INK
        k.icon(image, icon, 30, LINK_H / 2, ink if active or ready else ui.IDLE_GREY, 0.7)
        k.text(image, 54, 27, title, "semibold", 10, ink, width=LINK_W - 64)
        warn = detail in ("Wrong password",) or detail.startswith("Can't find")
        if not active:
            k.dot(image, 58, 47, 3, ui.OK_GREEN if ready else
                  (ERROR_RED if warn else ui.IDLE_GREY))
        k.text(image, 54 if active else 66, 47, detail, "regular", 8.5,
               ERROR_RED if warn and not active else sub,
               width=LINK_W - (64 if active else 76))
        return image

    def paint_wireless_summary(self):
        k = self.kit
        image = k.canvas(CARD_WIDTH, 20, PANEL_BG)
        state = self.pair_state()
        if state == "paired":
            ink = ui.OK_GREEN
            text = (f"End-to-end encrypted with AES-256-GCM \u00b7 key "
                    f"{secure.key_id(self.link_key)}")
        elif state == "mismatch":
            ink = ERROR_RED
            text = (f"The knob is paired with another key ({self.knob_key_id()}). "
                    "Pair it again below to use it wirelessly from this PC.")
        elif state == "knob_only":
            ink = ERROR_RED
            text = "The knob forgot this PC. Pair it again below."
        else:
            ink = ui.MUTED_INK
            text = "Not paired yet. Plug in the cable and pair once below."
        k.icon(image, "Lock", 7, 10, ink, 0.45)
        k.text(image, 20, 10, text, "regular", 9, ui.SUBTLE_INK if state == "paired"
               else ink, width=CARD_WIDTH - 20)
        return image

    def paint_pair_note(self):
        k = self.kit
        image = k.canvas(CARD_WIDTH, 18, PANEL_BG)
        if self.wireless_note:
            text, error = self.wireless_note
            k.text(image, 0, 9, text, "regular", 9, ERROR_RED if error else ui.OK_GREEN,
                   width=CARD_WIDTH)
        return image

    def refresh_wireless(self):
        if not hasattr(self, "link_tiles"):
            return
        for tile, key, icon, title in self.link_tiles:
            tile.show(self.paint_link_tile(key, icon, title))
        self.wireless_summary.show(self.paint_wireless_summary())
        self.wireless_toggle.refresh()
        self.pair_note.show(self.paint_pair_note())
        for child in self.pair_actions.winfo_children():
            child.destroy()
        usb = self.connected and self.link_kind == "usb"
        paired = self.pair_state() == "paired"
        busy = self.pairing is not None
        if busy:
            label = "Pairing\u2026" if self.pairing == "pair" else "Forgetting\u2026"
        else:
            label = (("Update Wi-Fi" if self.settings["wifi_ssid"] else "Set up Wi-Fi")
                     if paired else "Pair over USB")
        actions = [(label, self.pair_knob, True, usb and not busy)]
        if self.link_key or self.knob_key_id():
            actions.append(("Forget pairing", self.forget_pairing, False, not busy))
        widths = self.fill_widths([self.pill_width(action[0]) for action in actions])
        buttons = []
        for (text, command, primary, enabled), width in zip(actions, widths):
            button = ui.Button(
                self.pair_actions, PANEL_BG,
                lambda hover, text=text, primary=primary, enabled=enabled, width=width:
                    self.paint_pill(text, hover, primary, enabled, width, height=34),
                command if enabled else (lambda: None))
            if not enabled:
                button.config(cursor="arrow")
            buttons.append(button)
        self.pack_row(buttons)

    # ----- actions ----------------------------------------------------------

    def toggle_wireless(self):
        self.settings["wireless"] = not self.settings["wireless"]
        config.save(self.settings)
        self.bridge.set_wireless(self.link_key, self.settings["wireless"])
        self.refresh_wireless()

    def pair_knob(self):
        if self.pairing:
            return
        if not (self.connected and self.link_kind == "usb"):
            self.wireless_note = ("Connect the knob with the USB cable to pair it.", True)
            self.refresh_wireless()
            return
        ssid = self.ssid_entry.get().strip()
        password = self.password_entry.get()
        if len(ssid.encode("utf-8")) > 32:
            self.wireless_note = ("The network name is too long (32 bytes at most).", True)
        elif password and not 8 <= len(password.encode("utf-8")) <= 63:
            self.wireless_note = ("Wi-Fi passwords are 8 to 63 characters long.", True)
        else:
            # Keeps the key when only the network changes, so other links stay valid.
            key = self.link_key if self.pair_state() == "paired" else secure.new_key()
            self.pairing = "pair"
            self.pair_ssid = ssid
            self.wireless_note = None
            self.bridge.pair(key, ssid, password)
        self.refresh_wireless()

    def forget_pairing(self):
        if self.pairing:
            return
        if self.connected and self.link_kind == "usb":
            self.pairing = "unpair"
            self.wireless_note = None
            self.bridge.unpair()
        elif messagebox.askyesno(
                "Forget pairing",
                "The knob isn't connected with the cable, so only this PC forgets the "
                "pairing. The knob keeps its key until you forget it with the cable "
                "plugged in.\n\nForget it on this PC?", parent=self.root):
            self.store_pairing(None)
            self.wireless_note = ("Forgotten on this PC.", False)
        self.refresh_wireless()

    def store_pairing(self, key, ssid=None):
        self.link_key = key
        self.settings["link_key"] = secure.protect_key(key) if key else ""
        if key is None:
            self.settings["knob_ip"] = ""
            self.settings["knob_ble"] = ""
        if ssid is not None:
            self.settings["wifi_ssid"] = ssid
        config.save(self.settings)
        self.bridge.set_wireless(key, self.settings["wireless"],
                                 self.settings["knob_ip"], self.settings["knob_ble"])

    def on_wireless_event(self, kind, payload):
        if kind == "net":
            changed = payload != self.knob_net
            self.knob_net = payload
            if payload["ip"] and payload["ip"] != self.settings["knob_ip"]:
                self.settings["knob_ip"] = payload["ip"]
                config.save(self.settings)
                self.bridge.set_wireless(self.link_key, self.settings["wireless"],
                                         payload["ip"])
            if changed:
                self.refresh_wireless()
        elif kind == "pair_done":
            action, self.pairing = self.pairing, None
            if payload is None:
                self.store_pairing(None)
                self.wireless_note = ("The knob and this PC forgot each other.", False)
            else:
                self.store_pairing(payload, self.pair_ssid)
                self.password_entry.delete(0, "end")
                where = (f"It joins {self.pair_ssid} and also works over Bluetooth."
                         if self.pair_ssid else "It works over Bluetooth.")
                self.wireless_note = (("Wi-Fi updated. " if action == "pair" and
                                       self.knob_net and self.knob_net["key_id"] ==
                                       secure.key_id(payload) else "Paired. ") + where, False)
            self.refresh_wireless()
        elif kind == "pair_error":
            self.pairing = None
            self.wireless_note = (payload, True)
            self.refresh_wireless()
        elif kind == "knob_seen":
            link, address = payload
            setting = "knob_ip" if link == "wifi" else "knob_ble"
            if self.settings[setting] != address:
                self.settings[setting] = address
                config.save(self.settings)
        elif kind == "ssid":
            if not self.ssid_entry.get().strip() and not self.settings["wifi_ssid"]:
                self.ssid_entry.insert(0, payload)
