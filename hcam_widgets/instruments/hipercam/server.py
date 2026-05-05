# HiPERCAM server-related widgets
from __future__ import absolute_import, division, print_function, unicode_literals

import pickle
import subprocess
import time

import six
from astropy import coordinates as coord
from astropy import units as u
from astropy.time import Time
from hcam_devices.gtc.headers import add_gtc_header_table_row, create_gtc_header_table
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.task import LoopingCall

from ... import DriverError
from ...astro import calc_time_to_rotator_limit
from ...widgets import ActButton, Ilabel
from ...tkutils import get_root
from .tools import (
    ReadNGCTelemetry,
    execCommand,
    getRunNumber,
    insertFITSHDU,
    isPoweredOn,
    isRunActive,
    postJSON,
    stopNodding,
)

if not six.PY3:
    import Tkinter as tk
    import tkMessageBox as messagebox
else:
    import tkinter as tk
    from tkinter import messagebox



class Stop(ActButton):
    """
    Class defining the 'Stop' button's operation
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="Stop")
        g = get_root(self).globals
        self.config(bg=g.COL["stop"])

        # flags to help with stopping in background
        self.stopping = False

    def enable(self):
        """
        Enable the button.
        """
        ActButton.enable(self)
        g = get_root(self).globals
        self.config(bg=g.COL["stop"])

    def disable(self):
        """
        Disable the button, if in non-expert mode.
        """
        ActButton.disable(self)
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
        ActButton.setExpert(self)
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
        res = ReadNGCTelemetry(telemetry)
        stopped = res.state == "idle"

        if stopped and self.stopping:
            # Exposure stopped OK; modify buttons
            self.disable()

            # try and write FITS table before enabling start button, otherwise
            # a new start will clear table
            try:
                yield insertFITSHDU(g)
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
                success = yield postJSON(g, idle)
                if not success:
                    raise Exception("postJSON returned false")
            except Exception as err:
                g.clog.warn("Failed to enable idle mode")
                g.clog.warn(str(err))

            g.clog.info("Stopping offsets (if running")
            try:
                success = yield stopNodding(g)
                if not success:
                    raise Exception("Failed to stop dithering: response was false")
            except Exception as err:
                g.clog.warn("Failed to stop GTC offset script")
                g.clog.warn(str(err))

            returnValue(True)
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


class NGCReset(ActButton):
    """
    Class defining the 'NGC Reset' button
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="NGC Reset")

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
            returnValue(False)
        else:
            g.clog.info("NGC Reset succeeded")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            returnValue(True)


class NGCStandby(ActButton):
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
        ActButton.__init__(self, master, width, text="NGC Standby")

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
            returnValue(False)
        else:
            g.clog.info("Standby command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            returnValue(True)


class NGCOnline(ActButton):
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
        ActButton.__init__(self, master, width, text="NGC Online")

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
            returnValue(False)
        else:
            g.clog.info("Online command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.enable()
            g.setup.cldcOff.disable()
            returnValue(True)


class NGCOff(ActButton):
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
        ActButton.__init__(self, master, width, text="NGC Off")

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
            returnValue(False)
        else:
            g.clog.info("off command successful; server in loaded state")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.disable()
            g.setup.cldcOff.disable()
            returnValue(True)


class SeqStart(ActButton):
    """
    Class defining the button to start sequencers.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="Seq Start")
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
            returnValue(False)
        else:
            g.clog.info("seq start command successful; clocks powered on")
            # alter buttons here
            g.observe.start.enable()
            g.observe.stop.enable()
            g.setup.seqStop.enable()
            self.disable()
            returnValue(True)


class SeqStop(ActButton):
    """
    Class defining the button to stop sequencers.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="Seq Stop")
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
            returnValue(False)
        else:
            g.clog.info("seq stop command successful")
            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.seqStart.enable()
            self.disable()
            returnValue(True)


class CLDCOn(ActButton):
    """
    Class defining the button to turn on clocks.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="CLDC On")
        self.disable()

    @inlineCallbacks
    def act(self):
        root = get_root(self)
        g = root.globals
        g.clog.debug("CLDC On pressed")
        session = root.globals.session
        try:
            powered_on = yield isPoweredOn(g)
        except Exception as err:
            g.clog.warn(str(err))
            returnValue(False)

        if powered_on:
            g.clog.info("clocks already on")
            returnValue(True)

        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.pon")
            if not ok:
                raise RuntimeError("could not power on clocks")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("CLDC On failed: " + msg)
            returnValue(False)
        else:
            g.clog.info("CLDC on command successful; clocks powered on")
            # alter buttons here
            g.observe.start.enable()
            g.observe.stop.enable()
            g.setup.cldcOff.enable()
            g.setup.seqStart.enable()
            self.disable()
            returnValue(True)


class CLDCOff(ActButton):
    """
    Class defining the button to turn off clocks.
    """

    def __init__(self, master, width):
        """
        master   : containing widget
        width    : width of button
        """
        ActButton.__init__(self, master, width, text="CLDC Off")
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
            returnValue(False)
        else:
            g.clog.info("CLDC off command successful; clocks powered off")

            # alter buttons here
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.cldcOn.enable()
            self.disable()
            returnValue(True)


class PowerOn(ActButton):
    """
    Class defining the 'Power on' button's operation
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        ActButton.__init__(self, master, width, text="Power on")

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
                powered_on = yield isPoweredOn(g)
            except Exception as err:
                g.clog.warn("cannot determine if CLDC is already on")
                msg = err.error_message() if hasattr(err, "error_message") else str(err)
                g.clog.warn(msg)
                returnValue(False)

            if not powered_on:
                success = yield execCommand(g, "pon")
                if not success:
                    g.clog.warn("Unable to power on CLDC")
                    returnValue(False)

            success = yield execCommand(g, "seq_start")
            if not success:
                g.clog.warn("Failed to start sequencer after Power On.")

            try:
                run = yield getRunNumber(g)
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
            returnValue(True)


class PowerOff(ActButton):
    """
    Class defining the 'Power off' button's operation
    """

    def __init__(self, master, width):
        """
        master  : containing widget
        width   : width of button
        """
        ActButton.__init__(self, master, width, text="Power off")
        self.disable()

    @inlineCallbacks
    def act(self):
        """
        Power off action
        """
        g = get_root(self).globals
        g.clog.debug("Power off pressed")

        success = yield execCommand(g, "poff")
        if not success:
            g.clog.warn("Unable to power off CLDC")
            returnValue(False)

        success = yield execCommand(g, "offline")
        if success:
            g.clog.info("ESO server idle")
            g.cpars["eso_server_online"] = False

            # alter buttons
            self.disable()
            g.observe.start.disable()
            g.observe.stop.disable()
            g.setup.powerOn.enable()
            returnValue(True)
        else:
            g.clog.warn("Power off failed")
            returnValue(False)


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
            res = ReadNGCTelemetry(telemetry)
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
                    run_active = yield isRunActive(g)
                except Exception as err:
                    g.clog.warn(str(err))
                if not run_active:
                    # try and write FITS table before enabling start button, otherwise
                    # a new start will clear table
                    try:
                        yield insertFITSHDU(g)
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
                        success = yield postJSON(g, idle)
                        if not success:
                            raise Exception("postJSON returned false")
                    except Exception as err:
                        g.clog.warn("Failed to enable idle mode")
                        g.clog.warn(str(err))

                    g.clog.info("Stopping offsets (if running")
                    try:
                        success = yield stopNodding(g)
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

        self.run = Ilabel(self, text="UNDEF")
        self.frame = Ilabel(self, text="UNDEF")
        self.timer = Timer(self)
        self.cadence = Ilabel(self, text="UNDEF")
        self.duty = Ilabel(self, text="UNDEF")
        self.ra = Ilabel(self, text="UNDEF")
        self.dec = Ilabel(self, text="UNDEF")
        self.alt = Ilabel(self, text="UNDEF")
        self.az = Ilabel(self, text="UNDEF")
        self.airmass = Ilabel(self, text="UNDEF")
        self.ha = Ilabel(self, text="UNDEF")
        self.pa = Ilabel(self, text="UNDEF")
        self.rotlimit = Ilabel(self, text="UNDEF")
        self.focus = Ilabel(self, text="UNDEF")
        self.mdist = Ilabel(self, text="UNDEF")
        self.fpslide = Ilabel(self, text="UNDEF")
        self.ccd_temps = Ilabel(self, text="UNDEF")

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
            status = ReadNGCTelemetry(telemetry)
            run = status.run
            frame_no = int(telemetry["exposure.frame"])
        except Exception as err:
            g.clog.warn("failed to parse NGC telemetry: " + str(err))
        else:
            self.run.configure(text="{0:03d}".format(run))
            self.frame.configure(text="{0:04d}".format(frame_no))
