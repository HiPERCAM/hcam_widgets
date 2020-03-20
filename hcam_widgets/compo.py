from __future__ import print_function, unicode_literals, absolute_import, division
import six

# non-standard imports
from astropy import units as u
from astropy.coordinates.matrix_utilities import rotation_matrix
from astropy.coordinates import CartesianRepresentation
from astropy.utils import lazyproperty
from scipy.interpolate import interp1d
import numpy as np
from matplotlib import path, transforms

# internal imports
from . import widgets as w
from .tkutils import get_root, addStyle

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk

flip_y = np.array([[1, 0, 0], [0, -1, 0], [0, 0, 1]])

# COMPO is only available on GTC, so these values are well-known
pixel_scale = 0.08086 * u.arcsec / u.pix
focal_plane_scale = 1.214 * u.arcsec / u.mm
MIRROR_SIZE = 300 * u.pix * pixel_scale / focal_plane_scale

# predicted position of pick-off pupil from FoV centre
# from Zeemax simulations
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
    return x_func(theta)*u.arcmin, y_func(theta)*u.arcmin


def focal_plane_to_sky(cartrep):
    return cartrep.transform(flip_y) * focal_plane_scale


class Chip:
    """
    Representing the Chip
    """
    NX = 2048 * u.pix * pixel_scale / focal_plane_scale
    NY = 1024 * u.pix * pixel_scale / focal_plane_scale

    @lazyproperty
    def vertices(self):
        return CartesianRepresentation(
            [-self.NX/2, self.NX/2, self.NX/2, -self.NX/2],
            [-self.NY/2, -self.NY/2, self.NY/2, self.NY/2],
            0*u.mm
        )

    def clip_shape(self, vertices):
        """
        Clip a shape defined as a CartesianRepresentation of points by the chip edges

        Works in 2D - i.e drops the z-axis - as this is a projected clipping

        Notes
        -----
        This makes use of Sutherland-Hodgman clipping as implemented in
        AGG 2.4 and exposed in Matplotlib.

        Parameters
        ----------
        vertices :  astropy.coordinates.CartesianRepresentation
            vertices of shape to be clipped

        Returns
        --------
        astropy.coordinates.CartesianRepresentation
            new vertices, after clipping
        """
        # enforce pixel space
        try:
            xyz = vertices.xyz.to(u.mm)
        except u.UnitConversionError:
            raise ValueError('vertices are not in units of physical length')

        # drop Z axis and reshape to (N, 2)
        xy = xyz[:2].T
        poly = path.Path(xy, closed=True)
        clip_rect = transforms.Bbox([[-self.NX.value/2, -self.NY.value/2],
                                    [self.NX.value/2, self.NY.value/2]])
        poly_clipped = poly.clip_to_bbox(clip_rect).to_polygons()[0]
        if np.all(poly_clipped[0] == poly_clipped[-1]):
            poly_clipped = poly_clipped[:-1]

        return CartesianRepresentation(*u.Quantity(poly_clipped, unit=u.mm).T, vertices.z)


class Baffle:
    """
    The Baffle present on both arms
    """
    BAFFLE_X = 36 * u.mm
    BAFFLE_Y = 44 * u.mm
    INJECTION_ROT = rotation_matrix(-INJECTOR_THETA, 'z')
    INJECTION_TRANS = CartesianRepresentation(57.5*u.mm, 23.2*u.mm, 0*u.mm)

    @lazyproperty
    def right_pickoff_vertices(self):
        """
        The vertices of the pickoff baffle when in place
        """
        vertices = CartesianRepresentation(
            [-self.BAFFLE_X/2, self.BAFFLE_X/2, self.BAFFLE_X/2, -self.BAFFLE_X/2],
            [-self.BAFFLE_Y/2, -self.BAFFLE_Y/2, self.BAFFLE_Y/2, self.BAFFLE_Y/2],
            0*u.mm
        )
        # rotate and translate
        vertices = vertices.transform(self.INJECTION_ROT) + self.INJECTION_TRANS

        # crop to chip
        c = Chip()
        return c.clip_shape(vertices)


class PickoffArm:

    @u.quantity_input(theta=u.deg)
    def position(self, theta):
        """
        Position of pupil stop centre in focal plane (mm)

        Uses approximate formula which agrees with Zeemax calculations inc distortion to 1pix
        """
        r = 270*u.mm
        x = r * np.sin(theta)
        y = r * (1 - np.cos(theta))
        # actually not in focal plane, but assuming it is is OK
        return CartesianRepresentation(x, y, 0*u.mm)


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
