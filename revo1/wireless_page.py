"""Bluetooth connection controls and one-time cable-assisted pairing."""

import tkinter as tk
from revo1 import dialogs as messagebox

from revo1 import config, secure, ui
from revo1.layout import FORM_WIDTH

LINKS = (("ble", "Bluetooth", "Bluetooth"),)
LINK_GAP = ui.HEADER_GAP
LINK_W = 240
LINK_H = ui.CONTROL_HEIGHT
NOTE_WIDTH = FORM_WIDTH


def link_kind(label):
    """"usb" or "ble" for the label a bridge connection reports."""
    return "ble" if label == "Bluetooth" else "usb"


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
        self.bluetooth_status = "idle"
        self.bridge.set_wireless(self.link_key, self.settings["knob_ble"])
        self.bridge.set_bluetooth(self.settings["bluetooth_enabled"])

    def build_wireless_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        row = tk.Frame(body, bg=ui.MAIN_BG)
        row.pack(anchor="w")
        self.link_tiles = []
        for key, icon, title in LINKS:
            tile = ui.Picture(row, ui.MAIN_BG)
            tile.pack(side="left", padx=(0, 0 if key == "ble" else k.px(LINK_GAP)))
            self.link_tiles.append((tile, key, icon, title))
        self.pair_actions = tk.Frame(row, bg=ui.MAIN_BG)
        self.pair_actions.pack(side="left", padx=(k.px(ui.GAP), 0))
        self.wireless_summary = ui.Picture(body, ui.MAIN_BG)
        self.wireless_summary.pack(anchor="w", pady=(k.px(ui.GAP), 0))
        self.pair_note = ui.Picture(body, ui.MAIN_BG)
        self.refresh_wireless()

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
        """(state line, ready) for one of the link tiles."""
        active = self.connected and self.link_kind == key
        paired = self.pair_state() == "paired"
        if not paired:
            return "Setup required", False
        if active:
            return "Connected", True
        if self.settings["bluetooth_enabled"] and self.bluetooth_status == "connecting":
            return "Connecting...", True
        return "Disconnected", False

    def paint_link_tile(self, key, icon, title):
        k = self.kit
        image = k.canvas(LINK_W, LINK_H, ui.MAIN_BG)
        active = self.connected and self.link_kind == key
        detail, ready = self.link_detail(key)
        k.icon(image, icon, 12, LINK_H / 2, ui.OK_GREEN if active else ui.SUBTLE_INK, 0.55)
        k.text(image, 30, LINK_H / 2, title, "semibold", ui.TEXT_BUTTON, ui.INK)
        k.dot(image, 126, LINK_H / 2, 3, ui.OK_GREEN if active or ready else ui.IDLE_GREY)
        k.text(image, 137, LINK_H / 2, detail, "regular", ui.TEXT_DETAIL, ui.SUBTLE_INK,
               width=LINK_W - 137)
        return image

    def paint_wireless_summary(self):
        k = self.kit
        state = self.pair_state()
        if state == "paired":
            ink = ui.OK_GREEN
            text = "Paired to this PC. Encrypted connection."
        elif state == "mismatch":
            ink = ui.ERROR_INK
            text = "Pairing does not match. Connect the cable and choose Connect to set it up again."
        elif state == "knob_only":
            ink = ui.ERROR_INK
            text = "The knob forgot this PC. Connect the cable and choose Connect to pair again."
        else:
            ink = ui.MUTED_INK
            text = "Connect the cable once, then choose Connect to set up Bluetooth."
        lines = k.wrap(text, "regular", ui.TEXT_BODY, NOTE_WIDTH - 24)
        image = k.canvas(NOTE_WIDTH, len(lines) * ui.TEXT_LINE, ui.MAIN_BG)
        k.icon(image, "Lock", 7, 11, ink, 0.45)
        for index, line in enumerate(lines):
            k.text(image, 24, index * 22 + 11, line, "regular", 9.5,
                   ui.SUBTLE_INK if state == "paired" else ink)
        return image

    def paint_pair_note(self):
        k = self.kit
        text, error = self.wireless_note or ("", False)
        lines = k.wrap(text, "regular", ui.TEXT_BODY, NOTE_WIDTH - 4)
        image = k.canvas(NOTE_WIDTH, len(lines) * ui.TEXT_LINE, ui.MAIN_BG)
        for index, line in enumerate(lines):
            k.text(image, 2, index * 22 + 11, line, "regular", ui.TEXT_BODY,
                   ui.ERROR_INK if error else ui.OK_GREEN)
        return image

    def refresh_wireless(self):
        if not hasattr(self, "link_tiles"):
            return
        for tile, key, icon, title in self.link_tiles:
            tile.show(self.paint_link_tile(key, icon, title))
        self.wireless_summary.show(self.paint_wireless_summary())
        text, error = self.wireless_note or ("", False)
        if text and (error or self.pairing or self.pair_state() != "paired"):
            self.pair_note.show(self.paint_pair_note())
            self.pair_note.pack(anchor="w", pady=(self.kit.px(ui.GAP), 0))
        else:
            self.pair_note.pack_forget()
        for child in self.pair_actions.winfo_children():
            child.destroy()
        busy = self.pairing is not None
        active = self.connected and self.link_kind == "ble"
        connecting = self.settings["bluetooth_enabled"] and self.bluetooth_status == "connecting"
        label = "Setting up..." if busy else ("Disconnect" if active or connecting else "Connect")
        command = self.disconnect_bluetooth if active or connecting else self.connect_bluetooth
        actions = [(label, command, not active, not busy)]
        widths = self.button_widths([self.pill_width(action[0]) for action in actions])
        buttons = []
        for (text, command, primary, enabled), width in zip(actions, widths):
            button = ui.Button(
                self.pair_actions, ui.MAIN_BG,
                lambda hover, text=text, primary=primary, enabled=enabled, width=width:
                    self.paint_pill(text, hover, primary, enabled, width, height=40),
                command if enabled else (lambda: None))
            if not enabled:
                button.config(cursor="arrow", takefocus=False)
            else:
                button.keyboard_access()
            buttons.append(button)
        self.pack_row(buttons)

    # ----- actions ----------------------------------------------------------

    def connect_bluetooth(self):
        self.settings["bluetooth_enabled"] = True
        config.save(self.settings)
        self.wireless_note = None
        if self.pair_state() != "paired":
            self.pair_knob()
        else:
            self.bluetooth_status = "connecting"
            self.bridge.set_bluetooth(True, prefer=True)
            self.refresh_wireless()

    def disconnect_bluetooth(self):
        self.settings["bluetooth_enabled"] = False
        config.save(self.settings)
        self.bluetooth_status = "idle"
        self.wireless_note = ("Bluetooth disconnected. Choose Connect to reconnect.", False)
        self.bridge.set_bluetooth(False)
        self.refresh_wireless()

    def pair_knob(self):
        if self.pairing:
            return
        if not (self.connected and self.link_kind == "usb"):
            self.wireless_note = ("Connect the knob with the USB cable to pair it.", True)
            self.refresh_wireless()
            return
        self.pairing = "pair"
        self.wireless_note = None
        self.bridge.pair(secure.new_key())
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

    def store_pairing(self, key):
        self.link_key = key
        self.settings["link_key"] = secure.protect_key(key) if key else ""
        if key is None:
            self.settings["knob_ble"] = ""
        config.save(self.settings)
        self.bridge.set_wireless(key, self.settings["knob_ble"])

    def on_wireless_event(self, kind, payload):
        if kind == "net":
            changed = payload != self.knob_net
            self.knob_net = payload
            if changed:
                self.refresh_wireless()
        elif kind == "pair_done":
            self.pairing = None
            if payload is None:
                self.store_pairing(None)
                self.wireless_note = ("The knob and this PC forgot each other.", False)
            else:
                self.store_pairing(payload)
                self.bluetooth_status = "connecting"
                self.bridge.set_bluetooth(True, prefer=True)
                self.wireless_note = ("Paired. Connecting over Bluetooth...", False)
            self.refresh_wireless()
        elif kind == "pair_error":
            self.pairing = None
            self.wireless_note = (payload, True)
            self.refresh_wireless()
        elif kind == "knob_seen":
            _, address = payload
            if self.settings["knob_ble"] != address:
                self.settings["knob_ble"] = address
                config.save(self.settings)
