"""Settings > Wireless: pair the knob once over USB, then use it over
Bluetooth whenever the cable is unplugged. The link is end-to-end encrypted
with a key only this PC and the knob hold."""

import tkinter as tk
from tkinter import messagebox

from revo1 import config, secure, ui
from revo1.layout import CARD_WIDTH, PANEL_BG

LINKS = (("usb", "Usb", "USB cable"), ("ble", "Bluetooth", "Bluetooth"))
LINK_GAP = 12
LINK_W = 236
LINK_H = 64
ERROR_RED = "#C8373D"


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
        self.bridge.set_wireless(self.link_key, self.settings["knob_ble"])

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
        auto = ui.Picture(body, PANEL_BG)
        image = k.canvas(CARD_WIDTH, 18, PANEL_BG)
        k.text(image, 0, 9, "With the cable unplugged, Revo1 finds the knob over "
               "Bluetooth on its own. USB takes over as soon as it is plugged in.",
               "regular", 8.5, ui.MUTED_INK, width=CARD_WIDTH)
        auto.show(image)
        auto.pack(anchor="w", pady=(k.px(8), 0))

        body = self.section(tab)
        self.caption(body, "PAIR OVER USB").pack(anchor="w")
        hint = ui.Picture(body, PANEL_BG)
        image = k.canvas(CARD_WIDTH, 34, PANEL_BG)
        k.text(image, 0, 9, "Pairing gives this PC and the knob one shared key, once, over "
               "the cable.", "regular", 8.5, ui.MUTED_INK, width=CARD_WIDTH)
        k.text(image, 0, 26, "No passwords are involved and the key never leaves either "
               "device.", "regular", 8.5, ui.MUTED_INK, width=CARD_WIDTH)
        hint.show(image)
        hint.pack(anchor="w", pady=(k.px(6), 0))
        self.pair_actions = tk.Frame(body, bg=PANEL_BG)
        self.pair_actions.pack(anchor="w", pady=(k.px(12), 0))
        self.pair_note = ui.Picture(body, PANEL_BG)
        self.pair_note.pack(anchor="w", pady=(k.px(8), 0))
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
        if key == "usb":
            return ("In use" if active else "Unplugged"), active
        if not paired:
            return "Not set up", False
        return ("In use" if active else "Ready"), True

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
        k.text(image, 54, 23, title, "semibold", 10, ink, width=LINK_W - 64)
        if not active:
            k.dot(image, 58, 43, 3, ui.OK_GREEN if ready else ui.IDLE_GREY)
        k.text(image, 54 if active else 66, 43, detail, "regular", 8.5, sub,
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
        self.pair_note.show(self.paint_pair_note())
        for child in self.pair_actions.winfo_children():
            child.destroy()
        usb = self.connected and self.link_kind == "usb"
        paired = self.pair_state() == "paired"
        busy = self.pairing is not None
        if busy:
            label = "Pairing\u2026" if self.pairing == "pair" else "Forgetting\u2026"
        else:
            label = "Pair again" if paired else "Pair over USB"
        actions = [(label, self.pair_knob, not paired, usb and not busy)]
        if self.link_key or self.knob_key_id():
            actions.append(("Forget pairing", self.forget_pairing, False, not busy))
        widths = self.button_widths([self.pill_width(action[0]) for action in actions])
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
                self.wireless_note = ("Paired. It works over Bluetooth when the cable is "
                                      "unplugged.", False)
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
