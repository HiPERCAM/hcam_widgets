# miscellaneous shared utilities
from __future__ import print_function, unicode_literals, absolute_import, division

import sys
import threading
import traceback

from six.moves import urllib
import six

from twisted.internet import reactor
from twisted.internet.task import deferLater

def async_sleep(secs):
    return deferLater(reactor, secs, lambda: None)

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
