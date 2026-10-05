"""Window layout shared by the pages, in 96-dpi pixels."""

SIDEBAR_WIDTH = 212
MAIN_WIDTH = 800
WINDOW_HEIGHT = 640
NAV_WIDTH = 188
NAV_HEIGHT = 44
CARD_WIDTH = MAIN_WIDTH - 56
# The dial pages: the dial on the left, its name, help and buttons beside it.
DIAL_SIZE = 360
DIAL_GAP = 40
SIDE_WIDTH = CARD_WIDTH - DIAL_SIZE - DIAL_GAP
# Switches, sliders and lists stop here rather than running to the far edge,
# so a switch stays close to the words it belongs to.
FORM_WIDTH = 440
# Buttons are as wide as their label, but never narrower than this.
BUTTON_MIN = 96
