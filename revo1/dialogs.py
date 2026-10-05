"""App-owned message dialogs using the current companion palette."""

import tkinter as tk
from tkinter import messagebox as native_messagebox

from revo1 import theme, ui


def _show(title, message, parent=None, question=False, default="ok", **options):
    if parent is None:
        method = native_messagebox.askyesno if question else native_messagebox.showinfo
        return method(title, message, default=default, **options)
    window = tk.Toplevel(parent)
    window.withdraw()
    window.title(title)
    window.configure(bg=ui.MAIN_BG)
    window.transient(parent)
    window.resizable(False, False)
    scale = parent.winfo_fpixels("1i") / 96
    kit = ui.Kit(scale)
    result = [False if question else "ok"]
    tk.Label(window, text=message, bg=ui.MAIN_BG, fg=ui.INK,
             font=(ui.TK_FAMILY, ui.TEXT_BUTTON), justify="left", wraplength=kit.px(430)).pack(
                 padx=kit.px(ui.MODAL_INSET),
                 pady=(kit.px(ui.MODAL_INSET), kit.px(ui.MODAL_INSET)), anchor="w")
    row = tk.Frame(window, bg=ui.MAIN_BG)
    row.pack(anchor="e", padx=kit.px(ui.MODAL_INSET), pady=(0, kit.px(ui.MODAL_INSET)))

    def finish(value):
        result[0] = value
        window.destroy()

    buttons = {}
    for label, value in (("No", False), ("Yes", True)) if question else (("OK", "ok"),):
        def paint(hover, label=label):
            image = kit.canvas(96, ui.CONTROL_HEIGHT, ui.MAIN_BG)
            ink, _ = kit.button_surface(image, 96, ui.CONTROL_HEIGHT, hover)
            kit.text(image, 48, ui.CONTROL_HEIGHT / 2, label, "semibold",
                     ui.TEXT_BUTTON, ink, anchor="mm")
            return image
        button = ui.Button(row, ui.MAIN_BG, paint, lambda value=value: finish(value))
        button.configure(takefocus=True, highlightthickness=1,
                         highlightbackground=ui.MAIN_BG, highlightcolor=ui.INK)
        button.bind("<Return>", lambda event, value=value: finish(value))
        button.bind("<space>", lambda event, value=value: finish(value))
        button.pack(side="left", padx=(kit.px(8), 0))
        buttons[label.lower()] = button
    window.bind("<Escape>", lambda event: finish(False if question else "ok"))
    window.protocol("WM_DELETE_WINDOW", lambda: finish(False if question else "ok"))
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    window.geometry(f"{width}x{height}{x:+d}{y:+d}")
    theme.title_bar(window, ui.ACTIVE_THEME == "dark")
    previous_grab = parent.grab_current()
    window.deiconify()
    window.grab_set()
    buttons.get(default, buttons["no" if question else "ok"]).focus_set()
    parent.wait_window(window)
    if previous_grab is not None and previous_grab.winfo_exists():
        previous_grab.grab_set()
    return result[0]


def askyesno(title, message, **options):
    return _show(title, message, question=True, default=options.pop("default", "no"), **options)


def showinfo(title, message, **options):
    return _show(title, message, **options)


def showwarning(title, message, **options):
    if options.get("parent") is None:
        return native_messagebox.showwarning(title, message, **options)
    return _show(title, message, **options)


def showerror(title, message, **options):
    if options.get("parent") is None:
        return native_messagebox.showerror(title, message, **options)
    return _show(title, message, **options)
