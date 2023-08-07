# Licensed under a 3-clause BSD style license - see LICENSE.rst

# This sub-module is destined for common non-package specific utility
# functions that will ultimately be merged into `astropy.utils`

# As far as possible, utils contains classes of generic use, such as
# PosInt for positive integer input. See e.g. 'hcam' for more instrument
# dependent components.

from __future__ import print_function, unicode_literals, absolute_import, division
import six

if not six.PY3:
    import tkFont as font
else:
    from tkinter import font


def get_root(w):
    """
    Simple method to access root for a widget
    """
    next_level = w
    while next_level.master:
        next_level = next_level.master
    return next_level


def addStyle(w):
    """
    Styles the GUI: global fonts and colours.

    Parameters
    ----------
    w : tkinter.tk
        widget element to style
    """
    # access global container in root widget
    root = get_root(w)
    g = root.globals
    fsize = g.cpars["font_size"]
    family = g.cpars["font_family"]

    # Default font
    g.DEFAULT_FONT = font.nametofont("TkDefaultFont")
    g.DEFAULT_FONT.configure(size=fsize, weight="bold", family=family)
    w.option_add("*Font", g.DEFAULT_FONT)

    # Menu font
    g.MENU_FONT = font.nametofont("TkMenuFont")
    g.MENU_FONT.configure(family=family)
    w.option_add("*Menu.Font", g.MENU_FONT)

    # Entry font
    g.ENTRY_FONT = font.nametofont("TkTextFont")
    g.ENTRY_FONT.configure(size=fsize, family=family)
    w.option_add("*Entry.Font", g.ENTRY_FONT)

    # position and size
    # root.geometry("320x240+325+200")

    # Default colours. Note there is a difference between
    # specifying 'background' with a capital B or lowercase b
    w.option_add("*background", g.COL["main"])
    w.option_add("*HighlightBackground", g.COL["main"])
    w.config(background=g.COL["main"])


def place_at_edge(parent, win, padding=10):
    """
    Places a window at the edge of its parent window.

    This is useful when deiconifying a window that has been withdrawn
    so that it doesn't overlap with the main window.

    Parameters
    ----------
    parent : tkinter widget
        parent widget
    win : tkinter widget
        widget to place
    padding : int
        padding in pixels between windows
    """

    # make sure windows are updated so we get current positions
    win.update_idletasks()
    parent.update_idletasks()

    # width and height of window to place
    width = win.winfo_width()
    height = win.winfo_height()

    # position and size of parent
    parent_x_upperleft = parent.winfo_rootx()
    parent_y_upperleft = parent.winfo_rooty()
    titlebar_height = parent.winfo_rooty() - parent.winfo_y()
    parent_width = parent.winfo_width()
    parent_height = parent.winfo_height()

    win.geometry(
        "{}x{}+{}+{}".format(
            width,
            height,
            parent_x_upperleft + parent_width + padding,
            parent_y_upperleft - titlebar_height,
        )
    )
