import six
import pickle
import traceback
import itertools
from astropy import units as u
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from twisted.internet.defer import inlineCallbacks

# internal imports
from ..mimic import Mimic
from ..tkutils import addStyle, get_root
from .utils import (plot_compo, INJECTOR_THETA,
                    NOMINAL_PICKOFF_ZERO,
                    NOMINAL_INJECTOR_ZERO,
                    target_lens_position, PARK_POSITION)
from .. import widgets as w


if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk


class COMPOSetupFrame(tk.Frame):
    """
    This is a minimal frame that contains only the buttons for injection side and the pickoff
    angle button.
    """
    def __init__(self, master):

        tk.Frame.__init__(self, master)
        addStyle(self)

        # create control widgets
        tk.Label(self, text='Injection Position').grid(row=0, column=0, pady=4, padx=4, sticky=tk.W)
        self.injection_side = w.Radio(self, ('L', 'R', 'G', 'P'), 4, None, initial=1)
        self.injection_side.grid(row=0, column=1, pady=2, stick=tk.W)

        tk.Label(self, text='Pickoff Angle').grid(row=1, column=0, pady=4, padx=4, sticky=tk.W)
        self.pickoff_angle = w.RangedFloat(self, 0.0, -67, 67, None, False,
                                           allowzero=True, width=4)
        self.pickoff_angle.grid(row=1, column=1, pady=2, stick=tk.W)


class COMPOSetupWidget(tk.Toplevel):
    """
    A child window to setup the COMPO pickoff arms.

    This is a minimal frame that contains only the buttons for injection side and the pickoff
    angle button. It is primarily used for defining instrument setups.

    Normally this window is hidden, but can be revealed from the main GUIs menu
    or by clicking on a "use COMPO" widget in the main GUI.
    """
    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent)
        self.transient(parent)
        self.parent = parent

        addStyle(self)
        self.title("COMPO setup")
        # do not display on creation
        # self.withdraw()

        # dont destroy when we click the close button
        self.protocol('WM_DELETE_WINDOW', self.withdraw)

        self.setup_frame = COMPOSetupFrame(self)
        self.setup_frame.pack()

    def dumpJSON(self):
        """
        Encodes current COMPO setup data to JSON compatible dictionary
        """
        raise NotImplementedError

    def loadJSON(self, data):
        """
        Sets widget values from JSON data
        """
        raise NotImplementedError


class COMPOControlWidget(tk.Toplevel):
    """
    A child window to control the COMPO pickoff arms.

    This is a more advanced window that adds widgets to monitor the state of COMPO
    and allow user control of the hardware.

    Normally this window is hidden, but can be revealed from the main GUIs menu
    or by clicking on a "use COMPO" widget in the main GUI.
    """
    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent)
        self.transient(parent)
        self.parent = parent

        g = get_root(self).globals
        addStyle(self)
        self.title("COMPO setup")

        # do not display on creation
        self.withdraw()

        # dont destroy when we click the close button
        self.protocol('WM_DELETE_WINDOW', self.withdraw)

        # frames for sections
        left = tk.Frame(self)
        right = tk.Frame(self)

        self.setup_frame = COMPOSetupFrame(left)
        self.setup_frame.grid(row=1, column=0, columnspan=2, pady=2, sticky=tk.W)

        # buttons
        self.go = w.ActButton(left, width=12, callback=self.move, text='Move')
        self.conn = w.ActButton(left, width=12, callback=self.handle_connection, text='Connect')
        self.stop = w.ActButton(left, width=12, callback=self.stop_all, text='Stop')
        self.home = w.ActButton(left, width=12, callback=self.home_all, text='Home')

        self.conn.grid(row=2, column=0, pady=2, sticky=tk.E)
        self.home.grid(row=2, column=1, pady=2, sticky=tk.W)
        self.stop.grid(row=3, column=1, pady=2, sticky=tk.W)
        self.go.grid(row=3, column=0, pady=2, sticky=tk.E)

        # create status widgets
        status = tk.LabelFrame(left, text='status')
        status.grid(row=4, column=0, columnspan=2, pady=4, padx=4, sticky=tk.N)

        tk.Label(status, text='Injection Arm').grid(row=0, column=0, sticky=tk.W)
        self.injection_status = w.Ilabel(status, text='INIT', width=10, anchor=tk.W)
        self.injection_status.config(bg=g.COL['warn'])
        self.injection_status.grid(row=0, column=1, sticky=tk.W, pady=2, padx=2)

        tk.Label(status, text='Pickoff Arm').grid(row=1, column=0, sticky=tk.W)
        self.pickoff_status = w.Ilabel(status, text='INIT', width=10, anchor=tk.W)
        self.pickoff_status.config(bg=g.COL['warn'])
        self.pickoff_status.grid(row=1, column=1, sticky=tk.W, pady=2, padx=2)

        tk.Label(status, text='Lens Position').grid(row=2, column=0, sticky=tk.W)
        self.lens_status = w.Ilabel(status, text='INIT', width=10, anchor=tk.W)
        self.lens_status.config(bg=g.COL['warn'])
        self.lens_status.grid(row=2, column=1, sticky=tk.W, pady=2, padx=2)

        # telemetry
        tel_frame = tk.LabelFrame(right, text='telemetry')
        self.label = tk.Text(tel_frame, height=10, width=40, bg=g.COL['log'])
        self.label.configure(state=tk.NORMAL, font=g.ENTRY_FONT)
        self.label.pack(fill=tk.Y)
        tel_frame.grid(row=0, column=0, columnspan=1)

        # mimic
        mimic_width = 350
        Mimic.__init__(self, height=int(mimic_width/2.5), width=mimic_width)
        mimic_frame = tk.LabelFrame(right, text='mimic')
        self.canvas = FigureCanvasTkAgg(self.figure, mimic_frame)
        self.canvas.get_tk_widget().pack()
        mimic_frame.grid(row=1, column=0, padx=4, pady=4)

        left.pack(pady=2, side=tk.LEFT, fill=tk.Y)
        right.pack(pady=2, side=tk.LEFT, fill=tk.Y)

    @property
    def session(self):
        return get_root(self).globals.session

    @inlineCallbacks
    def handle_connection(self):
        if not self.session:
            self.print_message('no session')
            return

        rpc_templates = [
            'hipercam.compo_lens.rpc.connection.{}',
            'hipercam.compo_arms.rpc.connection.{}'
        ]
        if self.conn['text'].lower() == 'disconnect':
            rpcs = [template.format('disconnect') for template in rpc_templates]
            action = 'disconnect'
        else:
            rpcs = [template.format('connect') for template in rpc_templates]
            action = 'connect'
        try:
            for rpc in rpcs:
                yield self.session.call(rpc)
        except Exception as err:
            g = get_root(self).globals
            msg = err.error_message() if hasattr(err, 'error_message') else str(err)
            g.clog.warn(f"Failed to {action} to COMPO: {err}")

    @inlineCallbacks
    def home_stage(self, stage):
        if not self.session:
            self.print_message('no session')
            return
        if stage == 'lens':
            rpc = 'hipercam.compo_lens.rpc.stage.home'
        else:
            rpc = "hipercam.compo_arms.rpc.{}.home".format(stage)
        try:
            yield self.session.call(rpc)
        except Exception as err:
            g = get_root(self).globals
            msg = err.error_message() if hasattr(err, 'error_message') else str(err)
            g.clog.warn(f"Failed to home {stage} in COMPO: {err}")

    @inlineCallbacks
    def home_all(self):
        for stage in ('injection', 'pickoff', 'lens'):
            yield self.home_stage(stage)

    @inlineCallbacks
    def stop_all(self):
        if not self.session:
            self.print_message('no session')
            return
        try:
            for stage in ('injection', 'pickoff', 'lens'):
                rpc = "hipercam.compo_arms.rpc.{}.stop".format(stage)
                if stage == 'lens':
                    rpc = 'hipercam.compo_lens.rpc.stage.stop'

                yield self.session.call(rpc)
        except Exception as err:
            g = get_root(self).globals
            msg = err.error_message() if hasattr(err, 'error_message') else str(err)
            g.clog.warn(f"Failed to stop {stage} in COMPO: {err}")

    @inlineCallbacks
    def move(self):
        """
        Send commands to COMPO
        """
        if not self.session:
            self.print_message('no session')
            return

        if self.setup_frame.injection_side.value() == 'L':
            ia = INJECTOR_THETA + NOMINAL_INJECTOR_ZERO
        elif self.setup_frame.injection_side.value() == 'R':
            ia = -INJECTOR_THETA + NOMINAL_INJECTOR_ZERO
        else:
            ia = PARK_POSITION + NOMINAL_INJECTOR_ZERO

        poa = self.setup_frame.pickoff_angle.value() * u.deg 
        poa += NOMINAL_PICKOFF_ZERO

        lens = target_lens_position(
            self.setup_frame.pickoff_angle.value() * u.deg,
            False  # guiding
        ).to_value(u.mm)
        self.session.publish('hipercam.compo.target_pickoff_angle',
                             poa.to_value(u.deg))
        self.session.publish('hipercam.compo.target_injection_angle',
                             ia.to_value(u.deg))
        self.session.publish('hipercam.compo.target_lens_position', lens)
        try:
            yield self.session.call('hipercam.compo_arms.rpc.pickoff.move')
            yield self.session.call('hipercam.compo_arms.rpc.injection.move')
            yield self.session.call('hipercam.compo_lens.rpc.stage.move')
        except Exception as err:
            g = get_root(self).globals
            msg = err.error_message() if hasattr(err, 'error_message') else str(err)
            g.clog.warn(f"Failed to move stages in COMPO: {err}")

    def send_message(self, topic, msg):
        if self.session:
            self.session.publish(topic, msg)

    def print_message(self, msg):
        self.label.delete(1.0, tk.END)
        self.label.insert(tk.END, msg+'\n')

    def set_stage_status(self, stage, telemetry):
        if stage == 'lens':
            state = telemetry['state']['lens_state']['stage']
        else:
            state = telemetry['state']['arms_state'][stage]
        
        if stage == 'injection':
            widget = self.injection_status
        elif stage == 'pickoff':
            widget = self.pickoff_status
        elif stage == 'lens':
            widget = self.lens_status
        else:
            raise ValueError('unkown stage ' + stage)

        g = get_root(self).globals
        colours = {'inpos': g.COL['start'], 'moving': g.COL['warn'], 'stopped': g.COL['warn'],
                   'init': g.COL['warn'], 'homing': g.COL['warn']}
        matched_state = set(state).intersection(colours.keys())
        if not matched_state:
            print('unhandled state ' + '/'.join(state))
        elif len(matched_state) > 1:
            print('ambiguous state ' + '/'.join(state))
        else:
            state = matched_state.pop()
            c = colours[state]
            widget.config(text=state.upper(), bg=c)

    def update_mimic(self, telemetry):
        """
        Use incoming telemetry to update mimic
        """
        if not telemetry:
            return

        injection_angle, _ = self.get_stage_position(telemetry, 'injection_angle') * u.deg
        pickoff_angle, _ = self.get_stage_position(telemetry, 'pickoff_angle') * u.deg

        injection_angle -= NOMINAL_INJECTOR_ZERO
        pickoff_angle -= NOMINAL_PICKOFF_ZERO

        self.ax.clear()
        _ = plot_compo(pickoff_angle, injection_angle, self.ax)
        self.ax.set_xlim(-250, 250)
        self.ax.set_aspect('equal')
        self.ax.set_axis_off()
        self.canvas.draw()

    def get_stage_position(self, telemetry, pos_str):
        try:
            pos = telemetry[pos_str]['current'].value
        except AttributeError:
            pos = telemetry[pos_str]['current']

        try:
            targ = telemetry[pos_str]['target'].value
        except AttributeError:
            targ = telemetry[pos_str]['target']
        return pos, targ

    def on_telemetry(self, package_data):
        try:
            telemetry = pickle.loads(package_data)
            state = telemetry['state']

            # check for error status
            g = get_root(self).globals
            # extract connection states from telemetry state package
            # and join into one long list for both arms and lens
            connection_states = list(
                itertools.chain(*[s['connection'] for s in state.values()])
            )
            if 'error' in connection_states:
                self.lens_status.config(text='ERROR',
                                        bg=g.COL['critical'])
                self.pickoff_status.config(text='ERROR',
                                        bg=g.COL['critical'])
                self.injection_status.config(text='ERROR',
                                            bg=g.COL['critical'])
                self.conn.config(text='Connect')
            elif 'offline' in connection_states:
                self.lens_status.config(text='DISCONN',
                                        bg=g.COL['critical'])
                self.pickoff_status.config(text='DISCONN',
                                        bg=g.COL['critical'])
                self.injection_status.config(text='DISCONN',
                                            bg=g.COL['critical'])
                self.conn.config(text='Connect')
            else:
                self.conn.config(text='Disconnect')
                for stage in ('injection', 'pickoff', 'lens'):
                    self.set_stage_status(stage, telemetry)

            str = f"{telemetry['timestamp'].iso}:\n"
            for key, stage, pos_str in zip(
                    ('arms_state', 'arms_state', 'lens_state'),
                    ('injection', 'pickoff', 'stage'),
                    ('injection_angle', 'pickoff_angle', 'lens_position')):
                pos, targ = self.get_stage_position(telemetry, pos_str)

                status = '/'.join(state[key][stage][4:])
                str += f"{stage}: curr={pos:.2f}, targ={targ:.2f}\n{status}\n\n"

            self.print_message(str)
            self.update_mimic(telemetry)
        except Exception as err:
            print('error handling COMPO telemetry')
            print(traceback.format_exc())


    def dumpJSON(self):
        """
        Encodes current COMPO setup data to JSON compatible dictionary
        """
        raise NotImplementedError

    def loadJSON(self, data):
        """
        Sets widget values from JSON data
        """
        raise NotImplementedError
