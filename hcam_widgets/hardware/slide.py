from __future__ import absolute_import, division, print_function

import pickle

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import patches

import six
import numpy as np

from autobahn.wamp.exception import SerializationError

from hcam_widgets.tkutils import get_root
from hcam_widgets.widgets import IntegerEntry
from hcam_widgets.mimic import Mimic
from hcam_devices.models.slide import BLOCK_POS, UNBLOCK_POS
from hcam_widgets.misc import async_sleep

from twisted.internet.defer import inlineCallbacks

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk


SLEEP_BEFORE_MOVE = 0.5


class SlideFrame(tk.LabelFrame, Mimic):
    """
    Self-contained widget to deal with the focal plane slide
    """

    def __init__(self, master, show_mimic=True):
        """
        master  : containing widget
        """
        Mimic.__init__(self, height=200, width=100)
        tk.LabelFrame.__init__(self, master, text="Focal plane slide", padx=10, pady=4)

        # Top for table of buttons
        top = tk.Frame(self)

        # Define the buttons
        width = 8
        self.connect = tk.Button(
            top,
            fg="black",
            text="conn",
            width=width,
            command=lambda: self.action("connection.connect"),
        )

        self.home = tk.Button(
            top,
            fg="black",
            text="home",
            width=width,
            command=lambda: self.action("stage.home"),
        )

        self.block = tk.Button(
            top,
            fg="black",
            text="block",
            width=width,
            command=lambda: self.action("block"),
        )

        self.unblock = tk.Button(
            top,
            fg="black",
            text="unblock",
            width=width,
            command=lambda: self.action("unblock"),
        )

        self.gval = IntegerEntry(top, UNBLOCK_POS, None, True, width=4)

        self.goto = tk.Button(
            top,
            fg="black",
            text="goto",
            width=width,
            command=lambda: self.action("goto", self.gval.value()),
        )

        self.reset = tk.Button(
            top,
            fg="black",
            text="reset",
            width=width,
            command=lambda: self.action("reset"),
        )

        self.stop = tk.Button(
            top,
            fg="black",
            text="stop",
            width=width,
            command=lambda: self.action("stage.stop"),
        )

        self.enable = tk.Button(
            top,
            fg="black",
            text="enable",
            width=width,
            command=lambda: self.action("enable"),
        )

        self.disable = tk.Button(
            top,
            fg="black",
            text="disable",
            width=width,
            command=lambda: self.action("disable"),
        )

        self.restore = tk.Button(
            top,
            fg="black",
            text="restore",
            width=width,
            command=lambda: self.action("restore"),
        )

        # arrange the permanent ones
        self.connect.grid(row=0, column=0)
        self.home.grid(row=0, column=1)
        self.block.grid(row=0, column=2)
        self.unblock.grid(row=1, column=2)
        self.goto.grid(row=1, column=0)
        self.gval.grid(row=1, column=1)

        # set others according to expertlevel
        self.setExpertLevel()

        g = get_root(self).globals

        # widget for messages
        self.label = tk.Text(top, height=4, width=30, bg=g.COL["log"])
        self.label.configure(state=tk.NORMAL, font=g.ENTRY_FONT)
        self.label.grid(row=4, column=0, columnspan=3)

        # mimic
        self.showing_mimic = show_mimic
        if show_mimic:
            self.canvas = FigureCanvasTkAgg(self.figure, top)
            self.canvas.get_tk_widget().grid(row=5, column=0, columnspan=3)

        top.pack(pady=2)

    def update_mimic(self, telemetry):
        """
        Use current telemetry to update Mimic of the slide
        """
        if not telemetry or not self.showing_mimic:
            return

        try:
            pos = telemetry["position"]["current"].value
        except Exception:
            pos = telemetry["position"]["current"]

        state = telemetry["state"]
        connection_state = state["connection"]
        stage_state = state["stage"]

        ccd_color, slide_color = ("b", "k")  # chip slide (stopped)
        if (
            "error" in connection_state
            or "offline" in connection_state
            or "homed" not in stage_state
        ):
            slide_color = "r"
        elif "moving" in stage_state:
            slide_color = "y"

        ll = (0, 0)
        width = 2048
        height = 1024
        ccd = patches.Rectangle(ll, width, height, color=ccd_color, fill=False)
        slide_origin = 3500
        slide_corners = np.array(
            [
                ((-50, slide_origin + 50)),  # top left
                (-50, pos),  # bottom left
                (2048 + 50, pos),  # bottom right
                (2048 + 50, slide_origin + 50),  # top right
            ]
        )
        slide = patches.Polygon(
            slide_corners, closed=False, alpha=0.8, color=slide_color
        )
        self.ax.clear()
        self.ax.add_patch(ccd)
        self.ax.add_patch(slide)
        self.ax.set_xlim(-80, 2048 + 80)
        self.ax.set_ylim(-200, slide_origin + 100)
        self.ax.set_aspect("equal")
        self.ax.set_axis_off()
        self.canvas.draw()

    def setExpertLevel(self):
        """
        Modifies widget according to expertise level, which in this
        case is just matter of hiding or revealing the LED option
        and changing the lower limit on the exposure button.
        """
        g = get_root(self).globals
        level = g.cpars["expert_level"]
        if level == 0:
            self.reset.grid_forget()
            self.enable.grid_forget()
            self.disable.grid_forget()
            self.restore.grid_forget()
            self.stop.grid_forget()
        else:
            self.stop.grid(row=2, column=0)
            self.disable.grid(row=2, column=1)
            self.enable.grid(row=2, column=2)
            self.reset.grid(row=3, column=0)
            self.restore.grid(row=3, column=1)

    @inlineCallbacks
    def action(self, *comm):
        """
        Send a command to the focal plane slide
        """
        session = get_root(self).globals.session
        if not session:
            self.print_message("no session")
            return

        if comm[0] == "block":
            topic = "hipercam.slide.rpc.stage.move"
            self.set_slide_target_position(BLOCK_POS)
            # allow time for statemachines to step forward
            # this means we state is updated to out of position before moving
            yield async_sleep(SLEEP_BEFORE_MOVE)
        elif comm[0] == "unblock":
            topic = "hipercam.slide.rpc.stage.move"
            self.set_slide_target_position(UNBLOCK_POS)
            yield async_sleep(SLEEP_BEFORE_MOVE)
        elif comm[0] == "goto":
            topic = "hipercam.slide.rpc.stage.move"
            self.set_slide_target_position(int(comm[1]))
            yield async_sleep(SLEEP_BEFORE_MOVE)
        else:
            topic = f"hipercam.slide.rpc.{comm[0]}"

        try:
            yield session.call(topic)
        except SerializationError:
            pass
        except Exception as err:
            g = get_root(self).globals
            msg = err.error_message() if hasattr(err, "error_message") else str(err)
            g.clog.warn("error in slide command:" + msg)

    def set_slide_target_position(self, pos):
        topic = "hipercam.slide.target_position"
        session = get_root(self).globals.session
        if session:
            session.publish(topic, pos)

    def send_message(self, topic, msg):
        session = get_root(self).globals.session
        if session:
            session.publish(topic, msg)

    def print_message(self, msg):
        self.label.delete(1.0, tk.END)
        self.label.insert(tk.END, msg + "\n")

    def on_telemetry(self, package_data):
        telemetry = pickle.loads(package_data)

        try:
            pos = telemetry["position"]["current"].value
            targ = telemetry["position"]["target"].value
        except Exception:
            pos = telemetry["position"]["current"]
            targ = telemetry["position"]["target"]

        state = telemetry["state"]
        if "error" in state["connection"] or "offline" in state["connection"]:
            self.connect.config(
                command=lambda: self.action("connection.connect"), text="conn"
            )
        else:
            self.connect.config(
                command=lambda: self.action("connection.disconnect"), text="disconn"
            )

        str = f"{telemetry['timestamp']}:\n"
        status = "/".join(state["stage"][4:])
        str += f"pos: curr={pos:.0f}, targ={targ:.0f}\n{status}\n\n"
        self.update_mimic(telemetry)
        self.print_message(str)
