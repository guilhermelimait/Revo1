"""Seven launcher slots, configured on the PC and selected on the knob."""

import tkinter as tk
from tkinter import filedialog, ttk
from revo1 import dialogs as messagebox
import time
import uuid

from PIL import ImageTk

from revo1 import config, launcher, theme, ui
from revo1.layout import CARD_WIDTH

ROW_HEIGHT = 58


class LauncherPage:
    def init_launcher(self):
        self.settings["launcher"] = list(self.settings["launcher"])
        self.launcher_icons = {}
        self.launcher_catalog_icons = {}
        self.launcher_token = uuid.uuid4().hex[:8]
        self.launcher_ready = False
        self.launcher_note = "Choose up to 7 apps. Revo1 must be running to launch them."
        self.launcher_last_launch = 0.0

    def build_launcher_panel(self, page):
        k = self.kit
        self.launcher_panel = tk.Frame(page, bg=ui.MAIN_BG)
        self.launcher_header = ui.Picture(self.launcher_panel, ui.MAIN_BG)
        self.launcher_header.pack(padx=k.px(ui.PAGE_INSET),
                                  pady=(k.px(ui.PAGE_TOP), k.px(ui.HEADER_GAP)), anchor="w")
        self.launcher_rows = []
        for index in range(launcher.SLOTS):
            row = tk.Frame(self.launcher_panel, bg=ui.MAIN_BG)
            row.pack(padx=k.px(28), pady=(0, k.px(8)), anchor="w")
            picture = ui.Picture(row, ui.MAIN_BG)
            picture.pack(side="left", padx=(0, k.px(10)))
            choose = ui.Button(row, ui.MAIN_BG,
                               lambda hover, index=index: self.paint_pill(
                                   "Replace" if self.settings["launcher"][index] else "Choose app",
                                   hover, width=106),
                               lambda index=index: self.choose_launcher_app(index))
            choose.pack(side="left", padx=(0, k.px(8)))
            remove = ui.Button(row, ui.MAIN_BG,
                               lambda hover: self.paint_pill("Clear", hover, width=70),
                               lambda index=index: self.set_launcher_slot(index, None))
            remove.pack(side="left")
            self.launcher_rows.append((picture, choose, remove))

    def refresh_launcher(self):
        if not hasattr(self, "launcher_header"):
            return
        k = self.kit
        image = k.canvas(CARD_WIDTH, 84, ui.MAIN_BG)
        image.paste(k.page_header("App launcher",
                                  "On the knob: turn to choose, then tap the center to launch.",
                                  CARD_WIDTH), (0, 0))
        k.text(image, 0, 74, self.launcher_note, "regular", ui.TEXT_DETAIL,
               ui.SUBTLE_INK, width=CARD_WIDTH)
        self.launcher_header.show(image)
        for index, (picture, choose, remove) in enumerate(self.launcher_rows):
            item = self.settings["launcher"][index]
            width = CARD_WIDTH - 194
            image = k.canvas(width, ROW_HEIGHT, ui.MAIN_BG)
            k.text(image, 18, 29, str(index + 1), "semibold", 10, ui.MUTED_INK)
            icon = self.launcher_icons.get(index)
            if icon is not None:
                icon = icon.convert("RGBA").resize((k.px(40), k.px(40)))
                image.paste(icon, (k.px(38), k.px(9)), icon)
            else:
                k.icon(image, "Launcher", 58, 29, ui.MUTED_INK, 0.8)
            k.text(image, 90, 21, item["name"] if item else "Empty slot", "semibold", 10,
                   ui.INK if item else ui.MUTED_INK, width=width - 104)
            detail = ("Ready on the knob" if self.launcher_ready else "Saved on this PC") if item else \
                     "Add an app or shortcut"
            k.text(image, 90, 40, detail,
                   "regular", ui.TEXT_DETAIL, ui.SUBTLE_INK, width=width - 104)
            picture.show(image)
            choose.refresh()
            remove.refresh()

    def choose_launcher_app(self, index):
        try:
            apps = launcher.installed_apps()
        except OSError as exc:
            messagebox.showerror("App launcher", f"Could not read installed apps: {exc}",
                                 parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Choose an app")
        window.configure(bg=ui.MAIN_BG)
        window.transient(self.root)
        width, height = self.kit.px(560), self.kit.px(520)
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        window.geometry(f"{width}x{height}{x:+d}{y:+d}")
        theme.title_bar(window, ui.ACTIVE_THEME == "dark")
        heading = ui.Picture(window, ui.MAIN_BG)
        image = self.kit.canvas(520, 48, ui.MAIN_BG)
        self.kit.text(image, 0, 16, "Choose an app", "semibold", 14, ui.INK)
        self.kit.text(image, 0, 40, "Your desktop and Microsoft Store apps, together.",
                      "regular", 9, ui.SUBTLE_INK)
        heading.show(image)
        heading.pack(padx=self.kit.px(20), pady=(self.kit.px(12), 0), anchor="w")
        search = tk.StringVar()
        show_all = tk.BooleanVar(value=False)
        field = ui.TextField(window, self.kit, 520, textvariable=search)
        field.pack(fill="x", padx=self.kit.px(20), pady=(self.kit.px(ui.GAP), self.kit.px(ui.GAP)))
        entry = field.entry
        toggle = ui.Button(
            window, ui.MAIN_BG,
            lambda hover: self.paint_toggle(show_all.get(), "Show all apps",
                                             "Include technical tools and system utilities",
                                             hover, width=520),
            lambda: show_all.set(not show_all.get()))
        toggle.keyboard_access()
        toggle.pack(padx=self.kit.px(20), pady=(0, self.kit.px(8)), anchor="w")
        listing = tk.Frame(window, bg=ui.MAIN_BG)
        listing.pack(fill="both", expand=True, padx=self.kit.px(20))
        style = ttk.Style(window)
        style.configure("Launcher.Treeview", background=ui.CARD_BG,
                        fieldbackground=ui.CARD_BG, foreground=ui.INK,
                        rowheight=self.kit.px(48), font=(ui.TK_FAMILY, ui.TEXT_BUTTON))
        style.map("Launcher.Treeview", background=[("selected", ui.SELECT_BG)],
                  foreground=[("selected", ui.SELECT_INK)])
        listing_view = ttk.Treeview(listing, style="Launcher.Treeview",
                                   columns=("source",), show="tree", selectmode="browse", height=5)
        listing_view.column("#0", width=self.kit.px(366), minwidth=self.kit.px(200), stretch=True)
        listing_view.column("source", width=self.kit.px(120), stretch=False, anchor="center")
        scrollbar = ttk.Scrollbar(listing, command=listing_view.yview)
        scrollbar.pack(side="right", fill="y")
        listing_view.configure(yscrollcommand=scrollbar.set)
        listing_view.pack(side="left", fill="both", expand=True)
        visible = []
        photos = {}
        pending = []
        failed = set()
        timer = [None]
        note = tk.StringVar()
        tk.Label(window, textvariable=note, bg=ui.MAIN_BG, fg=ui.SUBTLE_INK,
                 font=(ui.TK_FAMILY, ui.TEXT_DETAIL), anchor="w").pack(
                     fill="x", padx=self.kit.px(20), pady=(self.kit.px(6), 0))

        def update_note():
            text = f"{len(visible)} apps"
            if not visible:
                text = "No matching apps. Try Show all apps or Browse."
            if failed:
                text += f" / {len(failed)} icons unavailable; select an app for details."
            note.set(text)

        def load_icons():
            timer[0] = None
            for _ in range(min(4, len(pending))):
                iid, app = pending.pop(0)
                try:
                    icon = self.launcher_catalog_icons.get(app.path)
                    if icon is None:
                        icon = launcher.shell_icon(app.path)
                        self.launcher_catalog_icons[app.path] = icon
                    photos[iid] = ImageTk.PhotoImage(icon.resize(
                        (self.kit.px(36), self.kit.px(36))), master=listing_view)
                    listing_view.item(iid, image=photos[iid])
                except (OSError, ValueError) as exc:
                    failed.add(app.path)
                    self.status.set(f"Icon unavailable for {app.name}: {exc}")
            update_note()
            if pending:
                timer[0] = window.after(20, load_icons)

        def filter_apps(*_):
            toggle.refresh()
            if timer[0] is not None:
                window.after_cancel(timer[0])
                timer[0] = None
            visible[:] = [item for item in apps if (show_all.get() or not item.technical)
                          and search.get().casefold() in item.name.casefold()]
            listing_view.delete(*listing_view.get_children())
            photos.clear()
            pending.clear()
            failed.clear()
            for index, app in enumerate(visible):
                iid = str(index)
                listing_view.insert("", "end", iid=iid, text="  " + app.name,
                                    values=("Store app" if app.store else "Desktop app",))
                pending.append((iid, app))
            update_note()
            if pending:
                timer[0] = window.after(0, load_icons)

        def accept(path):
            try:
                item = launcher.target(path)
                icon = self.launcher_catalog_icons.get(path)
                if icon is None:
                    icon = launcher.shell_icon(item["path"])
                self.set_launcher_slot(index, item, icon)
            except (OSError, ValueError) as exc:
                messagebox.showerror("App launcher", str(exc), parent=window)
                return
            window.destroy()

        def pick(*_):
            selection = listing_view.selection()
            if selection:
                accept(visible[int(selection[0])].path)

        def browse():
            path = filedialog.askopenfilename(
                parent=window, title="Choose an application or shortcut",
                filetypes=[("Apps and shortcuts", "*.exe *.lnk *.appref-ms")])
            if path:
                accept(path)

        buttons = tk.Frame(window, bg=ui.MAIN_BG)
        buttons.pack(fill="x", padx=self.kit.px(20), pady=self.kit.px(16))
        ui.Button(buttons, ui.MAIN_BG,
                  lambda hover: self.paint_pill("Browse...", hover, width=106),
                  browse).pack(side="left")
        ui.Button(buttons, ui.MAIN_BG,
                  lambda hover: self.paint_pill("Select app", hover, primary=True, width=106),
                  pick).pack(side="right")
        search.trace_add("write", filter_apps)
        show_all.trace_add("write", filter_apps)
        listing_view.bind("<Double-Button-1>", pick)
        listing_view.bind("<Return>", pick)

        def focus_results(*_):
            rows = listing_view.get_children()
            if rows:
                listing_view.selection_set(rows[0])
                listing_view.focus(rows[0])
                listing_view.focus_set()
            return "break"

        entry.bind("<Down>", focus_results)
        window.bind("<Control-o>", lambda event: browse())
        window.bind("<Escape>", lambda event: window.destroy())

        def cancel_loader(event):
            if event.widget == window and timer[0] is not None:
                window.after_cancel(timer[0])
                timer[0] = None

        window.bind("<Destroy>", cancel_loader)
        filter_apps()
        window.grab_set()
        entry.focus_set()

    def set_launcher_slot(self, index, item, icon=None):
        self.settings["launcher"][index] = item
        self.launcher_icons.pop(index, None)
        if icon is not None:
            self.launcher_icons[index] = icon
        config.save(self.settings)
        self.launcher_token = uuid.uuid4().hex[:8]
        self.launcher_ready = False
        self.push_launcher()
        self.refresh_launcher()
        self.refresh_dashboard_tile("Launcher")

    def push_launcher(self):
        items = []
        for index, item in enumerate(self.settings["launcher"]):
            if item is None:
                continue
            try:
                if index not in self.launcher_icons:
                    self.launcher_icons[index] = launcher.shell_icon(item["path"])
                items.append((index, launcher.wire_name(item["name"]),
                              launcher.icon_bytes(self.launcher_icons[index])))
            except (OSError, ValueError) as exc:
                self.launcher_note = f"Could not prepare {item['name']}: {exc}"
                self.status.set(self.launcher_note)
                self.refresh_launcher()
                return
        if self.connected:
            self.launcher_note = "Sending app names and icons to the knob..."
            self.bridge.send_launcher(self.launcher_token, items)
        else:
            self.launcher_note = "Saved on this PC. Connect the knob to sync your apps."
        self.refresh_launcher()

    def launch_from_device(self, token, index):
        if (not self.connected or not self.launcher_ready or token != self.launcher_token
                or not 0 <= index < launcher.SLOTS or self.settings["launcher"][index] is None):
            self.status.set("App launch rejected: launcher is not synced. Reconnect the knob.")
            return
        if time.monotonic() - self.launcher_last_launch < 0.7:
            self.status.set("Please wait before launching another app.")
            return
        self.launcher_last_launch = time.monotonic()
        self.actions.put(("__launch__", (token, index, dict(self.settings["launcher"][index]))))
