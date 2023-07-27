# miscellaneous useful tools
from __future__ import print_function, unicode_literals, absolute_import, division
import json
from six.moves import urllib
import six
import threading
import sys
import traceback
import os
import re

from astropy.io import fits
from astropy.io import ascii

from . import DriverError

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet import reactor
from twisted.internet.task import deferLater


if not six.PY3:
    import tkFileDialog as filedialog
    from StringIO import StringIO
else:
    from tkinter import filedialog
    from io import StringIO


def async_sleep(secs):
    return deferLater(reactor, secs, lambda: None)


class ReadNGCTelemetry(object):
    """
    Class to field the telemetry sent by the NGC server

    Set the following attributes:
     ok      : True if telemetry is read OK
     err     : reason if telemetry not parsed OK
     state   : state of the camera. Possibilties are:
               'IDLE', 'BUSY', 'ERROR', 'ABORT', 'UNKNOWN'
     clocks  : whether the clock voltages are enabled. Possible values:
               'enabled', 'disabled'
     run     : current or last run number
    """

    def __init__(self, telemetry):
        """
        Parameters
        ----------
        telemetry : dict
            telemetry package from NGC
        """
        # Determine state of the camera
        self.ok = True
        self.err = ""
        if "system.subStateName" not in telemetry:
            self.err += "could not identify state\n"
            self.state = None
        else:
            self.state = telemetry["system.subStateName"]

        # determine state of clocks
        if "cldc_0.statusName" not in telemetry:
            self.ok = False
            self.err += "could not identify clock status\n"
            self.clocks = None
        else:
            self.clocks = telemetry["cldc_0.statusName"]

        # Find current run number (set it to 0 if we fail)
        newDataFileName = telemetry["exposure.newDataFileName"]
        exposure_state = telemetry["exposure.expStatusName"]
        pattern = "\D*(\d*).*.fits"
        try:
            run_number = int(re.match(pattern, newDataFileName).group(1))
            if exposure_state in ["success", "aborted", "inactive", "failure"]:
                self.run = run_number
            elif exposure_state == "integrating":
                self.run = run_number + 1
            else:
                raise ValueError("unknown exposure state {}".format(exposure_state))
        except (ValueError, IndexError, AttributeError):
            self.run = 0
            self.ok = False
            self.err += "cannot read run number"


def overlap(xl1, yl1, nx1, ny1, xl2, yl2, nx2, ny2):
    """
    Determines whether two windows overlap
    """
    return xl2 < xl1 + nx1 and xl2 + nx2 > xl1 and yl2 < yl1 + ny1 and yl2 + ny2 > yl1


@inlineCallbacks
def startNodding(g, data):
    nodPattern = data.get("appdata", {}).get("nodpattern", {})
    if g.cpars["telins_name"] == "GTC" and nodPattern:
        session = g.session
        if session is None:
            g.clog.warn("no WAMP session")
            returnValue(False)
        try:
            yield session.call("hipercam.gtc.rpc.gtc.start_nodding")
        except Exception as err:
            g.clog.warn("Failed to stop dither server")
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn(msg)
            returnValue(False)
    returnValue(True)


@inlineCallbacks
def stopNodding(g):
    if g.cpars["telins_name"] == "GTC":
        session = g.session
        if session is None:
            g.clog.warn("no WAMP session")
            returnValue(False)
        try:
            yield session.call("hipercam.gtc.rpc.gtc.stop_nodding")
        except Exception as err:
            g.clog.warn("Failed to stop dither server")
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn(msg)
            returnValue(False)
    returnValue(True)


def saveJSON(g, data, backup=False):
    """
    Saves the current setup to disk.

    g : hcam_drivers.globals.Container
    Container with globals

    data : dict
    The current setup in JSON compatible dictionary format.

    backup : bool
    If we are saving a backup on close, don't prompt for filename
    """
    if not backup:
        fname = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[
                ("json files", ".json"),
            ],
            initialdir=g.cpars["app_directory"],
        )
    else:
        fname = os.path.join(os.path.expanduser("~/.hdriver"), "app.json")

    if not fname:
        g.clog.warn("Aborted save to disk")
        return False

    with open(fname, "w") as of:
        of.write(json.dumps(data, sort_keys=True, indent=4, separators=(",", ": ")))
    g.clog.info("Saved setup to" + fname)
    return True


@inlineCallbacks
def postJSON(g, data):
    """
    Posts the current setup to the camera and data servers.

    g : hcam_drivers.globals.Container
    Container with globals

    data : dict
    The current setup in JSON compatible dictionary format.
    """
    g.clog.debug("Entering postJSON")
    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    ok = True
    try:
        ok, status_msg = yield session.call("hipercam.ngc.rpc.load_setup", data)
    except Exception as err:
        status_msg = err.error_message() if hasattr(err, "error_message") else str(err)
        ok = False

    if not ok:
        g.clog.warn("Server response was not OK")
        g.rlog.warn("Error: " + status_msg)
        returnValue(False)

    # now try to setup nodding server if appropriate
    nodpattern = data.get("appdata", {}).get("nodpattern", {})
    if g.cpars["telins_name"] == "GTC" and nodpattern:
        try:
            ra_offsets = list(nodpattern["ra"])
            dec_offsets = list(nodpattern["dec"])
            yield session.call(
                "hipercam.gtc.rpc.load_nod_pattern", ra_offsets, dec_offsets
            )
            ok = True
        except Exception as err:
            status_msg = (
                err.error_message() if hasattr(err, "error_message") else str(err)
            )
            ok = False

        if not ok:
            g.clog.warn("Offset Server response was not OK")
            g.rlog.warn("Error: " + status_msg)
            returnValue(False)

    g.clog.debug("Leaving postJSON")
    returnValue(True)


@inlineCallbacks
def createJSON(g, full=True):
    """
    Create JSON compatible dictionary from current settings

    Parameters
    ----------
    g :  hcam_drivers.globals.Container
    Container with globals
    """
    data = dict()
    if "gps_attached" not in g.cpars:
        data["gps_attached"] = 1
    else:
        data["gps_attached"] = 1 if g.cpars["gps_attached"] else 0

    data["appdata"] = g.ipars.dumpJSON()
    data["user"] = g.rpars.dumpJSON()
    if full:
        data["hardware"] = g.ccd_hw.dumpJSON()
        data["tcs"] = g.info.dumpJSON()
        data["compo"] = g.compo_hw.dumpJSON()

        if g.cpars["telins_name"].lower() == "gtc":
            session = g.session
            if session is None:
                g.clog.warn("no WAMP session, not fetching telescope parameters")
            else:
                try:
                    telpars = yield session.call("hipercam.gtc.rpc.get_telescope_pars")
                    data["gtc_headers"] = telpars
                except Exception as err:
                    g.clog.warn("cannot get GTC headers from telescope server")
                    msg = (
                        err.error_message()
                        if hasattr(err, "error_message")
                        else str(err)
                    )
                    g.clog.warn(msg)
    returnValue(data)


def jsonFromFits(fname):
    hdr = fits.getheader(fname)

    def full_key(key):
        return "HIERARCH ESO {}".format(key)

    def get(name, default=None):
        return hdr.get(full_key(name), default)

    app_data = dict(
        multipliers=[1 + get("DET NSKIPS{}".format(i + 1), 0) for i in range(5)],
        dummy_out=get("DET DUMMY", 0),
        fastclk=get("DET FASTCLK", 0),
        oscan=int(get("DET INCPRSCX", False)),
        oscany=int(get("DET INCOVSCY", False)),
        readout="Slow" if get("DET SPEED", 0) == 0 else "Fast",
        xbin=get("DET BINX1", 1),
        ybin=get("DET BINY1", 1),
        clear=int(get("DET CLRCCD", True)),
        led_flsh=int(get("DET EXPLED", False)),
        dwell=get("DET TEXPOSE", 0.1) / 1000
        # TODO: numexp
    )

    user = dict(
        Observers=hdr.get("OBSERVER", ""),
        target=hdr.get("OBJECT", ""),
        comment=hdr.get("RUNCOM", ""),
        flags=hdr.get("IMAGETYP", "data"),
        filters=hdr.get("FILTERS", "us,gs,rs,is,zs"),
        ID=hdr.get("PROGRM", ""),
        PI=hdr.get("PI", ""),
    )

    mode = get("DET READ CURID")
    if mode == 2:
        # one window
        app_data["app"] = "Windows"
        app_data["x1size"] = get("DET WIN1 NX")
        app_data["y1size"] = get("DET WIN1 NY")
        app_data["x1start_lowerleft"] = get("DET WIN1 XSLL")
        app_data["x1start_lowerright"] = get("DET WIN1 XSLR")
        app_data["x1start_upperleft"] = get("DET WIN1 XSUL")
        app_data["x1start_upperright"] = get("DET WIN1 XSUR")
        app_data["y1start"] = get("DET WIN1 YS") + 1
    elif mode == 3:
        # two window
        app_data["app"] = "Windows"
        app_data["x1size"] = get("DET WIN1 NX")
        app_data["y1size"] = get("DET WIN1 NY")
        app_data["x1start_lowerleft"] = get("DET WIN1 XSLL")
        app_data["x1start_lowerright"] = get("DET WIN1 XSLR")
        app_data["x1start_upperleft"] = get("DET WIN1 XSUL")
        app_data["x1start_upperright"] = get("DET WIN1 XSUR")
        app_data["y1start"] = get("DET WIN1 YS") + 1
        app_data["x2size"] = get("DET WIN2 NX")
        app_data["y2size"] = get("DET WIN2 NY")
        app_data["x2start_lowerleft"] = get("DET WIN2 XSLL")
        app_data["x2start_lowerright"] = get("DET WIN2 XSLR")
        app_data["x2start_upperleft"] = get("DET WIN2 XSUL")
        app_data["x2start_upperright"] = get("DET WIN2 XSUR")
        app_data["y2start"] = get("DET WIN2 YS") + 1
    elif mode == 4:
        # drift mode
        app_data["app"] = "Drift"
        app_data["x1size"] = get("DET DRWIN NX")
        app_data["y1size"] = get("DET DRWIN NY")
        app_data["x1start_left"] = get("DET DRWIN XSL")
        app_data["x1start_right"] = get("DET DRWIN XSR")
        app_data["y1start"] = 1 + get("DET DRWIN YS")
    else:
        app_data["app"] = "FullFrame"

    setup_data = dict(appdata=app_data, user=user)
    return json.dumps(setup_data)


@inlineCallbacks
def insertFITSHDU(g):
    """
    Uploads a table of TCS data to the servers, which is appended onto a run.

    Arguments
    ---------
    g : hcam_drivers.globals.Container
        the Container object of application globals
    """
    if not g.cpars["hcam_server_on"]:
        g.clog.warn("insertFITSHDU: servers are not active")
        returnValue(False)

    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    run_number = yield getRunNumber(g)
    tcs_table = g.info.tcs_table

    g.clog.info("Adding TCS table data to run{:04d}.fits".format(run_number))
    try:
        fd = StringIO()
        ascii.write(tcs_table, format="ecsv", output=fd)
        yield session.call("hipercam.ngc.rpc.add_hdu", fd.getvalue(), run_number)
    except Exception as err:
        g.clog.warn("insertFITSHDU failed")
        msg = err.error_message() if hasattr(err, "error_message") else str(err)
        g.clog.warn(msg)
    returnValue(True)


@inlineCallbacks
def execCommand(g, command, timeout=10):
    """
    Executes a command by sending it to the NGC server

    Arguments:
      g : hcam_drivers.globals.Container
        the Container object of application globals
      command : (string)
           the command (see below)

    Possible commands are:

      start              : starts a run
      stop               : stops a run
      abort              : aborts a run
      online             : bring ESO control server online and connect it to hardware
      offline            : put ESO control server in idle state and power down
      standby            : server can communicate, but child processes disabled
      reset              : resets the NGC controller front end

    Returns True/False according to whether the command
    succeeded or not.
    """
    if not g.cpars["hcam_server_on"]:
        g.clog.warn("execCommand: servers are not active")
        returnValue(False)

    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    try:
        response = yield session.call("hipercam.ngc.rpc.{}".format(command))
        if response is not None:
            msg, ok = response
        else:
            msg = ""
            ok = True
        g.clog.info('execCommand, command = "' + command + '"')

        if ok:
            g.clog.info("Response from server was OK")
            returnValue(True)
        else:
            g.clog.warn("Response from server was not OK")
            g.clog.warn("Reason: " + msg)
            returnValue(False)
    except Exception as err:
        g.clog.warn("execCommand failed")
        msg = err.error_message() if hasattr(err, "error_message") else str(err)
        g.clog.warn(msg)

    returnValue(False)


@inlineCallbacks
def isRunActive(g):
    """
    Polls the data server to see if a run is active
    """
    session = g.session if hasattr(g, "session") else None
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    if g.cpars["hcam_server_on"]:
        try:
            response = yield session.call("hipercam.ngc.rpc.summary")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            raise DriverError("isRunActive error reading NGC status: " + msg)
        tel = ReadNGCTelemetry(response)

        if not tel.ok:
            raise DriverError("isRunActive error: " + str(tel.err))
        if tel.state == "idle":
            returnValue(False)
        elif tel.state == "active":
            returnValue(True)
        elif tel.state == "error":
            msg = """
            NGC is in error state.
            Try resetting it using 'start_hicam' and 'Power On'
            """
            raise DriverError("isRunActive error\n" + msg)
        else:
            raise DriverError("isRunActive error, state = " + tel.state)
    else:
        raise DriverError("isRunActive error: servers are not active")


@inlineCallbacks
def isPoweredOn(g):
    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    if g.cpars["hcam_server_on"]:
        try:
            response = yield session.call("hipercam.ngc.rpc.summary")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            raise DriverError("isPoweredOn error reading NGC status: " + msg)

        tel = ReadNGCTelemetry(response)
        if not tel.ok:
            raise DriverError("isPoweredOn error: " + str(tel.err))
        if tel.clocks == "enabled":
            returnValue(True)
        else:
            returnValue(False)
    else:
        raise DriverError("isPoweredOn error: servers are not active")


@inlineCallbacks
def isOnline(g):
    # checks if ESO Server is in ONLINE state
    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    if g.cpars["hcam_server_on"]:
        try:
            msg, ok = yield session.call("hipercam.ngc.rpc.status")
        except Exception as err:
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            raise DriverError("isOnline error: " + msg)

        if not ok:
            raise DriverError("isOnline error: " + msg)
        if msg.lower() == "online":
            returnValue(True)
        else:
            returnValue(False)
    else:
        raise DriverError("isOnline error: hserver is not active")


@inlineCallbacks
def getFrameNumber(g):
    """
    Polls the data server to find the current frame number.

    Throws an exceotion if it cannot determine it.
    """
    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    if not g.cpars["hcam_server_on"]:
        raise DriverError("getRunNumber error: servers are not active")
    msg, ok = yield session.call("hipercam.ngc.rpc.status", "DET.FRAM2.NO")
    if not ok:
        raise DriverError("getFrameNumber error: could not get frame number " + msg)
    try:
        frame_no = int(msg)
    except ValueError:
        raise DriverError("getFrameNumber error: invalid msg " + msg)
    returnValue(frame_no)


@inlineCallbacks
def getRunNumber(g):
    """
    Polls the data server to find the current run number. Throws
    exceptions if it can't determine it.
    """
    session = g.session
    if session is None:
        g.clog.warn("no WAMP session")
        returnValue(False)

    if not g.cpars["hcam_server_on"]:
        raise DriverError("getRunNumber error: servers are not active")
    try:
        response = yield session.call("hipercam.ngc.rpc.summary")
    except Exception as err:
        msg = err.error_message() if hasattr(err, "error_message") else str(err)
        raise DriverError("isRunActive error reading NGC status: " + msg)
    tel = ReadNGCTelemetry(response)
    if tel.ok:
        returnValue(tel.run)
    else:
        raise DriverError("getRunNumber error: " + str(tel.err))


def checkSimbad(g, target, maxobj=5, timeout=5):
    """
    Sends off a request to Simbad to check whether a target is recognised.
    Returns with a list of results, or raises an exception if it times out
    """
    url = "http://simbad.u-strasbg.fr/simbad/sim-script"
    q = (
        "set limit "
        + str(maxobj)
        + '\nformat object form1 "Target: %IDLIST(1) | %COO(A D;ICRS)"\nquery '
        + target
    )
    query = urllib.parse.urlencode({"submit": "submit script", "script": q})
    resp = urllib.request.urlopen(url, query.encode(), timeout)
    data = False
    error = False
    results = []
    for line in resp:
        line = line.decode()
        if line.startswith("::data::"):
            data = True
        if line.startswith("::error::"):
            error = True
        if data and line.startswith("Target:"):
            name, coords = line[7:].split(" | ")
            results.append(
                {"Name": name.strip(), "Position": coords.strip(), "Frame": "ICRS"}
            )
    resp.close()

    if error and len(results):
        g.clog.warn(
            "drivers.check: Simbad: there appear to be some "
            + "results but an error was unexpectedly raised."
        )
    return results


class FifoThread(threading.Thread):
    """
    Adds a fifo Queue to a thread in order to store up disasters which are
    added to the fifo for later retrieval. This is to get around the problem
    that otherwise exceptions thrown from withins threaded operations are
    lost.
    """

    def __init__(self, name, target, fifo, args=()):
        threading.Thread.__init__(self, target=target, args=args)
        self.fifo = fifo
        self.name = name

    def run(self):
        """
        Version of run that traps Exceptions and stores
        them in the fifo
        """
        try:
            threading.Thread.run(self)
        except Exception:
            t, v, tb = sys.exc_info()
            error = traceback.format_exception_only(t, v)[0][:-1]
            tback = (
                self.name
                + " Traceback (most recent call last):\n"
                + "".join(traceback.format_tb(tb))
            )
            self.fifo.put((self.name, error, tback))
