#!/usr/bin/env python
"""
ULTRACAM instrument-specific widgets and parameters
"""

from __future__ import print_function, absolute_import, unicode_literals, division
import six
import math
import os
import io
import xml.etree.ElementTree as ET

# Register the xlink namespace so it is preserved in serialised XML
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

# internal imports
from twisted.internet.defer import inlineCallbacks
from .. import widgets as w
from ..tkutils import get_root
from . import tools
from . import params as pars

if not six.PY3:
    import Tkinter as tk
    import tkFileDialog as fd
else:
    import tkinter as tk
    import tkinter.filedialog as fd

# Module-level constants for XML application management
_XLINK_NS = "http://www.w3.org/1999/xlink"

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "ultracam_templates",
)

# Maps GAIN_SPEED hex codes to/from the readSpeed widget values
_GAIN_SPEED = {"Slow": "0xcdd", "Fast": "0xfbb", "Turbo": "0xfdd"}
_SPEED_CODE = {v: k for k, v in _GAIN_SPEED.items()}

# Maps (mode, clear, oscan, npairs) -> (template_app_filename, expected_cfg_id)
# These mirror the TEMPLATE_APP / TEMPLATE_ID / TEMPLATE_PAIR entries in
# the Java udriver.conf, restricted to the templates that actually exist.
_TEMPLATE_MAP = {
    ("FullFrame", True, False, 0): (
        "appl3_fullframe_app.xml",
        "appl3_fullframe_cfg.xml",
    ),
    ("FullFrame", False, False, 0): (
        "appl9_fullframe_mindead_app.xml",
        "appl9_fullframe_mindead_cfg.xml",
    ),
    ("FullFrame", True, True, 0): (
        "appl4_frameover_app.xml",
        "appl4_frameover_cfg.xml",
    ),
    ("Windows", False, False, 1): (
        "appl5_window1pair_app.xml",
        "appl5_window1pair_cfg.xml",
    ),
    ("Windows", True, False, 1): (
        "appl5b_window1pair_app.xml",
        "appl5b_window1pair_cfg.xml",
    ),
    ("Windows", False, False, 2): (
        "appl6_window2pair_app.xml",
        "appl6_window2pair_cfg.xml",
    ),
    ("Windows", False, False, 3): (
        "appl7_window3pair_app.xml",
        "appl7_window3pair_cfg.xml",
    ),
    ("Drift", False, False, 1): ("appl8_driftscan_app.xml", "appl8_driftscan_cfg.xml"),
}

# Reverse map: cfg_id -> (mode, clear, oscan, npairs)
_CFG_ID_TO_MODE = {cfg_id: key for key, (_, cfg_id) in _TEMPLATE_MAP.items()}


def _apply_state(g, state):
    """
    Apply a named instrument state to all relevant panels.

    Calls ``apply_state`` on ``g.setup`` and, if set, on ``g.observe``.
    Freezes/unfreezes ``g.ipars`` when starting/stopping a run.
    """
    # set state on inst setup panel (if it exists)
    if getattr(g, "setup", None) is not None:
        g.setup.apply_state(state)

    # set state on observe panel (if it exists)
    if getattr(g, "observe", None) is not None:
        g.observe.apply_state(state)

    # freeze/unfreeze ipars if it exists
    if getattr(g, "ipars", None) is not None:
        if state == "after_start_run":
            g.ipars.freeze()
        elif state == "after_stop_run":
            g.ipars.enable()


# LabelFrames to hold widgets together in one place.
# Also used to handle enabling/disabling groups of widgets when the state changes.
class InstPars(tk.LabelFrame):
    """
    Ultracam instrument parameters block.
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text="Instrument setup", padx=10, pady=10)

        # left hand side
        lhs = tk.Frame(self)
        # Application (mode)
        tk.Label(lhs, text="Mode").grid(row=0, column=0, sticky=tk.W)
        self.app = w.Radio(
            lhs,
            ("FF", "Wins", "Drift"),
            3,
            self.check,
            ("FullFrame", "Windows", "Drift"),
        )
        self.app.grid(row=0, column=1, sticky=tk.W, columnspan=5)

        # Clear enabled
        self.clearLab = tk.Label(lhs, text="Clear")
        self.clearLab.grid(row=1, column=0, sticky=tk.W)
        self.clear = w.OnOff(lhs, True, self.check)
        self.clear.grid(row=1, column=1, sticky=tk.W)

        # o/scan enabled
        self.oscanLab = tk.Label(lhs, text="O/Scan")
        self.oscanLab.grid(row=2, column=0, sticky=tk.W)
        self.oscan = w.OnOff(lhs, False, self.check)
        self.oscan.grid(row=2, column=1, sticky=tk.W)

        # Readout speed
        tk.Label(lhs, text="Readout speed").grid(row=3, column=0, sticky=tk.NW)
        self.readSpeed = w.Radio(
            lhs, ("Slow", "Fast", "Turbo"), 1, self.check, ("Slow", "Fast", "Turbo")
        )
        self.readSpeed.grid(row=3, column=1, pady=2, sticky=tk.W)

        # Exposure delay
        tk.Label(lhs, text="Exp. delay (ms)").grid(row=4, column=0, sticky=tk.W)
        # Sub-frame keeps the three widgets packed tightly regardless of other column widths
        expose_frame = tk.Frame(lhs)
        expose_frame.grid(row=4, column=1, sticky=tk.W, pady=5)
        # exposure delay (whole ms)
        self.expose = w.PosInt(expose_frame, 0, None, True, width=6)
        self.expose.pack(side=tk.LEFT)
        # decimal point separator
        tk.Label(expose_frame, text=".").pack(side=tk.LEFT)
        # fractional ms (tenths); only shown in expert mode
        self.expose_frac = w.RangedInt(
            expose_frame, 5, 0, 9, self.check, False, width=2
        )
        self.expose_frac.pack(side=tk.LEFT)
        self.expose_frac.disable()

        # u-band coadds
        tk.Label(lhs, text="u-band coadds").grid(row=5, column=0, sticky=tk.W)
        self.nblue = w.RangedInt(lhs, 1, 1, 1000, self.check, False, width=4)
        self.nblue.grid(row=5, column=1, sticky=tk.W, pady=5)

        # Right-hand side: the window parameters
        rhs = tk.Frame(self)
        # window parameters
        xsl = (100, 100, 100)
        xslmin = (1, 1, 1)
        xslmax = (512, 512, 512)
        xsr = (600, 600, 600)
        xsrmin = (513, 513, 513)
        xsrmax = (1024, 1024, 1024)
        ys = (1, 201, 401)
        ysmin = (1, 1, 1)
        ysmax = (1024, 1024, 1024)
        nx = (50, 50, 50)
        ny = (50, 50, 50)
        xbfac = (1, 2, 3, 4, 5, 6, 8)
        ybfac = (1, 2, 3, 4, 5, 6, 8)
        self.wframe = w.WinPairs(
            rhs,
            xsl,
            xslmin,
            xslmax,
            xsr,
            xsrmin,
            xsrmax,
            ys,
            ysmin,
            ysmax,
            nx,
            ny,
            xbfac,
            ybfac,
            self.check,
            hcam=False,
        )
        self.wframe.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))

        # Pack two halfs
        lhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)
        rhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)

        self._frozen = False
        self.check()

    def setExpertLevel(self):
        """Enable/disable expert-only widgets based on the current expert level."""
        g = get_root(self).globals
        level = g.cpars.get("expert_level", 0)
        if level >= 1:
            self.expose_frac.enable()
        else:
            self.expose_frac.disable()

    @property
    def isFF(self):
        return self.app.value() == "FullFrame"

    @property
    def isDriftMode(self):
        return self.app.value() == "Drift"

    # ------------------------------------------------------------------
    # XML application management
    # ------------------------------------------------------------------

    def _which_template(self):
        """
        Return ``(app_filename, cfg_id, npairs)`` for the current GUI state.

        Raises ``ValueError`` if the combination is not covered by any template.
        """
        mode = self.app.value()
        clear = bool(self.clear())
        oscan = bool(self.oscan())
        npairs = self.wframe.npair.value() if not self.isFF else 0

        key = (mode, clear, oscan, npairs)
        if key not in _TEMPLATE_MAP:
            raise ValueError(
                "No template for mode={}, clear={}, oscan={}, npairs={}".format(
                    mode, clear, oscan, npairs
                )
            )
        app_file, cfg_id = _TEMPLATE_MAP[key]
        return app_file, cfg_id, npairs

    def create_xml(self):
        """
        Build an XML application string from the current GUI settings.

        Loads the appropriate template file, substitutes all
        ``set_parameter`` values with the current widget values, appends
        a ``<user>`` metadata block from ``g.cpars``, and returns the
        serialised XML string.

        Returns ``None`` on failure (error is logged to ``g.clog``).
        """
        g = get_root(self).globals
        try:
            app_file, cfg_id, npairs = self._which_template()
        except ValueError as exc:
            g.clog.error("create_xml: {}".format(exc))
            return None

        if g.cpars.get("templates_from_server", False):
            xml_string = tools.fetchApp(g, app_file)
            if xml_string is None:
                g.clog.error(
                    "create_xml: failed to fetch template {} from server".format(
                        app_file
                    )
                )
                return None
            try:
                tree = ET.ElementTree(ET.fromstring(xml_string))
            except Exception as exc:
                g.clog.error(
                    "create_xml: cannot parse template {} from server: {}".format(
                        app_file, exc
                    )
                )
                return None
        else:
            tdir = g.cpars.get("template_dir", _TEMPLATES_DIR)
            template_path = os.path.join(tdir, app_file)
            try:
                tree = ET.parse(template_path)
            except Exception as exc:
                g.clog.error(
                    "create_xml: cannot read template {}: {}".format(template_path, exc)
                )
                return None

        root_elem = tree.getroot()

        # Verify the template cfg id matches expectation
        for ec in root_elem.iter("executablecode"):
            href = ec.get("{{{ns}}}href".format(ns=_XLINK_NS)) or ec.get(
                "xlink:href", ""
            )
            if href and href != cfg_id:
                g.clog.error(
                    "create_xml: template cfg id '{}' does not match expected '{}'".format(
                        href, cfg_id
                    )
                )
                return None

        # Collect current GUI values
        xbin = self.wframe.xbin.value()
        ybin = self.wframe.ybin.value()
        speed = _GAIN_SPEED.get(self.readSpeed.value())
        if speed is None:
            g.clog.error(
                "create_xml: unknown readout speed '{}'".format(self.readSpeed.value())
            )
            return None
        # EXPOSE_TIME is in units of 0.1 ms; the Python widget stores whole ms
        expose = self.expose.value() * 10 + self.expose_frac.value()

        found = {
            "X_BIN_FAC": False,
            "Y_BIN_FAC": False,
            "NBLUE": False,
            "GAIN_SPEED": False,
            "EXPOSE_TIME": False,
        }
        for n in range(npairs):
            found["Y{}_START".format(n + 1)] = False
            found["X{}L_START".format(n + 1)] = False
            found["X{}R_START".format(n + 1)] = False
            found["X{}_SIZE".format(n + 1)] = False
            found["Y{}_SIZE".format(n + 1)] = False

        for elem in root_elem.iter("set_parameter"):
            ref = elem.get("ref", "")
            if ref == "X_BIN_FAC":
                elem.set("value", str(xbin))
                found["X_BIN_FAC"] = True
            elif ref == "Y_BIN_FAC":
                elem.set("value", str(ybin))
                found["Y_BIN_FAC"] = True
            elif ref == "NBLUE":
                elem.set("value", str(self.nblue.value()))
                found["NBLUE"] = True
            elif ref == "GAIN_SPEED":
                elem.set("value", speed)
                found["GAIN_SPEED"] = True
            elif ref == "EXPOSE_TIME":
                elem.set("value", str(expose))
                found["EXPOSE_TIME"] = True
            else:
                for n in range(npairs):
                    k = n + 1
                    xsl, xsr, ys, nx, ny = self.wframe.params(n)
                    if ref == "Y{}_START".format(k):
                        elem.set("value", str(ys))
                        found[ref] = True
                    elif ref == "X{}L_START".format(k):
                        elem.set("value", str(xsl))
                        found[ref] = True
                    elif ref == "X{}R_START".format(k):
                        elem.set("value", str(xsr))
                        found[ref] = True
                    elif ref == "X{}_SIZE".format(k):
                        elem.set("value", str(nx))
                        found[ref] = True
                    elif ref == "Y{}_SIZE".format(k):
                        elem.set("value", str(ny))
                        found[ref] = True

        missing = [k for k, v in found.items() if not v]
        if missing:
            g.clog.error(
                "create_xml: failed to locate set_parameter(s): {}".format(missing)
            )
            return None

        # Append <user> metadata block
        user_elem = ET.SubElement(root_elem, "user")
        if (
            getattr(g, "observe", None) is not None
            and getattr(g, "rpars", None) is not None
        ):
            # get run type
            runtype = g.observe.runType()
            print("runtype = {}".format(runtype))
            # target name depends on run type
            if runtype in ["data", "technical", "acquisition"]:
                target = g.rpars.target.value()
            else:
                # e.g BIAS, FLAT, DARK
                target = runtype.upper()
            ET.SubElement(user_elem, "target").text = target

            # filters
            ET.SubElement(user_elem, "filters").text = g.rpars.filter_string
            # ID, PI, Observers
            ET.SubElement(user_elem, "ID").text = g.rpars.prog_id.value()
            ET.SubElement(user_elem, "PI").text = g.rpars.pi.value()
            ET.SubElement(user_elem, "Observers").text = g.rpars.observers.value()

            # flags are the same as run type, but "data caution" for "acquisition"
            if runtype == "acquisition":
                flags = "data caution"
            else:
                flags = runtype
            ET.SubElement(user_elem, "flags").text = flags

        # Serialise
        buf = io.BytesIO()
        tree.write(buf, xml_declaration=True, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")

    def load_xml(self, path):
        """
        Load an XML application file and populate the GUI widgets.

        Reads ``executablecode xlink:href`` to identify the application type,
        then extracts all ``set_parameter`` values and sets the corresponding
        widgets.  Finishes by calling ``self.check()``.

        Parameters
        ----------
        path : str
            Absolute path to the XML application file.
        """
        g = get_root(self).globals
        try:
            tree = ET.parse(path)
        except Exception as exc:
            g.clog.error("load_xml: cannot parse {}: {}".format(path, exc))
            return

        root_elem = tree.getroot()

        # Identify application type from executablecode href
        cfg_id = None
        for ec in root_elem.iter("executablecode"):
            cfg_id = ec.get("{{{ns}}}href".format(ns=_XLINK_NS)) or ec.get("xlink:href")
            if cfg_id:
                break
        if cfg_id is None:
            g.clog.error(
                "load_xml: cannot find executablecode element in {}".format(path)
            )
            return

        if cfg_id not in _CFG_ID_TO_MODE:
            g.clog.error(
                "load_xml: unrecognised application id '{}' in {}".format(cfg_id, path)
            )
            return

        mode, clear, oscan, npairs = _CFG_ID_TO_MODE[cfg_id]

        # Set mode widgets
        self.app.set(mode)
        self.clear.set(1 if clear else 0)
        self.oscan.set(1 if oscan else 0)
        if not self.isFF:
            self.wframe.npair.set(npairs)

        # Extract set_parameter values
        for elem in root_elem.iter("set_parameter"):
            ref = elem.get("ref", "")
            val = elem.get("value", "")
            if ref == "X_BIN_FAC":
                self.wframe.xbin.set(int(val))
            elif ref == "Y_BIN_FAC":
                self.wframe.ybin.set(int(val))
            elif ref == "NBLUE":
                self.nblue.set(int(val, 0))
            elif ref == "GAIN_SPEED":
                speed_name = _SPEED_CODE.get(val)
                if speed_name:
                    self.readSpeed.set(speed_name)
                else:
                    g.clog.warn(
                        "load_xml: unrecognised GAIN_SPEED '{}'; ignoring".format(val)
                    )
            elif ref == "EXPOSE_TIME":
                # EXPOSE_TIME is in 0.1 ms units; Python widget stores whole ms
                self.expose.set(int(val) // 10)
                self.expose_frac.set(int(val) % 10)
            else:
                for n in range(npairs):
                    k = n + 1
                    if ref == "Y{}_START".format(k):
                        self.wframe.ys[n].set(int(val))
                    elif ref == "X{}L_START".format(k):
                        self.wframe.xsl[n].set(int(val))
                    elif ref == "X{}R_START".format(k):
                        self.wframe.xsr[n].set(int(val))
                    elif ref == "X{}_SIZE".format(k):
                        self.wframe.nx[n].set(int(val))
                    elif ref == "Y{}_SIZE".format(k):
                        self.wframe.ny[n].set(int(val))

        self.check()
        g.clog.info("load_xml: loaded {}".format(os.path.basename(path)))

    def save_xml(self, path):
        """
        Save the current GUI settings to an XML application file.

        Calls :meth:`create_xml` to build the XML string and writes it to
        *path*.

        Parameters
        ----------
        path : str
            Destination file path.
        """
        g = get_root(self).globals
        xml_string = self.create_xml()
        if xml_string is None:
            g.clog.error("save_xml: create_xml failed; file not written")
            return
        try:
            with open(path, "w", encoding="UTF-8") as fh:
                fh.write(xml_string)
            g.clog.info("save_xml: written to {}".format(os.path.basename(path)))
            self.enable()
        except OSError as exc:
            g.clog.error("save_xml: cannot write {}: {}".format(path, exc))

    def freeze(self):
        """Disable all input widgets (called when a run is started)."""
        self._frozen = True
        self.app.disable()
        self.clear.disable()
        self.oscan.disable()
        self.readSpeed.disable()
        self.expose.disable()
        self.nblue.disable()
        self.expose_frac.disable()
        # everything=True ensures xbin/ybin are also disabled
        self.wframe.disable(everything=True)

    def enable(self):
        """Re-enable all input widgets and re-apply mode constraints."""
        self._frozen = False
        self.app.enable()
        self.readSpeed.enable()
        self.expose.enable()
        self.nblue.enable()
        # expose_frac is only re-enabled if in expert mode
        g = get_root(self).globals
        if g.cpars.get("expert_level", 0) >= 1:
            self.expose_frac.enable()
        # xbin/ybin are not touched by WinPairs.enable() so restore them here
        self.wframe.xbin.enable()
        self.wframe.ybin.enable()
        # check() restores the correct state for clear, oscan and wframe
        self.check()

    def check(self, *args):
        """
        Checks the validity of the parameters and adjusts widget states
        to match the constraints imposed by the selected mode.

        Rules (matching the Java Udriver):
          - Drift mode : npairs forced to 1; clear and overscan disabled.
          - Full Frame  : wframe disabled; overscan only allowed when clear
                          is also enabled.
          - Windows     : overscan never allowed; clear only allowed with
                          exactly 1 window pair.
        """
        g = get_root(self).globals
        status = True

        # While frozen we only validate values; widget states are not touched.
        if self._frozen:
            return self.wframe.check() and status

        if self.isDriftMode:
            self.wframe.npair.set(1)
            self.clear.set(0)
            self.oscan.set(0)
            self.clear.disable()
            self.oscan.disable()
            self.wframe.enable()

        elif self.isFF:
            self.wframe.disable()
            self.clear.enable()
            # Overscan is only valid in FF mode when clear is also on.
            if self.clear():
                self.oscan.enable()
            else:
                if self.oscan():
                    self.oscan.set(0)
                self.oscan.disable()

        else:
            # Windows mode
            self.wframe.enable()
            # Overscan is never available in windowed mode.
            if self.oscan():
                self.oscan.set(0)
            self.oscan.disable()
            # Clear is only allowed with a single window pair.
            if self.wframe.npair.value() > 1:
                if self.clear():
                    self.clear.set(0)
                self.clear.disable()
            else:
                self.clear.enable()

        if status and hasattr(g, "count"):
            # if valid, update timing and SN info
            if hasattr(g.count, "update"):
                g.count.update()
            else:
                print("no count update")

        # check windows
        return self.wframe.check() and status

    def getRtplotWins(self):
        """
        Returns a string suitable to sending off to rtplot when
        it asks for window parameters. Returns null string '' if
        the windows are not OK. This operates on the basis of
        trying to send something back, even if it might not be
        OK as a window setup. Note that we have to take care
        here not to update any GUI components because this is
        called outside of the main thread.
        """
        try:
            xbin = self.wframe.xbin.value()
            ybin = self.wframe.ybin.value()
            if self.app.value() == 'Windows':
                nwin = 2 * self.wframe.npair.value()
                ret = str(xbin) + ' ' + str(ybin) + ' ' + str(nwin) + '\r\n'
                for xsl, xsr, ys, nx, ny in self.wframe:
                    ret += (str(xsl) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
                    ret += (str(xsr) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
            elif self.app.value() == 'Drift':
                ret = str(xbin) + ' ' + str(ybin) + ' 2\r\n'
                for xsl, xsr, ys, nx, ny in self.wframe:
                    ret += (str(xsl) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
                    ret += (str(xsr) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
            else:
                return ''
            return ret
        except Exception:
            return ''

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
        # video timing
        readSpeed = self.readSpeed.value()
        if readSpeed == "Fast":
            cdsTime = pars.CDS_TIME_FBB
        elif readSpeed == "Turbo":
            cdsTime = pars.CDS_TIME_FDD
        elif readSpeed == "Slow":
            cdsTime = pars.CDS_TIME_CDD
        else:
            raise RuntimeError("unknown read speed")
        video = cdsTime + pars.SWITCH_TIME

        # exposure delay in microsecs
        expose = self.expose.value() * 1000 + self.expose_frac.value() * 100

        # binning values
        xbin = self.wframe.xbin.value()
        ybin = self.wframe.ybin.value()

        # check all the mode cases
        if self.isFF and not self.oscan():
            frameTransfer = 1033 * pars.VCLOCK_FRAME
            readout = (
                pars.VCLOCK_STORAGE * ybin
                + 536 * pars.HCLOCK
                + (512 / xbin + 2) * video
            ) * (1024 / ybin)
            if self.clear():
                clearTime = (1033 + 1027) * pars.VCLOCK_STORAGE
                cycleTime = (
                    pars.INVERSION_DELAY + expose + clearTime + frameTransfer + readout
                ) / 1.0e6
                exposureTime = expose / 1e6
            else:
                cycleTime = (
                    pars.INVERSION_DELAY + expose + frameTransfer + readout
                ) / 1.0e6
                exposureTime = cycleTime - frameTransfer / 1.0e6
            readout /= 1.0e6

        elif self.isFF and self.oscan():
            clearTime = (1033 + 1032) * pars.VCLOCK_FRAME
            frameTransfer = 1033 * pars.VCLOCK_FRAME
            readout = (
                pars.VCLOCK_STORAGE * ybin
                + 540 * pars.HCLOCK
                + ((540 / xbin) + 2) * video
            ) * (1032 / ybin)
            cycleTime = (
                pars.INVERSION_DELAY + expose + clearTime + frameTransfer + readout
            ) / 1.0e6
            exposureTime = expose / 1e6
            readout /= 1.0e6

        elif self.isDriftMode:
            xsl, xsr, ys, nx, ny = self.wframe.params(0)
            # number of windows stacked in storage
            nwins = int(0.5 * (1.0 + 1033 / ny))
            # pipe shift
            pshift = int(1033 - (2 * nwins - 1) * ny)

            frameTransfer = (ny + ys - 1) * pars.VCLOCK_FRAME
            diffshift = abs(xsl - 1 - (1034 - xsr - nx + 1))

            if xsl - 1 > 1024 - xsr - nx + 1:
                numHclocks = nx + diffshift + (1024 - xsr - nx + 1) + 8
            else:
                numHclocks = nx + diffshift + (xsl - 1) + 8
            lineread = (
                pars.VCLOCK_STORAGE * ybin
                + numHclocks * pars.HCLOCK
                + (nx / xbin + 2) * video
            )
            read = lineread * ny / ybin

            cycleTime = (
                pars.INVERSION_DELAY
                + pshift * pars.VCLOCK_STORAGE
                + expose
                + frameTransfer
                + read
            ) / 1.0e6
            exposureTime = cycleTime - frameTransfer / 1.0e6
            readout = (read + pshift * pars.VCLOCK_STORAGE) / 1.0e6
        else:
            # windowed mode
            clearTime = (1033 + 1027) * pars.VCLOCK_STORAGE if self.clear() else 0
            frameTransfer = 1033.0 * pars.VCLOCK_FRAME
            cycleTime = pars.INVERSION_DELAY + expose + frameTransfer + clearTime
            readout = 0.0
            # loop over all pairs
            for i in range(self.wframe.npair.value()):
                xsl, xsr, ys, nx, ny = self.wframe.params(i)

                # y params of previous window
                if i > 0:
                    ystart_m = self.wframe.ys[i - 1].value()
                    ny_m = self.wframe.ny[i - 1].value()
                else:
                    ystart_m = 1
                    ny_m = 0

                # Time taken to shift the window next to the storage area
                yshift = (ys - ystart_m - ny_m) * pars.VCLOCK_STORAGE

                # Number of columns to shift whichever window is further from
                # the edge of the readout to get ready for simultaneous readout.
                diffshift = abs(xsl - 1 - (1024 - xsr - nx + 1))

                """
                Time taken to dump any pixels in a row that come after the ones we want.
                The '8' is the number of HCLOCKs needed to open the serial register dump gates
                If the left window is further from the left edge than the right window is from the
                right edge, then the diffshift will move it to be the same as the right window, and
                so we use the right window parameters to determine the number of hclocks needed, and
                vice versa.
                """
                if xsl - 1 > 1024 - xsr - nx + 1:
                    numHclocks = nx + diffshift + (1024 - xsr - nx + 1) + 8
                else:
                    numHclocks = nx + diffshift + (xsl - 1) + 8

                # Time taken to read one line.
                # The extra 2 is required to fill the video pipeline buffer
                lineRead = (
                    pars.VCLOCK_STORAGE * ybin
                    + numHclocks * pars.HCLOCK
                    + (nx / xbin + 2) * video
                )

                # time to read the window
                read = (ny / ybin) * lineRead

                cycleTime += read + yshift
                readout += read + yshift

            if self.clear():
                exposureTime = expose / 1e6
            else:
                exposureTime = (cycleTime - frameTransfer) / 1e6
            cycleTime /= 1e6

        deadTime = cycleTime - exposureTime
        frameRate = 1.0 / cycleTime
        dutyCycle = 100.0 * exposureTime / cycleTime
        return exposureTime, deadTime, cycleTime, dutyCycle, frameRate


class RunPars(tk.LabelFrame):
    """
    Run parameters for ULTRACAM.

    Provides fields for the target name (with Simbad verification), programme
    ID, principal investigator, observer(s), and three per-arm filter
    dropdowns (blue / green / red).  Values are pushed into ``g.cpars`` on
    every change so that :meth:`InstPars.create_xml` can read them directly.
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text="Run parameters", padx=10, pady=10)

        # --- Labels (column 0) ---
        tk.Label(self, text="Target name").grid(row=0, column=0, sticky=tk.W)
        tk.Label(self, text="Filters").grid(row=1, column=0, sticky=tk.W)
        tk.Label(self, text="Programme ID").grid(row=2, column=0, sticky=tk.W)
        tk.Label(self, text="Principal Investigator").grid(row=3, column=0, sticky=tk.W)
        tk.Label(self, text="Observer(s)").grid(row=4, column=0, sticky=tk.W)

        # Spacer column
        tk.Label(self, text=" ").grid(row=0, column=1)

        # --- Widgets (column 2) ---

        # Target name with Simbad verify button
        self.target = w.Target(self, self.check)
        self.target.grid(row=0, column=2, sticky=tk.W)

        # Three filter dropdowns in one sub-frame
        filter_frame = tk.Frame(self)
        filter_frame.grid(row=1, column=2, sticky=tk.W)
        self.filter1 = w.Choice(
            filter_frame, pars.BLUE_FILTER_NAMES, checker=self.check
        )
        self.filter1.pack(side=tk.LEFT, padx=(0, 4))
        self.filter2 = w.Choice(
            filter_frame, pars.GREEN_FILTER_NAMES, checker=self.check
        )
        self.filter2.pack(side=tk.LEFT, padx=(0, 4))
        self.filter3 = w.Choice(filter_frame, pars.RED_FILTER_NAMES, checker=self.check)
        self.filter3.pack(side=tk.LEFT)

        # Programme ID
        self.prog_id = w.TextEntry(self, 20, self.check)
        self.prog_id.grid(row=2, column=2, sticky=tk.W)

        # Principal investigator
        self.pi = w.TextEntry(self, 20, self.check)
        self.pi.grid(row=3, column=2, sticky=tk.W)

        # Observers
        self.observers = w.TextEntry(self, 20, self.check)
        self.observers.grid(row=4, column=2, sticky=tk.W)

    @property
    def filter_string(self):
        """Return a combined filter string, e.g. ``"u' g' r'"``."""
        return "{} {} {}".format(
            self.filter1.value(), self.filter2.value(), self.filter3.value()
        )

    def check(self, *args):
        """Always OK. return True."""
        return True


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
            lframe, 18.0, 0.0, 30.0, self.checkUpdate, True, width=5
        )
        self.seeing = w.RangedFloat(
            lframe, 1.0, 0.2, 20.0, self.checkUpdate, True, True, width=5
        )
        self.airmass = w.RangedFloat(
            lframe, 1.5, 1.0, 5.0, self.checkUpdate, True, width=5
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
            g.clog.error("Current observing parameters are not valid.")
            return False

        if not g.ipars.check():
            g.clog.error("Current instrument parameters are not valid.")
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
        if g.ipars.nblue.value() > 0 and self.filter.value() == "u":
            expTime *= g.ipars.nblue.value()
            cycleTime *= g.ipars.nblue.value()

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
        readSpeed = g.ipars.readSpeed.value()
        xbin, ybin = g.ipars.wframe.xbin.value(), g.ipars.wframe.ybin.value()
        # index for readout noise array
        if xbin == 1:
            read_idx = 0
        elif xbin < 4:
            read_idx = 1
        elif xbin < 4:
            read_idx = 2
        else:
            read_idx = 3

        # calculate SN info.
        zero, sky, skyTot, gain, read, darkTot = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        total, peak, correct, signal, readTot, seeing = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        noise, _, narcsec, npix, signalToNoise3 = 1.0, 0.0, 0.0, 0.0, 0.0

        tinfo = g.TINS[g.cpars["telins_name"]]
        filtnam = self.filter.value()
        zero = tinfo["zerop"][filtnam]
        mag = self.mag.value()
        seeing = self.seeing.value()
        sky = g.SKY[self.moon.value()][filtnam]
        airmass = self.airmass.value()

        # GAIN, RNO
        if readSpeed == "Fast":
            gain = pars.GAIN_FAST
            read = pars.READ_NOISE_FAST[read_idx]
        elif readSpeed == "Turbo":
            gain = pars.GAIN_TURBO
            read = pars.READ_NOISE_TURBO[read_idx]
        elif readSpeed == "Slow":
            gain = pars.GAIN_SLOW
            read = pars.READ_NOISE_SLOW[read_idx]

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
        darkTot = npix * pars.DARK_COUNT * expTime  # in electrons
        readTot = npix * read**2  # in electrons

        # noise, in electrons
        noise = math.sqrt(readTot + darkTot + skyTot + signal)

        # Now compute signal-to-noise in 3 hour seconds run
        signalToNoise3 = signal / noise * math.sqrt(3 * 3600.0 / cycleTime)

        # if using the avalanche mode, check that the signal level
        # is safe. A single electron entering the avalanche register
        # results in a distribution of electrons at the output with
        # mean value given by the parameter avalanche_gain. The
        # distribution is close to exponential, hence the probability
        # of obtaining an amplification n times higher than the mean is
        # given by e**-n. A value of 3/5 for n is adopted here for
        # warning/safety, which will occur once in every ~20/100
        # amplifications

        # convert from electrons to counts
        total /= gain
        peak /= gain

        warn = 25000
        sat = 60000

        peakSat = peak > sat
        peakWarn = peak > warn

        return (total, peak, peakSat, peakWarn, signal / noise, signalToNoise3)


class InstSetup(tk.LabelFrame):
    """
    Instrument setup frame for ULTRACAM.

    Collects together all the instrument setup/control buttons.
    In noddy mode (expert_level == 0) only 'Initialise' and 'Power off'
    are shown. In expert mode (expert_level >= 1) all individual buttons
    are shown.
    """

    # Declarative state machine: maps state name to {button_attr: enabled}
    _STATES = {
        "after_reset_sdsu": dict(
            resetSDSUHard=True,
            resetSDSUSoft=False,
            resetAll=False,
            resetPCI=True,
            setupServer=False,
            powerOn=False,
            expertPowerOff=False,
            noddyPowerOff=False,
        ),
        "after_reset_pci": dict(
            resetSDSUHard=True,
            resetSDSUSoft=True,
            resetAll=True,
            resetPCI=False,
            setupServer=True,
            powerOn=False,
            expertPowerOff=False,
            noddyPowerOff=False,
        ),
        "after_setup_server": dict(
            resetSDSUHard=True,
            resetSDSUSoft=True,
            resetAll=True,
            resetPCI=False,
            setupServer=False,
            powerOn=True,
            expertPowerOff=False,
            noddyPowerOff=False,
        ),
        "after_power_on": dict(
            resetSDSUHard=True,
            resetSDSUSoft=True,
            resetAll=True,
            resetPCI=False,
            setupServer=False,
            powerOn=False,
            expertPowerOff=True,
            noddyPowerOff=True,
        ),
        "after_power_off": dict(
            resetSDSUHard=True,
            resetSDSUSoft=True,
            resetAll=True,
            resetPCI=False,
            setupServer=False,
            powerOn=True,
            expertPowerOff=False,
            noddyPowerOff=False,
        ),
        # States driven by the Observe panel
        "after_start_run": dict(
            resetSDSUHard=False,
            resetSDSUSoft=False,
            resetAll=False,
            resetPCI=False,
            setupServer=False,
            powerOn=False,
            expertPowerOff=False,
            noddyPowerOff=False,
        ),
        "after_stop_run": dict(
            resetSDSUHard=True,
            resetSDSUSoft=True,
            resetAll=True,
            resetPCI=False,
            setupServer=False,
            powerOn=False,
            expertPowerOff=True,
            noddyPowerOff=True,
        ),
    }

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text="Instrument setup", padx=10, pady=10)

        width = 17

        # Expert-mode buttons
        self.resetSDSUHard = ResetSDSUHard(self, width)
        self.resetSDSUSoft = ResetSDSUSoft(self, width)
        self.resetAll = ResetAll(self, width)
        self.resetPCI = ResetPCI(self, width)
        self.setupServer = SetupServer(self, width)
        self.powerOn = PowerOn(self, width)
        self.expertPowerOff = PowerOff(self, width)

        # Noddy-mode buttons
        self.setupAll = SetupAll(self, width)
        self.noddyPowerOff = PowerOff(self, width)

        self.expert_buttons = [
            self.resetSDSUHard,
            self.resetSDSUSoft,
            self.resetAll,
            self.resetPCI,
            self.setupServer,
            self.powerOn,
            self.expertPowerOff,
        ]
        self.noddy_buttons = [self.setupAll, self.noddyPowerOff]
        self.all_buttons = self.expert_buttons + self.noddy_buttons

        self.setExpertLevel()

    def apply_state(self, state):
        """
        Enable/disable buttons according to a named instrument state.

        Parameters
        ----------
        state : str
            One of the keys in ``InstSetup._STATES``.
        """
        if state not in self._STATES:
            return
        for attr, enabled in self._STATES[state].items():
            if enabled is None:
                continue
            button = getattr(self, attr)
            button.enable() if enabled else button.disable()

    def setExpertLevel(self):
        """
        Adjust which buttons are visible and whether they can be
        permanently overridden based on the expert level setting.
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]

        for button in self.all_buttons:
            button.grid_forget()

        if level == 0:
            self.setupAll.grid(row=0, column=0)
            self.noddyPowerOff.grid(row=0, column=1)
        else:
            self.resetSDSUHard.grid(row=0, column=0)
            self.resetSDSUSoft.grid(row=1, column=0)
            self.resetAll.grid(row=2, column=0)
            self.resetPCI.grid(row=3, column=0)
            self.setupServer.grid(row=4, column=0)
            self.powerOn.grid(row=5, column=0)
            self.expertPowerOff.grid(row=0, column=1)

        if level == 0 or level == 1:
            for button in self.all_buttons:
                button.setNonExpert()
        elif level == 2:
            for button in self.all_buttons:
                button.setExpert()


class Observe(tk.LabelFrame):
    """
    Observing control frame for ULTRACAM.

    Collects the application-management and run-control buttons.
    """

    # Declarative state machine: maps state name to {button_attr: enabled}
    _STATES = {
        "after_reset_sdsu": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_reset_pci": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_setup_server": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_power_on": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_power_off": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_start_run": dict(
            loadApp=False,
            saveApp=True,
            enableChanges=True,
            startRun=False,
            stopRun=True,
        ),
        "after_stop_run": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=False,
            stopRun=False,
        ),
        "after_save_app": dict(
            loadApp=True,
            saveApp=True,
            enableChanges=False,
            startRun=None,
            stopRun=None,
        ),
        "after_runtype_set": dict(
            loadApp=None,
            saveApp=None,
            enableChanges=None,
            startRun=True,
            stopRun=None,
        ),
    }

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text="Observing", padx=10, pady=10)

        width = 17

        self.loadApp = LoadApp(self, width)
        self.saveApp = SaveApp(self, width)
        self.enableChanges = EnableChanges(self, width)
        self.startRun = StartRun(self, width)
        self.stopRun = StopRun(self, width)

        # Run-type dropdown: sits in a small sub-frame with its own label
        rt_frame = tk.Frame(self)
        tk.Label(rt_frame, text="Run type:").pack(side=tk.LEFT, padx=(0, 4))
        self.runType = RunType(rt_frame)
        self.runType.pack(side=tk.LEFT)

        self.all_buttons = [
            self.loadApp,
            self.saveApp,
            self.enableChanges,
            self.startRun,
            self.stopRun,
        ]

        self.loadApp.grid(row=0, column=0, padx=2, pady=2)
        self.saveApp.grid(row=1, column=0, padx=2, pady=2)
        self.enableChanges.grid(row=2, column=0, padx=2, pady=2)

        rt_frame.grid(row=0, column=1, padx=2, pady=2)
        self.startRun.grid(row=1, column=1, padx=2, pady=2)
        self.stopRun.grid(row=2, column=1, padx=2, pady=2)

        self._powered_on = False  # True only after camera is powered on
        self.setExpertLevel()

    def apply_state(self, state):
        """
        Enable/disable buttons according to a named instrument state.

        Parameters
        ----------
        state : str
            One of the keys in ``Observe._STATES``.
        """
        if state not in self._STATES:
            return

        # Track whether starting a run is permitted.
        # Allowed only after an app has been saved/loaded (after_save_app).
        # after_runtype_set does not change the permission level.
        if state == "after_power_on":
            self._powered_on = True
        elif state == "after_power_off":
            self._powered_on = False

        for attr, enabled in self._STATES[state].items():
            if enabled is None:
                continue
            # Don't enable startRun via after_runtype_set unless the instrument
            # is initialised and an application has been saved.
            if attr == "startRun" and enabled and not self._powered_on:
                continue
            button = getattr(self, attr)
            button.enable() if enabled else button.disable()

    def setExpertLevel(self):
        """
        Apply expert/non-expert overrides to all buttons based on the current
        expert level setting.
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]

        if level == 0 or level == 1:
            for button in self.all_buttons:
                button.setNonExpert()
        elif level == 2:
            for button in self.all_buttons:
                button.setExpert()


## Button wigdets for the instrument setup frame.
class ResetSDSUHard(w.ActButton):
    """
    Class defining the 'Reset SDSU (hardware)' button's operation.

    Sends a hardware reset command ("RCO") to the camera server.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Reset SDSU (hw)")

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Reset SDSU (hardware) pressed")
        ok = yield tools.execCommand(g, "RCO")
        if ok:
            g.clog.info("Reset SDSU hardware")
            _apply_state(g, "after_reset_sdsu")
        return ok


class ResetSDSUSoft(w.ActButton):
    """
    Class defining the 'Reset SDSU (software)' button's operation.

    Sends a software reset command ("RS") to the camera server.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Reset SDSU (sw)")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Reset SDSU (software) pressed")
        ok = yield tools.execCommand(g, "RS")
        if ok:
            g.clog.info("Reset SDSU software")
            _apply_state(g, "after_reset_sdsu")
        return ok


class ResetAll(w.ActButton):
    """
    Class defining the 'System reset' button's operation.

    Sends the "SRS" command to the camera server.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="System reset")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("System reset pressed")
        ok = yield tools.execCommand(g, "SRS")
        if ok:
            g.clog.info("System reset")
            _apply_state(g, "after_reset_sdsu")
        return ok


class ResetPCI(w.ActButton):
    """
    Class defining the 'Reset PCI' button's operation.

    Sends the "RST" command to the camera server.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Reset PCI")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Reset PCI pressed")
        ok = yield tools.execCommand(g, "RST")
        if ok:
            g.clog.info("Reset PCI")
            _apply_state(g, "after_reset_pci")
        return ok


class SetupServer(w.ActButton):
    """
    Class defining the 'Setup servers' button's operation.

    Executes the generic ULTRACAM initialisation application on both servers.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Setup servers")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Setup servers pressed")
        app = g.cpars.get("generic_app", "ultracam.xml")
        ok = yield tools.execRemoteApp(g, app)
        if ok:
            g.clog.info("Servers set up")
            _apply_state(g, "after_setup_server")
        return ok


class PowerOn(w.ActButton):
    """
    Class defining the 'Power on' button's operation.

    Executes the power-on application on both servers.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Power on")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Power on pressed")
        app = g.cpars.get("power_on_app", "appl1_pon_cfg.xml")
        ok = yield tools.execRemoteApp(g, app)
        if ok:
            g.clog.info("Powered on SDSU")
            _apply_state(g, "after_power_on")
        return ok


class PowerOff(w.ActButton):
    """
    Class defining the 'Power off' button's operation.

    Executes the power-off application on both servers.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Power off")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Power off pressed")
        app = g.cpars.get("power_off_app", "appl2_pof_cfg.xml")
        ok = yield tools.execRemoteApp(g, app)
        if ok:
            g.clog.info("Powered off SDSU")
            _apply_state(g, "after_power_off")
        return ok


class SetupAll(w.ActButton):
    """
    Class defining the 'Initialise' button's operation (noddy mode).

    Performs a full initialisation sequence: system reset, server setup,
    then power on.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Initialise")

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Initialise pressed")

        ok = yield tools.execCommand(g, "SRS")
        if not ok:
            g.clog.warn("System reset failed; aborting initialise")
            return False

        ok = yield tools.execRemoteApp(g, g.cpars.get("generic_app", "ultracam.xml"))
        if not ok:
            g.clog.warn("Server setup failed; aborting initialise")
            return False

        ok = yield tools.execRemoteApp(
            g, g.cpars.get("power_on_app", "appl1_pon_cfg.xml")
        )
        if ok:
            g.clog.info("Initialise complete")
            _apply_state(g, "after_power_on")
        return ok


# Button widgets for the Observe frame
class LoadApp(w.ActButton):
    """
    Load an XML application from file and populate the instrument-parameters
    panel.

    Opens a file-chooser dialog.  Actual XML parsing is delegated to
    ``g.ipars.load_xml(path)`` if that method exists; otherwise the path is
    logged for future implementation.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Load application")

    def act(self):
        g = get_root(self).globals
        path = fd.askopenfilename(
            title="Load ULTRACAM application",
            filetypes=[("XML files", "*.xml"), ("All files", "*")],
        )
        if not path:
            return
        g.clog.info("Loading application: {}".format(path))
        if g.ipars is not None and hasattr(g.ipars, "load_xml"):
            g.ipars.load_xml(path)
        else:
            g.clog.warn("load_xml not yet implemented on ipars")


class SaveApp(w.ActButton):
    """
    Save the current instrument-parameter setup to an XML application file.

    Opens a file-chooser dialog.  Actual XML generation is delegated to
    ``g.ipars.save_xml(path)`` if that method exists.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Save application")

    def act(self):
        g = get_root(self).globals
        path = fd.asksaveasfilename(
            title="Save ULTRACAM application",
            defaultextension=".xml",
            filetypes=[("XML files", "*.xml"), ("All files", "*")],
        )
        if not path:
            return
        g.clog.info("Saving application to: {}".format(path))
        if g.ipars is not None and hasattr(g.ipars, "save_xml"):
            g.ipars.save_xml(path)
        else:
            g.clog.warn("save_xml not yet implemented on ipars")

        if getattr(g, "observe", None) is not None:
            g.observe.apply_state("after_save_app")


class EnableChanges(w.ActButton):
    """
    Re-enable instrument-parameter editing after a run has been started.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Unfreeze Udriver")
        self.disable()

    def act(self):
        g = get_root(self).globals
        if g.ipars is not None and hasattr(g.ipars, "enable"):
            g.ipars.enable()
        _apply_state(g, "after_save_app")


class StartRun(w.ActButton):
    """
    Post the current XML application then start an exposure.

    Calls ``g.ipars.create_xml()`` to build the XML, posts it to both servers
    via ``tools.postApp``, then sends the GO command to start the run.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Start exposure")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Start exposure pressed")

        if g.ipars is None or not hasattr(g.ipars, "create_xml"):
            g.clog.warn("create_xml not yet implemented on ipars")
            return False

        xml_string = g.ipars.create_xml()
        if xml_string is None:
            g.clog.warn("create_xml returned None; run not started")
            return False

        ok = yield tools.postApp(g, xml_string)
        if not ok:
            g.clog.warn("Failed to post application; run not started")
            return False

        g.clog.info("Application posted to servers")
        ok = yield tools.execCommand(g, "GO")
        if ok:
            g.clog.info("Exposure started")
            _apply_state(g, "after_start_run")
        return ok


class StopRun(w.ActButton):
    """
    Stop the current exposure by sending the ST command to the camera server.
    """

    def __init__(self, master, width):
        w.ActButton.__init__(self, master, width, text="Stop exposure")
        self.disable()

    @inlineCallbacks
    def act(self):
        g = get_root(self).globals
        g.clog.debug("Stop exposure pressed")
        ok = yield tools.execCommand(g, "ST")
        if ok:
            g.clog.info("Exposure stopped")
            _apply_state(g, "after_stop_run")
        return ok


class RunType(w.Select):
    """
    Dropdown box to select run type.

    Start button should be disabled until an option is made from this dropdown.
    """

    DTYPES = ("---", "data", "acquire", "bias", "flat", "dark", "tech")
    DVALS = ("", "data", "acquisition", "bias", "flat", "dark", "technical")

    def __init__(self, master, checker=None):
        w.Select.__init__(self, master, 0, RunType.DTYPES, self.check)
        self._checker = checker

    def __call__(self):
        index = self.options.index(self.val.get())
        return RunType.DVALS[index]

    def set(self, value):
        index = RunType.DVALS.index(value)
        w.Select.set(self, RunType.DTYPES[index])

    def check(self, *args):
        if self._checker is not None:
            self._checker()
        if self.val.get() != "---":
            g = get_root(self).globals
            _apply_state(g, "after_runtype_set")
