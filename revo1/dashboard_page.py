"""The Dashboard: every screen the knob can show, its live value, and a
switch to keep it on or off the knob's menu."""

import tkinter as tk

from revo1 import config, dial, pomodoro, ui
from revo1.layout import CARD_WIDTH

TILE_GAP = 10
TILE_COLUMNS = 3
TILE_WIDTH = (CARD_WIDTH - TILE_GAP * (TILE_COLUMNS - 1)) // TILE_COLUMNS
TILE_HEIGHT = 84
# The switch in a tile's top-right corner, in layout units from that corner.
SWITCH_W, SWITCH_H = 34, 20
LEVEL_REFRESH_MS = 2000
TILES = config.MODES + ("Screensaver",)


class DashboardPage:
    """Mixed into App; uses its kit, settings, bridge and painters."""

    def build_dashboard_page(self):
        k = self.kit
        page = tk.Frame(self.root, bg=ui.MAIN_BG)
        header = ui.Picture(page, ui.MAIN_BG)
        image = k.canvas(CARD_WIDTH, 62, ui.MAIN_BG)
        k.text(image, 0, 22, "Dashboard", "semibold", 18, ui.INK)
        k.text(image, 0, 50, "Switch off the screens you don't need on the knob.", "regular", 9, ui.MUTED_INK, width=CARD_WIDTH)
        header.show(image)
        header.pack(padx=k.px(28), pady=(k.px(18), k.px(12)), anchor="w")
        grid = tk.Frame(page, bg=ui.MAIN_BG)
        grid.pack(padx=k.px(28), anchor="w")
        self.dashboard_tiles = {}
        for index, key in enumerate(TILES):
            tile = ui.Button(grid, ui.MAIN_BG,
                             lambda hover, key=key: self.paint_tile(key, hover),
                             lambda: None)
            tile.bind("<Button-1>", lambda event, key=key: self.click_tile(key, event))
            column = index % TILE_COLUMNS
            tile.grid(row=index // TILE_COLUMNS, column=column,
                      padx=(0, k.px(TILE_GAP) if column < TILE_COLUMNS - 1 else 0),
                      pady=(0, k.px(TILE_GAP)))
            self.dashboard_tiles[key] = tile
        self.levels_pending = False
        self.dashboard_page = page

    def tile_on(self, key):
        if key == "Screensaver":
            return self.settings["saver_enabled"]
        return key in self.settings["screens"]

    def tile_text(self, key):
        """(headline, detail, level or None) for a tile."""
        if key in ("Volume", "Mic", "Brightness"):
            level = self.levels.get(key)
            if level is None:
                return "\u2014", "Not available" if key in self.levels else "", None
            return f"{level}%", "", level / 100
        if key == "Media":
            state = self.media_state or {}
            title = state.get("title")
            if not title:
                return "Nothing playing", "", None
            status = "Playing" if state.get("status") == 1 else "Paused"
            return title, " \u00b7 ".join(filter(None, (status, state.get("artist")))), None
        if key == "Pomodoro":
            timer = self.pomodoro
            remaining = timer.remaining()
            status = "running" if timer.running else "paused" if (
                remaining != timer.total) else "ready"
            return (f"{remaining // 60}:{remaining % 60:02d}",
                    f"{pomodoro.PHASE_NAMES[timer.phase]} \u00b7 {status}", timer.fraction())
        if key == "Games":
            return "Play on the knob", "", None
        if key == "Screensaver":
            count = len(self.library.items)
            pictures = f"{count} item{'s' if count != 1 else ''}"
            if self.settings["saver_show"] == "clock":
                pictures = "Date and time"
            if not self.settings["saver_enabled"]:
                return "Off", pictures, None
            return f"After {self.settings['saver_idle']} min", pictures, None
        return ("Turn to scroll" if key == "Scroll" else "Turn to zoom"), "", None

    def paint_tile(self, key, hover):
        k = self.kit
        width, height = TILE_WIDTH, TILE_HEIGHT
        image = k.canvas(width, height, ui.MAIN_BG)
        on = self.tile_on(key)
        k.rounded(image, (0, 0, width, height), 14,
                  "#FFFFFF" if hover else ui.CARD_BG, ui.CARD_EDGE)
        accent = self.accent(key) if key in config.MODES else ui.rgb(ui.SUBTLE_INK)
        ink = dial.label_ink(accent) if on else ui.MUTED_INK
        k.icon(image, key, 24, 24, ink, 0.72)
        k.text(image, 42, 24, key, "semibold", 10, ui.INK if on else ui.SUBTLE_INK,
               width=width - 42 - SWITCH_W - 16)
        self.paint_switch(image, width - 12 - SWITCH_W, 24 - SWITCH_H / 2, on, hover)
        headline, detail, level = self.tile_text(key)
        big = len(headline) <= 8
        k.text(image, 14, 52 if detail or level is not None else 58, headline,
               "semibold", 14 if big else 10, ui.INK if on else ui.SUBTLE_INK,
               width=width - 28)
        if level is not None:
            k.rounded(image, (14, 70, width - 14, 74), 2, ui.CARD_EDGE)
            if level > 0:
                k.rounded(image, (14, 70, max(18, 14 + (width - 28) * level), 74), 2,
                          dial.label_ink(accent) if on else ui.MUTED_INK)
            if detail:
                k.text(image, width - 14, 52, detail, "regular", 8, ui.MUTED_INK,
                       anchor="rm")
        elif detail:
            k.text(image, 14, 71, detail, "regular", 8.5, ui.MUTED_INK, width=width - 28)
        return image

    def paint_switch(self, image, x, y, on, hover):
        k = self.kit
        track = ui.INK if on else (ui.SUBTLE_INK if hover else ui.IDLE_GREY)
        k.rounded(image, (x, y, x + SWITCH_W, y + SWITCH_H), SWITCH_H / 2, track)
        r = SWITCH_H / 2 - 3
        k.dot(image, x + (SWITCH_W - SWITCH_H / 2 if on else SWITCH_H / 2), y + SWITCH_H / 2,
              r, "#FFFFFF")

    def click_tile(self, key, event):
        scale = self.kit.scale
        x, y = event.x / scale, event.y / scale
        if x >= TILE_WIDTH - SWITCH_W - 20 and y <= 44:
            self.toggle_tile(key)
        elif key == "Screensaver":
            self.navigate("Screensaver")
        elif self.tile_on(key):
            self.navigate(key)
        else:
            self.toggle_tile(key)

    def toggle_tile(self, key):
        if key == "Screensaver":
            self.toggle_setting("saver_enabled")
            return
        screens = list(self.settings["screens"])
        if key in screens:
            if len(screens) == 1:
                self.status.set("The knob needs at least one screen")
                return
            screens.remove(key)
        else:
            screens.append(key)
        self.set_screens([mode for mode in config.MODES if mode in screens])

    def set_screens(self, screens):
        self.settings["screens"] = screens
        if self.mode not in screens:
            # The knob moves off a screen that was switched off; follow it.
            self.select_mode(screens[0])
        config.save(self.settings)
        if self.connected:
            self.bridge.send_screens(config.screen_mask(screens))
        self.build_nav()
        self.refresh_dashboard()
        if self.menu:
            self.render()

    def refresh_dashboard(self):
        if not hasattr(self, "dashboard_tiles"):
            return
        for tile in self.dashboard_tiles.values():
            tile.refresh()

    def refresh_dashboard_tile(self, key):
        if hasattr(self, "dashboard_tiles"):
            self.dashboard_tiles[key].refresh()

    def refresh_levels(self):
        """Keeps the level tiles current while the dashboard is on screen."""
        if (self.page == "dashboard" and not self.levels_pending
                and self.root.state() != "withdrawn"):
            self.levels_pending = True
            self.actions.put(("__levels__", 0))
        self.root.after(LEVEL_REFRESH_MS, self.refresh_levels)
