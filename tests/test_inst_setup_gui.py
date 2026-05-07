#!/usr/bin/env python
"""
Interactive test for the ULTRACAM InstSetup and Observe panels.

Starts two dummy HTTP servers (camera on port 9980, data on port 9981) that
return valid ULTRACAM XML success responses for both GET and POST requests.
A small tkinter window shows both panels plus controls for:
  - switching expert level (0 = noddy, 1 = expert, 2 = super-expert)
  - toggling the servers on/off (to exercise the failure path)

The log output from clog/rlog is written to the console and to a scrolling
text widget in the window.

Run with::

    cd /Users/sl/code/python/github-packages/hcam_widgets
    conda activate py313
    python tests/test_inst_setup_gui.py
"""

from __future__ import print_function, unicode_literals

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import tkinter as tk
from tkinter import ttk
from twisted.internet import tksupport, reactor

from hcam_widgets.globals import Container
from hcam_widgets.ultracam.widgets import (
    InstSetup,
    Observe,
    InstPars,
    CountsFrame,
    RunPars,
)
from hcam_widgets.widgets import AstroFrame

# ---------------------------------------------------------------------------
# Dummy HTTP servers  (handle both GET and POST)
# ---------------------------------------------------------------------------

CAMERA_XML = (
    '<?xml version="1.0"?>'
    "<response>"
    "<source>Camera server</source>"
    '<status software="OK" camera="OK"/>'
    "</response>"
)

DATA_XML = (
    '<?xml version="1.0"?>'
    "<response>"
    "<source>Filesave data handler</source>"
    '<status software="OK"/>'
    "</response>"
)


def _make_handler(xml_body):
    """Return a request handler that replies with *xml_body* for GET and POST."""

    class _Handler(BaseHTTPRequestHandler):
        def _send_xml(self):
            body = xml_body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send_xml()

        def do_POST(self):
            # Consume the request body so the connection closes cleanly
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self._send_xml()

        def log_message(self, fmt, *args):  # silence access log noise
            pass

    return _Handler


def _start_server(port, xml_body):
    """Start an HTTPServer in a daemon thread; return the server object."""
    server = HTTPServer(("127.0.0.1", port), _make_handler(xml_body))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# Minimal logger that writes to console + an optional tk.Text widget
# ---------------------------------------------------------------------------


class _GuiLog:
    """Duck-typed logger with debug/info/warn/error methods."""

    def __init__(self, name, text_widget=None):
        self._log = logging.getLogger(name)
        self._text = text_widget

    def _write(self, level, msg):
        self._log.log(level, msg)
        if self._text is not None:
            self._text.configure(state="normal")
            self._text.insert(
                "end", "[{}] {}\n".format(logging.getLevelName(level), msg)
            )
            self._text.configure(state="disabled")
            self._text.see("end")

    def debug(self, msg):
        self._write(logging.DEBUG, msg)

    def info(self, msg):
        self._write(logging.INFO, msg)

    def warn(self, msg):
        self._write(logging.WARNING, msg)

    def error(self, msg):
        self._write(logging.ERROR, msg)


# ---------------------------------------------------------------------------
# Root window
# ---------------------------------------------------------------------------


class TestRoot(tk.Tk):
    """Root window that carries a ``globals`` Container on itself."""

    def __init__(self):
        super().__init__()
        self.title("ULTRACAM panel test")
        self.globals = Container()


# ---------------------------------------------------------------------------
# Build the UI
# ---------------------------------------------------------------------------


def build(root):
    g = root.globals

    # ---- configuration -------------------------------------------------------
    g.cpars = {
        "ucam_server_on": True,
        "http_camera_server": "http://127.0.0.1:9980/",
        "http_data_server": "http://127.0.0.1:9981/",
        "http_path_exec": "exec",
        "http_path_config": "config",
        "expert_level": 0,
        "generic_app": "ultracam.xml",
        "power_on_app": "appl1_pon_cfg.xml",
        "power_off_app": "appl2_pof_cfg.xml",
        "target": "",
        "filters": "",
        "prog_id": "",
        "pi": "",
        "observers": "",
        "run_type": "data",
        "telins_name": "NTT_CUBE",
    }

    # ---- log text widget -----------------------------------------------------
    log_frame = tk.LabelFrame(root, text="Log")
    log_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=6, pady=6)

    log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
    sb = tk.Scrollbar(log_frame, command=log_text.yview)
    log_text.configure(yscrollcommand=sb.set)
    log_text.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    g.clog = _GuiLog("clog", log_text)
    g.rlog = _GuiLog("rlog", log_text)

    # ---- Tabbed action panel (col 0) -----------------------------------------
    notebook = ttk.Notebook(root)
    notebook.grid(row=0, column=0, padx=6, pady=6, sticky="nw")

    setup = InstSetup(notebook)
    notebook.add(setup, text="Instrument setup")
    g.setup = setup

    observe = Observe(notebook)
    notebook.add(observe, text="Observing")
    g.observe = observe

    # ---- Instrument parameters panel (col 1) ---------------------------------
    ipars = InstPars(root)
    ipars.grid(row=0, column=1, padx=6, pady=6, sticky="n", rowspan=2)
    g.ipars = ipars

    # --- Run Parameters panel (col 1, row 2) -----------------------------------------
    rpars = RunPars(root)
    rpars.grid(row=2, column=1, padx=6, pady=6, sticky="n")
    g.rpars = rpars

    # ---- CountsFrame (col 0, row 1) --------------------------------------------------
    counts = CountsFrame(root)
    counts.grid(row=1, column=0, padx=6, pady=6, sticky="nw")
    g.count = counts
    counts.update()

    # ---- AstroFrame (col 0, row 2) --------------------------------------------------
    astro = AstroFrame(root)
    astro.grid(row=2, column=0, padx=6, pady=6, sticky="nw")
    g.astro = astro

    # ---- Menu bar ------------------------------------------------------------
    menubar = tk.Menu(root)
    root.config(menu=menubar)

    settings_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Settings", menu=settings_menu)

    def _set_level(lvl):
        g.cpars["expert_level"] = lvl
        setup.setExpertLevel()
        observe.setExpertLevel()
        ipars.setExpertLevel()
        g.clog.info("Expert level set to {}".format(lvl))

    level_var = tk.IntVar(value=0)
    for label, lvl in [("Noddy (0)", 0), ("Expert (1)", 1), ("Super-expert (2)", 2)]:
        settings_menu.add_radiobutton(
            label=label,
            variable=level_var,
            value=lvl,
            command=lambda l=lvl: _set_level(l),
        )

    settings_menu.add_separator()

    server_var = tk.BooleanVar(value=True)

    def _toggle_server():
        g.cpars["ucam_server_on"] = server_var.get()
        state = "ON" if g.cpars["ucam_server_on"] else "OFF"
        g.clog.info("ucam_server_on -> {}".format(state))

    settings_menu.add_checkbutton(
        label="Server on", variable=server_var, command=_toggle_server
    )

    root.columnconfigure(0, weight=0)
    root.columnconfigure(1, weight=0)
    root.columnconfigure(2, weight=0)
    root.rowconfigure(1, weight=1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(name)s %(levelname)s: %(message)s",
    )

    _start_server(9980, CAMERA_XML)
    _start_server(9981, DATA_XML)
    logging.info("Dummy servers started on ports 9980 (camera) and 9981 (data)")

    root = TestRoot()
    tksupport.install(root)
    build(root)
    reactor.run()


if __name__ == "__main__":
    main()
