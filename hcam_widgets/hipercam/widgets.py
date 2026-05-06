# HiPERCAM-specific widgets and widget groups
from __future__ import absolute_import, division, print_function, unicode_literals

import time
import subprocess
import json
import math
import pickle
from os.path import expanduser

# non-standard imports
import numpy as np
import six
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import LoopingCall
from hcam_devices.gtc.headers import add_gtc_header_table_row, create_gtc_header_table
from astropy import units as u
from astropy import coordinates as coord
from astropy.time import Time


# internal imports
from ..astro import calc_time_to_rotator_limit
from .. import DriverError
from .. import widgets as w
from ..tkutils import get_root, place_at_edge
from . import tools
from . import params as pars

if not six.PY3:
    import tkFileDialog as filedialog
    import Tkinter as tk
    import tkMessageBox as messagebox
else:
    import tkinter as tk
    from tkinter import filedialog, messagebox


class ExposureMultiplier(tk.LabelFrame):
    """
    Top to bottom group of RangedInt entry items to specify Nblue etc. Has a max
    number of rows after which it will jump to the left of next column and start over.
    """

    def __init__(
        self, master, labels, ivals, imins, imaxs, nrmax, checker, blank, **kw
    ):
        """
        Parameters
        ----------
        master : tk.widget
            enclosing widget
        labels : iterable
            labels for entry items
        ivals : list of int
            initial values
        imins : list of int
            minimum values
        imaxs : list of int
            maximum values
        nrmax : int
            maximum number of rows before wrapping
        checker : callable
            command that is run on any change to the entry
        blank : bool
            controls whether the field is allowed to be blank
            In some cases it makes things easier if blank fields are
            allowed, even if it is technically invalid
        kw : dict
            keyword arguments

        """
        tk.LabelFrame.__init__(self, master, bd=0)
        nitems = len(labels)
        if len(ivals) != nitems or len(imins) != nitems or len(imaxs) != nitems:
            raise DriverError(
                "ExposureMultiplier.__init__ values and options "
                + "must have same length"
            )
        self.nitems = nitems
        self.labels = labels
        self.widgets = [
            w.RangedInt(self, ival, imin, imax, checker, blank, **kw)
            for ival, imin, imax in zip(ivals, imins, imaxs)
        ]
        row = 0
        col = 0
        for nw, widget in enumerate(self.widgets):
            tk.Label(self, text=labels[nw]).grid(row=row, column=col, sticky=tk.W)
            widget.grid(row=row, column=col + 1, sticky=tk.W)
            row += 1
            if row == nrmax:
                col += 1
                row = 0

    def value(self, index):
        return self.widgets[index].value()

    def set(self, index, num):
        self.widgets[index].set(num)

    def getall(self):
        return [widget.value() for widget in self.widgets]

    def setall(self, nums):
        for index, val in enumerate(nums):
            self.set(index, val)

    def disable(self):
        for widget in self.widgets:
            widget.configure(state="disable")
            widget.set_unbind()

    def enable(self):
        for widget in self.widgets:
            widget.configure(state="normal")
            widget.set_bind()


class InstPars(tk.LabelFrame):
    """
    Instrument parameters block.

    This widget block contains the meat of hdriver. Window settings, readout speed
    etc.
    """

    def __init__(self, master):
        """
        master : enclosing widget
        """
        tk.LabelFrame.__init__(self, master)

        # left hand side
        lhs = tk.Frame(self)
        rhs = tk.Frame(self)

        # Application (mode)
        tk.Label(lhs, text="Mode").grid(row=0, column=0, sticky=tk.W)
        self.app = w.Radio(
            lhs,
            ("Full", "Wins", "Drift"),
            3,
            self.check,
            ("FullFrame", "Windows", "Drift"),
        )
        self.app.grid(row=0, column=1, columnspan=2, sticky=tk.W)

        # Clear enabled
        self.clearLab = tk.Label(lhs, text="Clear")
        self.clearLab.grid(row=1, column=0, sticky=tk.W)
        self.clear = w.OnOff(lhs, False, self.check)
        self.clear.grid(row=1, column=1, columnspan=2, sticky=tk.W)

        # nod telescope
        self.nodLab = tk.Label(lhs, text="Dithering")
        self.nodLab.grid(row=2, column=0, sticky=tk.W)
        self.nod = w.OnOff(lhs, False, self.setupNodding)
        self.nod.grid(row=2, column=1, columnspan=2, sticky=tk.W)
        self.nodPattern = {}

        # Overscan in x enabled
        self.oscanLab = tk.Label(lhs, text="Overscan")
        self.oscanLab.grid(row=3, column=0, sticky=tk.W)
        self.oscan = w.OnOff(lhs, False, self.check)
        self.oscany = w.OnOff(lhs, False, self.check)
        self.oscan.grid(row=3, column=1, sticky=tk.W)
        self.oscany.grid(row=3, column=2, sticky=tk.W)

        # led on (expert mode only)
        self.ledLab = tk.Label(lhs, text="LED setting")
        self.ledLab.grid(row=4, column=0, sticky=tk.W)
        self.led = w.OnOff(lhs, False, None)
        self.led.grid(row=4, column=1, columnspan=2, pady=2, sticky=tk.W)

        # dummy mode enabled (expert mode only)
        self.dummyLab = tk.Label(lhs, text="Dummy Output")
        self.dummyLab.grid(row=5, column=0, sticky=tk.W)
        self.dummy = w.OnOff(lhs, True, self.check)
        self.dummy.grid(row=5, column=1, columnspan=2, pady=2, sticky=tk.W)

        # Faster Clock speed enabled
        self.fastClkLab = tk.Label(lhs, text="Fast Clocks")
        self.fastClkLab.grid(row=6, column=0, sticky=tk.W)
        self.fastClk = w.OnOff(lhs, False, self.check)
        self.fastClk.grid(row=6, column=1, columnspan=2, pady=2, sticky=tk.W)

        # Readout speed
        tk.Label(lhs, text="Readout speed").grid(row=7, column=0, sticky=tk.W)
        self.readSpeed = w.Select(lhs, 1, ("Fast", "Slow"), self.check)
        self.readSpeed.grid(row=7, column=1, columnspan=2, pady=2, sticky=tk.W)

        # Exp delay
        tk.Label(lhs, text="Exposure delay (s)").grid(row=8, column=0, sticky=tk.W)
        self.expose = w.RangedFloat(
            lhs,
            0.1,
            0.00001,
            1677.7207,
            self.check,
            blank=True,
            allowzero=True,
            width=7,
        )
        self.expose.grid(row=8, column=1, columnspan=2, pady=2, sticky=tk.W)

        # num exp
        tk.Label(lhs, text="Num. exposures  ").grid(row=9, column=0, sticky=tk.W)
        self.number = w.PosInt(lhs, 0, None, False, width=7)
        self.number.grid(row=9, column=1, columnspan=2, pady=2, sticky=tk.W)

        # nb, ng, nr etc
        labels = ("nu", "ng", "nr", "ni", "nz")
        ivals = (1, 1, 1, 1, 1)
        imins = (1, 1, 1, 1, 1)
        imaxs = (500, 500, 500, 500, 500)
        self.nmult = ExposureMultiplier(
            rhs, labels, ivals, imins, imaxs, 5, self.check, False, width=4
        )
        # grid (on RHS)
        self.nmult.grid(row=0, column=0, columnspan=2, pady=2, sticky=tk.E + tk.S)

        tk.Label(rhs, text="COMPO  ").grid(row=1, column=0)
        self.compo = w.OnOff(rhs, False, self.check)
        self.compo.grid(row=1, column=1, pady=2, sticky=tk.W)

        # We have two possible window frames. A single pair for
        # drift mode, or a 2-quad frame for window mode.

        # drift frame
        # xstart - LH window of pair
        xsls = (1,)
        xslmins = (1,)
        xslmaxs = (1024,)
        # xstart - RH window of pair
        xsrs = (1025,)
        xsrmins = (1025,)
        xsrmaxs = (2048,)
        # ystart values
        yss = (1,)
        ysmins = (1,)
        ysmaxs = (512,)
        # sizes of windows (start at FF)
        nxs = (100,)
        nys = (100,)
        # allowed binning factors
        xbfac = tuple(range(1, 21))
        ybfac = tuple(range(1, 21))
        self.drift_frame = w.WinPairs(
            lhs,
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
            self.check,
        )

        # window frame for quads
        # xstart on LHS
        xsll = xsul = (1, 1)
        xsllmin = xsulmin = (1, 1)
        xsllmax = xsulmax = (1024, 1024)
        # xstart on RHS
        xslr = xsur = (1025, 1025)
        xslrmin = xsurmin = (1025, 1025)
        xslrmax = xsurmax = (2048, 2048)
        # ystart
        ys = (1, 1)
        ysmin = (1, 1)
        ysmax = (512, 512)
        # sizes (start at FF)
        nx = (1024, 1024)
        ny = (512, 512)
        self.quad_frame = w.WinQuads(
            lhs,
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
            self.check,
        )

        self.quad_frame.grid(row=10, column=0, columnspan=3, sticky=tk.W + tk.N)

        # Pack two halfs
        lhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)
        rhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)

        # Store freeze state
        self.frozen = False

        self.setExpertLevel()

    @property
    def wframe(self):
        if self.isDrift():
            return self.drift_frame
        return self.quad_frame

    def setupNodding(self):
        """
        Setup Nodding for GTC
        """
        g = get_root(self).globals

        if not self.nod():
            # re-enable clear mode box if not drift
            if not self.isDrift():
                self.clear.enable()

            # clear existing nod pattern
            self.nodPattern = {}
            self.check()
            return

        # Do nothing if we're not at the GTC
        if g.cpars["telins_name"] != "GTC":
            messagebox.showerror("Error", "Cannot dither WHT")
            self.nod.set(False)
            self.nodPattern = {}
            return

        # check for drift mode and bomb out
        if self.isDrift():
            messagebox.showerror("Error", "Cannot dither telescope in drift mode")
            self.nod.set(False)
            self.nodPattern = {}
            return

        # check for clear not enabled and warn
        if not self.clear():
            if not messagebox.askokcancel(
                "Warning", "Dithering telescope will enable clear mode. Continue?"
            ):
                self.nod.set(False)
                self.nodPattern = {}
                return

        # Ask for nod pattern
        try:
            home = expanduser("~")
            fname = filedialog.askopenfilename(
                title="Open offsets text file",
                defaultextension=".txt",
                filetypes=[("text files", ".txt")],
                initialdir=home,
            )

            if not fname:
                g.clog.warn("Aborted load from disk")
                raise ValueError

            ra, dec = np.loadtxt(fname).T
            if len(ra) != len(dec):
                g.clog.warn("Mismatched lengths of RA and Dec offsets")
                raise ValueError

            data = dict(ra=ra.tolist(), dec=dec.tolist())
        except Exception:
            g.clog.warn("Setting dither pattern failed. Disabling dithering")
            self.nod.set(False)
            self.nodPattern = {}
            return

        # store nodding on ipars object
        self.nodPattern = data
        # enable clear mode
        self.clear.set(True)
        # update
        self.check()

    def setExpertLevel(self):
        g = get_root(self).globals
        level = g.cpars["expert_level"]
        if level == 0:
            self.ledLab.grid_forget()
            self.led.grid_forget()
            self.led.set(0)

            self.oscanLab.config(text="Overscan")
            self.oscany.grid_forget()
            self.remember_oscany = self.oscany()
            self.oscany.set(0)

            self.dummyLab.grid_forget()
            self.dummy.grid_forget()
        else:
            self.ledLab.grid(row=4, column=0, sticky=tk.W)
            self.led.grid(row=4, column=1, columnspan=2, pady=2, sticky=tk.W)

            self.oscanLab.config(text="Overscan (x, y)")
            self.oscany.grid(row=3, column=2, sticky=tk.W)
            if hasattr(self, "remember_oscany"):
                self.oscany.set(self.remember_oscany)

            self.dummyLab.grid(row=5, column=0, sticky=tk.W)
            self.dummy.grid(row=5, column=1, columnspan=2, pady=2, sticky=tk.W)

    def isDrift(self):
        if self.app.value() == "Drift":
            return True
        elif self.app.value() in ["FullFrame", "Windows"]:
            return False
        else:
            raise DriverError(
                "InstPars.isDrift: application " + self.app.value() + " not recognised"
            )

    def isFF(self):
        if self.app.value() == "FullFrame":
            return True
        elif self.app.value() in ["Drift", "Windows"]:
            return False
        else:
            raise DriverError(
                "InstPars.isDrift: application " + self.app.value() + " not recognised"
            )

    def dumpJSON(self):
        """
        Encodes current parameters to JSON compatible dictionary
        """
        numexp = self.number.get()
        expTime, _, cadence, _, _ = self.timing()
        if numexp == 0:
            numexp = -1

        data = dict(
            numexp=self.number.value(),
            app=self.app.value(),
            led_flsh=self.led(),
            dummy_out=self.dummy(),
            fast_clks=self.fastClk(),
            readout=self.readSpeed(),
            dwell=self.expose.value(),
            exptime=expTime,
            cadence=cadence,
            oscan=self.oscan(),
            oscany=self.oscany(),
            xbin=self.wframe.xbin.value(),
            ybin=self.wframe.ybin.value(),
            multipliers=self.nmult.getall(),
            clear=self.clear(),
        )

        # only allow nodding in clear mode, even if GUI has got confused
        if data["clear"] and self.nodPattern:
            data["nodpattern"] = self.nodPattern

        # no mixing clear and multipliers, no matter what GUI says
        if data["clear"]:
            data["multipliers"] = [1 for i in self.nmult.getall()]

        # add window mode
        if not self.isFF():
            if self.isDrift():
                # no clear, multipliers or oscan in drift
                for setting in ("clear", "oscan", "oscany"):
                    data[setting] = 0
                data["multipliers"] = [1 for i in self.nmult.getall()]

                for iw, (xsl, xsr, ys, nx, ny) in enumerate(self.wframe):
                    data["x{}start_left".format(iw + 1)] = xsl
                    data["x{}start_right".format(iw + 1)] = xsr
                    data["y{}start".format(iw + 1)] = ys
                    data["y{}size".format(iw + 1)] = ny
                    data["x{}size".format(iw + 1)] = nx
            else:
                # no oscany in window mode
                data["oscany"] = 0

                for iw, (xsll, xsul, xslr, xsur, ys, nx, ny) in enumerate(self.wframe):
                    data["x{}start_upperleft".format(iw + 1)] = xsul
                    data["x{}start_lowerleft".format(iw + 1)] = xsll
                    data["x{}start_upperright".format(iw + 1)] = xsur
                    data["x{}start_lowerright".format(iw + 1)] = xslr
                    data["y{}start".format(iw + 1)] = ys
                    data["x{}size".format(iw + 1)] = nx
                    data["y{}size".format(iw + 1)] = ny
        return data

    def loadJSON(self, json_string):
        """
        Loads in an application saved in JSON format.
        """
        g = get_root(self).globals

        # enable COMPO if present in JSON
        if "compo" in json.loads(json_string):
            self.compo.set(1)
        else:
            self.compo.set(0)

        data = json.loads(json_string)["appdata"]
        # first set the parameters which change regardless of mode
        # number of exposures
        numexp = data.get("numexp", 0)
        if numexp == -1:
            numexp = 0
        self.number.set(numexp)
        # Overscan (x, y)
        if "oscan" in data:
            self.oscan.set(data["oscan"])
        if "oscany" in data:
            self.oscan.set(data["oscany"])
        # LED setting
        self.led.set(data.get("led_flsh", 0))
        # Dummy output enabled
        self.dummy.set(data.get("dummy_out", 1))
        # Fast clocking option?
        self.fastClk.set(data.get("fast_clks", 0))
        # readout speed
        self.readSpeed.set(data.get("readout", "Slow"))
        # dwell
        dwell = data.get("dwell", 0)
        self.expose.set(str(float(dwell)))

        # multipliers
        mult_values = data.get("multipliers", (1, 1, 1, 1, 1))
        self.nmult.setall(mult_values)

        # look for nodpattern in data
        nodPattern = data.get("nodpattern", {})
        if nodPattern and g.cpars["telins_name"] == "GTC":
            self.nodPattern = nodPattern
            self.nod.set(True)
            self.clear.set(True)
        else:
            self.nodPattern = {}
            self.nod.set(False)

        # binning
        self.quad_frame.xbin.set(data.get("xbin", 1))
        self.quad_frame.ybin.set(data.get("ybin", 1))
        self.drift_frame.xbin.set(data.get("xbin", 1))
        self.drift_frame.ybin.set(data.get("ybin", 1))

        # now for the behaviour which depends on mode
        if "app" in data:
            self.app.set(data["app"])
            app = data["app"]

            if app == "Drift":
                # disable clear mode in drift
                self.clear.set(0)
                # only one pair allowed
                self.wframe.npair.set(1)

                # set the window pair values
                labels = (
                    "x1start_left",
                    "y1start",
                    "x1start_right",
                    "x1size",
                    "y1size",
                )
                if not all(label in data for label in labels):
                    raise DriverError("Drift mode application missing window params")
                # now actually set them
                self.wframe.xsl[0].set(data["x1start_left"])
                self.wframe.xsr[0].set(data["x1start_right"])
                self.wframe.ys[0].set(data["y1start"])
                self.wframe.nx[0].set(data["x1size"])
                self.wframe.ny[0].set(data["y1size"])
                self.wframe.check()

            elif app == "FullFrame":
                # enable clear mode if set
                self.clear.set(data.get("clear", 0))

            elif app == "Windows":
                # enable clear mode if set
                self.clear.set(data.get("clear", 0))
                nquad = 0
                for nw in range(2):
                    labels = (
                        (
                            "x{0}start_lowerleft y{0}start x{0}start_upperleft x{0}start_upperright "
                            + "x{0}start_lowerright x{0}size y{0}size"
                        )
                        .format(nw + 1)
                        .split()
                    )
                    if all(label in data for label in labels):
                        xsll = data[labels[0]]
                        xslr = data[labels[4]]
                        xsul = data[labels[2]]
                        xsur = data[labels[3]]
                        ys = data[labels[1]]
                        nx = data[labels[5]]
                        ny = data[labels[6]]
                        self.wframe.xsll[nw].set(xsll)
                        self.wframe.xslr[nw].set(xslr)
                        self.wframe.xsul[nw].set(xsul)
                        self.wframe.xsur[nw].set(xsur)
                        self.wframe.ys[nw].set(ys)
                        self.wframe.nx[nw].set(nx)
                        self.wframe.ny[nw].set(ny)
                        nquad += 1
                    else:
                        break
                self.wframe.nquad.set(nquad)
                self.wframe.check()

    @inlineCallbacks
    def check(self, *args):
        """
        Callback to check validity of instrument parameters.

        Performs the following tasks:
            - spots and flags overlapping windows or null window parameters
            - flags windows with invalid dimensions given the binning parameter
            - sets the correct number of enabled windows
            - disables or enables clear and nod buttons depending on drift mode or not
            - checks for window synchronisation, enabling sync button if required
            - enables or disables start button if settings are OK

        Returns
        -------
        status : bool
            True or False according to whether the settings are OK.
        """
        status = True
        root = get_root(self)
        g = root.globals

        # if we've just enabled COMPO, then raise window if exists
        if self.compo():
            compo_hw_widget = getattr(g, "compo_hw", None)
            if compo_hw_widget is not None:
                if compo_hw_widget.state() == "withdrawn":
                    compo_hw_widget.deiconify()
                    place_at_edge(root, compo_hw_widget)

        # clear errors on binning (may be set later if FF)
        xbinw, ybinw = self.wframe.xbin, self.wframe.ybin
        xbinw.config(bg=g.COL["main"])
        ybinw.config(bg=g.COL["main"])

        # keep binning factors of drift mode and windowed mode up to date
        oframe, aframe = (
            (self.quad_frame, self.drift_frame)
            if self.drift_frame.winfo_ismapped()
            else (self.drift_frame, self.quad_frame)
        )
        xbin, ybin = aframe.xbin.value(), aframe.ybin.value()
        oframe.xbin.set(xbin)
        oframe.ybin.set(ybin)

        if not self.frozen:
            if self.clear() or self.isDrift():
                # disable nmult in clear or drift mode
                self.nmult.disable()
            else:
                self.nmult.enable()

        if self.isDrift():
            self.clearLab.config(state="disable")
            self.nodLab.config(state="disable")
            if not self.drift_frame.winfo_ismapped():
                self.quad_frame.grid_forget()
                self.drift_frame.grid(
                    row=10, column=0, columnspan=3, sticky=tk.W + tk.N
                )

            if not self.frozen:
                self.oscany.config(state="disable")
                self.oscan.config(state="disable")
                self.clear.config(state="disable")
                self.nod.config(state="disable")
                self.wframe.enable()
                status = self.wframe.check()

        elif self.isFF():
            # special case check of binning from window frame
            if 1024 % xbin != 0:
                status = False
                xbinw.config(bg=g.COL["error"])
            elif (1024 // xbin) % 4 != 0:
                status = False
                xbinw.config(bg=g.COL["error"])
            if 512 % ybin != 0:
                status = False
                ybinw.config(bg=g.COL["error"])

            if not self.quad_frame.winfo_ismapped():
                self.drift_frame.grid_forget()
                self.quad_frame.grid(row=10, column=0, columnspan=3, sticky=tk.W + tk.N)

            self.clearLab.config(state="normal")
            if g.cpars["telins_name"] == "GTC":
                self.nodLab.config(state="normal")
            else:
                self.nodLab.config(state="disable")
            if not self.frozen:
                self.oscany.config(state="normal")
                self.oscan.config(state="normal")
                self.clear.config(state="normal")
                if g.cpars["telins_name"] == "GTC":
                    self.nod.config(state="normal")
                else:
                    self.nod.config(state="disable")
                self.wframe.disable()

        else:
            self.clearLab.config(state="normal")
            if g.cpars["telins_name"] == "GTC":
                self.nodLab.config(state="normal")
            else:
                self.nodLab.config(state="disable")
            if not self.quad_frame.winfo_ismapped():
                self.drift_frame.grid_forget()
                self.quad_frame.grid(row=10, column=0, columnspan=3, sticky=tk.W + tk.N)

            if not self.frozen:
                self.oscany.config(state="disable")
                self.oscan.config(state="normal")
                self.clear.config(state="normal")
                if g.cpars["telins_name"] == "GTC":
                    self.nod.config(state="normal")
                else:
                    self.nod.config(state="disable")
                self.wframe.enable()
                status = self.wframe.check()

        # exposure delay
        if self.expose.ok():
            self.expose.config(bg=g.COL["main"])
        else:
            self.expose.config(bg=g.COL["warn"])
            status = False

        # don't allow binning other than 1, 2 in overscan or prescan mode
        if self.oscan() or self.oscany():
            if xbin not in (1, 2):
                status = False
                xbinw.config(bg=g.COL["error"])
            if ybin not in (1, 2):
                status = False
                ybinw.config(bg=g.COL["error"])

        # disable clear if nodding enabled. re-enable if not drift
        if not self.frozen:
            if self.nod() or self.nodPattern:
                self.clear.config(state="disabled")
                self.clearLab.config(state="disabled")
            elif not self.isDrift():
                self.clear.config(state="normal")
                self.clearLab.config(state="normal")

        # allow posting if parameters are OK. update count and SN estimates too
        if status:
            try:
                run_active = yield tools.isRunActive(g)
                powered_on = yield tools.isPoweredOn(g)
            except Exception as err:
                g.clog.warn(str(err))
            if (
                g.cpars["hcam_server_on"]
                and g.cpars["eso_server_online"]
                and g.observe.start["state"] == "disabled"
                and not run_active
                and powered_on
            ):
                g.observe.start.enable()
            g.count.update()
        else:
            g.observe.start.disable()

        return status

    def freeze(self):
        """
        Freeze all settings so they cannot be altered
        """
        self.app.disable()
        self.clear.disable()
        self.nod.disable()
        self.led.disable()
        self.dummy.disable()
        self.readSpeed.disable()
        self.expose.disable()
        self.number.disable()
        self.wframe.disable(everything=True)
        self.nmult.disable()
        self.frozen = True

    def unfreeze(self):
        """
        Reverse of freeze
        """
        self.app.enable()
        self.clear.enable()
        self.nod.enable()
        self.led.enable()
        self.dummy.enable()
        self.readSpeed.enable()
        self.expose.enable()
        self.number.enable()
        self.wframe.enable()
        self.nmult.enable()
        self.frozen = False

    def getRtplotWins(self):
        """ "
        Returns a string suitable to sending off to rtplot when
        it asks for window parameters. Returns null string '' if
        the windows are not OK. This operates on the basis of
        trying to send something back, even if it might not be
        OK as a window setup. Note that we have to take care
        here not to update any GUI components because this is
        called outside of the main thread.
        """
        try:
            if self.isFF():
                return "fullframe\r\n"
            elif self.isDrift():
                xbin = self.wframe.xbin.value()
                ybin = self.wframe.ybin.value()
                nwin = 2 * self.wframe.npair.value()
                ret = str(xbin) + " " + str(ybin) + " " + str(nwin) + "\r\n"
                for xsl, xsr, ys, nx, ny in self.wframe:
                    ret += "{:d} {:d} {:d} {:d}\r\n".format(xsl, ys, nx, ny)
                    ret += "{:d} {:d} {:d} {:d}".format(xsr, ys, nx, ny)
                return ret
            else:
                xbin = self.wframe.xbin.value()
                ybin = self.wframe.ybin.value()
                nwin = 4 * self.wframe.nquad.value()
                ret = str(xbin) + " " + str(ybin) + " " + str(nwin) + "\r\n"
                for xsll, xsul, xslr, xsur, ys, nx, ny in self.wframe:
                    ret += "{:d} {:d} {:d} {:d}\r\n".format(xsll, ys, nx, ny)
                    ret += "{:d} {:d} {:d} {:d}\r\n".format(
                        xsul, 1025 - ys - ny, nx, ny
                    )
                    ret += "{:d} {:d} {:d} {:d}\r\n".format(xslr, ys, nx, ny)
                    ret += "{:d} {:d} {:d} {:d}\r\n".format(
                        xsur, 1025 - ys - ny, nx, ny
                    )
                return ret
        except Exception:
            return ""

    def timing(self):
        """
        Estimates timing information for the current setup. You should
        run a check on the instrument parameters before calling this.

        Returns: (expTime, deadTime, cycleTime, dutyCycle)

        expTime   : exposure time per frame (seconds)
        deadTime  : dead time per frame (seconds)
        cycleTime : sampling time (cadence), (seconds)
        dutyCycle : percentage time exposing.
        frameRate : number of frames per second
        """
        # drift mode y/n?
        isDriftMode = self.isDrift()
        # FF y/n?
        isFF = self.isFF()

        # Set the readout speed
        readSpeed = self.readSpeed()

        if readSpeed == "Fast" and self.dummy():
            video = pars.VIDEO_FAST
        elif readSpeed == "Slow" and self.dummy():
            video = pars.VIDEO_SLOW
        elif not self.dummy():
            video = pars.VIDEO_SLOW_SE
        else:
            raise DriverError(
                "InstPars.timing: readout speed = " + readSpeed + " not recognised."
            )

        if self.fastClk():
            DUMP_TIME = pars.DUMP_TIME_FAST
            VCLOCK_FRAME = pars.VCLOCK_FAST
            VCLOCK_STORAGE = pars.VCLOCK_FAST
            HCLOCK = pars.HCLOCK_FAST
        else:
            DUMP_TIME = pars.DUMP_TIME_SLOW
            VCLOCK_FRAME = pars.VCLOCK_FRAME_SLOW
            VCLOCK_STORAGE = pars.VCLOCK_STORAGE_SLOW
            HCLOCK = pars.HCLOCK_SLOW

        # clear chip on/off?
        lclear = not isDriftMode and self.clear()

        # overscan read or not
        oscan = not isDriftMode and self.oscan()
        oscany = not isDriftMode and self.oscany()

        # get exposure delay
        expose = self.expose.value()

        # window parameters
        xbin = self.wframe.xbin.value()
        ybin = self.wframe.ybin.value()
        if isDriftMode:
            nwin = 1  # number of windows per output
            dys = self.wframe.ys[0].value() - 1
            dnx = self.wframe.nx[0].value()
            dny = self.wframe.ny[0].value()
            dxsl = self.wframe.xsl[0].value()
            dxsr = self.wframe.xsr[0].value()
            # differential shift needed to line both
            # windows up with the edge of the chip
            diffshift = abs(dxsl - 1 - (2 * pars.FFX - dxsr - dnx + 1))
        elif isFF:
            nwin = 1
            ys, nx, ny = [0], [1024], [512]
        else:
            ys, nx, ny = [], [], []
            xse, xsf, xsg, xsh = [], [], [], []
            nwin = self.wframe.nquad.value()
            for xsll, xsul, xslr, xsur, ysv, nxv, nyv in self.wframe:
                xse.append(xsll - 1)
                xsf.append(2049 - xslr - nxv)
                xsg.append(2049 - xsur - nxv)
                xsh.append(xsul - 1)
                ys.append(ysv - 1)
                nx.append(nxv)
                ny.append(nyv)

        # convert timing parameters to seconds
        expose_delay = expose

        # clear chip by VCLOCK-ing the image and area and dumping storage area (x5)
        if lclear:
            clear_time = 5 * (pars.FFY * VCLOCK_FRAME + pars.FFY * DUMP_TIME)
        else:
            clear_time = 0.0

        if isDriftMode:
            # for drift mode, we need the number of windows in the pipeline
            # and the pipeshift
            nrows = pars.FFY  # number of rows in storage area
            pnwin = int(((nrows / dny) + 1) / 2)
            pshift = nrows - (2 * pnwin - 1) * dny
            frame_transfer = (dny + dys) * VCLOCK_FRAME

            yshift = [dys * VCLOCK_STORAGE]

            # After placing the window adjacent to the serial register, the
            # register must be cleared by clocking out the entire register,
            # taking FFX hclocks.
            line_clear = [0.0]
            if yshift[0] != 0:
                line_clear[0] = DUMP_TIME

            # to calculate number of HCLOCKS needed to read a line in
            # drift mode we have to account for the diff shifts and dumping.
            # first perform diff shifts
            # for now we need this *2 (for quadrants E, H or F, G)
            numhclocks = 2 * diffshift
            # now add the amount of clocks needed to get
            # both windows to edge of chip
            if dxsl - 1 > 2 * pars.FFX - dxsr - dnx + 1:
                # it was the left window that got the diff shift,
                # so the number of hclocks increases by the amount
                # needed to get the RH window to the edge
                numhclocks += 2 * pars.FFX - dxsr - dnx + 1
            else:
                # vice versa
                numhclocks += dxsl - 1
            # now we actually clock the windows themselves
            numhclocks += dnx
            # finally, we need to hclock the additional pre-scan pixels
            numhclocks += 2 * pars.PRSCX

            # here is the total time to read the whole line
            line_read = [
                VCLOCK_STORAGE * ybin
                + numhclocks * HCLOCK
                + video * dnx / xbin
                + DUMP_TIME
                + 2 * pars.SETUP_READ
            ]

            readout = [(dny / ybin) * line_read[0]]
        elif isFF:
            # move entire image into storage area
            frame_transfer = pars.FFY * VCLOCK_FRAME + DUMP_TIME

            yshift = [0]
            line_clear = [0]

            numhclocks = pars.FFX + pars.PRSCX
            line_read = [
                VCLOCK_STORAGE * ybin
                + numhclocks * HCLOCK
                + video * nx[0] / xbin
                + pars.SETUP_READ
            ]
            if oscan:
                line_read[0] += video * pars.PRSCX / xbin
            nlines = ny[0] / ybin if not oscany else (ny[0] + 8 / ybin)
            readout = [nlines * line_read[0]]
        else:
            # windowed mode
            # move entire image into storage area
            frame_transfer = pars.FFY * VCLOCK_FRAME + DUMP_TIME

            # dump rows in storage area up to start of the window without changing the
            # image area.
            yshift = nwin * [0.0]
            yshift[0] = ys[0] * DUMP_TIME
            for nw in range(1, nwin):
                yshift[nw] = (ys[nw] - ys[nw - 1] - ny[nw - 1]) * DUMP_TIME

            line_clear = nwin * [0.0]
            # Naidu always dumps the serial register, in windowed mode
            # regardless of whether we need to or not
            for nw in range(nwin):
                line_clear[nw] = DUMP_TIME

            # calculate how long it takes to shift one row into the serial
            # register shift along serial register and then read out the data.
            # total number of hclocks needs to account for diff shifts of
            # windows, carried out in serial
            numhclocks = nwin * [0]
            for nw in range(nwin):
                common_shift = min(xse[nw], xsf[nw], xsg[nw], xsh[nw])
                diffshifts = sum(
                    (xs - common_shift for xs in (xse[nw], xsf[nw], xsg[nw], xsh[nw]))
                )
                numhclocks[nw] = 2 * pars.PRSCX + common_shift + diffshifts + nx[nw]

            line_read = nwin * [0.0]
            # line read includes vclocking a row, all the hclocks, digitising pixels and dumping serial register
            # when windows are read out.
            for nw in range(nwin):
                line_read[nw] = (
                    VCLOCK_STORAGE * ybin
                    + numhclocks[nw] * HCLOCK
                    + video * nx[nw] / xbin
                    + 2 * pars.SETUP_READ
                    + DUMP_TIME
                )
                if oscan:
                    line_read[nw] += video * pars.PRSCX / xbin

            # multiply time to shift one row into serial register by
            # number of rows for total readout time
            readout = nwin * [0.0]
            for nw in range(nwin):
                nlines = ny[nw] / ybin if not oscany else (ny[nw] + 8 / ybin)
                readout[nw] = nlines * line_read[nw]

        # now get the total time to read out one exposure.
        cycleTime = expose_delay + clear_time + frame_transfer
        if isDriftMode:
            cycleTime += (
                pshift * VCLOCK_STORAGE + yshift[0] + line_clear[0] + readout[0]
            )
        else:
            for nw in range(nwin):
                cycleTime += yshift[nw] + line_clear[nw] + readout[nw]

        # use 5sec estimate for nod time
        # TODO: replace with accurate estimate
        if self.nod() and lclear:
            cycleTime += 5
        elif self.nod():
            g = get_root(self).globals
            g.clog.warn("ERR: dithering enabled with clear mode off")

        frameRate = 1.0 / cycleTime
        expTime = expose_delay if lclear else cycleTime - frame_transfer
        deadTime = cycleTime - expTime
        dutyCycle = 100.0 * expTime / cycleTime
        return (expTime, deadTime, cycleTime, dutyCycle, frameRate)


class RunPars(tk.LabelFrame):
    """
    Run parameters
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(
            self, master, text="Next run parameters", padx=10, pady=10
        )

        row = 0
        column = 0
        tk.Label(self, text="Target name").grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text="Filters").grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text="Programme ID/OB").grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text="Principal Investigator").grid(
            row=row, column=column, sticky=tk.W
        )

        row += 1
        tk.Label(self, text="Observer(s)").grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text="Pre-run comment").grid(row=row, column=column, sticky=tk.W)

        # spacer
        column += 1
        tk.Label(self, text=" ").grid(row=0, column=column)

        # target
        row = 0
        column += 1
        self.target = w.Target(self, self.check)
        self.target.grid(row=row, column=column, sticky=tk.W)

        # filter
        row += 1
        self.filter = w.TextEntry(self, 20, self.check)
        self.filter.grid(row=row, column=column, sticky=tk.W)

        # programme ID / OBID
        row += 1
        self.prog_ob = w.ProgramID(self)
        self.prog_ob.grid(row=row, column=column, sticky=tk.W)

        # principal investigator
        row += 1
        self.pi = w.TextEntry(self, 20, self.check)
        self.pi.grid(row=row, column=column, sticky=tk.W)

        # observers
        row += 1
        self.observers = w.TextEntry(self, 20, self.check)
        self.observers.grid(row=row, column=column, sticky=tk.W)

        # comment
        row += 1
        self.comment = w.TextEntry(self, 38)
        self.comment.grid(row=row, column=column, sticky=tk.W)

    def loadJSON(self, json_string):
        """
        Sets the values of the run parameters given an JSON string
        """
        g = get_root(self).globals
        user = json.loads(json_string)["user"]

        def setField(widget, field):
            val = user.get(field)
            if val is not None:
                widget.set(val.strip())

        setField(self.prog_ob.obid, "OB")
        setField(self.target, "target")
        setField(self.prog_ob.progid, "ID")
        setField(self.pi, "PI")
        setField(self.observers, "Observers")
        setField(self.comment, "comment")
        setField(self.filter, "filters")
        setField(g.observe.rtype, "flags")

    def dumpJSON(self):
        """
        Encodes current parameters to JSON compatible dictionary
        """
        g = get_root(self).globals
        dtype = g.observe.rtype()
        if dtype == "bias":
            target = "BIAS"
        elif dtype == "flat":
            target = "FLAT"
        elif dtype == "dark":
            target = "DARK"
        else:
            target = self.target.value()

        return dict(
            target=target,
            ID=self.prog_ob.progid.value(),
            PI=self.pi.value(),
            OB="{:04d}".format(self.prog_ob.obid.value()),
            Observers=self.observers.value(),
            comment=self.comment.value(),
            flags=dtype,
            filters=self.filter.value(),
        )

    def check(self, *args):
        """
        Checks the validity of the run parameters. Returns
        flag (True = OK), and a message which indicates the
        nature of the problem if the flag is False.
        """

        ok = True
        msg = ""
        g = get_root(self).globals
        dtype = g.observe.rtype()
        expert = g.cpars["expert_level"] > 0

        if dtype == "bias" or dtype == "flat" or dtype == "dark":
            self.pi.configure(state="disable")
            self.prog_ob.configure(state="disable")
            self.target.disable()
        else:
            if expert:
                self.pi.configure(state="normal")
                self.prog_ob.configure(state="normal")
                self.prog_ob.enable()
            else:
                self.prog_ob.configure(state="disable")
                self.pi.configure(state="disable")
                self.prog_ob.disable()
            self.target.enable()

        if g.cpars["require_run_params"]:
            if self.target.ok():
                self.target.entry.config(bg=g.COL["main"])
            else:
                self.target.entry.config(bg=g.COL["error"])
                ok = False
                msg += "Target name field cannot be blank\n"

            if dtype == "acquisition" or dtype == "data" or dtype == "technical":
                if self.prog_ob.ok():
                    self.prog_ob.config(bg=g.COL["main"])
                else:
                    self.prog_ob.config(bg=g.COL["error"])
                    ok = False
                    msg += "Programme or OB ID field cannot be blank\n"

                if self.pi.ok():
                    self.pi.config(bg=g.COL["main"])
                else:
                    self.pi.config(bg=g.COL["error"])
                    ok = False
                    msg += "Principal Investigator field cannot be blank\n"

            if self.observers.ok():
                self.observers.config(bg=g.COL["main"])
            else:
                self.observers.config(bg=g.COL["error"])
                ok = False
                msg += "Observers field cannot be blank"
        return (ok, msg)

    def setExpertLevel(self):
        g = get_root(self).globals
        expert = g.cpars["expert_level"] > 0
        if expert:
            self.pi.configure(state="normal")
            self.prog_ob.configure(state="normal")
            self.prog_ob.enable()
        else:
            self.prog_ob.configure(state="disable")
            self.pi.configure(state="disable")
            self.prog_ob.disable()

    def freeze(self):
        """
        Freeze all settings so that they can't be altered
        """
        self.target.disable()
        self.filter.configure(state="disable")
        self.prog_ob.configure(state="disable")
        self.pi.configure(state="disable")
        self.observers.configure(state="disable")
        self.comment.configure(state="disable")

    def unfreeze(self):
        """
        Unfreeze all settings so that they can be altered
        """
        g = get_root(self).globals
        self.filter.configure(state="normal")
        dtype = g.observe.rtype()
        if dtype == "acquisition" or dtype == "data" or dtype == "technical":
            self.prog_ob.configure(state="normal")
            self.pi.configure(state="normal")
            self.target.enable()
        self.observers.configure(state="normal")
        self.comment.configure(state="normal")


class CountsFrame(tk.LabelFrame):
    """
    Frame for count rate estimates
    """

    def __init__(self, master):
        """
        master : enclosing widget
        """
        tk.LabelFrame.__init__(self, master, pady=2, text="Count & S-to-N estimator")

        # divide into left and right frames
        lframe = tk.Frame(self, padx=2)
        rframe = tk.Frame(self, padx=2)

        # entries
        self.filter = w.Radio(
            lframe, ("u", "g", "r", "i", "z"), 3, self.checkUpdate, initial=1
        )
        self.mag = w.RangedFloat(
            lframe, 18.0, 0.0, 30.0, self.checkUpdate, True, width=5, nplaces=2
        )
        self.seeing = w.RangedFloat(
            lframe, 1.0, 0.2, 20.0, self.checkUpdate, True, True, width=5, nplaces=1
        )
        self.airmass = w.RangedFloat(
            lframe, 1.5, 1.0, 5.0, self.checkUpdate, True, width=5, nplaces=2
        )
        self.moon = w.Radio(lframe, ("d", "g", "b"), 3, self.checkUpdate)

        # results
        self.cadence = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.exposure = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.duty = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.peak = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.total = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.ston = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)
        self.ston3 = w.Ilabel(rframe, text="UNDEF", width=10, anchor=tk.W)

        # layout
        # left
        tk.Label(lframe, text="Filter:").grid(
            row=0, column=0, padx=5, pady=3, sticky=tk.W + tk.N
        )
        self.filter.grid(row=0, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text="Mag:").grid(row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.mag.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text="Seeing:").grid(
            row=2, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.seeing.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text="Airmass:").grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.airmass.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text="Moon:").grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.moon.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)

        # right
        tk.Label(rframe, text="Cadence:").grid(
            row=0, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.cadence.grid(row=0, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="Exposure:").grid(
            row=1, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.exposure.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="Duty cycle:").grid(
            row=2, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.duty.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="Peak:").grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.peak.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="Total:").grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.total.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="S/N:").grid(row=5, column=0, padx=5, pady=3, sticky=tk.W)
        self.ston.grid(row=5, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text="S/N (3h):").grid(
            row=6, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.ston3.grid(row=6, column=1, padx=5, pady=3, sticky=tk.W)

        # slot frames in
        lframe.grid(row=0, column=0, sticky=tk.W + tk.N)
        rframe.grid(row=0, column=1, sticky=tk.W + tk.N)

    def checkUpdate(self, *args):
        """
        Updates values after first checking instrument parameters are OK.
        This is not integrated within update to prevent ifinite recursion
        since update gets called from ipars.
        """
        g = get_root(self).globals
        if not self.check():
            g.clog.warn("Current observing parameters are not valid.")
            return False

        if not g.ipars.check():
            g.clog.warn("Current instrument parameters are not valid.")
            return False

    def check(self):
        """
        Checks values
        """
        status = True
        g = get_root(self).globals
        if self.mag.ok():
            self.mag.config(bg=g.COL["main"])
        else:
            self.mag.config(bg=g.COL["warn"])
            status = False

        if self.airmass.ok():
            self.airmass.config(bg=g.COL["main"])
        else:
            self.airmass.config(bg=g.COL["warn"])
            status = False

        if self.seeing.ok():
            self.seeing.config(bg=g.COL["main"])
        else:
            self.seeing.config(bg=g.COL["warn"])
            status = False

        return status

    def update(self, *args):
        """
        Updates values. You should run a check on the instrument and
        target parameters before calling this.
        """
        g = get_root(self).globals
        expTime, deadTime, cycleTime, dutyCycle, frameRate = g.ipars.timing()

        total, peak, peakSat, peakWarn, ston, ston3 = self.counts(expTime, cycleTime)

        if cycleTime < 0.01:
            self.cadence.config(text="{0:7.5f} s".format(cycleTime))
        elif cycleTime < 0.1:
            self.cadence.config(text="{0:6.4f} s".format(cycleTime))
        elif cycleTime < 1.0:
            self.cadence.config(text="{0:5.3f} s".format(cycleTime))
        elif cycleTime < 10.0:
            self.cadence.config(text="{0:4.2f} s".format(cycleTime))
        elif cycleTime < 100.0:
            self.cadence.config(text="{0:4.1f} s".format(cycleTime))
        elif cycleTime < 1000.0:
            self.cadence.config(text="{0:4.0f} s".format(cycleTime))
        else:
            self.cadence.config(text="{0:5.0f} s".format(cycleTime))

        if expTime < 0.01:
            self.exposure.config(text="{0:7.5f} s".format(expTime))
        elif expTime < 0.1:
            self.exposure.config(text="{0:6.4f} s".format(expTime))
        elif expTime < 1.0:
            self.exposure.config(text="{0:5.3f} s".format(expTime))
        elif expTime < 10.0:
            self.exposure.config(text="{0:4.2f} s".format(expTime))
        elif expTime < 100.0:
            self.exposure.config(text="{0:4.1f} s".format(expTime))
        elif expTime < 1000.0:
            self.exposure.config(text="{0:4.0f} s".format(expTime))
        else:
            self.exposure.config(text="{0:5.0f} s".format(expTime))

        self.duty.config(text="{0:4.1f} %".format(dutyCycle))
        self.peak.config(text="{0:d} cts".format(int(round(peak))))
        if peakSat:
            self.peak.config(bg=g.COL["error"])
        elif peakWarn:
            self.peak.config(bg=g.COL["warn"])
        else:
            self.peak.config(bg=g.COL["main"])

        self.total.config(text="{0:d} cts".format(int(round(total))))
        self.ston.config(text="{0:.1f}".format(ston))
        self.ston3.config(text="{0:.1f}".format(ston3))

    def counts(self, expTime, cycleTime, ap_scale=1.6, ndiv=5):
        """
        Computes counts per pixel, total counts, sky counts
        etc given current magnitude, seeing etc. You should
        run a check on the instrument parameters before calling
        this.

        expTime   : exposure time per frame (seconds)
        cycleTime : sampling, cadence (seconds)
        ap_scale  : aperture radius as multiple of seeing

        Returns: (total, peak, peakSat, peakWarn, ston, ston3)

        total    -- total number of object counts in aperture
        peak     -- peak counts in a pixel
        peakSat  -- flag to indicate saturation
        peakWarn -- flag to indication level approaching saturation
        ston     -- signal-to-noise per exposure
        ston3    -- signal-to-noise after 3 hours on target
        """

        # code directly translated from Java equivalent.
        g = get_root(self).globals

        # Set the readout speed
        readSpeed = g.ipars.readSpeed()
        if readSpeed == "Fast":
            gain = pars.GAIN_FAST
            read = pars.RNO_FAST
        elif readSpeed == "Slow":
            gain = pars.GAIN_SLOW
            read = pars.RNO_SLOW
        else:
            raise DriverError(
                "CountsFrame.counts: readout speed = " + readSpeed + " not recognised."
            )

        xbin, ybin = g.ipars.wframe.xbin.value(), g.ipars.wframe.ybin.value()

        # calculate SN info.
        zero, sky, skyTot, darkTot = 0.0, 0.0, 0.0, 0.0
        total, peak, correct, signal, readTot, seeing = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        noise, narcsec, npix, signalToNoise3 = 1.0, 0.0, 0.0, 0.0

        tinfo = g.TINS[g.cpars["telins_name"]]
        filtnam = self.filter.value()

        zero = tinfo["zerop"][filtnam]
        mag = self.mag.value()
        seeing = self.seeing.value()
        sky = g.SKY[self.moon.value()][filtnam]
        airmass = self.airmass.value()
        plateScale = tinfo["plateScale"]

        # calculate expected electrons
        total = 10.0 ** ((zero - mag - airmass * g.EXTINCTION[filtnam]) / 2.5) * expTime

        # compute fraction that fall in central pixel
        # assuming target exactly at its centre. Do this
        # by splitting each pixel of the central (potentially
        # binned) pixel into ndiv * ndiv points at
        # which the seeing profile is added. sigma is the
        # RMS seeing in terms of pixels.
        sigma = seeing / g.EFAC / plateScale

        sum = 0.0
        for iyp in range(ybin):
            yoff = -ybin / 2.0 + iyp
            for ixp in range(xbin):
                xoff = -xbin / 2.0 + ixp
                for iys in range(ndiv):
                    y = (yoff + (iys + 0.5) / ndiv) / sigma
                    for ixs in range(ndiv):
                        x = (xoff + (ixs + 0.5) / ndiv) / sigma
                        sum += math.exp(-(x * x + y * y) / 2.0)
        peak = total * sum / (2.0 * math.pi * sigma**2 * ndiv**2)

        # Work out fraction of flux in aperture with radius AP_SCALE*seeing
        correct = 1.0 - math.exp(-((g.EFAC * ap_scale) ** 2) / 2.0)

        # expected sky e- per arcsec
        skyPerArcsec = 10.0 ** ((zero - sky) / 2.5) * expTime
        # skyPerPixel = skyPerArcsec*plateScale**2*xbin*ybin
        narcsec = math.pi * (ap_scale * seeing) ** 2
        skyTot = skyPerArcsec * narcsec
        npix = math.pi * (ap_scale * seeing / plateScale) ** 2 / xbin / ybin

        signal = correct * total  # in electrons
        darkTot = npix * pars.DARK_E * expTime  # in electrons
        readTot = npix * read**2  # in electrons

        # noise, in electrons
        noise = math.sqrt(readTot + darkTot + skyTot + signal)

        # Now compute signal-to-noise in 3 hour seconds run
        signalToNoise3 = signal / noise * math.sqrt(3 * 3600.0 / cycleTime)

        # convert from electrons to counts
        total /= gain
        peak /= gain

        warn = 25000
        sat = 60000

        peakSat = peak > sat
        peakWarn = peak > warn

        return (total, peak, peakSat, peakWarn, signal / noise, signalToNoise3)


class RunType(w.Select):
    """
    Dropdown box to select run type.

    Start button should be disabled until an option is made from this dropdown.
    """

    DTYPES = ("", "data", "acquire", "bias", "flat", "dark", "tech")
    DVALS = ("", "data", "acquisition", "bias", "flat", "dark", "technical")

    def __init__(self, master, start_button, checker=None):
        w.Select.__init__(self, master, 0, RunType.DTYPES, self.check)
        self.start_button = start_button
        self._checker = checker

    def __call__(self):
        index = self.options.index(self.val.get())
        return RunType.DVALS[index]

    def set(self, value):
        index = RunType.DVALS.index(value)
        w.Select.set(self, RunType.DTYPES[index])

    @inlineCallbacks
    def check(self, *args):
        if self._checker is not None:
            self._checker()
        if self.val.get() == "":
            self.start_button.run_type_set = False
            self.start_button.disable()
        else:
            self.start_button.run_type_set = True
            g = get_root(self).globals
            try:
                run_active = yield tools.isRunActive(g)
                powered_on = yield tools.isPoweredOn(g)
            except Exception as err:
                g.clog.warn(str(err))
            if (
                g.cpars["hcam_server_on"]
                and g.cpars["eso_server_online"]
                and g.observe.start["state"] == "disabled"
                and not run_active
                and powered_on
            ):
                self.start_button.enable()
            g.rpars.check()


class Start(w.ActButton):
    """
    Button to start a run.

    This is a complex process including the following steps:

    -- check the instrument and run parameters are OK
    -- optionally, hassle the user if the target changes
    -- post the run settings to the ESO NGC control server
    -- start the run
    -- update the button status
    -- start the exposure timer
    """

    def __init__(self, master, width):
        """
        Parameters
        ----------
        master : tk
            containing widget
        width : int
            width of button
        """
        w.ActButton.__init__(self, master, width, text="Start")
        g = get_root(self).globals
        self.config(bg=g.COL["start"])
        self.target = None
        self.run_type_set = False

    def enable(self):
        """
        Enable the button
        """
        if self.run_type_set:
            w.ActButton.enable(self)
            g = get_root(self).globals
            self.config(bg=g.COL["start"])

    def disable(self):
        """
        Disable the button, if in non-expert mode.
        """
        w.ActButton.disable(self)
        g = get_root(self).globals
        if self._expert:
            self.config(bg=g.COL["start"])
        else:
            self.config(bg=g.COL["startD"])

    def setExpert(self):
        """
        Turns on 'expert' status whereby the button is always enabled,
        regardless of its activity status.
        """
        w.ActButton.setExpert(self)
        g = get_root(self).globals
        self.config(bg=g.COL["start"])

    def setNonExpert(self):
        """
        Turns off 'expert' status whereby to allow a button to be disabled
        """
        self._expert = False
        if self._active and self.run_type_set:
            self.enable()
        else:
            self.disable()

    @inlineCallbacks
    def on_telemetry(self, package):
        """
        This is run every time a telemetry packet comes in from NGC.

        It is the responsibility of an implementing GUI to subscribe to the
        NGC telemetry topic with this function as the callback.
        """
        telemetry = pickle.loads(package)
        res = tools.ReadNGCTelemetry(telemetry)
        if not res.ok:
            raise DriverError("cannot read NGC telemetry: " + str(res.err))
        if res.clocks != "enabled":
            # NGC voltages are not powered on, cannot start runs
            self.disable()
        elif res.state == "active":
            # run is underway - cannot start runs
            self.disable()
        else:
            self.enable()

    @inlineCallbacks
    def act(self):
        """
        Carries out action associated with start button
        """
        g = get_root(self).globals
        # check binning against overscan
        msg = """
        HiperCAM has an o/scan of 50 pixels.
        Your binning does not fit into this
        region. Some columns will contain a
        mix of o/scan and data.

        Click OK if you wish to continue."""
        if g.ipars.oscan():
            xbin, ybin = g.ipars.wframe.xbin.value(), g.ipars.wframe.ybin.value()
            if xbin not in (1, 2, 5, 10) or ybin not in (1, 2, 5, 10):
                if not messagebox.askokcancel("Binning alert", msg):
                    return False

        # Check instrument pars are OK
        if not g.ipars.check():
            g.clog.warn("Invalid instrument parameters; start failed.")
            return False

        # create JSON to post
        data = yield tools.createJSON(g)

        # check if COMPO is in position
        # Do this regardless if enabled or not, as we might need to park
        if not g.compo_hw.ok_to_start_run:
            msg = """
            COMPO is reporting that it is not ready to start a run.
            Please check the state of COMPO.
            
            Click OK if you wish to continue anyway."""
            if not messagebox.askokcancel("COMPO alert", msg):
                return False

        # check autoguiding is started if we are guiding with COMPO
        if g.ipars.compo() and g.compo_hw.setup_frame.injection_side.value() == "G":
            msg = """
            COMPO setup implies you will be guiding with COMPO.
            Check that autoguiding is set up and running.
            
            Click OK when you wish to continue and start run.
            Click Cancel to abort run."""
            if not messagebox.askokcancel("Guiding alert", msg):
                return False

        # check time to limit for rotator
        if (
            g.info.time_to_limit is not None
            and g.info.time_to_limit < g.info.WARN_LIMIT
        ):
            msg = f"""
            The rotator limit will be reach in less than {g.info.WARN_LIMIT.value} hour.

            You may want to de-rotate before starting the run. 
            Click OK when you wish to continue and start run.
            Click Cancel to abort run."""
            if not messagebox.askokcancel("Rotator alert", msg):
                return False

        # POST
        try:
            success = yield tools.postJSON(g, data)
            if not success:
                raise Exception("postJSON returned False")
        except Exception as err:
            g.clog.warn("Failed to post data to servers")
            g.clog.warn(str(err))
            return False

        # START
        try:
            success = yield tools.execCommand(g, "start")
            if not success:
                raise Exception("Start command failed: check server response")
        except Exception as err:
            g.clog.warn("Failed to start run")
            g.clog.warn(str(err))
            return False

        # Is nod enabled? Should we start GTC offsetter?
        try:
            success = yield tools.startNodding(g, data)
            if not success:
                raise Exception("Failed to start dither: response was false")
        except Exception as err:
            g.clog.warn("Failed to start GTC offsetter")
            g.clog.warn(str(err))
            g.clog.warn("Run may be paused indefinitely")
            g.clog.warn('use "ngcbCmd seq start" to fix')
            return False

        # Run successfully started.
        # enable stop button, disable Start
        # also make inactive until RunType select box makes active again
        # start run timer
        # finally, clear table which stores TCS info during this run
        self.disable()
        self.run_type_set = False
        g.observe.stop.enable()
        g.info.timer.start()
        g.info.clear_tcs_table()
        return True


class Load(w.ActButton):
    """
    Class defining the 'Load' button's operation. This loads a previously
    saved configuration from disk.
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        w.ActButton.__init__(self, master, width, text="Load")

    def act(self):
        """
        Carries out the action associated with the Load button
        """
        g = get_root(self).globals
        fname = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("json files", ".json"), ("fits files", ".fits")],
            initialdir=g.cpars["app_directory"],
        )
        if not fname:
            g.clog.warn("Aborted load from disk")
            return False

        # load json
        if fname.endswith(".json"):
            with open(fname) as ifname:
                json_string = ifname.read()
        else:
            json_string = tools.jsonFromFits(fname)

        # load up the instrument settings
        g.ipars.loadJSON(json_string)

        # load up the run parameters
        g.rpars.loadJSON(json_string)

        # load the COMPO setup
        g.compo_hw.loadJSON(json_string)

        return True


class Save(w.ActButton):
    """
    Class defining the 'Save' button's operation. This saves the
    current configuration to disk.
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        w.ActButton.__init__(self, master, width, text="Save")

    @inlineCallbacks
    def act(self):
        """
        Carries out the action associated with the Save button
        """
        g = get_root(self).globals
        g.clog.info("\nSaving current application to disk")

        # check instrument parameters
        if not g.ipars.check():
            g.clog.warn("Invalid instrument parameters; save failed.")
            return False

        # check run parameters
        rok, msg = g.rpars.check()
        if not rok:
            g.clog.warn("Invalid run parameters; save failed.")
            g.clog.warn(msg)
            return False

        # Get data to save
        data = yield tools.createJSON(g, full=False)

        # Save to disk
        if tools.saveJSON(g, data):
            # modify buttons
            g.observe.load.enable()
            g.observe.unfreeze.disable()

            # unfreeze the instrument and run params
            g.ipars.unfreeze()
            g.rpars.unfreeze()
            return True
        else:
            return False


class Unfreeze(w.ActButton):
    """
    Class defining the 'Unfreeze' button's operation.
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        w.ActButton.__init__(self, master, width, text="Unfreeze")

    def act(self):
        """
        Carries out the action associated with the Unfreeze button
        """
        g = get_root(self).globals
        g.ipars.unfreeze()
        g.rpars.unfreeze()
        g.observe.load.enable()
        self.disable()


class Observe(tk.LabelFrame):
    """
    Observe widget. Collects together all the buttons needed for observing.
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, padx=10, pady=10)

        width = 10
        self.load = Load(self, width)
        self.save = Save(self, width)
        self.unfreeze = Unfreeze(self, width)
        self.start = Start(self, width)
        self.rtype = RunType(self, self.start)
        self.stop = Stop(self, width)

        # Lay them out
        self.load.grid(row=0, column=0)
        self.save.grid(row=1, column=0)
        self.unfreeze.grid(row=2, column=0)
        self.rtype.grid(row=0, column=1, sticky=tk.EW)
        self.start.grid(row=1, column=1)
        self.stop.grid(row=2, column=1)

        # Define initial status
        self.start.disable()
        self.stop.disable()
        self.unfreeze.disable()

        # Implement expert level
        self.setExpertLevel()
        self.telemetry_topics = [("hipercam.ngc.telemetry", self.on_telemetry)]

    def on_telemetry(self, package):
        self.stop.on_telemetry(package)
        self.start.on_telemetry(package)

    def setExpertLevel(self):
        """
        Set expert level
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]

        # now set whether buttons are permanently enabled or not
        if level == 0 or level == 1:
            self.load.setNonExpert()
            self.save.setNonExpert()
            self.unfreeze.setNonExpert()
            self.start.setNonExpert()
            self.stop.setNonExpert()

        elif level == 2:
            self.load.setExpert()
            self.save.setExpert()
            self.unfreeze.setExpert()
            self.start.setExpert()
            self.stop.setExpert()


class Stop(w.ActButton):
    """
    Class defining the 'Stop' button's operation
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="Stop")
        g = get_root(self).globals
        self.config(bg=g.COL["stop"])

        # flags to help with stopping in background
        self.stopping = False

    def enable(self):
        """
        Enable the button.
        """
        w.ActButton.enable(self)
        g = get_root(self).globals
        self.config(bg=g.COL["stop"])

    def disable(self):
        """
        Disable the button, if in non-expert mode.
        """
        w.ActButton.disable(self)
        g = get_root(self).globals
        if self._expert:
            self.config(bg=g.COL["stop"])
        else:
            self.config(bg=g.COL["stopD"])

    def setExpert(self):
        """
        Turns on 'expert' status whereby the button is always enabled,
        regardless of its activity status.
        """
        w.ActButton.setExpert(self)
        g = get_root(self).globals
        self.config(bg=g.COL["stop"])

    def setNonExpert(self):
        """
        Turns off 'expert' status whereby to allow a button to be disabled
        """
        self._expert = False
        if self._active:
            self.enable()
        else:
            self.disable()

    @inlineCallbacks
    def act(self):
        """
        Carries out the action associated with Stop button
        """
        g = get_root(self).globals
        g.clog.info("Stop pressed")

        # Stop exposure meter
        # do this first, so timer doesn't also try to enable idle mode
        g.info.timer.stop()

        try:
            session = get_root(self).globals.session
            yield session.call("hipercam.ngc.rpc.abort")
            self.stopping = True
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("Run stop failed. Error = " + msg)
            self.stopping = False

    @inlineCallbacks
    def on_telemetry(self, package):
        """
        Checks the status of the stop exposure command
        This is run every time a telemetry packet comes in from NGC.

        It is the responsibility of an implementing GUI to subscribe to the
        NGC telemetry topic with this function as the callback.
        """
        telemetry = pickle.loads(package)

        g = get_root(self).globals
        res = tools.ReadNGCTelemetry(telemetry)
        stopped = res.state == "idle"

        if stopped and self.stopping:
            # Exposure stopped OK; modify buttons
            self.disable()

            # try and write FITS table before enabling start button, otherwise
            # a new start will clear table
            try:
                yield tools.insertFITSHDU(g)
            except Exception as err:
                g.clog.warn("Could not add FITS Table to run")
                g.clog.warn(str(err))

            g.observe.start.enable()
            g.setup.powerOn.disable()
            g.setup.powerOff.enable()
            self.disable()

            # Report that run has stopped
            g.clog.info("Run stopped")
            self.stopping = False

            # enable idle mode now run has stopped
            g.clog.info("Setting chips to idle")
            idle = {"appdata": {"app": "Idle"}}
            try:
                success = yield tools.postJSON(g, idle)
                if not success:
                    raise Exception("postJSON returned false")
            except Exception as err:
                g.clog.warn("Failed to enable idle mode")
                g.clog.warn(str(err))

            g.clog.info("Stopping offsets (if running")
            try:
                success = yield tools.stopNodding(g)
                if not success:
                    raise Exception("Failed to stop dithering: response was false")
            except Exception as err:
                g.clog.warn("Failed to stop GTC offset script")
                g.clog.warn(str(err))

            return True
        elif stopped and not self.stopping:
            # exposure is not running, but we haven't been pressed
            g.observe.start.enable()
            self.disable()
        elif self.stopping:
            # Exposure in process of stopping
            # Disable lots of buttons
            self.disable()
            g.observe.start.disable()
            g.setup.powerOn.disable()
            g.setup.powerOff.disable()
        elif res.state == "active":
            # exposure is underway
            self.enable()
            g.observe.start.disable()
            g.setup.powerOn.disable()
            g.setup.powerOff.disable()


class NGCReset(w.ActButton):
    """
    Class defining the 'NGC Reset' button
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="NGC Reset")

    @inlineCallbacks
    def act(self):
        """
        Carries out the action associated with the System Reset
        """
        root = get_root(self)
        g = root.globals
        g.clog.debug("NGC Reset pressed")
        session = root.globals.session
        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.reset")
            if not ok:
                raise RuntimeError("reset command failed: " + msg)
        except Exception:
            g.clog.warn("NGC Reset failed")
            return False
        else:
            g.clog.info("NGC Reset succeeded")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            return True


class NGCStandby(w.ActButton):
    """
    Class defining the standby button.

    In standby, the NGC server will respond to commands, but processes (sequencer) etc are
    halted, and power is off to controller.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="NGC Standby")

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("NGC Standby pressed")
        session = root.globals.session
        try:
            yield session.call("hipercam.ngc.rpc.standby")
        except Exception as err:
            g.clog.warn("NGC Standby failed: " + str(err))
            return False
        else:
            g.clog.info("Standby command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            return True


class NGCOnline(w.ActButton):
    """
    Class defining the online button.

    In online, the NGC server will respond to commands, but processes (e.g sequencer)
    are autostarted if autostart is enabled, as are any clocks. You can turn clocks on
    and off in this state.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="NGC Online")

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("NGC Online pressed")
        session = root.globals.session
        try:
            yield session.call("hipercam.ngc.rpc.online")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("NGC Online failed: " + msg)
            return False
        else:
            g.clog.info("Online command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.enable()
            g.setup.cldcOff.disable()
            return True


class NGCOff(w.ActButton):
    """
    Class defining the off button.

    In the off (loaded) state, the NGC server will respond to commands, but no-subprocesses
    are launched, and the controller electronics configuration and detector configuration
    is not applied.

    The server initialises in this state.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="NGC Off")

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("NGC Off pressed")
        session = root.globals.session
        try:
            yield session.call("hipercam.ngc.rpc.offline")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("NGC Off failed: " + msg)
            return False
        else:
            g.clog.info("off command successful; server in loaded state")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            return True


class SeqStart(w.ActButton):
    """
    Class defining the button to start sequencers.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="Seq Start")
        self.disable()

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("Seq Start pressed")
        session = root.globals.session

        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.seq_start")
            if not ok:
                raise RuntimeError("could not start sequencer: " + msg)
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("Seq Start failed: " + msg)
            return False
        else:
            g.clog.info("seq start command successful; clocks powered on")
            # alter buttons here
            g.observe.start.enable()
            g.observe.stop.enable()
            g.setup.seqStop.enable()
            self.disable()
            return True


class SeqStop(w.ActButton):
    """
    Class defining the button to stop sequencers.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="Seq Stop")
        self.disable()

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("Seq Stop pressed")
        session = root.globals.session

        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.seq_stop")
            if not ok:
                raise RuntimeError("could not stop sequencer: " + msg)
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("Seq Stop failed: " + msg)
            return False
        else:
            g.clog.info("seq stop command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.seqStart.enable()
            self.disable()
            return True


class CLDCOn(w.ActButton):
    """
    Class defining the button to turn on clocks.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="CLDC On")
        self.disable()

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("CLDC On pressed")
        session = root.globals.session
        try:
            powered_on = yield tools.isPoweredOn(g)
        except Exception as err:
            g.clog.warn(str(err))
            return False

        if powered_on:
            g.clog.info("clocks already on")
            return True

        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.pon")
            if not ok:
                raise RuntimeError("could not power on clocks")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("CLDC On failed: " + msg)
            return False
        else:
            g.clog.info("CLDC on command successful; clocks powered on")
            # alter buttons here
            g.observe.start.enable()
            g.observe.stop.enable()
            g.setup.cldcOff.enable()
            g.setup.seqStart.enable()
            self.disable()
            return True


class CLDCOff(w.ActButton):
    """
    Class defining the button to turn off clocks.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        w.ActButton.__init__(self, master, width, text="CLDC Off")
        self.disable()

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("CLDC Off pressed")
        session = root.globals.session

        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.poff")
            if not ok:
                raise RuntimeError("could not power off clocks")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("CLDC Off failed: " + msg)
            return False
        else:
            g.clog.info("CLDC off command successful; clocks powered off")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.enable()
            self.disable()
            return True


class PowerOn(w.ActButton):
    """
    Class defining the 'Power on' button's operation
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        w.ActButton.__init__(self, master, width, text="Power on")

    @inlineCallbacks
    def act(self):
        """
        Power on action
        """
        root = get_root(self)
        g = root.globals
        g.clog.debug("Power on pressed")
        try:
            session = root.globals.session
            msg, ok = yield session.call("hipercam.ngc.rpc.online")
            if not ok:
                raise RuntimeError(msg)
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("Failed to bring server online: " + msg)
            return False
        else:
            g.clog.info("ESO server online")
            g.cpars["eso_server_online"] = True
            try:
                powered_on = yield tools.isPoweredOn(g)
            except Exception as err:
                g.clog.warn("cannot determine if CLDC is already on")
                msg = err.error_message() if hasattr(err, "error_message") else str(err)
                g.clog.warn(msg)
                return False

            if not powered_on:
                success = yield tools.execCommand(g, "pon")
                if not success:
                    g.clog.warn("Unable to power on CLDC")
                    return False

            success = yield tools.execCommand(g, "seq_start")
            if not success:
                g.clog.warn("Failed to start sequencer after Power On.")

            try:
                run = yield tools.getRunNumber(g)
                g.info.run.configure(text="{0:03d}".format(run))
            except Exception as err:
                g.clog.warn("Failed to determine run number at start of run")
                g.clog.warn(str(err))
                g.info.run.configure(text="UNDEF")

            # change other buttons
            self.disable()
            g.observe.start.enable()
            g.observe.stop.disable()
            g.setup.powerOff.enable()
            return True


class PowerOff(w.ActButton):
    """
    Class defining the 'Power off' button's operation
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        w.ActButton.__init__(self, master, width, text="Power off")
        self.disable()

    @inlineCallbacks
    def act(self):
        """
        Power off action
        """
        g = get_root(self).globals
        g.clog.debug("Power off pressed")

        success = yield tools.execCommand(g, "poff")
        if not success:
            g.clog.warn("Unable to power off CLDC")
            return False

        success = yield tools.execCommand(g, "offline")
        if success:
            g.clog.info("ESO server idle")
            g.cpars["eso_server_online"] = False

            # alter buttons
            self.disable()
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.powerOn.enable()
            return True
        else:
            g.clog.warn("Power off failed")
            return False


class InstSetup(tk.LabelFrame):
    """
    Instrument setup frame.
    """

    def __init__(self, master):
        """
        master -- containing widget
        """
        tk.LabelFrame.__init__(self, master, text="Instrument setup", padx=10, pady=10)

        # Define all buttons
        width = 17
        # expert
        self.ngcReset = NGCReset(self, width)
        self.ngcStandby = NGCStandby(self, width)
        self.ngcOnline = NGCOnline(self, width)
        self.ngcOff = NGCOff(self, width)
        self.cldcOff = CLDCOff(self, width)
        self.cldcOn = CLDCOn(self, width)
        self.seqStart = SeqStart(self, width)
        self.seqStop = SeqStop(self, width)
        # non-expert
        self.powerOn = PowerOn(self, width)
        self.powerOff = PowerOff(self, width)
        self.all_buttons = [
            self.ngcReset,
            self.ngcStandby,
            self.ngcOnline,
            self.ngcOff,
            self.cldcOn,
            self.cldcOff,
            self.powerOn,
            self.powerOff,
            self.seqStart,
            self.seqStop,
        ]
        # set which buttons are presented and where they go
        self.setExpertLevel()
        self.telemetry_topics = [("hipercam.ngc.telemetry", self.on_telemetry)]

    def on_telemetry(self, package):
        g = get_root(self).globals
        try:
            telemetry = pickle.loads(package)
            ngc_status = telemetry.get("system.stateName", "unknown")
            res = tools.ReadNGCTelemetry(telemetry)
            # clocks
            if res.clocks == "enabled":
                self.cldcOn.disable()
                self.cldcOff.enable()
                self.seqStart.enable()
            else:
                self.cldcOn.enable()
                self.cldcOff.disable()
            # power on/off
            if res.clocks == "enabled" and ngc_status.lower() == "online":
                self.powerOff.enable()
                self.powerOn.disable()
            else:
                self.powerOn.enable()
                self.powerOff.disable()
        except Exception:
            g.clog.warn("could not decode NGC telemetry")

    def setExpertLevel(self):
        """
        Set expert level
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]

        # first define which buttons are visible
        if level == 0:
            # simple layout
            for button in self.all_buttons:
                button.grid_forget()

            # then re-grid the two simple ones
            self.powerOn.grid(row=0, column=0)
            self.powerOff.grid(row=0, column=1)

        elif level == 1 or level == 2:
            # first remove all possible buttons
            for button in self.all_buttons:
                button.grid_forget()

            # restore detailed layout
            self.cldcOn.grid(row=0, column=1)
            self.cldcOff.grid(row=1, column=1)
            self.seqStart.grid(row=2, column=1)
            self.seqStop.grid(row=3, column=1)
            self.ngcOnline.grid(row=0, column=0)
            self.ngcOff.grid(row=1, column=0)
            self.ngcStandby.grid(row=2, column=0)
            self.ngcReset.grid(row=3, column=0)

        # now set whether buttons are permanently enabled or not
        if level == 0 or level == 1:
            for button in self.all_buttons:
                button.setNonExpert()

        elif level == 2:
            for button in self.all_buttons:
                button.setExpert()


class Switch(tk.Frame):
    """
    Frame sub-class to switch between setup, focal plane slide
    and observing frames. Provides radio buttons and hides / shows
    respective frames
    """

    def __init__(self, master):
        """
        master : containing widget
        """
        tk.Frame.__init__(self, master)

        self.val = tk.StringVar()
        self.val.set("Setup")
        self.val.trace_add("write", self._changed)

        g = get_root(self).globals
        tk.Radiobutton(
            self, text="Setup", variable=self.val, font=g.ENTRY_FONT, value="Setup"
        ).grid(row=0, column=0, sticky=tk.W)
        tk.Radiobutton(
            self, text="Observe", variable=self.val, font=g.ENTRY_FONT, value="Observe"
        ).grid(row=0, column=1, sticky=tk.W)
        tk.Radiobutton(
            self,
            text="Focal plane slide",
            variable=self.val,
            font=g.ENTRY_FONT,
            value="Focal plane slide",
        ).grid(row=0, column=2, sticky=tk.W)
        self.tecs = tk.Radiobutton(
            self,
            text="CCD TECs",
            variable=self.val,
            font=g.ENTRY_FONT,
            value="CCD TECs",
        )
        self.tecs.grid(row=0, column=3, sticky=tk.W)

        self.setExpertLevel()

    def _changed(self, *args):
        g = get_root(self).globals
        if self.val.get() == "Setup":
            g.setup.pack(anchor=tk.W, pady=10)
            g.fpslide.pack_forget()
            g.observe.pack_forget()
            g.tecs.pack_forget()

        elif self.val.get() == "Focal plane slide":
            g.setup.pack_forget()
            g.fpslide.pack(anchor=tk.W, pady=10)
            g.observe.pack_forget()
            g.tecs.pack_forget()

        elif self.val.get() == "Observe":
            g.setup.pack_forget()
            g.fpslide.pack_forget()
            g.observe.pack(anchor=tk.W, pady=10)
            g.tecs.pack_forget()

        elif self.val.get() == "CCD TECs":
            g.setup.pack_forget()
            g.fpslide.pack_forget()
            g.observe.pack_forget()
            g.tecs.pack(anchor=tk.W, pady=10)

        else:
            raise DriverError("Unrecognised Switch value")

    def setExpertLevel(self):
        """
        Modifies widget according to expertise level, which in this
        case is just matter of hiding or revealing the button to
        set CCD temps
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]
        if level == 0:
            if self.val.get() == "CCD TECs":
                self.val.set("Observe")
                self._changed()
            self.tecs.grid_forget()
        else:
            self.tecs.grid(row=0, column=3, sticky=tk.W)


class Timer(tk.Label):
    """
    Run Timer class.

    Responsible for monitoring a started run. If a run reaches the end without
    Stop being pressed, this class will make sure that button statuses are
    updated and Idle mode is engaged.

    Updates @10Hz, checks run status @1Hz.
    """

    def __init__(self, master):
        tk.Label.__init__(self, master, text="{0:<d} s".format(0))
        g = get_root(self).globals
        self.config(font=g.ENTRY_FONT)
        self._loop = None
        self.count = 0

    def start(self):
        """
        Starts the timer from zero
        """
        self.startTime = time.time()
        self.configure(text="{0:<d} s".format(0))
        self._loop = LoopingCall(self.tick)
        self._loop.start(0.1)

    @inlineCallbacks
    def tick(self):
        """
        Updates @ 10Hz to give smooth running clock, checks
        run status @0.2Hz to reduce load on servers.
        """
        g = get_root(self).globals
        try:
            self.count += 1
            delta = int(round(time.time() - self.startTime))
            self.configure(text="{0:<d} s".format(delta))

            if self.count % 50 == 0:
                try:
                    run_active = yield tools.isRunActive(g)
                except Exception as err:
                    g.clog.warn(str(err))
                if not run_active:
                    # try and write FITS table before enabling start button, otherwise
                    # a new start will clear table
                    try:
                        yield tools.insertFITSHDU(g)
                    except Exception as err:
                        g.clog.warn("Could not add FITS Table to run")
                        g.clog.warn(str(err))

                    g.observe.start.enable()
                    g.observe.stop.disable()
                    g.setup.ngcReset.enable()
                    g.setup.powerOn.disable()
                    g.setup.powerOff.enable()
                    g.clog.info("Timer detected stopped run")

                    warn_cmd = "/usr/bin/ssh observer@192.168.1.1 spd-say \"'exposure finished'\""
                    try:
                        subprocess.check_output(
                            warn_cmd, shell=True, stderr=subprocess.PIPE
                        )
                    except Exception:
                        pass

                    # enable idle mode now run has stopped
                    g.clog.info("Setting chips to idle")
                    idle = {"appdata": {"app": "Idle"}}
                    try:
                        success = yield tools.postJSON(g, idle)
                        if not success:
                            raise Exception("postJSON returned false")
                    except Exception as err:
                        g.clog.warn("Failed to enable idle mode")
                        g.clog.warn(str(err))

                    g.clog.info("Stopping offsets (if running")
                    try:
                        success = yield tools.stopNodding(g)
                        if not success:
                            raise Exception("failed to stop dithering")
                    except Exception as err:
                        g.clog.warn("Failed to stop GTC offset script")
                        g.clog.warn(str(err))

                    self.stop()

        except Exception as err:
            if self.count % 100 == 0:
                g.clog.warn("Timer.update: error = " + str(err))

    def stop(self):
        if hasattr(self, "_loop") and self._loop is not None:
            self._loop.stop()
        self._loop = None


class InfoFrame(tk.LabelFrame):
    """
    Information frame: run number, exposure time, etc.
    """

    # if time to rotator limit is less than this, there will be a
    # warning before runs can be started
    WARN_LIMIT = 1 * u.hourangle

    def __init__(self, master):
        tk.LabelFrame.__init__(
            self, master, text="Current run & telescope status", padx=4, pady=4
        )

        self.run = w.Ilabel(self, text="UNDEF")
        self.frame = w.Ilabel(self, text="UNDEF")
        self.timer = Timer(self)
        self.cadence = w.Ilabel(self, text="UNDEF")
        self.duty = w.Ilabel(self, text="UNDEF")
        self.ra = w.Ilabel(self, text="UNDEF")
        self.dec = w.Ilabel(self, text="UNDEF")
        self.alt = w.Ilabel(self, text="UNDEF")
        self.az = w.Ilabel(self, text="UNDEF")
        self.airmass = w.Ilabel(self, text="UNDEF")
        self.ha = w.Ilabel(self, text="UNDEF")
        self.pa = w.Ilabel(self, text="UNDEF")
        self.rotlimit = w.Ilabel(self, text="UNDEF")
        self.focus = w.Ilabel(self, text="UNDEF")
        self.mdist = w.Ilabel(self, text="UNDEF")
        self.fpslide = w.Ilabel(self, text="UNDEF")
        self.ccd_temps = w.Ilabel(self, text="UNDEF")

        # left-hand side
        tk.Label(self, text="Run:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.run.grid(row=0, column=1, padx=5, sticky=tk.W)

        tk.Label(self, text="Frame:").grid(row=1, column=0, padx=5, sticky=tk.W)
        self.frame.grid(row=1, column=1, padx=5, sticky=tk.W)

        tk.Label(self, text="Exposure:").grid(row=2, column=0, padx=5, sticky=tk.W)
        self.timer.grid(row=2, column=1, padx=5, sticky=tk.W)

        tk.Label(self, text="Cadence:").grid(row=3, column=0, padx=5, sticky=tk.W)
        self.cadence.grid(row=3, column=1, padx=5, sticky=tk.W)

        tk.Label(self, text="Duty cycle:").grid(row=4, column=0, padx=5, sticky=tk.W)
        self.duty.grid(row=4, column=1, padx=5, sticky=tk.W)

        # middle
        tk.Label(self, text="RA:").grid(row=0, column=3, padx=5, sticky=tk.W)
        self.ra.grid(row=0, column=4, padx=5, sticky=tk.W)

        tk.Label(self, text="Dec:").grid(row=1, column=3, padx=5, sticky=tk.W)
        self.dec.grid(row=1, column=4, padx=5, sticky=tk.W)

        tk.Label(self, text="Alt:").grid(row=2, column=3, padx=5, sticky=tk.W)
        self.alt.grid(row=2, column=4, padx=5, sticky=tk.W)

        tk.Label(self, text="Az:").grid(row=3, column=3, padx=5, sticky=tk.W)
        self.az.grid(row=3, column=4, padx=5, sticky=tk.W)

        tk.Label(self, text="Airm:").grid(row=4, column=3, padx=5, sticky=tk.W)
        self.airmass.grid(row=4, column=4, padx=5, sticky=tk.W)

        tk.Label(self, text="HA:").grid(row=5, column=3, padx=5, sticky=tk.W)
        self.ha.grid(row=5, column=4, padx=5, sticky=tk.W)

        # right-hand side
        tk.Label(self, text="PA:").grid(row=0, column=6, padx=5, sticky=tk.W)
        self.pa.grid(row=0, column=7, padx=5, sticky=tk.W)

        tk.Label(self, text="Rot Lim:").grid(row=1, column=6, padx=5, sticky=tk.W)
        self.rotlimit.grid(row=1, column=7, padx=5, sticky=tk.W)

        tk.Label(self, text="Focus:").grid(row=2, column=6, padx=5, sticky=tk.W)
        self.focus.grid(row=2, column=7, padx=5, sticky=tk.W)

        tk.Label(self, text="Mdist:").grid(row=3, column=6, padx=5, sticky=tk.W)
        self.mdist.grid(row=3, column=7, padx=5, sticky=tk.W)

        tk.Label(self, text="FP slide:").grid(row=4, column=6, padx=5, sticky=tk.W)
        self.fpslide.grid(row=4, column=7, padx=5, sticky=tk.W)

        tk.Label(self, text="CCD temps:").grid(row=5, column=6, padx=5, sticky=tk.W)
        self.ccd_temps.grid(row=5, column=7, padx=5, sticky=tk.W)

        # add a FITS table to record TCS info
        self.tcs_table = create_gtc_header_table()

        # need to keep track of time to rotator limit
        self.time_to_limit = None

        # start
        self.count = 0
        self.update()

        # an implementing GUI must subscribe this widget to the
        # following topics, with the given callbacks
        self.telemetry_topics = [
            ("hipercam.slide.telemetry", self.update_slidepos),
            ("hipercam.gtc.telemetry", self.update_tcs),
            ("hipercam.ccd1.telemetry", self.update_ccd),
            ("hipercam.ccd2.telemetry", self.update_ccd),
            ("hipercam.ccd3.telemetry", self.update_ccd),
            ("hipercam.ccd4.telemetry", self.update_ccd),
            ("hipercam.ccd5.telemetry", self.update_ccd),
            ("hipercam.ngc.telemetry", self.update_runstatus),
        ]

        self._update_tcs_table_loop = LoopingCall(self.update_tcs_table)
        self._update_tcs_table_loop.start(60)

    def _getVal(self, widg):
        return -99.0 if widg["text"] == "UNDEF" else float(widg["text"])

    def dumpJSON(self):
        """
        Return dictionary of data for FITS headers.
        """
        g = get_root(self).globals
        return dict(
            RA=self.ra["text"],
            DEC=self.dec["text"],
            tel=g.cpars["telins_name"],
            alt=self._getVal(self.alt),
            az=self._getVal(self.az),
            secz=self._getVal(self.airmass),
            pa=self._getVal(self.pa),
            foc=self._getVal(self.focus),
            mdist=self._getVal(self.mdist),
        )

    def clear_tcs_table(self):
        """
        Create a new table from scratch - should be cleared for each run.
        """
        self.tcs_table = create_gtc_header_table()

    @inlineCallbacks
    def update_tcs_table(self):
        """
        Periodically update a table of info from the TCS.

        Only works at GTC. Called every 60s.
        """
        root = get_root(self)
        g = root.globals
        if not g.cpars["tcs_on"] or not g.cpars["telins_name"].lower() == "gtc":
            return
        try:
            session = root.globals.session
            telpars = yield session.call("hipercam.gtc.rpc.get_telescope_pars")
            if telpars is None:
                raise RuntimeError("no telescope parameters returned from server")
            add_gtc_header_table_row(self.tcs_table, telpars)
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("Could not update table of TCS info: " + msg)

    def update_tcs(self, packet):
        """
        Update TCS data.

        This is a callback to be used with subscription to the GTC telemetry
        topic.

        Parameters
        ----------
        packet: bytes
            a pickled serialisation of the telemetry packet
        """
        g = get_root(self).globals
        try:
            telemetry = pickle.loads(packet)
            header = telemetry["telpars"]
        except Exception as err:
            g.clog.warn("Could not parse telemetry from TCS: " + str(err))
        else:
            ra = float(header["RADEG"])
            dec = float(header["DECDEG"])
            pa = float(header["INSTRPA"])
            mechanical_angle = float(header["ROTATOR"])
            focus = float(header["M2UZ"])

            # format ra, dec as HMS
            coo = coord.SkyCoord(ra, dec, unit=(u.deg, u.deg))
            ratxt = coo.ra.to_string(sep=":", unit=u.hour, precision=0)
            dectxt = coo.dec.to_string(
                sep=":", unit=u.deg, alwayssign=True, precision=0
            )
            self.ra.configure(text=ratxt)
            self.dec.configure(text=dectxt)

            # set angle units
            mechanical_angle = mechanical_angle * u.deg
            pa = pa * u.deg

            # wrap pa from 0 to 360
            wrapped_pa = coord.Longitude(pa)
            self.pa.configure(text="{0:6.2f}".format(wrapped_pa.value))

            # set focus
            self.focus.configure(text="{0:+5.2f}".format(focus))

            # Calculate most of the
            # stuff that we don't get from the telescope
            now = Time.now()
            lon = g.astro.obs.lon
            lst = now.sidereal_time(kind="mean", longitude=lon)
            ha = lst - coo.ra.hourangle * u.hourangle
            hatxt = ha.wrap_at(12 * u.hourangle).to_string(
                sep=":", precision=0, fields=2
            )
            self.ha.configure(text=hatxt)

            altaz_frame = coord.AltAz(obstime=now, location=g.astro.obs)
            altaz = coo.transform_to(altaz_frame)
            self.alt.configure(text="{0:<4.1f}".format(altaz.alt.value))
            self.az.configure(text="{0:<5.1f}".format(altaz.az.value))
            # set airmass
            self.airmass.configure(text="{0:<4.2f}".format(altaz.secz))

            # time to rotator limit
            self.time_to_limit = calc_time_to_rotator_limit(
                ha,
                g.astro.obs.lat,
                coo.dec,
                pa,
                mechanical_angle,
                (-240.0, 240) * u.deg,
            )
            if self.time_to_limit is None:
                limit_txt = ">12:00"
            else:
                limit_txt = (
                    coord.Longitude(self.time_to_limit)
                    .wrap_at(12 * u.hourangle)
                    .to_string(sep=":", precision=0, fields=2)
                )
                # warn if too limit is near
                if self.time_to_limit < 1 * u.hourangle:
                    self.rotlimit.configure(bg=g.COL["warn"])
                else:
                    self.rotlimit.configure(bg=g.COL["main"])

            self.rotlimit.configure(text=limit_txt)

            # distance to the moon. Warn if too close
            # (configurable) to it.
            md = coord.get_moon(now, g.astro.obs).separation(coo)
            self.mdist.configure(text="{0:<7.2f}".format(md.value))
            if md < g.cpars["mdist_warn"] * u.deg:
                self.mdist.configure(bg=g.COL["warn"])
            else:
                self.mdist.configure(bg=g.COL["main"])

    def update_ccd(self, packet):
        """
        Update the CCD label.

        This routine is a callback to be called whenever a telemetry message
        from a CCD is received.

        Parameters
        ----------
        packet: bytes
            a pickled serialisation of the telemetry packet
        """
        g = get_root(self).globals
        try:
            telemetry = pickle.loads(packet)
        except Exception as err:
            g.clog.warn("could not decode CCD telemetry: " + str(err))
            self.ccd_temps.configure(text="UNDEF")
            self.ccd_temps.configure(bg=g.COL["warn"])
        else:
            if telemetry["state"] == "OK":
                self.ccd_temps.configure(text="OK")
                self.ccd_temps.configure(bg=g.COL["main"])
            else:
                self.ccd_temps.configure(text="ERR")
                self.ccd_temps.configure(bg=g.COL["warn"])

    def update_slidepos(self, packet):
        """
        Update the slide position.

        This routine is a callback to be called whenever a telemetry message
        from the slide is received.

        Parameters
        ----------
        packet: bytes
            a pickled serialisation of the telemetry packet
        """
        g = get_root(self).globals
        if not g.cpars["focal_plane_slide_on"]:
            return

        try:
            telemetry = pickle.loads(packet)
        except Exception as err:
            g.clog.warn("could not decode slide telemetry: " + str(err))
        else:
            # get positions, dealing with the fact that sometimes it has units
            try:
                pos = telemetry["position"]["current"]
                targ = telemetry["position"]["target"]
                pos = pos.value if hasattr(pos, "value") else pos
                targ = targ.value if hasattr(targ, "value") else targ
                state = telemetry["state"]
                if "error" in state["connection"] or "offline" in state["connection"]:
                    self.fpslide.configure(bg=g.COL["warn"])
                    g.clog.warn("slide in error state")

                self.fpslide.configure(text="{0:d}".format(int(round(pos))))
                if pos < 1050.0 or abs(pos - targ) > 3:
                    self.fpslide.configure(bg=g.COL["warn"])
                else:
                    self.fpslide.configure(bg=g.COL["main"])
            except Exception as err:
                g.clog.warn("unable to process slide telemetry: ") + str(err)

    def update_runstatus(self, packet):
        """
        Updates run status widgets.

        This routine is a callback to be called whenever a telemetry message
        from the NGC is received.

        Parameters
        ----------
        packet: bytes
            a pickled serialisation of the telemetry packet
        """
        g = get_root(self).globals
        if not (g.cpars["hcam_server_on"] and g.cpars["eso_server_online"]):
            return

        try:
            telemetry = pickle.loads(packet)
            status = tools.ReadNGCTelemetry(telemetry)
            run = status.run
            frame_no = int(telemetry["exposure.frame"])
        except Exception as err:
            g.clog.warn("failed to parse NGC telemetry: " + str(err))
        else:
            self.run.configure(text="{0:03d}".format(run))
            self.frame.configure(text="{0:04d}".format(frame_no))
