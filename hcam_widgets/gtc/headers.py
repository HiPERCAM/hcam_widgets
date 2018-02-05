# deal with headers from GTC
from __future__ import print_function, unicode_literals, absolute_import, division
import warnings
import re

from astropy.io import fits


def yield_three(iterable):
    """
    From some iterable, return three items, bundling all extras into last one.
    """
    return iterable[0], iterable[1], iterable[2:]


def parse_hstring(hs):
    """
    Parse a single item from the telescope server into name, value, comment.
    """
    # split the string on = and /, also stripping whitespace and annoying quotes
    name, value, comment = yield_three(
        [val.strip().strip("'") for val in filter(None, re.split("[=/]+", hs))]
    )

    # if comment has a slash in it, put it back together
    try:
        len(comment)
    except:
        pass
    else:
        comment = '/'.join(comment)
    return name, value, comment


def create_header_from_telpars(telpars):
    """
    Create a list of fits header items from GTC telescope pars.

    The GTC telescope server gives a list of string describing
    FITS header items such as RA, DEC, etc.
    """
    # pars is a list of strings describing tel info in FITS
    # style, each entry in the list is a different class of
    # thing (weather, telescope, instrument etc).

    # first, we munge it into a single list of strings, each one
    # describing a single item whilst also stripping whitespace
    pars = [val.strip() for val in (';').join(telpars).split(';')
            if val.strip() != '']

    # apply parse_hstring to everything in pars
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', fits.verify.VerifyWarning)
        hdr = fits.Header(map(parse_hstring, pars))

    return hdr
