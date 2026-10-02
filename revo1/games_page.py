"""The Games screen in the window: a card per game, laid out in a grid.
The games themselves are played on the knob."""

import tkinter as tk

from revo1 import config, dial, ui
from revo1.layout import CARD_WIDTH

CARD_GAP = 10
CARD_COLUMNS = 3
CARD_W = (CARD_WIDTH - CARD_GAP * (CARD_COLUMNS - 1)) // CARD_COLUMNS
CARD_H = 176
ART_Y = 52
ART_SIZE = 1.6
# Whack-a-Mole's picture, as the knob draws it (draw_card_art): shape, colour.
WHACK_ART = (("HoleRim", "#C4C4CE"), ("HoleDirt", "#4A403C"), ("MoleBody", "#8C5E3C"),
             ("MoleFace", "#D2A47C"), ("MoleEyes", "#1E1A18"), ("MoleNose", "#E86A82"))
# Each game: (name, art or None for a placeholder). None names are "soon" cards.
GAMES = (("Whack-a-Mole", WHACK_ART), (None, None), (None, None))


class GamesPage:
    """Mixed into App; uses its kit and settings (which keep the scores)."""

    def build_games_panel(self, page):
        k = self.kit
        panel = tk.Frame(page, bg=ui.MAIN_BG)
        header = ui.Picture(panel, ui.MAIN_BG)
        image = k.canvas(CARD_WIDTH, 62, ui.MAIN_BG)
        k.text(image, 0, 22, "Games", "semibold", 18, ui.INK)
        k.text(image, 0, 50, "Play them on the knob: open Games there and tap a card.",
               "regular", 9, ui.MUTED_INK, width=CARD_WIDTH)
        header.show(image)
        header.pack(padx=k.px(28), pady=(k.px(18), k.px(12)), anchor="w")
        grid = tk.Frame(panel, bg=ui.MAIN_BG)
        grid.pack(padx=k.px(28), anchor="w")
        self.game_cards = []
        for index in range(len(GAMES)):
            card = ui.Picture(grid, ui.MAIN_BG)
            column = index % CARD_COLUMNS
            card.grid(row=index // CARD_COLUMNS, column=column,
                      padx=(0, k.px(CARD_GAP) if column < CARD_COLUMNS - 1 else 0),
                      pady=(0, k.px(CARD_GAP)))
            self.game_cards.append(card)
        self.games_panel = panel

    def record_score(self, last, best):
        """Keeps the knob's Whack-a-Mole scores; `last` is None when the knob
        only reports its best (on connecting)."""
        best = max(best, self.settings["whack_best"])
        last = self.settings["whack_last"] if last is None else last
        if (best, last) == (self.settings["whack_best"], self.settings["whack_last"]):
            return
        self.settings["whack_best"], self.settings["whack_last"] = best, last
        config.save(self.settings)
        self.refresh_games()
        self.refresh_dashboard_tile("Games")

    def refresh_games(self):
        for card, (name, art) in zip(self.game_cards, GAMES):
            card.show(self.paint_game_card(name, art))

    def paint_game_card(self, name, art):
        k = self.kit
        image = k.canvas(CARD_W, CARD_H, ui.MAIN_BG)
        k.rounded(image, (0, 0, CARD_W, CARD_H), 16, ui.CARD_BG, ui.CARD_EDGE)
        centre = CARD_W / 2
        if name is None:
            k.dot(image, centre, ART_Y, 21, ui.CARD_EDGE)
            k.dot(image, centre, ART_Y, 19, ui.MAIN_BG)
            k.text(image, centre, ART_Y, "?", "semibold", 16, ui.IDLE_GREY, anchor="mm")
            k.text(image, centre, 100, "Soon", "semibold", 12, ui.SUBTLE_INK, anchor="mm")
            k.text(image, centre, 122, "Another game is on the way", "regular", 8.5,
                   ui.MUTED_INK, anchor="mm", width=CARD_W - 24)
            return image
        for shape, colour in art:
            k.icon(image, shape, centre, ART_Y, colour, ART_SIZE)
        k.text(image, centre, 100, name, "semibold", 12, ui.INK, anchor="mm",
               width=CARD_W - 24)
        best, last = self.settings["whack_best"], self.settings["whack_last"]
        if last >= 0:
            score = f"Best {best} \u00b7 Last {last}"
        elif best:
            score = f"Best {best}"
        else:
            score = "No score yet"
        k.text(image, centre, 122, score, "regular", 8.5, ui.MUTED_INK, anchor="mm",
               width=CARD_W - 24)
        ink = dial.label_ink(self.accent("Games"))
        k.rounded(image, (24, 140, CARD_W - 24, 162), 11, ui.MAIN_BG)
        k.text(image, centre, 151, "Play on the knob", "semibold", 8.5, ink, anchor="mm")
        return image
