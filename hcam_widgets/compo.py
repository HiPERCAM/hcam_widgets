# Information and utilities regarding COMPO
from __future__ import print_function, unicode_literals, absolute_import, division
import six

# non-standard imports
from astropy import units as u
from scipy.interpolate import interp1d
import numpy as np

# internal imports
from . import widgets as w
from .tkutils import get_root, addStyle

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk

# predicted position of pick-off pupil from FoV centre
THETA = u.Quantity([0, 5, 10, 15, 20, 25, 30,
                    35, 40, 45, 50, 55, 60, 65], unit=u.deg)
X = u.Quantity([0.0, 0.476, 0.949, 1.414, 1.868, 2.309, 2.731, 3.133,
                3.511, 3.863, 4.185, 4.475, 4.731, 4.951], unit=u.arcmin)
Y = u.Quantity([0.0, 0.021, 0.083, 0.186, 0.329, 0.512, 0.732, 0.988,
                1.278, 1.600, 1.951, 2.329, 2.731, 3.154], unit=u.arcmin)
PICKOFF_SIZE = 26.73*u.arcsec  # 330 pixels
MIRROR_SIZE = 24.3*u.arcsec  # 300 pixels
SHADOW_X = 39.285*u.arcsec  # 485 pix, extent of vignetting by injector arm
SHADOW_Y = 45.36*u.arcsec  # 560 pix, extent of vignetting by injector arm
INJECTOR_THETA = 13*u.deg  # angle of injector arm when in position

# interpolated functions for X and Y positions - not unit aware
x_func = interp1d(THETA, X, kind='cubic', bounds_error=False, fill_value='extrapolate')
y_func = interp1d(THETA, Y, kind='cubic', bounds_error=False, fill_value='extrapolate')


@u.quantity_input(theta=u.deg)
def field_stop_centre(theta):
    """
    Returns field stop centre X and Y positions

    This is used in preference to the interpolated functions above
    because it is unit-aware.
    """
    neg_mask = theta < 0*u.deg
    theta = np.fabs(theta.to(u.deg)).value
    x, y = u.Quantity(x_func(theta), unit=u.arcmin), u.Quantity(y_func(theta), unit=u.arcmin)
    x[neg_mask] *= -1
    return x, y


class COMPOSetupWidget(tk.Toplevel):
    """
    A child window to setup the COMPO pickoff arms.

    Normally this window is hidden, but can be revealed from the main GUIs menu
    or by clicking on a "use COMPO" widget in the main GUI.
    """
    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent)

        g = get_root(self).globals

        self.transient(parent)
        self.parent = parent

        addStyle(self)
        self.title("COMPO setup")
        # do not display on creation
        self.withdraw()

        # dont destroy when we click the close button
        self.protocol('WM_DELETE_WINDOW', self.withdraw)

        # create control widgets
        tk.Label(self, text='Injection Side').grid(row=0, column=0, pady=4, padx=4, sticky=tk.W)
        self.injection_side = w.Radio(self, ('L', 'R'), 3, None, initial=1)
        self.injection_side.grid(row=0, column=1, pady=2, stick=tk.W)

        tk.Label(self, text='Pickoff Angle').grid(row=1, column=0, pady=4, padx=4, sticky=tk.W)
        self.pickoff_angle = w.RangedFloat(self, 0.0, -80, 80, None, False,
                                           allowzero=True, width=4)
        self.pickoff_angle.grid(row=1, column=1, pady=2, stick=tk.W)

        # create status widgets
        status = tk.LabelFrame(self, text='status')
        status.grid(row=2, column=0, columnspan=2, pady=4, padx=4, sticky=tk.W)

        tk.Label(status, text='Injection Arm').grid(row=0, column=0, sticky=tk.W)
        self.injection_status = w.Ilabel(status, text='MOVING', width=10, anchor=tk.W)
        self.injection_status.config(bg=g.COL['warn'])
        self.injection_status.grid(row=0, column=1, sticky=tk.W, pady=2, padx=2)

        tk.Label(status, text='Pickoff Arm').grid(row=1, column=0, sticky=tk.W)
        self.pickoff_status = w.Ilabel(status, text='OK', width=10, anchor=tk.W)
        self.pickoff_status.config(bg=g.COL['start'])
        self.pickoff_status.grid(row=1, column=1, sticky=tk.W, pady=2, padx=2)

        tk.Label(status, text='Lens Position').grid(row=2, column=0, sticky=tk.W)
        self.lens_status = w.Ilabel(status, text='ERROR', width=10, anchor=tk.W)
        self.lens_status.config(bg=g.COL['critical'])
        self.lens_status.grid(row=2, column=1, sticky=tk.W, pady=2, padx=2)


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
