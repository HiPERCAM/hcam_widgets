from __future__ import print_function, unicode_literals, absolute_import, division
import six
import pkg_resources

# non-standard imports
from astropy import units as u
from astropy.coordinates.matrix_utilities import rotation_matrix
from astropy.coordinates import CartesianRepresentation
from astropy.utils import lazyproperty
from scipy.interpolate import interp1d
import numpy as np
from matplotlib import pyplot as plt
from matplotlib import path, transforms, patches, colors
from matplotlib.collections import PatchCollection

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
gtc_focalplane_equivalencies = [
    (u.mm, u.arcsec, lambda x: x*1.214, lambda x: x/1.214),
    (u.pix, u.arcsec, lambda x: x/0.08086, lambda x: x*0.08086),
    (u.mm, u.pix, lambda x: x*1.214/0.08086, lambda x: x*0.08086/1.214)
]

# predicted position of pick-off pupil from FoV centre
# from Zeemax simulations
THETA = u.Quantity([0, 5, 10, 15, 20, 25, 30,
                    35, 40, 45, 50, 55, 60, 65], unit=u.deg)
X = u.Quantity([0.0, 0.476, 0.949, 1.414, 1.868, 2.309, 2.731, 3.133,
                3.511, 3.863, 4.185, 4.475, 4.731, 4.951], unit=u.arcmin)
Y = u.Quantity([0.0, 0.021, 0.083, 0.186, 0.329, 0.512, 0.732, 0.988,
                1.278, 1.600, 1.951, 2.329, 2.731, 3.154], unit=u.arcmin)

# Vital statistics from FDR
PARK_POSITION = -60*u.deg
MAX_ANGLE = 55*u.deg
PICKOFF_SIZE = 26.73*u.arcsec  # 330 pixels
MIRROR_SIZE = 24.3*u.arcsec  # 20 mm
SHADOW_X = 40*u.mm  # extent of vignetting by injector arm
SHADOW_Y = 49*u.mm  # extent of vignetting by injector arm (~739 pix)
INJECTOR_THETA = 13.04*u.deg  # angle of injector arm when in position
LENS_REF_POSITION = 20 * u.mm  # TODO: this is made up, replace with true value

# interpolated functions for X and Y positions - not unit aware
x_func = interp1d(THETA, X, kind='cubic', bounds_error=False, fill_value='extrapolate')
y_func = interp1d(THETA, Y, kind='cubic', bounds_error=False, fill_value='extrapolate')

# interpolated functions for lens offset
lens_data_file = pkg_resources.resource_filename('hcam_widgets', 'data/compo_lens_offset.csv')
_, po_theta, lens_off = np.loadtxt(lens_data_file, delimiter=',', skiprows=1).T
_g = interp1d(po_theta, lens_off, bounds_error=False, fill_value='extrapolate')


@u.quantity_input(pickoff_theta=u.deg)
def target_lens_position(pickoff_theta, guiding=False):
    """
    Find the correct position for the corrector lens
    """
    offset = _g(abs(pickoff_theta.to_value(u.deg))) * u.mm
    return LENS_REF_POSITION + offset


@u.quantity_input(theta=u.deg)
def field_stop_centre(theta):
    """
    Where does the field stop of the injector arm fall in the focal plane?

    This is based on Zeemax simulations that include distortions
    and the curvature of the plane.
    """
    theta = theta.to_value(u.deg)
    return x_func(theta)*u.arcmin, y_func(theta)*u.arcmin


def focal_plane_units(unit):
    return unit in (u.deg, u.arcmin, u.arcsec, u.rad)


def focal_plane_to_sky(cartrep):
    """
    Convert physical position in focal plane to sky offset from FoV
    """
    cartrep = cartrep.transform(flip_y)
    with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
        return CartesianRepresentation(cartrep.xyz.to(u.arcsec))


@u.quantity_input(pickoff_angle=u.deg)
def plot_compo(pickoff_angle, injection_side, axis=None):
    if axis is None:
        fig, axis = plt.subplots()
    c = Chip().to_patches()
    poa = PickoffArm().to_patches(pickoff_angle)
    ia = InjectionArm(injection_side).to_patches()
    # todo set colors with pc.set_array
    cmap = colors.ListedColormap(
        [
            '#BFD7EA',  # Chip (blue)
            '#59C9A5',  # POA arc
            '#56E39F',  # POA Baffle
            '#3A3042',  # POA FOV
            '#FF8C42',  # Inj Baffle
            '#3A3042',  # Inj Fov
        ]
    )
    pc = PatchCollection(c+poa+ia, alpha=0.8, cmap=cmap)
    pc.set_array(np.array([0, 1, 2, 3, 4, 5]))
    axis.add_collection(pc)
    axis.set_xlim(-300, 300)
    axis.set_ylim(-50, 150)
    axis.set_aspect('equal')
    return axis


class Chip:
    """
    Representing the Chip
    """
    with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
        NX = (2048 * u.pix).to(u.mm)
        NY = (1024 * u.pix).to(u.mm)

    @lazyproperty
    def vertices(self):
        return CartesianRepresentation(
            [-self.NX/2, self.NX/2, self.NX/2, -self.NX/2],
            [-self.NY/2, -self.NY/2, self.NY/2, self.NY/2],
            0*u.mm
        )

    def to_patches(self, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            ll = ((-self.NX/2).to_value(unit), (-self.NY/2).to_value(unit))
            width = self.NX.to_value(unit)
            height = self.NY.to_value(unit)
            rect = patches.Rectangle(ll, width, height)
        return [rect]

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
            with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
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
    BAFFLE_X = SHADOW_X
    BAFFLE_Y = SHADOW_Y
    INJECTION_ROTATION_RIGHT = rotation_matrix(-INJECTOR_THETA, 'z')
    INJECTION_ROTATION_LEFT = rotation_matrix(INJECTOR_THETA, 'z')
    INJECTION_TRANSLATION_RIGHT = CartesianRepresentation(57.5*u.mm, 23.2*u.mm, 0*u.mm)
    INJECTION_TRANSLATION_LEFT = CartesianRepresentation(-57.5*u.mm, 23.2*u.mm, 0*u.mm)

    @lazyproperty
    def vertices(self):
        return CartesianRepresentation(
            [-self.BAFFLE_X/2, self.BAFFLE_X/2, self.BAFFLE_X/2, -self.BAFFLE_X/2],
            [-self.BAFFLE_Y/2, -self.BAFFLE_Y/2, self.BAFFLE_Y/2, self.BAFFLE_Y/2],
            0*u.mm
        )

    @lazyproperty
    def right_injection_vertices(self):
        """
        The vertices of the injection baffle when in place
        """
        v = self.vertices
        # rotate and translate
        v = v.transform(self.INJECTION_ROTATION_RIGHT) + self.INJECTION_TRANSLATION_RIGHT

        # crop to chip
        c = Chip()
        return c.clip_shape(v)

    @lazyproperty
    def left_injection_vertices(self):
        """
        The vertices of the injection baffle when in place
        """
        v = self.vertices
        # rotate and translate
        v = v.transform(self.INJECTION_ROTATION_LEFT) + self.INJECTION_TRANSLATION_LEFT

        # crop to chip
        c = Chip()
        return c.clip_shape(v)


class InjectionArm:

    def __init__(self, side):
        self.b = Baffle()
        self.side = side

    @property
    def side(self):
        return self._side

    @side.setter
    def side(self, value):
        if value.lower() not in ('left', 'right', 'guide'):
            raise ValueError('side must be left or right')
        self._side = value

    @property
    def position(self):
        """
        Position of field stop centre for injection arm
        """
        val = self.b.INJECTION_TRANSLATION_RIGHT
        if self.side == 'left':
            val = self.b.INJECTION_TRANSLATION_LEFT
        elif self.side == 'guide':
            theta = PARK_POSITION
            r = 254.72 * u.mm  # length of injection arm
            off = 270 * u.mm  # dist from rotation axis to FoV centre
            d = off - r
            x = r * np.sin(theta)
            y = d + r * (1-np.cos(theta))
            val = CartesianRepresentation(x, y, 0*u.mm)
        return val

    def to_patches(self, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            centre = self.position
            fov = patches.Circle(
                tuple(centre.xyz[:2].to_value(unit)),
                radius=MIRROR_SIZE.to_value(unit)/2
            )
            if self.side != 'guide':
                v = self.b.left_injection_vertices if self.side == 'left' else self.b.right_injection_vertices
                v = v.xyz[:2].T.to_value(unit)
                baffle = patches.Polygon(v, closed=True)
            else:
                baffle_cart = Baffle().vertices
                baffle_cart = baffle_cart.transform(rotation_matrix(-PARK_POSITION))
                baffle_cart += centre
                baffle_xy = baffle_cart.xyz[:2].T.to_value(unit)
                baffle = patches.Polygon(baffle_xy, closed=True)
            return [baffle, fov]


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

    @u.quantity_input(theta=u.deg)
    def to_patches(self, theta, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            centre = self.position(theta)
            patrol_arc_centre = (0, (270*u.mm).to_value(unit))
            radius = (270*u.mm + 0.5*MIRROR_SIZE).to_value(unit)
            arc = patches.Wedge(
                patrol_arc_centre, radius,
                # mpl, 0 is along x axis. COMPO, 0 is along -y
                PARK_POSITION.to_value(u.deg) - 90, MAX_ANGLE.to_value(u.deg) - 90,
                width=MIRROR_SIZE.to_value(unit)
            )
            pickoff = patches.Circle(
                tuple(centre.xyz[:2].to_value(unit)),
                radius=MIRROR_SIZE.to_value(unit)/2
            )
            baffle_cart = Baffle().vertices
            baffle_cart = baffle_cart.transform(rotation_matrix(-theta))
            baffle_cart += centre
            baffle_xy = baffle_cart.xyz[:2].T.to_value(unit)
            baffle = patches.Polygon(baffle_xy, closed=True)

        return [arc, baffle, pickoff]


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
