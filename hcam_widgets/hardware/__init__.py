# Licensed under a 3-clause BSD style license - see LICENSE.rst

# This sub-module is destined for common non-package specific utility
# functions that will ultimately be merged into `astropy.utils`

# As far as possible, utils contains classes of generic use, such as
# PosInt for positive integer input. See e.g. 'hcam' for more instrument
# dependent components.

from __future__ import print_function, unicode_literals, absolute_import, division
import six
import numpy as np
import pickle

from hcam_devices.devices.meerstetter import TEC_CURRENT_LIMIT
from hcam_widgets import widgets as w
from hcam_widgets.tkutils import get_root, addStyle
from .alarms import NoAlarmState

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk


class BoolFormatter(object):
    """
    A simple class to convert integer values to True/False strings.

    This class is a bit of a Kludge to make boolean values work nicely with the
    HardwareDisplayWidget, which was originally written with floating point numbers
    in mind. It provides one function, format, which converts 0 to 'ERROR' and 1 to
    'OK'.
    """
    def format(self, val):
        if val == 1:
            return 'OK'
        else:
            return 'ERROR'


class HardwareDisplayWidget(tk.Frame):
    """
    A widget that displays and checks the status of a piece of hardware.

    Consists of a label naming the piece of hardware, and an Ilabel to display the results of
    the hardware check.

    Has a telemetry topic and a callback to be used whenever a telemetry message is published
    to that topic. It is the responsibility of implementing widgets to subscribe to that
    topic with the correct callback.

    Each HardwareDisplayWidget has its own status (ok/nok) and an alarm state which can
    be NoAlarm, ActiveAlarm, AcknowledgedAlarm.

    Arguments
    ----------
    parent : tk.Widget
        parent widget
    kind : string
        type of hardware item, e.g. 'pressure'
    name : string
        name to display on label
    fmt : string
        format string for displaying results
    lower_limit : float, `~astropy.units.Quantity`
        lower limit for hardware check
    upper_limit : float, `~astropy.units.Quantity`
        upper limit for hardware check
    """
    def __init__(self, parent, topic, kind, name, lower_limit, upper_limit):
        tk.Frame.__init__(self, parent)
        self.parent = parent
        self.topic = topic
        self.name = name
        self.kind = kind
        self.ok = True
        self.fmt = '{:.1f}'
        self.upper_limit = upper_limit
        self.lower_limit = lower_limit
        self.set_state(NoAlarmState)
        tk.Label(self, text=self.name + ':', width=9, anchor=tk.E).pack(side=tk.LEFT, anchor=tk.N, padx=5)
        self.label = w.Ilabel(self, text='nan', width=9)
        self.label.pack(side=tk.LEFT, anchor=tk.N, padx=5)

    def on_telemetry(self, data):
        """
        Try and get the result of hardware update from the queue. If it's not ready yet,
        reschedule this check for 200ms later.
        """
        try:
            telemetry = pickle.loads(data)
            val, errmsg = self.process_telemetry(telemetry)
            g = get_root(self.parent).globals
            if errmsg is not None:
                g.clog.warn('Could not update {} for {}: {}'.format(self.kind, self.name, errmsg))

            self.label.configure(text=self.fmt.format(val), bg=g.COL['main'])

            if errmsg is None and val <= self.upper_limit and val >= self.lower_limit:
                self.ok = True
            elif not isinstance(val, str) and np.isnan(val) and errmsg is None:
                # no error and nan returned means checking disabled
                self.ok = True
            elif isinstance(val, str) and val == '??':
                # checking disabled
                self.ok = True
            else:
                self.ok = False

            if not self.ok:
                self.label.configure(bg=g.COL['warn'])
        except Exception as err:
            g = get_root(self.parent).globals
            g.clog.warn('could not process {} telemetry for {}: {}'.format(
                self.kind, self.name, str(err)
            ))

    def _extract_telemetry(self, attr, telemetry):
        if attr in telemetry:
            val = telemetry[attr]
            if hasattr(val, 'value'):
                val = val.value
            return val, None
        else:
            return np.nan, 'cannot parse telemetry'

    def process_telemetry(self):
        raise NotImplementedError('concrete class must implement process_telemetry')

    def acknowledge_alarm(self):
        self._state.acknowledge_alarm(self)

    def raise_alarm(self):
        self._state.raise_alarm(self)

    def cancel_alarm(self):
        self._state.cancel_alarm(self)

    def set_state(self, state):
        self._state = state


class MeerstetterWidget(HardwareDisplayWidget):
    """
    Get CCD info from Meerstetters
    """
    def __init__(self, parent, ccdnum, name, kind, lower_limit, upper_limit):
        meerstetter = 1 + ccdnum // 4
        topic = 'hipercam.meerstetter{}.telemetry'.format(meerstetter)
        HardwareDisplayWidget.__init__(self, parent, topic, kind, name,
                                       lower_limit, upper_limit)
        self.address = [1, 2, 3, 1, 2][ccdnum-1]
        if kind == 'peltier power':
            self.fmt = '{:.0f}'
        elif kind == 'status':
            self.fmt = '{:s}'

    def process_telemetry(self, telemetry):
        g = get_root(self.parent).globals
        if g.cpars['ccd_temp_monitoring_on']:
            if self.kind == 'status':
                return self._extract_telemetry('status{}'.format(self.address),
                                               telemetry)
            if self.kind == 'temperature':
                return self._extract_telemetry('temperature{}'.format(self.address),
                                               telemetry)
            elif self.kind == 'heatsink temperature':
                return self._extract_telemetry('heatsink{}'.format(self.address),
                                               telemetry)
            elif self.kind == 'peltier power':
                current, msg = self._extract_telemetry('current{}'.format(self.address),
                                                       telemetry)
                return 100 * current / TEC_CURRENT_LIMIT, None
            else:
                raise ValueError('unknown kind: {}'.format(self.kind))
        else:
            value = '??' if self.kind == 'status' else np.nan
            return value, None


class ChillerWidget(HardwareDisplayWidget):
    """
    Get Temperature from Chiller
    """
    def __init__(self, parent, lower_limit, upper_limit):
        topic = 'hipercam.chiller.telemetry'
        HardwareDisplayWidget.__init__(self, parent, topic, 'temperature', 'CHILLER',
                                       lower_limit, upper_limit)

    def process_telemetry(self, telemetry):
        g = get_root(self.parent).globals
        if g.cpars['chiller_temp_monitoring_on']:
            return self._extract_telemetry('temperature', telemetry)
        else:
            return np.nan, None


class RackSensorWidget(HardwareDisplayWidget):
    """
    Get Temperature and Humidity from Rack Sensor
    """
    def __init__(self, parent, lower_limit, upper_limit):
        topic = 'hipercam.gtc.telemetry'
        HardwareDisplayWidget.__init__(self, parent, topic, 'temperature', 'RACK',
                                       lower_limit, upper_limit)

    def process_telemetry(self, telemetry):
        g = get_root(self.parent).globals
        if g.cpars['chiller_temp_monitoring_on']:
            return self._extract_telemetry('rack_temp', telemetry)
        else:
            return np.nan, None


class FlowRateWidget(HardwareDisplayWidget):
    """
    Flow rates from honeywell
    """
    def __init__(self, parent, pen_number, name, lower_limit, upper_limit):
        topic = 'hipercam.flow.telemetry'
        HardwareDisplayWidget.__init__(self, parent, topic, 'flow rate', name,
                                       lower_limit, upper_limit)
        self.pen_number = pen_number
        self.fmt = '{:.2f}'

    def process_telemetry(self, telemetry):
        g = get_root(self.parent).globals
        if g.cpars['flow_monitoring_on']:
            attr = 'pen{}'.format(self.pen_number)
            return self._extract_telemetry(attr, telemetry)
        else:
            return np.nan, None


class VacuumWidget(HardwareDisplayWidget):
    """
    Vacuum pressure from gauge
    """
    def __init__(self, parent, ccdnum, name, lower_limit, upper_limit):
        topic = 'hipercam.pressure{}.telemetry'.format(ccdnum)
        HardwareDisplayWidget.__init__(self, parent, topic, 'pressure', name,
                                       lower_limit, upper_limit)
        self.fmt = '{:.2E}'

    def process_telemetry(self, telemetry):
        g = get_root(self.parent).globals
        if g.cpars['ccd_vac_monitoring_on']:
            val, msg = self._extract_telemetry('pressure', telemetry)
            return 1000*val, msg
        else:
            return np.nan, None


class FocalPlaneSlideWidget(HardwareDisplayWidget):
    """
    Focal plane Slide
    """
    def __init__(self, parent, name, lower_limit, upper_limit):
        topic = 'hipercam.slide.telemetry'
        HardwareDisplayWidget.__init__(self, parent, topic, 'position', name,
                                       lower_limit, upper_limit)
        self.fmt = '{:.0f}'

    def process_telemetry(self, telemetry):
        g = get_root(self).globals
        if g.cpars['focal_plane_slide_on']:
            position_dict, msg = self._extract_telemetry('position', telemetry)
            current = position_dict['current']
            if hasattr(current, 'value'):
                return position_dict['current'].value, msg
            else:
                return position_dict['current'], msg
        else:
            return np.nan, None


class CCDInfoWidget(tk.Toplevel):
    """
    A child window to monitor and show the status of the CCD heads.

    Keeps track of vacuum levels, CCD temperatures, flow rates etc. Normally this
    window is hidden, but can be revealed from the main GUIs menu. It will also
    appear automatically if there any issues, and should play a sound to notify
    users.
    """
    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent)
        self.transient(parent)
        self.parent = parent

        addStyle(self)
        self.title("CCD Head Status")

        # do not display on creation
        self.withdraw()

        # dont destroy when we click the close button
        self.protocol('WM_DELETE_WINDOW', self.withdraw)

        # create label frames
        self.status_frm = tk.LabelFrame(self, text='Meerstetter status', padx=4, pady=4)
        self.temp_frm = tk.LabelFrame(self, text='Temperatures (C)', padx=4, pady=4)
        self.heatsink_frm = tk.LabelFrame(self, text='Heatsink Temps (C)', padx=4, pady=4)
        self.peltier_frm = tk.LabelFrame(self, text='Peltier Powers (%)', padx=4, pady=4)
        self.flow_frm = tk.LabelFrame(self, text='Flow Rates (l/min)', padx=4, pady=4)
        self.vac_frm = tk.LabelFrame(self, text='Vacuums (mbar)', padx=4, pady=4)

        # variables to store hardware widgets
        g = get_root(self).globals
        self.ms_status = []
        self.ccd_temps = []
        self.heatsink_temps = []
        self.peltier_powers = []
        self.ccd_flow_rates = []
        self.vacuums = []
        if g.cpars['telins_name'].lower() == 'wht':
            self.chiller_temp = ChillerWidget(self.temp_frm, g.cpars['chiller_temp_lower'],
                                              g.cpars['chiller_temp_upper'])
        else:
            self.chiller_temp = RackSensorWidget(self.temp_frm, g.cpars['rack_temp_lower'],
                                                 g.cpars['rack_temp_upper'])

        self.ngc_flow_rate = FlowRateWidget(self.flow_frm, 6, 'NGC',
                                            g.cpars['ngc_flow_lower'], g.cpars['ngc_flow_upper'])

        # populate CCD frames
        for iccd in range(5):
            ccdnum = iccd+1
            name = 'CCD {}'.format(iccd+1)
            # meerstetter widgets
            self.ms_status.append(
                MeerstetterWidget(self.status_frm, ccdnum, name, 'status', 'run', 'run')
            )
            self.ccd_temps.append(
                MeerstetterWidget(self.temp_frm, ccdnum, name, 'temperature',
                                  g.cpars['ccd_temp_lower'],
                                  g.cpars['ccd_temp_upper'])
            )
            self.heatsink_temps.append(
                MeerstetterWidget(self.heatsink_frm, ccdnum, name, 'heatsink temperature',
                                  g.cpars['ccd_sink_temp_lower'],
                                  g.cpars['ccd_sink_temp_upper'])
            )
            self.peltier_powers.append(
                MeerstetterWidget(self.peltier_frm, ccdnum, name, 'peltier power',
                                  g.cpars['ccd_peltier_lower'],
                                  g.cpars['ccd_peltier_upper'])
            )

            # grid
            self.ms_status[-1].grid(
                    row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
                )
            self.ccd_temps[-1].grid(
                    row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
                )
            self.heatsink_temps[-1].grid(
                row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
            )
            self.peltier_powers[-1].grid(
                row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
            )

            # flow rates
            pen_number = iccd+1
            self.ccd_flow_rates.append(
                FlowRateWidget(self.flow_frm, pen_number, name,
                               g.cpars['ccd_flow_lower'], g.cpars['ccd_flow_upper'])
            )
            self.ccd_flow_rates[-1].grid(
                    row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
            )

            # vacuum gauges
            name = 'CCD {}'.format(iccd+1)
            self.vacuums.append(
                VacuumWidget(self.vac_frm, iccd+1, name, -1e6, 5e-3)
            )
            self.vacuums[-1].grid(
                    row=int(iccd/3), column=iccd % 3, padx=5, sticky=tk.W
            )

        # hidden slide widget (not displayed, but used for JSON output)
        self.fpslide = FocalPlaneSlideWidget(self, 'slide', -100, 4000)

        # now for one-off items
        self.chiller_temp.grid(row=1, column=2, padx=5, sticky=tk.W)
        self.ngc_flow_rate.grid(row=1, column=2, padx=5, sticky=tk.W)

        # grid frames
        self.status_frm.grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)
        self.temp_frm.grid(row=1, column=0, padx=4, pady=4, sticky=tk.W)
        self.heatsink_frm.grid(row=2, column=0, padx=4, pady=4, sticky=tk.W)
        self.peltier_frm.grid(row=3, column=0, padx=4, pady=4, sticky=tk.W)
        self.flow_frm.grid(row=4, column=0, padx=4, pady=4, sticky=tk.W)
        self.vac_frm.grid(row=5, column=0, padx=4, pady=4, sticky=tk.W)

        self.after_id = self.after(10000, self.raise_if_nok)

    def _getVal(self, widg):
        """
        Return value from widget if set, else return -99.
        """
        return -99 if widg.label['text'].lower() == 'nan' else float(widg.label['text'])

    def dumpJSON(self):
        """
        Encodes current hw data to JSON compatible dictionary
        """
        data = dict()
        for i in range(5):
            ccd = i+1
            data['ccd{}temp'.format(ccd)] = self._getVal(self.ccd_temps[i])
            data['ccd{}vac'.format(ccd)] = self._getVal(self.vacuums[i])
            data['ccd{}flow'.format(ccd)] = self._getVal(self.ccd_flow_rates[i])
        data['fpslide'] = self._getVal(self.fpslide)
        return data

    @property
    def ok(self):
        okl = [self.chiller_temp.ok, self.ngc_flow_rate.ok]
        okl += [ms_state.ok for ms_state in self.ms_status]
        okl += [ccd_temp.ok for ccd_temp in self.ccd_temps]
        okl += [vac.ok for vac in self.vacuums]
        okl += [flow.ok for flow in self.ccd_flow_rates]
        okl += [power.ok for power in self.peltier_powers]
        return all(okl)

    def raise_if_nok(self):
        widgets = [self.chiller_temp, self.ngc_flow_rate]
        widgets.extend(self.ccd_temps)
        widgets.extend(self.ms_status)
        widgets.extend(self.ccd_flow_rates)
        widgets.extend(self.peltier_powers)
        for widget in widgets:
            if not widget.ok:
                self.deiconify()
                widget.raise_alarm()

        self.after_id = self.after(10000, self.raise_if_nok)

    @property
    def telemetry_topics(self):
        widgets = [self.chiller_temp, self.ngc_flow_rate]
        widgets.extend(self.ccd_temps)
        widgets.extend(self.ms_status)
        widgets.extend(self.ccd_flow_rates)
        widgets.extend(self.peltier_powers)
        widgets.extend(self.heatsink_temps)
        widgets.extend(self.vacuums)
        widgets.append(self.fpslide)
        topics = [
            (widget.topic, widget.on_telemetry) for widget in widgets
        ]
        return topics
