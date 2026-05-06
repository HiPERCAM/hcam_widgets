# general purpose widgets
from __future__ import absolute_import, division, print_function, unicode_literals

import socket
from functools import partial, reduce

import numpy as np
import six

# astropy utilities
from astropy import coordinates as coord
from astropy import units as u
from astropy.time import Time
from six.moves import urllib

# twisted and async support
from twisted.internet.defer import inlineCallbacks

# internal
from . import DriverError
from .astro import calc_riseset, calc_time_to_rotator_limit
from .logs import GuiHandler, Logger
from .misc import async_sleep, checkSimbad
from .tkutils import get_root

if not six.PY3:
    import Tkinter as tk
    import tkMessageBox as messagebox
else:
    import tkinter as tk
    from tkinter import messagebox


# GENERAL UI WIDGETS
class Boolean(tk.IntVar):
    """
    Defines an object representing one of the boolean configuration
    parameters to allow it to be interfaced with the menubar easily.

    If defined, callback is run with the new value of the flag as its
    argument
    """

    def __init__(self, master, flag, callback=None):
        tk.IntVar.__init__(self)
        self.master = master
        # get globals from root
        g = get_root(master).globals

        self.set(g.cpars[flag])
        self.trace_add("write", self._update)
        self.flag = flag
        self.callback = callback

    def _update(self, *args):
        # get globals from root
        g = get_root(self.master).globals
        if self.get():
            g.cpars[self.flag] = True
        else:
            g.cpars[self.flag] = False
        if self.callback:
            self.callback(g.cpars[self.flag])


class IntegerEntry(tk.Entry):
    """
    Defines an Entry field which only accepts integer input.
    This is the base class for several varieties of integer
    input fields and defines much of the feel to do with holding
    the mouse buttons down etc.
    """

    def __init__(self, master, ival, checker, blank, **kw):
        """
        Parameters
        -----------
        master : tkinter.tk
            enclosing widget
        ival : int
            initial integer value
        checker : callable
            check function that is run on any change to the entry
        blank : boolean
            controls whether the field is allowed to be
            blank. In some cases it makes things easier if
            a blank field is allowed, even if it is technically
            invalid (the latter case requires some other checking)
        kw : dict
            optional keyword arguments that are passed to Entry.
        """
        tk.Entry.__init__(self, master, **kw)
        # important to set the value of _variable before tracing it
        # to avoid immediate run of _callback.
        self._variable = tk.StringVar()
        self._value = str(int(ival))
        self._variable.set(self._value)
        self._variable.trace_add("write", self._callback)
        self.config(textvariable=self._variable)
        self.checker = checker
        self.blank = blank
        self.set_bind()

        # Checking for repeated keys
        self.has_prev_key_release = None

        # Nasty stuff to do with holding mouse
        # buttons down
        self._leftMousePressed = False
        self._shiftLeftMousePressed = False
        self._rightMousePressed = False
        self._shiftRightMousePressed = False
        self._mouseJustPressed = True

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            # trap blank fields here
            if not self.blank or value:
                int(value)
            return value
        except ValueError:
            return None

    def value(self):
        """
        Returns integer value, if possible, None if not.
        """
        try:
            return int(self._value)
        except ValueError:
            return None

    def set(self, num):
        """
        Sets the current value equal to num
        """
        self._value = str(int(num))
        self._variable.set(self._value)

    def add(self, num):
        """
        Adds num to the current value
        """
        try:
            val = self.value() + num
        except Exception:
            val = num
        self.set(val)

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num
        self.set(val)

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            int(self._value)
            return True
        except ValueError:
            return False

    def enable(self):
        self.configure(state="normal")
        self.set_bind()

    def disable(self):
        self.configure(state="disable")
        self.set_unbind()

    def on_key_release(self, *dummy):
        self.has_prev_key_release = None
        if self.checker:
            self.checker(dummy)

    def on_key_release_repeat(self, *dummy):
        """
        Avoid repeated trigger of callback.

        When holding a key down, multiple key press and release events
        are fired in succession. Debouncing is implemented to squash these.
        """
        self.has_prev_key_release = self.after_idle(self.on_key_release, dummy)

    def on_key_press_repeat(self, keysym):
        if self.has_prev_key_release:
            # stop the key release callback being called yet
            self.after_cancel(self.has_prev_key_release)
            # set prev_key_release to None, so next key release will reactivate
            self.has_prev_key_release = None
        # increment the value
        increment = 1
        if "Shift" in keysym:
            increment = 10
        elif "Control" in keysym:
            increment = 100
        if "Up" in keysym:
            self.add(increment)
        elif "Down" in keysym:
            self.sub(increment)

    def set_bind(self):
        """
        Sets key bindings.
        """
        # Arrow keys and enter
        self.bind("<Up>", lambda e: self.on_key_press_repeat("Up"))
        self.bind("<Down>", lambda e: self.on_key_press_repeat("Down"))
        self.bind("<Shift-Up>", lambda e: self.on_key_press_repeat("Shift-Up"))
        self.bind("<Shift-Down>", lambda e: self.on_key_press_repeat("Shift-Down"))
        self.bind("<Control-Up>", lambda e: self.on_key_press_repeat("Control-Up"))
        self.bind("<Control-Down>", lambda e: self.on_key_press_repeat("Control-Down"))
        self.bind("<KeyRelease>", lambda e: self.on_key_release_repeat())

        # Mouse buttons: bit complex since they don't automatically
        # run in continuous mode like the arrow keys
        self.bind("<ButtonPress-1>", self._leftMouseDown)
        self.bind("<ButtonRelease-1>", self._leftMouseUp)
        self.bind("<Shift-ButtonPress-1>", self._shiftLeftMouseDown)
        self.bind("<Shift-ButtonRelease-1>", self._shiftLeftMouseUp)
        self.bind("<Control-Button-1>", lambda e: self.add(100))

        self.bind("<ButtonPress-3>", self._rightMouseDown)
        self.bind("<ButtonRelease-3>", self._rightMouseUp)
        self.bind("<Shift-ButtonPress-3>", self._shiftRightMouseDown)
        self.bind("<Shift-ButtonRelease-3>", self._shiftRightMouseUp)
        self.bind("<Control-Button-3>", lambda e: self.sub(100))

        self.bind("<Double-Button-1>", self._dadd1)
        self.bind("<Double-Button-3>", self._dsub1)
        self.bind("<Shift-Double-Button-1>", self._dadd10)
        self.bind("<Shift-Double-Button-3>", self._dsub10)
        self.bind("<Control-Double-Button-1>", self._dadd100)
        self.bind("<Control-Double-Button-3>", self._dsub100)

        self.bind("<Enter>", self._enter)

    def _leftMouseDown(self, event):
        self._leftMousePressed = True
        self._mouseJustPressed = True
        self._pollMouse()

    def _leftMouseUp(self, event):
        if self._leftMousePressed:
            self._leftMousePressed = False
            self.after_cancel(self.after_id)
        if self.checker:
            self.checker()

    def _shiftLeftMouseDown(self, event):
        self._shiftLeftMousePressed = True
        self._mouseJustPressed = True
        self._pollMouse()

    def _shiftLeftMouseUp(self, event):
        if self._shiftLeftMousePressed:
            self._shiftLeftMousePressed = False
            self.after_cancel(self.after_id)
        if self.checker:
            self.checker()

    def _rightMouseDown(self, event):
        self._rightMousePressed = True
        self._mouseJustPressed = True
        self._pollMouse()

    def _rightMouseUp(self, event):
        if self._rightMousePressed:
            self._rightMousePressed = False
            self.after_cancel(self.after_id)
        if self.checker:
            self.checker()

    def _shiftRightMouseDown(self, event):
        self._shiftRightMousePressed = True
        self._mouseJustPressed = True
        self._pollMouse()

    def _shiftRightMouseUp(self, event):
        if self._shiftRightMousePressed:
            self._shiftRightMousePressed = False
            self.after_cancel(self.after_id)
        if self.checker:
            self.checker()

    def _pollMouse(self):
        """
        Polls @10Hz, with a slight delay at the
        start.
        """
        if self._mouseJustPressed:
            delay = 300
            self._mouseJustPressed = False
        else:
            delay = 100

        if self._leftMousePressed:
            self.add(1)
            self.after_id = self.after(delay, self._pollMouse)

        if self._shiftLeftMousePressed:
            self.add(10)
            self.after_id = self.after(delay, self._pollMouse)

        if self._rightMousePressed:
            self.sub(1)
            self.after_id = self.after(delay, self._pollMouse)

        if self._shiftRightMousePressed:
            self.sub(10)
            self.after_id = self.after(delay, self._pollMouse)

    def set_unbind(self):
        """
        Unsets key bindings.
        """
        self.unbind("<Up>")
        self.unbind("<Down>")
        self.unbind("<Shift-Up>")
        self.unbind("<Shift-Down>")
        self.unbind("<Control-Up>")
        self.unbind("<Control-Down>")

        self.unbind("<Shift-Button-1>")
        self.unbind("<Shift-Button-3>")
        self.unbind("<Control-Button-1>")
        self.unbind("<Control-Button-3>")
        self.unbind("<ButtonPress-1>")
        self.unbind("<ButtonRelease-1>")
        self.unbind("<ButtonPress-3>")
        self.unbind("<ButtonRelease-3>")
        self.unbind("<Double-Button-1>")
        self.unbind("<Double-Button-3>")
        self.unbind("<Shift-Double-Button-1>")
        self.unbind("<shiftDouble-Button-3>")
        self.unbind("<Control-Double-Button-1>")
        self.unbind("<Control-Double-Button-3>")
        self.unbind("<Enter>")

    def _callback(self, *dummy):
        """
        This gets called on any attempt to change the value
        """
        # retrieve the value from the Entry
        value = self._variable.get()

        # run the validation. Returns None if no good
        newvalue = self.validate(value)

        if newvalue is None:
            # Invalid: restores previously stored value
            # no checker run.
            self._variable.set(self._value)

        elif newvalue != value:
            # If the value is different update appropriately
            # Store new value.
            self._value = newvalue
            self._variable.set(self.newvalue)
        else:
            # Store new value
            self._value = value

    # following are callbacks for bindings
    def _dadd1(self, event):
        self.add(1)
        return "break"

    def _dsub1(self, event):
        self.sub(1)
        return "break"

    def _dadd10(self, event):
        self.add(10)
        return "break"

    def _dsub10(self, event):
        self.sub(10)
        return "break"

    def _dadd100(self, event):
        self.add(100)
        return "break"

    def _dsub100(self, event):
        self.sub(100)
        return "break"

    def _enter(self, event):
        self.focus()
        self.icursor(tk.END)


class PosInt(IntegerEntry):
    """
    Provide positive or 0 integer input. Basically
    an IntegerEntry with one or two extras.
    """

    def set_bind(self):
        """
        Sets key bindings -- we need this more than once
        """
        IntegerEntry.set_bind(self)
        self.bind("<Next>", lambda e: self.set(0))

    def set_unbind(self):
        """
        Unsets key bindings -- we need this more than once
        """
        IntegerEntry.set_unbind(self)
        self.unbind("<Next>")

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            # trap blank fields here
            if not self.blank or value:
                v = int(value)
                if v < 0:
                    return None
            return value
        except ValueError:
            return None

    def add(self, num):
        """
        Adds num to the current value
        """
        try:
            val = self.value() + num
        except Exception:
            val = num
        self.set(max(0, val))

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num
        self.set(max(0, val))

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            v = int(self._value)
            if v < 0:
                return False
            else:
                return True
        except Exception:
            return False


class RangedInt(IntegerEntry):
    """
    Provides range-checked integer input.
    """

    def __init__(self, master, ival, imin, imax, checker, blank, **kw):
        """
        master  -- enclosing widget
        ival    -- initial integer value
        imin    -- minimum value
        imax    -- maximum value
        checker -- command that is run on any change to the entry
        blank   -- controls whether the field is allowed to be
                   blank. In some cases it makes things easier if
                   a blank field is allowed, even if it is technically
                   invalid.
        kw      -- keyword arguments
        """
        self.imin = imin
        self.imax = imax
        IntegerEntry.__init__(self, master, ival, checker, blank, **kw)
        self.bind("<Next>", lambda e: self.set(self.imin))
        self.bind("<Prior>", lambda e: self.set(self.imax))

    def set_bind(self):
        """
        Sets key bindings -- we need this more than once
        """
        IntegerEntry.set_bind(self)
        self.bind("<Next>", lambda e: self.set(self.imin))
        self.bind("<Prior>", lambda e: self.set(self.imax))

    def set_unbind(self):
        """
        Unsets key bindings -- we need this more than once
        """
        IntegerEntry.set_unbind(self)
        self.unbind("<Next>")
        self.unbind("<Prior>")

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            # trap blank fields here
            if not self.blank or value:
                v = int(value)
                if v < self.imin or v > self.imax:
                    return None
            return value
        except ValueError:
            return None

    def add(self, num):
        """
        Adds num to the current value
        """
        try:
            val = self.value() + num
        except Exception:
            val = num
        self.set(min(self.imax, max(self.imin, val)))

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num
        self.set(min(self.imax, max(self.imin, val)))

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            v = int(self._value)
            if v < self.imin or v > self.imax:
                return False
            else:
                return True
        except Exception:
            return False


class RangedMint(RangedInt):
    """
    This is the same as RangedInt but locks to multiples
    """

    def __init__(self, master, ival, imin, imax, mfac, checker, blank, **kw):
        """
        mfac must be class that support 'value()' to return an integer value.
        to allow it to be updated
        """
        self.mfac = mfac
        RangedInt.__init__(self, master, ival, imin, imax, checker, blank, **kw)
        self.unbind("<Next>")
        self.unbind("<Prior>")
        self.bind("<Next>", lambda e: self.set(self._min()))
        self.bind("<Prior>", lambda e: self.set(self._max()))

    def set_bind(self):
        """
        Sets key bindings -- we need this more than once
        """
        RangedInt.set_bind(self)
        self.unbind("<Next>")
        self.unbind("<Prior>")
        self.bind("<Next>", lambda e: self.set(self._min()))
        self.bind("<Prior>", lambda e: self.set(self._max()))

    def set_unbind(self):
        """
        Sets key bindings -- we need this more than once
        """
        RangedInt.set_unbind(self)
        self.unbind("<Next>")
        self.unbind("<Prior>")

    def add(self, num):
        """
        Adds num to the current value, jumping up the next
        multiple of mfac if the result is not a multiple already
        """
        try:
            val = self.value() + num
        except Exception:
            val = num

        chunk = self.mfac.value()
        if val % chunk > 0:
            if num > 0:
                val = chunk * (val // chunk + 1)
            elif num < 0:
                val = chunk * (val // chunk)

        val = max(self._min(), min(self._max(), val))
        self.set(val)

    def sub(self, num):
        """
        Subtracts num from the current value, forcing the result to be within
        range and a multiple of mfac
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num

        chunk = self.mfac.value()
        if val % chunk > 0:
            if num > 0:
                val = chunk * (val // chunk)
            elif num < 0:
                val = chunk * (val // chunk + 1)

        val = max(self._min(), min(self._max(), val))
        self.set(val)

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            v = int(self._value)
            chunk = self.mfac.value()
            if v < self.imin or v > self.imax or (v % chunk != 0):
                return False
            else:
                return True
        except Exception:
            return False

    def _min(self):
        chunk = self.mfac.value()
        mval = chunk * (self.imin // chunk)
        return mval + chunk if mval < self.imin else mval

    def _max(self):
        chunk = self.mfac.value()
        return chunk * (self.imax // chunk)


class ListInt(IntegerEntry):
    """
    Provides integer input allowing only a finite list of integers.
    Needed for the binning factors.
    """

    def __init__(self, master, ival, allowed, checker, **kw):
        """
        master  -- enclosing widget
        ival    -- initial integer value
        allowed -- list of allowed values. Will be checked for uniqueness
        checker -- command that is run on any change to the entry
        kw      -- keyword arguments
        """
        if ival not in allowed:
            raise DriverError(
                "utils.widgets.ListInt: value = "
                + str(ival)
                + " not in list of allowed values."
            )
        if len(set(allowed)) != len(allowed):
            raise DriverError(
                "utils.widgets.ListInt: not all values unique" + " in allowed list."
            )

        # we need to maintain an index of which integer has been selected
        self.allowed = allowed
        self.index = allowed.index(ival)
        IntegerEntry.__init__(self, master, ival, checker, False, **kw)
        self.set_bind()

    def set_bind(self):
        """
        Sets key bindings -- we need this more than once
        """
        IntegerEntry.set_bind(self)
        self.unbind("<Shift-Up>")
        self.unbind("<Shift-Down>")
        self.unbind("<Control-Up>")
        self.unbind("<Control-Down>")
        self.unbind("<Double-Button-1>")
        self.unbind("<Double-Button-3>")
        self.unbind("<Shift-Button-1>")
        self.unbind("<Shift-Button-3>")
        self.unbind("<Control-Button-1>")
        self.unbind("<Control-Button-3>")

        self.bind("<Button-1>", lambda e: self.add(1))
        self.bind("<Button-3>", lambda e: self.sub(1))
        self.bind("<Up>", lambda e: self.add(1))
        self.bind("<Down>", lambda e: self.sub(1))
        self.bind("<Enter>", self._enter)
        self.bind("<Next>", lambda e: self.set(self.allowed[0]))
        self.bind("<Prior>", lambda e: self.set(self.allowed[-1]))

    def set_unbind(self):
        """
        Unsets key bindings -- we need this more than once
        """
        IntegerEntry.set_unbind(self)
        self.unbind("<Button-1>")
        self.unbind("<Button-3>")
        self.unbind("<Up>")
        self.unbind("<Down>")
        self.unbind("<Enter>")
        self.unbind("<Next>")
        self.unbind("<Prior>")

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            v = int(value)
            if v not in self.allowed:
                return None
            return value
        except ValueError:
            return None

    def set(self, num):
        """
        Sets current value to num
        """
        if self.validate(num) is not None:
            self.index = self.allowed.index(num)
        IntegerEntry.set(self, num)

    def add(self, num):
        """
        Adds num to the current value
        """
        self.index = max(0, min(len(self.allowed) - 1, self.index + num))
        self.set(self.allowed[self.index])

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        self.index = max(0, min(len(self.allowed) - 1, self.index - num))
        self.set(self.allowed[self.index])

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        return True


class FloatEntry(tk.Entry):
    """
    Defines an Entry field which only accepts floating point input.
    """

    def __init__(self, master, fval, checker, blank, **kw):
        """
        master  -- enclosing widget
        ival    -- initial integer value
        checker -- command that is run on any change to the entry
        blank   -- controls whether the field is allowed to be
                   blank. In some cases it makes things easier if
                   a blank field is allowed, even if it is technically
                   invalid (the latter case requires some other checking)
        kw      -- optional keyword arguments that can be used for
                   an Entry. If 'nplaces' argument is set, precision
                   of FloatEntry will be limited to nplaces decimal places.
        """
        # important to set the value of _variable before tracing it
        # to avoid immediate run of _callback.
        np = kw.pop("nplaces", 8)
        tk.Entry.__init__(self, master, **kw)
        self._variable = tk.StringVar()
        self.nplaces = np
        self._value = str(round(float(fval), self.nplaces))
        self._variable.set(self._value)
        self._variable.trace_add("write", self._callback)
        self.config(textvariable=self._variable)
        self.checker = checker
        self.blank = blank
        self.set_bind()

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            # trap blank fields here
            if not self.blank or value:
                float(value)
            return value
        except ValueError:
            return None

    def value(self):
        """
        Returns float value, if possible, None if not.
        """
        try:
            return float(self._value)
        except Exception:
            return None

    def set(self, num):
        """
        Sets the current value equal to num
        """
        self._value = str(round(float(num), self.nplaces))
        self._variable.set(self._value)

    def add(self, num):
        """
        Adds num to the current value
        """
        try:
            val = self.value() + num
        except Exception:
            val = num
        self.set(val)

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num
        self.set(val)

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            float(self._value)
            return True
        except Exception:
            return False

    def enable(self):
        self.configure(state="normal")
        self.set_bind()

    def disable(self):
        self.configure(state="disable")
        self.set_unbind()

    def set_bind(self):
        """
        Sets key bindings.
        """
        self.bind("<Button-1>", lambda e: self.add(0.1))
        self.bind("<Button-3>", lambda e: self.sub(0.1))
        self.bind("<Up>", lambda e: self.add(0.1))
        self.bind("<Down>", lambda e: self.sub(0.1))
        self.bind("<Shift-Up>", lambda e: self.add(1))
        self.bind("<Shift-Down>", lambda e: self.sub(1))
        self.bind("<Control-Up>", lambda e: self.add(10))
        self.bind("<Control-Down>", lambda e: self.sub(10))
        self.bind("<Double-Button-1>", self._dadd)
        self.bind("<Double-Button-3>", self._dsub)
        self.bind("<Shift-Button-1>", lambda e: self.add(1))
        self.bind("<Shift-Button-3>", lambda e: self.sub(1))
        self.bind("<Control-Button-1>", lambda e: self.add(10))
        self.bind("<Control-Button-3>", lambda e: self.sub(10))
        self.bind("<Enter>", self._enter)

    def set_unbind(self):
        """
        Unsets key bindings.
        """
        self.unbind("<Button-1>")
        self.unbind("<Button-3>")
        self.unbind("<Up>")
        self.unbind("<Down>")
        self.unbind("<Shift-Up>")
        self.unbind("<Shift-Down>")
        self.unbind("<Control-Up>")
        self.unbind("<Control-Down>")
        self.unbind("<Double-Button-1>")
        self.unbind("<Double-Button-3>")
        self.unbind("<Shift-Button-1>")
        self.unbind("<Shift-Button-3>")
        self.unbind("<Control-Button-1>")
        self.unbind("<Control-Button-3>")
        self.unbind("<Enter>")

    def _callback(self, *dummy):
        """
        This gets called on any attempt to change the value
        """
        # retrieve the value from the Entry
        value = self._variable.get()

        # run the validation. Returns None if no good
        newvalue = self.validate(value)

        if newvalue is None:
            # Invalid: restores previously stored value
            # no checker run.
            self._variable.set(self._value)

        elif newvalue != value:
            # If the value is different update appropriately
            # Store new value.
            self._value = newvalue
            self._variable.set(self.newvalue)
            if self.checker:
                self.checker(*dummy)
        else:
            # Store new value
            self._value = value
            if self.checker:
                self.checker(*dummy)

    # following are callbacks for bindings
    def _dadd(self, event):
        self.add(0.1)
        return "break"

    def _dsub(self, event):
        self.sub(0.1)
        return "break"

    def _enter(self, event):
        self.focus()
        self.icursor(tk.END)


class RangedFloat(FloatEntry):
    """
    Provides range-checked float input.
    """

    def __init__(self, master, fval, fmin, fmax, checker, blank, allowzero=False, **kw):
        """
        master    -- enclosing widget
        fval      -- initial float value
        fmin      -- minimum value
        fmax      -- maximum value
        checker   -- command that is run on any change to the entry
        blank     -- controls whether the field is allowed to be
                   blank. In some cases it makes things easier if
                   a blank field is allowed, even if it is technically
                   invalid.
        allowzero -- if 0 < fmin < 1 input of numbers in the range fmin to 1
                     can be difficult unless 0 is allowed even though it is
                     an invalid value.
        kw        -- keyword arguments
        """
        self.fmin = fmin
        self.fmax = fmax
        FloatEntry.__init__(self, master, fval, checker, blank, **kw)
        self.bind("<Next>", lambda e: self.set(self.fmin))
        self.bind("<Prior>", lambda e: self.set(self.fmax))
        self.allowzero = allowzero

    def set_bind(self):
        """
        Sets key bindings -- we need this more than once
        """
        FloatEntry.set_bind(self)
        self.bind("<Next>", lambda e: self.set(self.fmin))
        self.bind("<Prior>", lambda e: self.set(self.fmax))

    def set_unbind(self):
        """
        Unsets key bindings -- we need this more than once
        """
        FloatEntry.set_unbind(self)
        self.unbind("<Next>")
        self.unbind("<Prior>")

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.

        Overload this in derived classes.
        """
        try:
            # trap blank fields here
            if not self.blank or value:
                v = float(value)
                if (
                    (self.allowzero and v != 0 and v < self.fmin)
                    or (not self.allowzero and v < self.fmin)
                    or v > self.fmax
                ):
                    return None
            return value
        except ValueError:
            return None

    def add(self, num):
        """
        Adds num to the current value
        """
        try:
            val = self.value() + num
        except Exception:
            val = num
        self.set(min(self.fmax, max(self.fmin, val)))

    def sub(self, num):
        """
        Subtracts num from the current value
        """
        try:
            val = self.value() - num
        except Exception:
            val = -num
        self.set(min(self.fmax, max(self.fmin, val)))

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            v = float(self._value)
            if v < self.fmin or v > self.fmax:
                return False
            else:
                return True
        except Exception:
            return False


class TextEntry(tk.Entry):
    """
    Sub-class of Entry for basic text input. Not a lot to
    it but it keeps things neater and it has a check for
    blank entries.
    """

    def __init__(self, master, width, callback=None):
        """
        master  : the widget this gets placed inside
        """  # Define a StringVar, connect it to the callback, if there is one
        self.val = tk.StringVar()
        if callback is not None:
            self.val.trace_add("write", callback)
        tk.Entry.__init__(self, master, textvariable=self.val, width=width)
        # get globals
        g = get_root(self).globals
        self.config(fg=g.COL["text"], bg=g.COL["main"])
        # Control input behaviour.
        self.bind("<Enter>", lambda e: self.focus())

    def value(self):
        """
        Returns value.
        """
        return self.val.get()

    def set(self, text):
        """
        Returns value.
        """
        return self.val.set(text)

    def ok(self):
        if self.value() == "" or self.value().isspace():
            return False
        else:
            return True


class Choice(tk.OptionMenu):
    """
    Menu choice class.
    """

    def __init__(self, master, options, initial=None, width=0, checker=None):
        """
        master  : containing widget
        options : list of strings
        initial : the initial one to select. If None will default to the first.
        width   : minimum character width to use. Width set will be large
                  enough for longest option.
        checker : callback to run on any change of selection.
        """

        self.val = tk.StringVar()
        if initial is None:
            self.val.set(options[0])
        else:
            self.val.set(initial)
        tk.OptionMenu.__init__(self, master, self.val, *options)
        width = max(width, reduce(max, [len(s) for s in options]))
        g = get_root(self).globals
        self.config(width=width, font=g.ENTRY_FONT)
        self.checker = checker
        if self.checker is not None:
            self.val.trace_add("write", self.checker)
        self.options = options

    def update(self, new_options):
        """
        Update option list with new options
        """
        menu = self["menu"]
        # clear the menu
        menu.delete(0, "end")
        for option in new_options:
            menu.add_command(label=option, command=partial(self.val.set, option))

    def value(self):
        return self.val.get()

    def set(self, choice):
        return self.val.set(choice)

    def disable(self):
        self.configure(state="disable")

    def enable(self):
        self.configure(state="normal")

    def getIndex(self):
        """
        Returns the index of the selected choice,
        Throws a ValueError if the set value is not
        one of the options.
        """
        return self.options.index(self.val.get())


class Expose(RangedFloat):
    """
    Special entry field for exposure times designed to return
    an integer number of 0.01ms increments.
    """

    def __init__(self, master, fval, fmin, fmax, checker, **kw):
        """
        master  -- enclosing widget
        fval    -- initial value, seconds
        fmin    -- minimum value, seconds
        fmax    -- maximum value, seconds
        checker -- command that is run on any change to the entry

        fval, fmin and fmax must be multiples of 0.00001
        """
        if abs(round(100000 * fval) - 100000 * fval) > 1.0e-12:
            raise DriverError(
                "utils.widgets.Expose.__init__: fval must be a multiple of 0.00001"
            )
        if abs(round(100000 * fmin) - 100000 * fmin) > 1.0e-12:
            raise DriverError(
                "utils.widgets.Expose.__init__: fmin must be a multiple of 0.00001"
            )
        if abs(round(100000 * fmax) - 100000 * fmax) > 1.0e-12:
            raise DriverError(
                "utils.widgets.Expose.__init__: fmax must be a multiple of 0.00001"
            )
        kw["nplaces"] = 5
        RangedFloat.__init__(self, master, fval, fmin, fmax, checker, True, **kw)

    def validate(self, value):
        """
        This prevents setting any value more precise than 0.00001
        """
        try:
            # trap blank fields here
            if value:
                v = float(value)
                if (v != 0 and v < self.fmin) or v > self.fmax:
                    return None
                if abs(round(100000 * v) - 100000 * v) > 1.0e-12:
                    return None
            return value
        except ValueError:
            return None

    def ivalue(self):
        """
        Returns integer value in units of 0.01ms, if possible, None if not.
        """
        try:
            return int(round(100000 * float(self._value)))
        except Exception:
            return None

    def set_min(self, fmin):
        """
        Updates minimum value
        """
        if round(100000 * fmin) != 100000 * fmin:
            raise DriverError(
                "utils.widgets.Expose.set_min: " + "fmin must be a multiple of 0.00001"
            )
        self.fmin = fmin
        self.set(self.fmin)


class Radio(tk.Frame):
    """
    Left-to-right radio button class. Lays out buttons in a grid
    from left-to-right. Has a max number of columns after which it
    will jump to left of next row and start over.
    """

    def __init__(self, master, options, ncmax, checker=None, values=None, initial=0):
        """
        master : containing widget
        options : array of option strings, in order. These are the choices
        presented to the user.
        ncmax : max number of columns (flows onto next row if need be)
        checker : callback to be run after any change
        values : array of string values used by the code internally.
        If 'None', the value from 'options' will be used.
        initial : index of initial value to set.
        """
        tk.Frame.__init__(self, master)
        # get globals from root widget
        g = get_root(self).globals
        if values is not None and len(values) != len(options):
            raise DriverError(
                "utils.widgets.Radio.__init__: values and "
                + "options must have same length"
            )

        self.val = tk.StringVar()
        if values is None:
            self.val.set(options[initial])
        else:
            self.val.set(values[initial])

        row = 0
        col = 0
        self.buttons = []
        for nopt, option in enumerate(options):
            if values is None:
                self.buttons.append(
                    tk.Radiobutton(
                        self,
                        text=option,
                        variable=self.val,
                        font=g.ENTRY_FONT,
                        value=option,
                    )
                )
                self.buttons[-1].grid(row=row, column=col, sticky=tk.W)
            else:
                self.buttons.append(
                    tk.Radiobutton(
                        self,
                        text=option,
                        variable=self.val,
                        font=g.ENTRY_FONT,
                        value=values[nopt],
                    )
                )
                self.buttons[-1].grid(row=row, column=col, sticky=tk.W)
            col += 1
            if col == ncmax:
                row += 1
                col = 0

        self.checker = checker
        if self.checker is not None:
            self.val.trace_add("write", self.checker)
        self.options = options

    def value(self):
        return self.val.get()

    def set(self, choice):
        self.val.set(choice)

    def disable(self):
        for b in self.buttons:
            b.configure(state="disable")

    def enable(self):
        for b in self.buttons:
            b.configure(state="normal")

    def getIndex(self):
        """
        Returns the index of the selected choice,
        Throws a ValueError if the set value is not
        one of the options.
        """
        return self.options.index(self.val.get())


class OnOff(tk.Checkbutton):
    """
    On or Off choice
    """

    def __init__(self, master, value, checker=None):
        self.val = tk.IntVar()
        self.val.set(value)
        tk.Checkbutton.__init__(self, master, variable=self.val, command=checker)

    def __call__(self):
        return self.val.get()

    def disable(self):
        self.configure(state="disable")

    def enable(self):
        self.configure(state="normal")

    def set(self, state):
        self.val.set(state)


class Select(tk.OptionMenu):
    """
    Dropdown box menu for selection
    """

    def __init__(self, master, initial_index, options, checker=None):
        self.val = tk.StringVar()
        self.options = options
        self.val.set(options[initial_index])
        tk.OptionMenu.__init__(self, master, self.val, *options, command=checker)

    def __call__(self):
        return self.val.get()

    def disable(self):
        self.configure(state="disable")

    def enable(self):
        self.configure(state="normal")

    def set(self, value):
        if value not in self.options:
            raise ValueError(
                "{0} not one of the possible options: {1!r}".format(value, self.options)
            )
        self.val.set(value)


class GuiLogger(Logger, tk.Frame):
    """
    Defines a GUI logger, a combination of Logger and a Frame

     logname : unique name for logger
     root    : the root widget the LabelFrame descends from
     height  : height in pixels
     width   : width in pixels

    """

    def __init__(self, logname, root, height, width):
        # configure the Logger
        Logger.__init__(self, logname)

        # configure the LabelFrame
        tk.Frame.__init__(self, root)

        g = get_root(self).globals
        scrollbar = tk.Scrollbar(self)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        twidget = tk.Text(
            self,
            height=height,
            width=width,
            bg=g.COL["log"],
            yscrollcommand=scrollbar.set,
        )
        twidget.configure(state=tk.DISABLED)
        twidget.pack(side=tk.LEFT)
        scrollbar.config(command=twidget.yview)

        # create and add a handler for the GUI
        self._log.addHandler(GuiHandler(twidget))


class LabelGuiLogger(Logger, tk.LabelFrame):
    """
    Defines a GUI logger, a combination of Logger and a LabelFrame

     logname : unique name for logger
     root    : the root widget the LabelFrame descends from
     height  : height in pixels
     width   : width in pixels
     label   : label for the LabelFrame

    """

    def __init__(self, logname, root, height, width, label):
        # configure the Logger
        Logger.__init__(self, logname)

        # configure the LabelFrame
        tk.LabelFrame.__init__(self, root, text=label)

        g = get_root(self).globals
        scrollbar = tk.Scrollbar(self)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        twidget = tk.Text(
            self,
            height=height,
            width=width,
            bg=g.COL["log"],
            yscrollcommand=scrollbar.set,
        )
        twidget.configure(state=tk.DISABLED)
        twidget.pack(side=tk.LEFT)
        scrollbar.config(command=twidget.yview)

        # create and add a handler for the GUI
        self._log.addHandler(GuiHandler(twidget))


class ActButton(tk.Button):
    """
    Base class for action buttons. This keeps an internal flag
    representing whether the button should be active or not.
    Whether it actually is, might be overridden, but the internal
    flag tracks the (potential) activity status allowing it to be
    reset. The 'expert' flag controls whether the activity status
    will be overridden. The button starts out in non-expert mode by
    default. This can be switched with setExpert, setNonExpert.
    """

    def __init__(self, master, width, callback=None, **kwargs):
        """
        master   : containing widget
        width    : width in characters of the button
        callback : function that is called when button is pressed
        bg       : background colour
        kwargs   : keyword arguments
        """
        tk.Button.__init__(
            self, master, fg="black", width=width, command=self.act, **kwargs
        )

        # store some attributes. other anc calbback are obvious.
        # _active indicates whether the button should be enabled or disabled
        # _expert indicates whether the activity state should be overridden so
        #         that the button is enabled in any case (if set True)
        self.callback = callback
        self._active = True
        self._expert = False

    def enable(self):
        """
        Enable the button, set its activity flag.
        """
        self.config(state="normal")
        self._active = True

    def disable(self):
        """
        Disable the button, if in non-expert mode;
        unset its activity flag come-what-may.
        """
        if not self._expert:
            self.config(state="disable")
        self._active = False

    def setExpert(self):
        """
        Turns on 'expert' status whereby the button is always enabled,
        regardless of its activity status.
        """
        self._expert = True
        self.configure(state="normal")

    def setNonExpert(self):
        """
        Turns off 'expert' status whereby to allow a button to be disabled
        """
        self._expert = False
        if self._active:
            self.enable()
        else:
            self.disable()

    def act(self):
        """
        Carry out the action associated with the button.
        Override in derived classes
        """
        self.callback()


class Ilabel(tk.Label):
    """
    Class to define an information label which uses the same font
    as the entry fields rather than the default font
    """

    def __init__(self, master, **kw):
        tk.Label.__init__(self, master, **kw)
        g = get_root(self).globals
        self.config(font=g.ENTRY_FONT)


class PABox(RangedFloat):
    """
    A float that wraps at 360 deg
    """

    def set(self, value):
        new_val = coord.Longitude(value * u.deg).deg
        RangedFloat.set(self, new_val)


class Sexagesimal(tk.Entry):
    """
    Widget for coordinate entry
    """

    def __init__(self, master, ival=0, callback=None, unit="hms", **kw):
        tk.Entry.__init__(self, master, **kw)
        if unit == "hms":
            self.unit = u.hourangle
        else:
            self.unit = u.deg
        # variable is the thing that's shown in the widget
        self._variable = tk.StringVar()
        # value is the thing that tracks the value, and has a unit
        self._value = coord.Angle(ival, unit=u.deg)
        self._variable.set(self.as_string())
        self._variable.trace_add("write", self._callback)
        self.config(textvariable=self._variable)
        self.checker = callback
        self.set_unbind()
        self.set_bind()

    def as_string(self):
        if self.unit == u.hourangle:
            return self._value.to_string(unit=self.unit, sep=":", precision=2)
        else:
            return self._value.to_string(
                unit=self.unit, sep=":", precision=1, alwayssign=True
            )

    def validate(self, value):
        """
        Applies the validation criteria.
        Returns value, new value, or None if invalid.
        """
        try:
            coord.Angle(value, unit=self.unit)
            return value
        except ValueError:
            return None

    def value(self):
        """
        Returns float value in degrees, if possible, None if not.
        """
        try:
            return self._value.deg
        except Exception:
            return None

    def set(self, num):
        """
        Sets the current value equal to num
        """
        self._value = coord.Angle(num, unit=u.deg)
        self._variable.set(self.as_string())

    @u.quantity_input(quantity=u.deg)
    def add(self, quantity):
        """
        Adds an angle to the value
        """
        newvalue = self._value + quantity
        self.set(newvalue.deg)

    @u.quantity_input(quantity=u.deg)
    def sub(self, quantity):
        """
        Subtracts an angle from the value
        """
        newvalue = self._value - quantity
        self.set(newvalue.deg)

    def ok(self):
        """
        Returns True if OK to use, else False
        """
        try:
            coord.Angle(self._value, unit=u.deg)
            return True
        except ValueError:
            return False

    def enable(self):
        self.configure(state="normal")
        self.set_bind()

    def disable(self):
        self.configure(state="disable")
        self.set_unbind()

    def set_bind(self):
        """
        Sets key bindings.
        """
        self.bind("<Button-1>", lambda e: self.add(0.1 * u.arcsec))
        self.bind("<Button-3>", lambda e: self.sub(0.1 * u.arcsec))
        self.bind("<Up>", lambda e: self.add(0.1 * u.arcsec))
        self.bind("<Down>", lambda e: self.sub(0.1 * u.arcsec))
        self.bind("<Shift-Up>", lambda e: self.add(1 * u.arcsec))
        self.bind("<Shift-Down>", lambda e: self.sub(1 * u.arcsec))
        self.bind("<Control-Up>", lambda e: self.add(10 * u.arcsec))
        self.bind("<Control-Down>", lambda e: self.sub(10 * u.arcsec))
        self.bind("<Double-Button-1>", self._dadd)
        self.bind("<Double-Button-3>", self._dsub)
        self.bind("<Shift-Button-1>", lambda e: self.add(1 * u.arcsec))
        self.bind("<Shift-Button-3>", lambda e: self.sub(1 * u.arcsec))
        self.bind("<Control-Button-1>", lambda e: self.add(10 * u.arcsec))
        self.bind("<Control-Button-3>", lambda e: self.sub(10 * u.arcsec))
        self.bind("<Enter>", self._enter)

    def set_unbind(self):
        """
        Unsets key bindings.
        """
        self.unbind("<Button-1>")
        self.unbind("<Button-3>")
        self.unbind("<Up>")
        self.unbind("<Down>")
        self.unbind("<Shift-Up>")
        self.unbind("<Shift-Down>")
        self.unbind("<Control-Up>")
        self.unbind("<Control-Down>")
        self.unbind("<Double-Button-1>")
        self.unbind("<Double-Button-3>")
        self.unbind("<Shift-Button-1>")
        self.unbind("<Shift-Button-3>")
        self.unbind("<Control-Button-1>")
        self.unbind("<Control-Button-3>")
        self.unbind("<Enter>")

    def _callback(self, *dummy):
        """
        This gets called on any attempt to change the value
        """
        # retrieve the value from the Entry
        value = self._variable.get()
        # run the validation. Returns None if no good
        newvalue = self.validate(value)
        if newvalue is None:
            # Invalid: restores previously stored value
            # no checker run.
            self._variable.set(self.as_string())
        else:
            # Store new value
            self._value = coord.Angle(value, unit=self.unit)
            if self.checker:
                self.checker(*dummy)

    # following are callbacks for bindings
    def _dadd(self, event):
        self.add(0.1 * u.arcsec)
        return "break"

    def _dsub(self, event):
        self.sub(0.1 * u.arcsec)
        return "break"

    def _enter(self, event):
        self.focus()
        self.icursor(tk.END)


class ProgramID(tk.Frame):
    """
    Class to combine the ProgramID and OB number.

    This is a text entry field and a PosInt widget bound together.
    The point of this widget is simply to get a nice layout.
    """

    def __init__(self, master):
        tk.Frame.__init__(self, master)
        self.master = master
        check = master.check if hasattr(master, "check") else None
        self.progid = TextEntry(self, 20, check)
        self.obid = PosInt(self, 1, check, True, width=4)

        self.progid.pack(side=tk.LEFT, anchor=tk.W)
        tk.Label(self, text="/").pack(side=tk.LEFT, anchor=tk.W, padx=2)
        self.obid.pack(side=tk.LEFT, anchor=tk.W, padx=2)

    def disable(self):
        self.obid.disable()

    def enable(self):
        self.obid.enable()

    def ok(self):
        return self.progid.ok() & self.obid.ok()

    def configure(self, **kwargs):
        self.progid.configure(**kwargs)
        self.obid.configure(**kwargs)


class Target(tk.Frame):
    """
    Class wrapping up what is needed for a target name which
    is an entry field and a verification button. The verification
    button checks for simbad recognition and goes green or red
    according to the results. If no check has been made, it has
    a default colour.
    """

    def __init__(self, master, callback=None):
        tk.Frame.__init__(self, master)

        g = get_root(self).globals

        # Entry field, linked to a StringVar which is traced for
        # any modification
        self.val = tk.StringVar()
        self.val.trace_add("write", self.modver)
        self.entry = tk.Entry(
            self, textvariable=self.val, fg=g.COL["text"], bg=g.COL["main"], width=25
        )
        self.entry.bind("<Enter>", lambda e: self.entry.focus())

        # Verification button which accesses simbad to see if
        # the target is recognised.
        self.verify = tk.Button(
            self, fg="black", width=8, text="Verify", bg=g.COL["main"], command=self.act
        )
        self.entry.pack(side=tk.LEFT, anchor=tk.W)
        self.verify.pack(side=tk.LEFT, anchor=tk.W, padx=5)
        self.verify.config(state="disable")
        # track successed and failures
        self.successes = []
        self.failures = []
        self.callback = callback

    def value(self):
        """
        Returns value.
        """
        return self.val.get()

    def set(self, text):
        """
        Sets value.
        """
        return self.val.set(text)

    def disable(self):
        self.entry.configure(state="disable")
        g = get_root(self).globals
        if self.ok():
            tname = self.val.get()
            if tname in self.successes:
                # known to be in simbad
                self.verify.config(bg=g.COL["startD"])
            elif tname in self.failures:
                # known not to be in simbad
                self.verify.config(bg=g.COL["stopD"])
            else:
                # not known whether in simbad
                self.verify.config(bg=g.COL["main"])
        else:
            self.verify.config(bg=g.COL["main"])
        self.verify.config(state="disable")

    def enable(self):
        self.entry.configure(state="normal")
        g = get_root(self).globals
        if self.ok():
            tname = self.val.get()
            if tname in self.successes:
                # known to be in simbad
                self.verify.config(bg=g.COL["start"])
            elif tname in self.failures:
                # known not to be in simbad
                self.verify.config(bg=g.COL["stop"])
            else:
                # not known whether in simbad
                self.verify.config(bg=g.COL["main"])
        else:
            self.verify.config(bg=g.COL["main"])
        self.verify.config(state="normal")

    def ok(self):
        if self.val.get() == "" or self.val.get().isspace():
            return False
        else:
            return True

    def modver(self, *args):
        """
        Switches colour of verify button
        """
        g = get_root(self).globals
        if self.ok():
            tname = self.val.get()
            if tname in self.successes:
                # known to be in simbad
                self.verify.config(bg=g.COL["start"])
            elif tname in self.failures:
                # known not to be in simbad
                self.verify.config(bg=g.COL["stop"])
            else:
                # not known whether in simbad
                self.verify.config(bg=g.COL["main"])
            self.verify.config(state="normal")
        else:
            self.verify.config(bg=g.COL["main"])
            self.verify.config(state="disable")

        if self.callback is not None:
            self.callback()

    def act(self):
        """
        Carries out the action associated with Verify button
        """
        tname = self.val.get()
        g = get_root(self).globals
        g.clog.info("Checking " + tname + " in simbad")
        try:
            ret = checkSimbad(g, tname)
            if len(ret) == 0:
                self.verify.config(bg=g.COL["stop"])
                g.clog.warn('No matches to "' + tname + '" found.')
                if tname not in self.failures:
                    self.failures.append(tname)
            elif len(ret) == 1:
                self.verify.config(bg=g.COL["start"])
                g.clog.info(tname + " verified OK in simbad")
                g.clog.info("Primary simbad name = " + ret[0]["Name"])
                if tname not in self.successes:
                    self.successes.append(tname)
            else:
                g.clog.warn('More than one match to "' + tname + '" found')
                self.verify.config(bg=g.COL["stop"])
                if tname not in self.failures:
                    self.failures.append(tname)
        except urllib.error.URLError:
            g.clog.warn("Simbad lookup timed out")
        except socket.timeout:
            g.clog.warn("Simbad lookup timed out")


class TelChooser(tk.Menu):
    """
    Provides a menu to choose the telescope.

    The telescope setting affects the signal/noise calculations
    and routines for pulling RA/Dec etc from the TCS.
    """

    def __init__(self, master, *args):
        """
        Parameters
        ----------
        master : tk.Widget
            the containing widget, .e.g toolbar menu
        """
        tk.Menu.__init__(self, master, tearoff=0)
        g = get_root(self).globals

        self.val = tk.StringVar()
        tel = g.cpars.get("telins_name", list(g.TINS)[0])
        self.val.set(tel)
        self.val.trace_add("write", self._change)
        for tel_name in g.TINS.keys():
            self.add_radiobutton(label=tel_name, value=tel_name, variable=self.val)
        self.args = args
        self.root = master

    def _change(self, *args):
        g = get_root(self).globals
        g.cpars["telins_name"] = self.val.get()
        g.count.update()
        g.ipars.check()


class ExpertMenu(tk.Menu):
    """
    Provides a menu to select the level of expertise wanted
    when interacting with a control GUI. This setting might
    be used to hide buttons for instance according to
    the status of others, etc. Use ExpertMenu.indices
    to pass a set of indices of the master menu which get
    enabled or disabled according to the expert level (disabled
    at level 0, otherwise enabled)
    """

    def __init__(self, master, *args):
        """
        master   -- the containing widget, e.g. toolbar menu
        args     -- other objects that have a 'setExpertLevel()' method.
        """
        tk.Menu.__init__(self, master, tearoff=0)
        g = get_root(self).globals

        self.val = tk.IntVar()
        self.val.set(g.cpars["expert_level"])
        self.val.trace_add("write", self._change)
        self.add_radiobutton(label="Level 0", value=0, variable=self.val)
        self.add_radiobutton(label="Level 1", value=1, variable=self.val)
        self.add_radiobutton(label="Level 2", value=2, variable=self.val)
        self.args = args
        self.root = master
        self.indices = []

    def _change(self, *args):
        g = get_root(self).globals
        g.cpars["expert_level"] = self.val.get()
        for arg in self.args:
            arg.setExpertLevel()
        for index in self.indices:
            if g.cpars["expert_level"]:
                self.root.entryconfig(index, state=tk.NORMAL)
            else:
                self.root.entryconfig(index, state=tk.DISABLED)


class AstroFrame(tk.LabelFrame):
    """
    Astronomical information frame
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, padx=2, pady=2, text="Time & Sky")

        # times
        self.mjd = Ilabel(self)
        self.utc = Ilabel(self, width=9, anchor=tk.W)
        self.lst = Ilabel(self)

        # sun info
        self.sunalt = Ilabel(self, width=11, anchor=tk.W)
        self.riset = Ilabel(self)
        self.lriset = Ilabel(self)
        self.astro = Ilabel(self)

        # moon info
        self.moonra = Ilabel(self)
        self.moondec = Ilabel(self)
        self.moonalt = Ilabel(self)
        self.moonphase = Ilabel(self)

        # observatory info
        g = get_root(self).globals
        tins = g.TINS[g.cpars["telins_name"]]
        lat = tins["latitude"]
        lon = tins["longitude"]
        elevation = tins["elevation"]
        self.obs = coord.EarthLocation.from_geodetic(
            lon * u.deg, lat * u.deg, elevation * u.m
        )
        # report back to the user
        g.clog.info("Tel/ins = " + g.cpars["telins_name"])
        g.clog.info("Longitude = " + str(tins["longitude"]) + " E")
        g.clog.info("Latitude = " + str(tins["latitude"]) + " N")
        g.clog.info("Elevation = " + str(tins["elevation"]) + " m")

        # arrange time info
        tk.Label(self, text="MJD:").grid(row=0, column=0, padx=2, pady=3, sticky=tk.W)
        self.mjd.grid(row=0, column=1, columnspan=2, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="UTC:").grid(row=0, column=3, padx=2, pady=3, sticky=tk.W)
        self.utc.grid(row=0, column=4, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="LST:").grid(row=0, column=5, padx=2, pady=3, sticky=tk.W)
        self.lst.grid(row=0, column=6, padx=2, pady=3, sticky=tk.W)

        # arrange solar info
        tk.Label(self, text="Sun:").grid(row=1, column=0, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="Alt:").grid(row=1, column=1, padx=2, pady=3, sticky=tk.W)
        self.sunalt.grid(row=1, column=2, padx=2, pady=3, sticky=tk.W)
        self.lriset.grid(row=1, column=3, padx=2, pady=3, sticky=tk.W)
        self.riset.grid(row=1, column=4, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="At -18:").grid(
            row=1, column=5, padx=2, pady=3, sticky=tk.W
        )
        self.astro.grid(row=1, column=6, padx=2, pady=3, sticky=tk.W)

        # arrange moon info
        tk.Label(self, text="Moon:").grid(row=2, column=0, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="RA:").grid(row=2, column=1, padx=2, pady=3, sticky=tk.W)
        self.moonra.grid(row=2, column=2, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="Dec:").grid(row=3, column=1, padx=2, sticky=tk.W)
        self.moondec.grid(row=3, column=2, padx=2, sticky=tk.W)
        tk.Label(self, text="Alt:").grid(row=2, column=3, padx=2, pady=3, sticky=tk.W)
        self.moonalt.grid(row=2, column=4, padx=2, pady=3, sticky=tk.W)
        tk.Label(self, text="Phase:").grid(row=3, column=3, padx=2, sticky=tk.W)
        self.moonphase.grid(row=3, column=4, padx=2, sticky=tk.W)

        # parameters used to reduce re-calculation of sun rise etc, and
        # to provide info for other widgets
        self.lastRiset = self.lastAstro = Time.now()
        self.counter = 0

        # start loop. Updates @ 10Hz to give smooth running clock
        self.update()

    def update(self):
        """
        Update astro widgets
        """
        try:
            # update counter
            self.counter += 1
            g = get_root(self).globals

            # current time
            now = Time.now()

            # configure times
            self.utc.configure(text=now.datetime.strftime("%H:%M:%S"))
            self.mjd.configure(text="{0:11.5f}".format(now.mjd))
            lon = self.obs.lon
            lst = now.sidereal_time(kind="mean", longitude=lon)
            self.lst.configure(text=lst.to_string(sep=":", precision=0))

            if self.counter % 600 == 1:
                # only re-compute Sun & Moon info once every 600 calls
                altaz_frame = coord.AltAz(obstime=now, location=self.obs)
                sun = coord.get_sun(now)
                sun_aa = sun.transform_to(altaz_frame)
                moon = coord.get_moon(now, self.obs)
                moon_aa = moon.transform_to(altaz_frame)
                elongation = sun.separation(moon)
                moon_phase_angle = np.arctan2(
                    sun.distance * np.sin(elongation),
                    moon.distance - sun.distance * np.cos(elongation),
                )
                moon_phase = (1 + np.cos(moon_phase_angle)) / 2.0

                self.sunalt.configure(text="{0:+03d} deg".format(int(sun_aa.alt.deg)))
                self.moonra.configure(
                    text=moon.ra.to_string(unit="hour", sep=":", precision=0)
                )
                self.moondec.configure(
                    text=moon.dec.to_string(unit="deg", sep=":", precision=0)
                )
                self.moonalt.configure(text="{0:+03d} deg".format(int(moon_aa.alt.deg)))
                self.moonphase.configure(
                    text="{0:02d} %".format(int(100.0 * moon_phase.value))
                )

                if now > self.lastRiset and now > self.lastAstro:
                    # Only re-compute rise and setting times when necessary,
                    # and only re-compute when both rise/set and astro
                    # twilight times have gone by

                    # For sunrise and set we set the horizon down to match a
                    # standard amount of refraction at the horizon and subtract size of disc
                    horizon = -64 * u.arcmin
                    sunset = calc_riseset(
                        now, "sun", self.obs, "next", "setting", horizon
                    )
                    sunrise = calc_riseset(
                        now, "sun", self.obs, "next", "rising", horizon
                    )

                    # Astro twilight: geometric centre at -18 deg
                    horizon = -18 * u.deg
                    astroset = calc_riseset(
                        now, "sun", self.obs, "next", "setting", horizon
                    )
                    astrorise = calc_riseset(
                        now, "sun", self.obs, "next", "rising", horizon
                    )

                    if sunrise > sunset:
                        # In the day time we report the upcoming sunset and
                        # end of evening twilight
                        self.lriset.configure(text="Sets:", font=g.DEFAULT_FONT)
                        self.lastRiset = sunset
                        self.lastAstro = astroset

                    elif astrorise > astroset and astrorise < sunrise:
                        # During evening twilight, we report the sunset just
                        # passed and end of evening twilight
                        self.lriset.configure(text="Sets:", font=g.DEFAULT_FONT)
                        horizon = -64 * u.arcmin
                        self.lastRiset = calc_riseset(
                            now, "sun", self.obs, "previous", "setting", horizon
                        )
                        self.lastAstro = astroset

                    elif astrorise > astroset and astrorise < sunrise:
                        # During night, report upcoming start of morning
                        # twilight and sunrise
                        self.lriset.configure(text="Rises:", font=g.DEFAULT_FONT)
                        horizon = -64 * u.arcmin
                        self.lastRiset = sunrise
                        self.lastAstro = astrorise

                    else:
                        # During morning twilight report start of twilight
                        # just passed and upcoming sunrise
                        self.lriset.configure(text="Rises:", font=g.DEFAULT_FONT)
                        horizon = -18 * u.deg
                        self.lastRiset = sunrise
                        self.lastAstro = calc_riseset(
                            now, "sun", self.obs, "previous", "rising", horizon
                        )

                    # Configure the corresponding text fields
                    self.riset.configure(
                        text=self.lastRiset.datetime.strftime("%H:%M:%S")
                    )
                    self.astro.configure(
                        text=self.lastAstro.datetime.strftime("%H:%M:%S")
                    )

        except Exception as err:
            # catchall
            g.clog.warn("AstroFrame.update: error = " + str(err))

        # run again after 100 milli-seconds
        self.after_id = self.after(100, self.update)


class WinPairs(tk.Frame):
    """
    Class to define a frame of multiple window pairs,
    contained within a gridded block that can be easily position.
    """

    def __init__(
        self,
        master,
        xsls,
        xslmins,
        xslmaxs,
        xsrs,
        xsrmins,
        xsrmaxs,
        yss,
        ysmins,
        ysmaxs,
        nxs,
        nys,
        xbfac,
        ybfac,
        checker,
        hcam=True,
    ):
        """
        Arguments:

          master :
            container widget

          xsls, xslmins, xslmaxs :
            initial X values of the leftmost columns of left-hand windows
            along with minimum and maximum values (array-like)

          xsrs, xsrmins, xsrmaxs :
            initial X values of the leftmost column of right-hand windows
            along with minimum and maximum values (array-like)

          yss, ysmins, ysmaxs :
            initial Y values of the lowest row of the window
            along with minimum and maximum values (array-like)

          nxs :
            X dimensions of windows, unbinned pixels
            (array-like)

          nys :
            Y dimensions of windows, unbinned pixels
            (array-like)

          xbfac :
            array of unique x-binning factors

          ybfac :
            array of unique y-binning factors

          checker :
            checker function to provide a global check and update in response
            to any changes made to the values stored in a Window. Can be None.

        It is assumed that the maximum X dimension is the same for both left
        and right windows and equal to xslmax-xslmin+1.
        """
        self.is_hcam = hcam
        npair = len(xsls)
        checks = (
            xsls,
            xslmins,
            xslmaxs,
            xsrs,
            xsrmins,
            xsrmaxs,
            yss,
            ysmins,
            ysmaxs,
            nxs,
            nys,
        )
        for check in checks:
            if npair != len(check):
                raise DriverError(
                    "drivers.WindowPairs.__init__:"
                    + " conflict array lengths amonst inputs"
                )

        tk.Frame.__init__(self, master)

        # top part contains the binning factors and
        # the number of active windows
        top = tk.Frame(self)
        top.pack(anchor=tk.W)

        tk.Label(top, text="Binning factors (X x Y): ").grid(
            row=0, column=0, sticky=tk.W
        )

        xyframe = tk.Frame(top)
        self.xbin = ListInt(xyframe, xbfac[0], xbfac, checker, width=2)
        self.xbin.pack(side=tk.LEFT)
        tk.Label(xyframe, text=" x ").pack(side=tk.LEFT)
        self.ybin = ListInt(xyframe, ybfac[0], ybfac, checker, width=2)
        self.ybin.pack(side=tk.LEFT)
        xyframe.grid(row=0, column=1, sticky=tk.W)

        row = 1
        allowed_pairs = (1, 2, 3)
        ap = [pairnum for pairnum in allowed_pairs if pairnum <= npair]
        self.npair = ListInt(top, ap[0], ap, checker, width=2)
        if npair > 1:
            # Second row: number of windows
            tk.Label(top, text="Number of window pairs").grid(
                row=1, column=0, sticky=tk.W
            )
            self.npair.grid(row=row, column=1, sticky=tk.W, pady=2)
            row += 1

        # bottom part contains the window settings
        bottom = tk.Frame(self)
        bottom.pack(anchor=tk.W)

        # top row
        tk.Label(bottom, text="xsl").grid(row=row, column=1, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="xsr").grid(row=row, column=2, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ys").grid(row=row, column=3, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="nx").grid(row=row, column=4, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ny").grid(row=row, column=5, ipady=5, sticky=tk.S)

        row += 1
        (self.label, self.xsl, self.xsr, self.ys, self.nx, self.ny) = (
            [],
            [],
            [],
            [],
            [],
            [],
        )
        nr = 0
        for xsl, xslmin, xslmax, xsr, xsrmin, xsrmax, ys, ysmin, ysmax, nx, ny in zip(
            *checks
        ):
            # create
            if npair == 1:
                self.label.append(tk.Label(bottom, text="Pair: "))
            else:
                self.label.append(tk.Label(bottom, text="Pair " + str(nr) + ": "))

            self.xsl.append(
                RangedInt(bottom, xsl, xslmin, xslmax, checker, True, width=4)
            )
            self.xsr.append(
                RangedInt(bottom, xsr, xsrmin, xsrmax, checker, True, width=4)
            )
            self.ys.append(RangedInt(bottom, ys, ysmin, ysmax, checker, True, width=4))
            self.nx.append(
                RangedMint(
                    bottom,
                    nx,
                    1,
                    xslmax - xslmin + 1,
                    self.xbin,
                    checker,
                    True,
                    width=4,
                )
            )
            self.ny.append(
                RangedMint(
                    bottom, ny, 1, ysmax - ysmin + 1, self.ybin, checker, True, width=4
                )
            )

            # arrange
            self.label[-1].grid(row=row, column=0)
            self.xsl[-1].grid(row=row, column=1)
            self.xsr[-1].grid(row=row, column=2)
            self.ys[-1].grid(row=row, column=3)
            self.nx[-1].grid(row=row, column=4)
            self.ny[-1].grid(row=row, column=5)

            row += 1
            nr += 1

        # syncing button
        self.sbutt = ActButton(bottom, 5, self.sync, text="Sync")
        self.sbutt.grid(row=row, column=0, columnspan=5, pady=10, sticky=tk.W)
        self.frozen = False

    def check(self):
        """
        Checks the values of the window pairs. If any problems are found, it
        flags them by changing the background colour.

        Returns (status, synced)

          status : flag for whether parameters are viable at all
          synced : flag for whether the windows are synchronised.
        """

        status = True
        synced = True

        xbin = self.xbin.value()
        ybin = self.ybin.value()
        npair = self.npair.value()

        g = get_root(self).globals
        # individual pair checks
        for xslw, xsrw, ysw, nxw, nyw in zip(
            self.xsl[:npair],
            self.xsr[:npair],
            self.ys[:npair],
            self.nx[:npair],
            self.ny[:npair],
        ):
            xslw.config(bg=g.COL["main"])
            xsrw.config(bg=g.COL["main"])
            ysw.config(bg=g.COL["main"])
            nxw.config(bg=g.COL["main"])
            nyw.config(bg=g.COL["main"])
            status = status if xslw.ok() else False
            status = status if xsrw.ok() else False
            status = status if ysw.ok() else False
            status = status if nxw.ok() else False
            status = status if nyw.ok() else False
            xsl = xslw.value()
            xsr = xsrw.value()
            ys = ysw.value()
            nx = nxw.value()
            ny = nyw.value()

            # Are unbinned dimensions consistent with binning factors?
            if nx is None or nx % xbin != 0:
                nxw.config(bg=g.COL["error"])
                status = False
            elif self.is_hcam and (nx // xbin) % 4 != 0:
                """
                The NGC collects pixel data in chunks before transmission.
                As a result, to avoid loss of data from frames, the binned
                x-size must be a multiple of 4.
                """
                nxw.config(bg=g.COL["error"])
                status = False

            if ny is None or ny % ybin != 0:
                nyw.config(bg=g.COL["error"])
                status = False

            # overlap checks
            if xsl is None or xsr is None or xsl >= xsr:
                xsrw.config(bg=g.COL["error"])
                status = False

            if xsl is None or xsr is None or nx is None or xsl + nx > xsr:
                xsrw.config(bg=g.COL["error"])
                status = False

            # Are the windows synchronised? This means that they would
            # be consistent with the pixels generated were the whole CCD
            # to be binned by the same factors. If relevant values are not
            # set, we count that as "synced" because the purpose of this is
            # to enable / disable the sync button and we don't want it to be
            # enabled just because xs or ys are not set.
            perform_check = all([param is not None for param in (xsl, xsr, ys, nx, ny)])
            if perform_check and (
                (xsl - 1) % xbin != 0
                or (xsr - 1025) % xbin != 0
                or (ys - 1) % ybin != 0
            ):
                synced = False

            # Range checks
            if xsl is None or nx is None or xsl + nx - 1 > xslw.imax:
                xslw.config(bg=g.COL["error"])
                status = False

            if xsr is None or nx is None or xsr + nx - 1 > xsrw.imax:
                xsrw.config(bg=g.COL["error"])
                status = False

            if ys is None or ny is None or ys + ny - 1 > ysw.imax:
                ysw.config(bg=g.COL["error"])
                status = False

        # Pair overlap checks. Compare one pair with the next one in the
        # same quadrant (if there is one). Only bother if we have survived
        # so far, which saves a lot of checks
        if status:
            for index in range(npair - 2):
                ys1 = self.ys[index].value()
                ny1 = self.ny[index].value()

                ysw2 = self.ys[index + 2]
                ys2 = ysw2.value()
                if ys1 + ny1 > ys2:
                    ysw2.config(bg=g.COL["error"])
                    status = False

        if synced:
            self.sbutt.config(bg=g.COL["main"])
            self.sbutt.disable()
        else:
            if not self.frozen:
                self.sbutt.enable()
            self.sbutt.config(bg=g.COL["warn"])

        return status

    def sync(self):
        """
        Synchronise the settings. This means that the pixel start
        values are shifted downwards so that they are synchronised
        with a full-frame binned version. This does nothing if the
        binning factors == 1.
        """

        # needs some mods for ultracam ??
        xbin = self.xbin.value()
        ybin = self.ybin.value()
        n = 0
        for xsl, xsr, ys, nx, ny in self:
            if xbin > 1:
                xsl = xbin * ((xsl - 1) // xbin) + 1
                self.xsl[n].set(xsl)
                xsr = xbin * ((xsr - 1025) // xbin) + 1025
                self.xsr[n].set(xsr)

            if ybin > 1:
                ys = ybin * ((ys - 1) // ybin) + 1
                self.ys[n].set(ys)

            n += 1
        g = get_root(self).globals
        self.sbutt.config(bg=g.COL["main"])
        self.sbutt.config(state="disable")

    def freeze(self):
        """
        Freeze (disable) all settings so they can't be altered
        """
        for xsl, xsr, ys, nx, ny in zip(self.xsl, self.xsr, self.ys, self.nx, self.ny):
            xsl.disable()
            xsr.disable()
            ys.disable()
            nx.disable()
            ny.disable()
        self.npair.disable()
        self.xbin.disable()
        self.ybin.disable()
        self.sbutt.disable()
        self.frozen = True

    def unfreeze(self):
        """
        Unfreeze all settings so that they can be altered
        """
        self.enable()
        self.frozen = False
        self.check()

    def disable(self, everything=False):
        """
        Disable all but possibly not binning, which is needed for FF apps

        Parameters
        ---------
        everything : bool
            disable binning as well
        """
        self.freeze()
        if not everything:
            self.xbin.enable()
            self.ybin.enable()
        self.frozen = False

    def enable(self):
        """
        Enables WinPair settings
        """
        npair = self.npair.value()
        for label, xsl, xsr, ys, nx, ny in zip(
            self.label[:npair],
            self.xsl[:npair],
            self.xsr[:npair],
            self.ys[:npair],
            self.nx[:npair],
            self.ny[:npair],
        ):
            label.config(state="normal")
            xsl.enable()
            xsr.enable()
            ys.enable()
            nx.enable()
            ny.enable()

        for label, xsl, xsr, ys, nx, ny in zip(
            self.label[npair:],
            self.xsl[npair:],
            self.xsr[npair:],
            self.ys[npair:],
            self.nx[npair:],
            self.ny[npair:],
        ):
            label.config(state="disable")
            xsl.disable()
            xsr.disable()
            ys.disable()
            nx.disable()
            ny.disable()

        self.npair.enable()
        self.xbin.enable()
        self.ybin.enable()
        self.sbutt.enable()

    def params(self, n):
        """
        return xsl, xsr, ys, nx, ny for this pair
        """
        return (
            self.xsl[n].value(),
            self.xsr[n].value(),
            self.ys[n].value(),
            self.nx[n].value(),
            self.ny[n].value(),
        )

    def __iter__(self):
        """
        Generator to allow looping through through the window pairs.
        Successive calls return xsl, xsr, ys, nx, ny for each pair
        """
        n = 0
        npair = self.npair.value()
        while n < npair:
            yield (
                self.xsl[n].value(),
                self.xsr[n].value(),
                self.ys[n].value(),
                self.nx[n].value(),
                self.ny[n].value(),
            )
            n += 1


class WinQuads(tk.Frame):
    """
    Class to define a frame of multiple window quads,
    contained within a gridded block that can be easily postioned.
    """

    def __init__(
        self,
        master,
        xsll,
        xsllmin,
        xsllmax,
        xsul,
        xsulmin,
        xsulmax,
        xslr,
        xslrmin,
        xslrmax,
        xsur,
        xsurmin,
        xsurmax,
        ys,
        ysmin,
        ysmax,
        nx,
        ny,
        xbfac,
        ybfac,
        checker,
    ):
        """
        Arguments:

            master:
                container widget

            xsll, xsllmin, xsllmax: float or container of floats
                initial X values of the lower left window in quad, along
                with minimum and maximum values.

            xsul, xsulmin, xsulmax: float or container of floats
                initial X values of the upper left window in quad, along
                with minimum and maximum values.

            xslr, xslrmin, xslrmax: float or container of floats
                initial X values of the lower right window in quad, along
                with minimum and maximum values.

            xsur, xsurmin, xsurmax: float or container of floats
                initial X values of the upper right window in quad, along
                with minimum and maximum values.

            ys, ysmin, ysmax: float or container of floats
                initial Y values of the window, as measured from serial
                register, along with minimum and maximum values

            nx : float or container of floats
                X dimensions of windows, unbinned pixels

            ny : float or container of floats
                Y dimensions of windows, unbinned pixels

            xbfac : float or container of floats
                array of unique x-binning factors

            ybfac : float or container of floats
                array of unique y-binning factors

            checker :
                checker function to provide a global check and update in response
                to any changes made to the values stored in a Window. Can be None.

        It is assumed that the maximum X dimension is the same for all windows in the quad
        and is equal to xsllmax - xsllmin + 1.
        """
        # check we have a consistent number of quads in all parameters
        nquad = len(xsll)
        checks = (
            xsll,
            xsllmin,
            xsllmax,
            xslr,
            xslrmin,
            xslrmax,
            xsul,
            xsulmin,
            xsulmax,
            xsur,
            xsurmin,
            xsurmax,
            ys,
            ysmin,
            ysmax,
            nx,
            ny,
        )
        for check in checks:
            if nquad != len(check):
                raise DriverError(
                    "drivers.WinQuads.__init__:"
                    + " conflicting array lengths amongst inputs"
                )

        tk.Frame.__init__(self, master)

        # top part contains binning factors and number of quads
        top = tk.Frame(self)
        top.pack(anchor=tk.W)

        tk.Label(top, text="Binning factors (X x Y): ").grid(
            row=0, column=0, sticky=tk.W
        )

        xyframe = tk.Frame(top)
        self.xbin = ListInt(xyframe, xbfac[0], xbfac, checker, width=2)
        self.xbin.pack(side=tk.LEFT)
        tk.Label(xyframe, text=" x ").pack(side=tk.LEFT)
        self.ybin = ListInt(xyframe, ybfac[0], ybfac, checker, width=2)
        self.ybin.pack(side=tk.LEFT)
        xyframe.grid(row=0, column=1, sticky=tk.W)

        row = 1
        allowed_quads = (1, 2)
        aq = [quadnum for quadnum in allowed_quads if quadnum <= nquad]
        self.nquad = ListInt(top, aq[0], aq, checker, width=2)
        if nquad > 1:
            # Second row: number of quads selector
            tk.Label(top, text="Number of window quads: ").grid(
                row=1, column=0, sticky=tk.W
            )
            self.nquad.grid(row=row, column=1, sticky=tk.W, pady=2)
            row += 1

        # bottom part of the frame contains the window settings
        bottom = tk.Frame(self)
        bottom.pack(anchor=tk.W)

        # top row - labels
        tk.Label(bottom, text="xsll").grid(row=row, column=1, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="xslr").grid(row=row, column=2, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="xsul").grid(row=row, column=3, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="xsur").grid(row=row, column=4, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ys").grid(row=row, column=5, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="nx").grid(row=row, column=6, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ny").grid(row=row, column=7, ipady=5, sticky=tk.S)

        row += 1
        (
            self.label,
            self.xsll,
            self.xsul,
            self.xslr,
            self.xsur,
            self.ys,
            self.nx,
            self.ny,
        ) = ([], [], [], [], [], [], [], [])
        nr = 0
        for (
            xsll,
            xsllmin,
            xsllmax,
            xslr,
            xslrmin,
            xslrmax,
            xsul,
            xsulmin,
            xsulmax,
            xsur,
            xsurmin,
            xsurmax,
            ys,
            ysmin,
            ysmax,
            nx,
            ny,
        ) in zip(*checks):
            # create
            if nquad == 1:
                self.label.append(tk.Label(bottom, text="Quad: "))
            else:
                self.label.append(tk.Label(bottom, text="Quad " + str(nr + 1) + ": "))

            self.xsll.append(
                RangedInt(bottom, xsll, xsllmin, xsllmax, checker, True, width=4)
            )
            self.xsul.append(
                RangedInt(bottom, xsul, xsulmin, xsulmax, checker, True, width=4)
            )
            self.xslr.append(
                RangedInt(bottom, xslr, xslrmin, xslrmax, checker, True, width=4)
            )
            self.xsur.append(
                RangedInt(bottom, xsur, xsurmin, xsurmax, checker, True, width=4)
            )
            self.ys.append(RangedInt(bottom, ys, ysmin, ysmax, checker, True, width=4))
            self.nx.append(
                RangedMint(
                    bottom,
                    nx,
                    1,
                    xsulmax - xsulmin + 1,
                    self.xbin,
                    checker,
                    True,
                    width=4,
                )
            )
            self.ny.append(
                RangedMint(
                    bottom, ny, 1, ysmax - ysmin + 1, self.ybin, checker, True, width=4
                )
            )

            # arrange
            self.label[-1].grid(row=row, column=0)
            self.xsll[-1].grid(row=row, column=1)
            self.xslr[-1].grid(row=row, column=2)
            self.xsul[-1].grid(row=row, column=3)
            self.xsur[-1].grid(row=row, column=4)
            self.ys[-1].grid(row=row, column=5)
            self.nx[-1].grid(row=row, column=6)
            self.ny[-1].grid(row=row, column=7)

            row += 1
            nr += 1

        # sync button
        self.sbutt = ActButton(bottom, 5, self.sync, text="Sync")
        self.sbutt.grid(row=row, column=0, columnspan=7, pady=10, sticky=tk.W)
        self.frozen = False

    def check(self):
        """
        Checks the values of the window quads. If any problems are found it
        flags the offending window by changing the background colour.

        Returns:
            status : bool
        """
        status = synced = True

        xbin = self.xbin.value()
        ybin = self.ybin.value()
        nquad = self.nquad.value()

        g = get_root(self).globals
        # individual window checks
        for xsllw, xsulw, xslrw, xsurw, ysw, nxw, nyw in zip(
            self.xsll[:nquad],
            self.xsul[:nquad],
            self.xslr[:nquad],
            self.xsur[:nquad],
            self.ys[:nquad],
            self.nx[:nquad],
            self.ny[:nquad],
        ):
            all_fields = (xsllw, xsulw, xslrw, xsurw, ysw, nxw, nyw)
            for field in all_fields:
                field.config(bg=g.COL["main"])
                status = status if field.ok() else False

            xsll = xsllw.value()
            xsul = xsulw.value()
            xslr = xslrw.value()
            xsur = xsurw.value()
            ys = ysw.value()
            nx = nxw.value()
            ny = nyw.value()

            # Are unbinned dimensions consistent with binning factors?
            if nx is None or nx % xbin != 0:
                nxw.config(bg=g.COL["error"])
                status = False
            elif (nx // xbin) % 4 != 0:
                """
                The NGC collects pixel data in chunks before transmission.
                As a result, to avoid loss of data from frames, the binned
                x-size must be a multiple of 4.
                """
                nxw.config(bg=g.COL["error"])
                status = False

            if ny is None or ny % ybin != 0:
                nyw.config(bg=g.COL["error"])
                status = False

            # overlap checks in x direction
            if xsll is None or xslr is None or xsll >= xslr:
                xslrw.config(bg=g.COL["error"])
                status = False
            if xsul is None or xsur is None or xsul >= xsur:
                xsurw.config(bg=g.COL["error"])
                status = False
            if nx is None or xsll is None or xsll + nx > xslr:
                xslrw.config(bg=g.COL["error"])
                status = False
            if xsul is None or nx is None or xsul + nx > xsur:
                xsurw.config(bg=g.COL["error"])
                status = False

            # Are the windows synchronised? This means that they would
            # be consistent with the pixels generated were the whole CCD
            # to be binned by the same factors. If relevant values are not
            # set, we count that as "synced" because the purpose of this is
            # to enable / disable the sync button and we don't want it to be
            # enabled just because xs or ys are not set.
            perform_check = all(
                [param is not None for param in (xsll, xslr, ys, nx, ny)]
            )
            if perform_check and (
                (xsll - 1) % xbin != 0
                or (xslr - 1025) % xbin != 0
                or (ys - 1) % ybin != 0
            ):
                synced = False

            perform_check = all(
                [param is not None for param in (xsul, xsur, ys, nx, ny)]
            )
            if perform_check and (
                (xsul - 1) % xbin != 0
                or (xsur - 1025) % xbin != 0
                or (ys - 1) % ybin != 0
            ):
                synced = False

            # Range checks
            rchecks = (
                (xsll, nx, xsllw),
                (xslr, nx, xslrw),
                (xsul, nx, xsulw),
                (xsur, nx, xsurw),
                (ys, ny, ysw),
            )
            for check in rchecks:
                val, size, widg = check
                if val is None or size is None or val + size - 1 > widg.imax:
                    widg.config(bg=g.COL["error"])
                    status = False

        # Quad overlap checks. Compare one quad with the next one
        # in the same quadrant if there is one. Only bother if we
        # have survived so far, which saves a lot of checks.
        if status:
            for index in range(nquad - 1):
                ys1 = self.ys[index].value()
                ny1 = self.ny[index].value()
                ysw2 = self.ys[index + 1]
                ys2 = ysw2.value()
                if any([thing is None for thing in (ys1, ny1, ys2)]) or ys1 + ny1 > ys2:
                    ysw2.config(bg=g.COL["error"])
                    status = False

        if synced:
            self.sbutt.config(bg=g.COL["main"])
            self.sbutt.disable()
        else:
            if not self.frozen:
                self.sbutt.enable()
            self.sbutt.config(bg=g.COL["warn"])
        return status

    def sync(self):
        """
        Synchronise the settings.

        This routine changes the window settings so that the pixel start
        values are shifted downwards until they are synchronised with a
        full-frame binned version. This does nothing if the binning factor
        is 1.
        """
        xbin = self.xbin.value()
        ybin = self.ybin.value()
        if xbin == 1 and ybin == 1:
            self.sbutt.config(state="disable")
            return

        for n, (xsll, xsul, xslr, xsur, ys, nx, ny) in enumerate(self):
            if (xsll - 1) % xbin != 0:
                xsll = xbin * ((xsll - 1) // xbin) + 1
                self.xsll[n].set(xsll)
            if (xsul - 1) % xbin != 0:
                xsul = xbin * ((xsul - 1) // xbin) + 1
                self.xsul[n].set(xsul)
            if (xslr - 1025) % xbin != 0:
                xslr = xbin * ((xslr - 1025) // xbin) + 1025
                self.xslr[n].set(xslr)
            if (xsur - 1025) % xbin != 0:
                xsur = xbin * ((xsur - 1025) // xbin) + 1025
                self.xsur[n].set(xsur)

            if ybin > 1 and (ys - 1) % ybin != 0:
                ys = ybin * ((ys - 1) // ybin) + 1
                self.ys[n].set(ys)

        g = get_root(self).globals
        self.sbutt.config(bg=g.COL["main"])
        self.sbutt.config(state="disable")

    def freeze(self):
        """
        Freeze (disable) all settings
        """
        for fields in zip(
            self.xsll, self.xsul, self.xslr, self.xsur, self.ys, self.nx, self.ny
        ):
            for field in fields:
                field.disable()
        self.nquad.disable()
        self.xbin.disable()
        self.ybin.disable()
        self.sbutt.disable()
        self.frozen = True

    def unfreeze(self):
        """
        Unfreeze all settings so they can be altered
        """
        self.enable()
        self.frozen = False
        self.check()

    def disable(self, everything=False):
        """
        Disable all but optionally not binning, which is needed for FF apps

        Parameters
        -----------
        everything: bool
            disable binning as well
        """
        self.freeze()
        if not everything:
            self.xbin.enable()
            self.ybin.enable()
        self.frozen = False

    def enable(self):
        """
        Enables WinQuad setting
        """
        nquad = self.nquad.value()
        for label, xsll, xsul, xslr, xsur, ys, nx, ny in zip(
            self.label[:nquad],
            self.xsll[:nquad],
            self.xsul[:nquad],
            self.xslr[:nquad],
            self.xsur[:nquad],
            self.ys[:nquad],
            self.nx[:nquad],
            self.ny[:nquad],
        ):
            label.config(state="normal")
            for thing in (xsll, xsul, xslr, xsur, ys, nx, ny):
                thing.enable()

        for label, xsll, xsul, xslr, xsur, ys, nx, ny in zip(
            self.label[nquad:],
            self.xsll[nquad:],
            self.xsul[nquad:],
            self.xslr[nquad:],
            self.xsur[nquad:],
            self.ys[nquad:],
            self.nx[nquad:],
            self.ny[nquad:],
        ):
            label.config(state="disable")
            for thing in (xsll, xsul, xslr, xsur, ys, nx, ny):
                thing.disable()

        self.nquad.enable()
        self.xbin.enable()
        self.ybin.enable()
        self.sbutt.enable()

    def __iter__(self):
        """
        Generator to allow looping through window quads.

        Successive calls return xsll, xsul, xslr, xsur, ys, nx, ny
        for each quad.
        """
        n = 0
        nquad = self.nquad.value()
        while n < nquad:
            yield (
                self.xsll[n].value(),
                self.xsul[n].value(),
                self.xslr[n].value(),
                self.xsur[n].value(),
                self.ys[n].value(),
                self.nx[n].value(),
                self.ny[n].value(),
            )
            n += 1


class Windows(tk.Frame):
    """
    Class to define a frame of multiple windows as a gridded
    block that can be placed easily within a container widget.
    Also defines binning factors and the number of active windows.
    """

    def __init__(
        self,
        master,
        xss,
        xsmins,
        xsmaxs,
        yss,
        ysmins,
        ysmaxs,
        nxs,
        nys,
        xbfac,
        ybfac,
        checker,
    ):
        """
        Arguments:

          master :
            container widget

          xss, xsmins, xsmaxs :
            initial X values of the leftmost column of window(s)
            along with minimum and maximum values (array-like)

          yss, ysmins, ysmaxs :
            initial Y values of the lowest row of the window
            along with minimum and maximum values (array-like)

          nxs :
            initial X dimensions of windows, unbinned pixels
            (array-like)

          nys :
            initial Y dimension(s) of windows, unbinned pixels
            (array-like)

          xbfac :
            set of x-binning factors

          ybfac :
            set of y-binning factors

          checker :
            checker function to provide a global check and update in response
            to any changes made to the values stored in a Window. Can be None.
        """

        nwin = len(xss)
        checks = (xss, xsmins, xsmaxs, yss, ysmins, ysmaxs, nxs, nys)
        for check in checks:
            if nwin != len(check):
                raise DriverError(
                    "drivers.Windows.__init__: "
                    + "conflict array lengths amonst inputs"
                )

        tk.Frame.__init__(self, master)

        # top part contains the binning factors and the number
        # of active windows
        top = tk.Frame(self)
        top.pack(anchor=tk.W)

        tk.Label(top, text="Binning factors (X x Y): ").grid(
            row=0, column=0, sticky=tk.W
        )

        xyframe = tk.Frame(top)
        self.xbin = ListInt(xyframe, xbfac[0], xbfac, checker, width=2)
        self.xbin.pack(side=tk.LEFT)
        tk.Label(xyframe, text=" x ").pack(side=tk.LEFT)
        self.ybin = ListInt(xyframe, ybfac[0], ybfac, checker, width=2)
        self.ybin.pack(side=tk.LEFT)
        xyframe.grid(row=0, column=1, sticky=tk.W)

        # Second row: number of windows
        self.nwin = RangedInt(top, 1, 1, nwin, checker, False, width=2)
        row = 1
        if nwin > 1:
            tk.Label(top, text="Number of windows").grid(row=row, column=0, sticky=tk.W)
            self.nwin.grid(row=1, column=1, sticky=tk.W, pady=2)
            row += 1

        # bottom part contains the window settings
        bottom = tk.Frame(self)
        bottom.pack(anchor=tk.W)

        # top row
        tk.Label(bottom, text="xs").grid(row=row, column=1, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ys").grid(row=row, column=2, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="nx").grid(row=row, column=3, ipady=5, sticky=tk.S)
        tk.Label(bottom, text="ny").grid(row=row, column=4, ipady=5, sticky=tk.S)

        self.label, self.xs, self.ys, self.nx, self.ny = [], [], [], [], []
        nr = 0
        row += 1
        for xs, xsmin, xsmax, ys, ysmin, ysmax, nx, ny in zip(*checks):
            # create
            if nwin == 1:
                self.label.append(tk.Label(bottom, text="Window: "))
            else:
                self.label.append(tk.Label(bottom, text="Window " + str(nr + 1) + ": "))

            self.xs.append(RangedInt(bottom, xs, xsmin, xsmax, checker, True, width=4))
            self.ys.append(RangedInt(bottom, ys, ysmin, ysmax, checker, True, width=4))
            self.nx.append(
                RangedMint(
                    bottom, nx, 1, xsmax - xsmin + 1, self.xbin, checker, True, width=4
                )
            )
            self.ny.append(
                RangedMint(
                    bottom, ny, 1, ysmax - ysmin + 1, self.ybin, checker, True, width=4
                )
            )

            # arrange
            self.label[-1].grid(row=row, column=0)
            self.xs[-1].grid(row=row, column=1)
            self.ys[-1].grid(row=row, column=2)
            self.nx[-1].grid(row=row, column=3)
            self.ny[-1].grid(row=row, column=4)

            row += 1
            nr += 1

        self.sbutt = ActButton(bottom, 5, self.sync, text="Sync")
        self.sbutt.grid(row=row, column=0, columnspan=5, pady=6, sticky=tk.W)
        self.frozen = False

    def check(self):
        """
        Checks the values of the windows. If any problems are found,
        it flags them by changing the background colour. Only active
        windows are checked.

        Returns status, flag for whether parameters are viable.
        """

        status = True
        synced = True

        xbin = self.xbin.value()
        ybin = self.ybin.value()
        nwin = self.nwin.value()

        # individual window checks
        g = get_root(self).globals
        for xsw, ysw, nxw, nyw in zip(
            self.xs[:nwin], self.ys[:nwin], self.nx[:nwin], self.ny[:nwin]
        ):
            xsw.config(bg=g.COL["main"])
            ysw.config(bg=g.COL["main"])
            nxw.config(bg=g.COL["main"])
            nyw.config(bg=g.COL["main"])
            status = status if xsw.ok() else False
            status = status if ysw.ok() else False
            status = status if nxw.ok() else False
            status = status if nyw.ok() else False
            xs = xsw.value()
            ys = ysw.value()
            nx = nxw.value()
            ny = nyw.value()

            # Are unbinned dimensions consistent with binning factors?
            if nx is None or nx % xbin != 0:
                nxw.config(bg=g.COL["error"])
                status = False

            if ny is None or ny % ybin != 0:
                nyw.config(bg=g.COL["error"])
                status = False

            # Are the windows synchronised? This means that they
            # would be consistent with the pixels generated were
            # the whole CCD to be binned by the same factors
            # If relevant values are not set, we count that as
            # "synced" because the purpose of this is to enable
            # / disable the sync button and we don't want it to be
            # enabled just because xs or ys are not set.
            if xs is not None and ys is not None and nx is not None and ny is not None:
                if (
                    xs < 1025
                    and ((xs - 1) % xbin != 0 or (ys - 1) % ybin != 0)
                    or ((xs - 1025) % xbin != 0 or (ys - 1) % ybin != 0)
                ):
                    synced = False

            # Range checks
            if xs is None or nx is None or xs + nx - 1 > xsw.imax:
                xsw.config(bg=g.COL["error"])
                status = False

            if ys is None or ny is None or ys + ny - 1 > ysw.imax:
                ysw.config(bg=g.COL["error"])
                status = False

        # Overlap checks. Compare each window with the next one, requiring
        # no y overlap and that the second is higher than the first
        if status:
            n1 = 0
            for ysw1, nyw1 in zip(self.ys[: nwin - 1], self.ny[: nwin - 1]):
                ys1 = ysw1.value()
                ny1 = nyw1.value()

                n1 += 1
                ysw2 = self.ys[n1]

                ys2 = ysw2.value()

                if ys2 < ys1 + ny1:
                    ysw2.config(bg=g.COL["error"])
                    status = False

        if synced:
            self.sbutt.config(bg=g.COL["main"])
            self.sbutt.disable()
        else:
            if not self.frozen:
                self.sbutt.enable()
            self.sbutt.config(bg=g.COL["warn"])

        return status

    def sync(self, *args):
        """
        Synchronise the settings. This means that the pixel start
        values are shifted downwards so that they are synchronised
        with a full-frame binned version. This does nothing if the
        binning factor == 1
        """
        xbin = self.xbin.value()
        ybin = self.ybin.value()
        n = 0
        for xs, ys, nx, ny in self:
            if xbin > 1 and xs % xbin != 1:
                if xs < 1025:
                    xs = xbin * ((xs - 1) // xbin) + 1
                else:
                    xs = xbin * ((xs - 1025) // xbin) + 1025
                self.xs[n].set(xs)

            if ybin > 1 and ys % ybin != 1:
                ys = ybin * ((ys - 1) // ybin) + 1
                self.ys[n].set(ys)

            n += 1

        g = get_root(self).globals
        self.sbutt.config(bg=g.COL["main"])
        self.sbutt.config(state="disable")

    def freeze(self):
        """
        Freeze all settings so they can't be altered
        """
        for xs, ys, nx, ny in zip(self.xs, self.ys, self.nx, self.ny):
            xs.disable()
            ys.disable()
            nx.disable()
            ny.disable()
        self.nwin.disable()
        self.xbin.disable()
        self.ybin.disable()
        self.sbutt.disable()
        self.frozen = True

    def unfreeze(self):
        """
        Unfreeze all settings
        """
        self.enable()
        self.frozen = False
        self.check()

    def enable(self):
        """
        Enables all settings
        """
        nwin = self.nwin.value()
        for label, xs, ys, nx, ny in zip(
            self.label[:nwin],
            self.xs[:nwin],
            self.ys[:nwin],
            self.nx[:nwin],
            self.ny[:nwin],
        ):
            label.config(state="normal")
            xs.enable()
            ys.enable()
            nx.enable()
            ny.enable()

        for label, xs, ys, nx, ny in zip(
            self.label[nwin:],
            self.xs[nwin:],
            self.ys[nwin:],
            self.nx[nwin:],
            self.ny[nwin:],
        ):
            label.config(state="disable")
            xs.disable()
            ys.disable()
            nx.disable()
            ny.disable()

        self.nwin.enable()
        self.xbin.enable()
        self.ybin.enable()
        self.sbutt.enable()

    def __iter__(self):
        """
        Generator to allow looping through through the window values.
        Successive calls return xs, ys, nx, ny for each window
        """
        n = 0
        nwin = self.nwin.value()
        while n < nwin:
            yield (
                self.xs[n].value(),
                self.ys[n].value(),
                self.nx[n].value(),
                self.ny[n].value(),
            )
            n += 1
