"""The setup wizard's action button must survive the layout.

The window is a fixed-size vertical pack stack. `pack` hands out space in
packing order, so whichever widget is packed LAST absorbs any shortfall — and
the Install/Uninstall button was packed last, after a 14-line Text that asks
for 228px. Adding the port picker pushed the stack's requested height to 489px
inside a 640x460 window, and the button was squeezed to 3px tall: present, but
far too small to read or click.

These tests measure the real Tk layout rather than eyeballing it, so the button
cannot be crushed again by a future row or by a larger font.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

tk = pytest.importorskip("tkinter", reason="tkinter not available")


@pytest.fixture(params=[False, True], ids=["setup", "uninstall"])
def built_window(request, monkeypatch):
    """Build the real wizard, stop mainloop from blocking, and lay it out."""
    import host_setup

    monkeypatch.setattr(tk.Tk, "mainloop", lambda self: None)
    try:
        host_setup.run_gui(request.param)
    except tk.TclError as exc:  # no display / no Tk runtime
        pytest.skip(f"cannot open a Tk window here: {exc}")

    root = tk._default_root
    root.update_idletasks()
    root.update()
    yield root
    root.destroy()


def _action_button(root):
    """The Install / Uninstall / Close button — the only ttk Button packed
    directly on the root (the Browse… button lives inside a Frame)."""
    buttons = [w for w in root.pack_slaves() if w.winfo_class() == "TButton"]
    assert len(buttons) == 1, f"expected one action button, found {len(buttons)}"
    return buttons[0]


def test_the_window_is_tall_enough_for_everything_in_it(built_window):
    root = built_window
    assert root.winfo_reqheight() <= root.winfo_height(), (
        f"the packed stack wants {root.winfo_reqheight()}px but the window is "
        f"{root.winfo_height()}px — something will be squeezed"
    )


def test_the_action_button_is_not_squeezed(built_window):
    button = _action_button(built_window)
    assert button.winfo_height() >= button.winfo_reqheight(), (
        f"button got {button.winfo_height()}px of the "
        f"{button.winfo_reqheight()}px it asked for"
    )


def test_the_action_button_is_fully_inside_the_window(built_window):
    root, button = built_window, _action_button(built_window)
    bottom = button.winfo_y() + button.winfo_height()
    assert bottom <= root.winfo_height(), (
        f"button ends at y={bottom} but the window is only "
        f"{root.winfo_height()}px tall"
    )


def test_the_button_keeps_its_size_when_the_window_is_shrunk(built_window):
    # A user dragging the window smaller must not be able to crush the button
    # either: the log area is what should give way.
    root = built_window
    root.geometry(f"{root.winfo_width()}x300")
    root.update_idletasks()
    root.update()

    button = _action_button(root)
    assert button.winfo_height() >= button.winfo_reqheight(), (
        f"after shrinking, button got {button.winfo_height()}px of the "
        f"{button.winfo_reqheight()}px it asked for"
    )
