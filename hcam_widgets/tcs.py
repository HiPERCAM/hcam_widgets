# TCS access routines
from __future__ import print_function, unicode_literals, absolute_import, division
import subprocess
import warnings
import re
from astropy import coordinates as coord
from astropy import units as u

try:
    # should not be a required module since can run on WHT fine without it
    from .gtc.corba import get_telescope_server
    has_corba = True
except Exception as err:
    has_corba = False


def getWhtTcs():
    cmd = "ssh whtguest@taurus.ing.iac.es "
    cmd += "setenv LD_LIBRARY_PATH /wht/release/Ubuntu1404-64/lib; "
    cmd += "/wht/release/Ubuntu1404-64/bin/ParameterNoticeBoardLister | grep TCS"
    try:
        results = subprocess.check_output(cmd.split(), timeout=10).decode().split('\n')
    except subprocess.TimeoutExpired:
        raise IOError('Checking TCS info timed out')

    tcs_data = dict()
    pattern = 'TCS\.(\w*) -> (\w*) (.*)'
    for result in results:
        if not result.startswith('TCS.'):
            continue

        match = re.match(pattern, result)
        if match is None:
            warnings.warn('no match for {}'.format(result))
            continue

        name, _, value = match.groups()
        value = value.replace('{', '').replace('}', '')
        # convert anything we can to a float
        try:
            value = float(value)
        except ValueError:
            pass
        tcs_data[name] = value

    coo = coord.SkyCoord(tcs_data['RAHHMMSS'] + ' ' + tcs_data['DECDDMMSS'],
                         unit=(u.hour, u.deg))
    ra = coo.ra.deg
    dec = coo.dec.deg
    pa = tcs_data['skyPa']
    focus = tcs_data['focus']
    return ra, dec, pa, focus


def getGtcTcs():
    if not has_corba:
        raise IOError('CORBA not installed')

    server = get_telescope_server()

    # can now use as standard python object, e.g
    pars = server.getTelescopeParams()

    # pars is a list of strings describing tel info in FITS
    # style, each entry in the list is a different class of
    # thing (weather, telescope, instrument etc).

    # munge them all together into one list of entries
    # do some horrible munging to find PA
    pars = [val.strip() for val in (';').join(pars).split(';') if val.strip() != '']
    pa_entries = [par for par in pars if par.startswith('INSTRPA')]
    if len(pa_entries):
        _, value, _ = filter(None, re.split("[=/]+", pa_entries[0]))
        pa = float(value)
    else:
        pa = -999
    ra = server.getRightAscention()
    dec = server.getDeclination()
    focus = server.getFocus()

    # format is "keyword = value \ comment; keyword = value \ comment; ..."
    return ra, dec, pa, focus
