from __future__ import print_function, unicode_literals, absolute_import, division
import importlib

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

# optional
try:
    from ginga import trcalc
    from ginga.util import wcs
    import ginga.canvas.types.all as ginga_types

    has_ginga = True
except Exception:
    has_ginga = False

try:
    from importlib import resources as importlib_resources
except Exception:
    # backport for Python 3.6
    import importlib_resources

flip = np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])

# COMPO is only available on GTC, so these values are well-known
pixel_scale = 0.08086 * u.arcsec / u.pix
focal_plane_scale = 1.214 * u.arcsec / u.mm
gtc_focalplane_equivalencies = [
    (u.mm, u.arcsec, lambda x: x * 1.214, lambda x: x / 1.214),
    (u.pix, u.arcsec, lambda x: x / 0.08086, lambda x: x * 0.08086),
    (u.mm, u.pix, lambda x: x * 1.214 / 0.08086, lambda x: x * 0.08086 / 1.214),
]

# predicted position of pick-off pupil from FoV centre
# from Zeemax simulations
THETA = u.Quantity([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65], unit=u.deg)
X = u.Quantity(
    [
        0.0,
        0.476,
        0.949,
        1.414,
        1.868,
        2.309,
        2.731,
        3.133,
        3.511,
        3.863,
        4.185,
        4.475,
        4.731,
        4.951,
    ],
    unit=u.arcmin,
)
Y = u.Quantity(
    [
        0.0,
        0.021,
        0.083,
        0.186,
        0.329,
        0.512,
        0.732,
        0.988,
        1.278,
        1.600,
        1.951,
        2.329,
        2.731,
        3.154,
    ],
    unit=u.arcmin,
)

# Vital statistics for COMPO (from FDR and commissioning)
PARK_POSITION = -66.4 * u.deg
MAX_ANGLE = 55 * u.deg
PICKOFF_SIZE = 26.73 * u.arcsec  # 330 pixels
MIRROR_SIZE = 24.3 * u.arcsec  # 20 mm
SHADOW_X = 40 * u.mm  # extent of vignetting by injector arm
SHADOW_Y = 49 * u.mm  # extent of vignetting by injector arm (~739 pix)
INJECTOR_THETA = 13.04 * u.deg  # angle of injector arm when in position
GUIDE_THETA = -66.4 * u.deg  # angle of injector arm when guiding
LENS_REF_POSITION = 0 * u.mm  # TODO: this is made up, replace with true value
NOMINAL_INJECTOR_ZERO = -0.1583 * u.deg  # value of stage encoder when arm centred
NOMINAL_PICKOFF_ZERO = 0.34 * u.deg  # value of stage encoder when arm centred
MAX_ANGLE = 67 * u.deg  # hard stops at (67.79, -67.55) for PO, (67.4, -67.8) for IA

# interpolated functions for X and Y positions - not unit aware
x_func = interp1d(THETA, X, kind="cubic", bounds_error=False, fill_value="extrapolate")
y_func = interp1d(THETA, Y, kind="cubic", bounds_error=False, fill_value="extrapolate")

# interpolated functions for lens offset
lens_data_file = (
    importlib_resources.files("hcam_widgets") / "data" / "compo_lens_offset.csv"
)

_, po_theta, lens_off = np.loadtxt(lens_data_file, delimiter=",", skiprows=1).T
_g = interp1d(po_theta, lens_off, bounds_error=False, fill_value="extrapolate")


@u.quantity_input(pickoff_theta=u.deg)
def target_lens_position(pickoff_theta, guiding=False):
    """
    Find the correct position for the corrector lens
    """
    # TODO: find correct value for guiding!
    offset = _g(abs(pickoff_theta.to_value(u.deg))) * u.mm
    return LENS_REF_POSITION + offset


@u.quantity_input(theta=u.deg)
def field_stop_centre(theta):
    """
    Where does the field stop of the injector arm fall in the focal plane?

    This is based on Zeemax simulations that include distortions
    and the curvature of the plane.
    """
    # make a simple float or numpy array
    theta = theta.to_value(u.deg)

    # flip the sign of the x-position if we have a -ve angle
    xmul = xmul = np.where(theta < 0, -1.0, 1.0)

    # interpolate
    theta = np.fabs(theta)
    return xmul * x_func(theta) * u.arcmin, y_func(theta) * u.arcmin


def focal_plane_units(unit):
    return unit in (u.deg, u.arcmin, u.arcsec, u.rad)


def focal_plane_to_sky(cartrep):
    """
    Convert physical position in focal plane to sky offset from FoV
    """
    cartrep = cartrep.transform(flip)
    with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
        return CartesianRepresentation(cartrep.xyz.to(u.arcsec))


@u.quantity_input(pickoff_angle=u.deg)
@u.quantity_input(injection_angle=u.deg)
def plot_compo(pickoff_angle, injection_angle, axis=None):
    if axis is None:
        fig, axis = plt.subplots()
    c = Chip().to_patches()
    poa = PickoffArm().to_patches(pickoff_angle)
    ia = InjectionArm().to_patches(injection_angle)
    # todo set colors with pc.set_array
    cmap = colors.ListedColormap(
        [
            "#BFD7EA",  # Chip (blue)
            "#59C9A5",  # POA arc
            "#56E39F",  # POA Baffle
            "#3A3042",  # POA FOV
            "#FF8C42",  # Inj Baffle
            "#3A3042",  # Inj Fov
        ]
    )
    pc = PatchCollection(c + poa + ia, alpha=0.8, cmap=cmap)
    pc.set_array(np.array([0, 1, 2, 3, 4, 5]))
    axis.add_collection(pc)
    axis.set_xlim(-300, 300)
    axis.set_ylim(-50, 150)
    axis.set_aspect("equal")
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
            [-self.NX / 2, self.NX / 2, self.NX / 2, -self.NX / 2],
            [-self.NY / 2, -self.NY / 2, self.NY / 2, self.NY / 2],
            0 * u.mm,
        )

    def to_patches(self, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            ll = ((-self.NX / 2).to_value(unit), (-self.NY / 2).to_value(unit))
            width = self.NX.to_value(unit)
            height = self.NY.to_value(unit)
            rect = patches.Rectangle(ll, width, height)
        return [rect]

    def contains(self, repr):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            x = repr.x.to(u.mm)
            y = repr.y.to(u.mm)
        inchip = False
        if (-self.NX / 2 < x < self.NX / 2) and (-self.NY / 2 < y < self.NY / 2):
            inchip = True
        return inchip

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
            raise ValueError("vertices are not in units of physical length")

        # drop Z axis and reshape to (N, 2)
        xy = xyz[:2].T
        poly = path.Path(xy, closed=True)
        clip_rect = transforms.Bbox(
            [
                [-self.NX.value / 2, -self.NY.value / 2],
                [self.NX.value / 2, self.NY.value / 2],
            ]
        )
        poly_clipped = poly.clip_to_bbox(clip_rect).to_polygons()[0]
        if np.all(poly_clipped[0] == poly_clipped[-1]):
            poly_clipped = poly_clipped[:-1]

        return CartesianRepresentation(
            *u.Quantity(poly_clipped, unit=u.mm).T, vertices.z
        )


class Baffle:
    """
    The Baffle present on both arms
    """

    BAFFLE_X = SHADOW_X
    BAFFLE_Y = SHADOW_Y
    INJECTION_ROTATION_RIGHT = rotation_matrix(-INJECTOR_THETA, "z")
    INJECTION_ROTATION_LEFT = rotation_matrix(INJECTOR_THETA, "z")
    INJECTION_TRANSLATION_RIGHT = CartesianRepresentation(
        57.5 * u.mm, 23.2 * u.mm, 0 * u.mm
    )
    INJECTION_TRANSLATION_LEFT = CartesianRepresentation(
        -57.5 * u.mm, 23.2 * u.mm, 0 * u.mm
    )

    @lazyproperty
    def vertices(self):
        return CartesianRepresentation(
            [
                -self.BAFFLE_X / 2,
                self.BAFFLE_X / 2,
                self.BAFFLE_X / 2,
                -self.BAFFLE_X / 2,
            ],
            [
                -self.BAFFLE_Y / 2,
                -self.BAFFLE_Y / 2,
                self.BAFFLE_Y / 2,
                self.BAFFLE_Y / 2,
            ],
            0 * u.mm,
        )


class InjectionArm:
    @u.quantity_input(theta=u.deg)
    def position(self, theta):
        """
        Position of pupil stop centre in focal plane (mm)

        Uses approximate formula which agrees with Zeemax calculations inc distortion to 1pix
        """
        r = 254.72 * u.mm  # length of injection arm
        off = 270 * u.mm  # dist from rotation axis to FoV centre
        d = off - r
        x = r * np.sin(-theta)
        y = d + r * (1 - np.cos(-theta))
        return CartesianRepresentation(x, y, 0 * u.mm)

    @u.quantity_input(theta=u.deg)
    def to_patches(self, theta, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            centre = self.position(theta)
            fov = patches.Circle(
                tuple(centre.xyz[:2].to_value(unit)),
                radius=MIRROR_SIZE.to_value(unit) / 2,
            )

            baffle_cart = Baffle().vertices
            baffle_cart = baffle_cart.transform(rotation_matrix(theta))
            baffle_cart += centre
            c = Chip()
            if c.contains(centre):
                baffle_cart = c.clip_shape(baffle_cart)
            baffle_xy = baffle_cart.xyz[:2].T.to_value(unit)
            baffle = patches.Polygon(baffle_xy, closed=True)

        return [baffle, fov]

    @u.quantity_input(theta=u.deg)
    @u.quantity_input(ra_cen=u.deg)
    @u.quantity_input(dec_cen=u.deg)
    def to_ginga_object(self, theta, ra_cen, dec_cen, **params):
        if not has_ginga:
            raise RuntimeError("ginga not installed, cannot create Ginga object")

        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            # centre w.r.t FoV
            centre = self.position(theta)

            # now Baffle
            baffle_cart = Baffle().vertices
            baffle_cart = baffle_cart.transform(rotation_matrix(theta))
            baffle_cart += centre
            c = Chip()
            if c.contains(centre):
                baffle_cart = c.clip_shape(baffle_cart)

            # convert to sky plane
            centre = focal_plane_to_sky(centre)
            baffle_cart = focal_plane_to_sky(baffle_cart)

            # add centre of pointing
            x, y = wcs.add_offset_radec(
                ra_cen.to_value(u.deg),
                dec_cen.to_value(u.deg),
                *centre.xyz[:2].to_value(u.deg)
            )
            fov = ginga_types.Circle(
                x, y, MIRROR_SIZE.to_value(u.deg) / 2, coord="wcs", **params
            )
            # add vignetting by baffle
            corners = [
                wcs.add_offset_radec(
                    ra_cen.to_value(u.deg),
                    dec_cen.to_value(u.deg),
                    *p.xyz[:2].to_value(u.deg)
                )
                for p in baffle_cart
            ]
            vignetting = ginga_types.Polygon(corners, coord="wcs", **params)
            return ginga_types.CompoundObject(vignetting, fov)


class PickoffArm:
    @u.quantity_input(theta=u.deg)
    def position(self, theta):
        """
        Position of pupil stop centre in focal plane (mm)

        Uses approximate formula which agrees with Zeemax calculations inc distortion to 1pix
        """
        r = 270 * u.mm
        # stage for pickoff arm rotates in opposite sense to coordinate axes
        x = r * np.sin(theta)
        y = r * (1 - np.cos(theta))
        # actually not in focal plane, but assuming it is is OK
        return CartesianRepresentation(x, y, 0 * u.mm)

    @u.quantity_input(theta=u.deg)
    def to_patches(self, theta, unit=u.mm):
        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            centre = self.position(theta)
            patrol_arc_centre = (0, (270 * u.mm).to_value(unit))
            radius = (270 * u.mm + 0.5 * MIRROR_SIZE).to_value(unit)
            arc = patches.Wedge(
                patrol_arc_centre,
                radius,
                # mpl, 0 is along x axis. COMPO, 0 is along -y
                PARK_POSITION.to_value(u.deg) - 90,
                MAX_ANGLE.to_value(u.deg) - 90,
                width=MIRROR_SIZE.to_value(unit),
            )
            pickoff = patches.Circle(
                tuple(centre.xyz[:2].to_value(unit)),
                radius=MIRROR_SIZE.to_value(unit) / 2,
            )
            baffle_cart = Baffle().vertices
            baffle_cart = baffle_cart.transform(rotation_matrix(-theta))
            baffle_cart += centre
            baffle_xy = baffle_cart.xyz[:2].T.to_value(unit)
            baffle = patches.Polygon(baffle_xy, closed=True)

        return [arc, baffle, pickoff]

    @u.quantity_input(theta=u.deg)
    @u.quantity_input(ra_cen=u.deg)
    @u.quantity_input(dec_cen=u.deg)
    def to_ginga_object(self, theta, ra_cen, dec_cen, **params):
        if not has_ginga:
            raise RuntimeError("ginga not installed, cannot create Ginga object")

        with u.set_enabled_equivalencies(gtc_focalplane_equivalencies):
            # centre w.r.t FoV
            centre = self.position(theta)

            # now Baffle
            baffle_cart = Baffle().vertices
            baffle_cart = baffle_cart.transform(rotation_matrix(-theta))
            baffle_cart += centre

            # convert to sky plane
            centre = focal_plane_to_sky(centre)
            baffle_cart = focal_plane_to_sky(baffle_cart)

            # create Pickoff circle
            x, y = wcs.add_offset_radec(
                ra_cen.to_value(u.deg),
                dec_cen.to_value(u.deg),
                *centre.xyz[:2].to_value(u.deg)
            )
            fov = ginga_types.Circle(
                x, y, MIRROR_SIZE.to_value(u.deg) / 2, coord="wcs", **params
            )
            # create vignetting by baffle
            corners = [
                wcs.add_offset_radec(
                    ra_cen.to_value(u.deg),
                    dec_cen.to_value(u.deg),
                    *p.xyz[:2].to_value(u.deg)
                )
                for p in baffle_cart
            ]
            vignetting = ginga_types.Polygon(corners, coord="wcs", **params)

            # TODO patrol arc.
            return ginga_types.CompoundObject(vignetting, fov)
