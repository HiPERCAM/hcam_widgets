# Utility to query and set temps via Ethernet on Meerstetter
from __future__ import absolute_import, unicode_literals, print_function, division
import six
import pickle

# GUI imports
from hcam_widgets.widgets import RangedInt
from hcam_widgets.tkutils import get_root, addStyle

from twisted.internet.defer import inlineCallbacks

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk


class CCDTempFrame(tk.LabelFrame):
    """
    Self-contained widget to control CCD temps and reset TECS.
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text="CCD TECs", padx=10, pady=4)
        # Top for table of buttons
        top = tk.Frame(self)

        tk.Label(top, text="CCD1").grid(row=0, column=0)
        tk.Label(top, text="CCD2").grid(row=0, column=1)
        tk.Label(top, text="CCD3").grid(row=0, column=2)
        tk.Label(top, text="CCD4").grid(row=0, column=3)
        tk.Label(top, text="CCD5").grid(row=0, column=4)

        # maps ccd number to meerstetter, meerstetter address
        self.mapping = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 1), 5: (2, 2)}

        self.temp_entry_widgets = {}
        self.setpoint_displays = {}
        self.reset_buttons = {}
        width = 8
        for i in range(1, 6):
            ival = 5
            self.temp_entry_widgets[i] = RangedInt(
                top, ival, -100, 20, None, True, width=width
            )
            self.temp_entry_widgets[i].grid(row=1, column=i - 1)
            self.setpoint_displays[i] = tk.Label(top, text="nan", width=width)
            self.setpoint_displays[i].grid(row=2, column=i - 1)
            self.reset_buttons[i] = tk.Button(
                top,
                fg="black",
                width=width,
                text="Reset",
                command=lambda ccd=i: self.reset(ccd),
            )
            self.reset_buttons[i].grid(row=3, column=i - 1)

        # bind enter to set value routine
        for i in range(1, 6):
            widget = self.temp_entry_widgets[i]
            widget.unbind("<Return>")
            widget.bind("<Return>", lambda event, ccd=i: self.update(ccd))

        top.pack(pady=2)
        addStyle(self)

        self.telemetry_topics = [
            (
                "hipercam.meerstetter1.telemetry",
                lambda data: self.on_telemetry(1, data),
            ),
            (
                "hipercam.meerstetter2.telemetry",
                lambda data: self.on_telemetry(2, data),
            ),
        ]

    def on_telemetry(self, ms, data):
        g = get_root(self).globals
        try:
            telemetry = pickle.loads(data)
        except Exception as err:
            wrn = "cannot parse telemetry from Meerstetter {}: {}"
            g.clog.warn(wrn.format(ms, str(err)))
        else:
            if ms == 1:
                widget_numbers = (1, 2, 3)
            else:
                widget_numbers = (4, 5)
            for i, num in enumerate(widget_numbers):
                key = "target_temperature{}".format(i + 1)
                setpoint = telemetry[key].value
                widget = self.setpoint_displays[num]
                widget.configure(text=str(setpoint))

    @inlineCallbacks
    def update(self, ccd):
        g = get_root(self).globals
        if not g.cpars["ccd_temp_monitoring_on"]:
            g.clog.warn(
                "Temperature monitoring disabled. Will not update CCD{}".format(ccd)
            )
            return
        g.clog.info("Updating CCD{}".format(ccd))
        widget = self.temp_entry_widgets[ccd]
        val = widget.value()
        g.clog.info("desired setpoint " + str(val))

        try:
            session = get_root(self).globals.session
            topic = "hipercam.ccd{}.setpoint".format(ccd)
            g.clog.info("publishing to topic " + topic)
            yield session.publish(topic, float(val))
        except Exception:
            g.clog.warn("Unable to update setpoint for CCD{}".format(ccd))

    @inlineCallbacks
    def reset(self, ccd):
        g = get_root(self).globals
        if not g.cpars["ccd_temp_monitoring_on"]:
            g.clog.warn(
                "Temperature monitoring disabled. Will not reset CCD{}".format(ccd)
            )
            return
        g.clog.info("Resetting TEC on CCD{}".format(ccd))
        ms, address = self.mapping[ccd]
        try:
            rpc = "hipercam.meerstetter{}.rpc.reset".format(ms)
            session = get_root(self).globals.session
            yield session.call(rpc, address)
        except Exception as err:
            g.clog.warn("Unable to reset TEC {}".format(ccd))
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn(msg)
