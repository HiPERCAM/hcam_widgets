===============================
hcam-widgets
===============================


.. image:: https://img.shields.io/pypi/v/hcam_widgets.svg
        :target: https://pypi.python.org/pypi/hcam_widgets

.. image:: https://img.shields.io/travis/StuartLittlefair/hcam_widgets.svg
        :target: https://travis-ci.org/StuartLittlefair/hcam_widgets

.. image:: https://readthedocs.org/projects/hcam-widgets/badge/?version=latest
        :target: https://hcam-widgets.readthedocs.io/en/latest/?badge=latest
        :alt: Documentation Status

.. image:: https://pyup.io/repos/github/StuartLittlefair/hcam_widgets/shield.svg
     :target: https://pyup.io/repos/github/StuartLittlefair/hcam_widgets/
     :alt: Updates


Tkinter Widgets for HiPerCAM tools

``hcam_widgets`` provides a set of TKinter widgets and utility functions for writing tools to
plan and carry out HiPERCAM observations. The idea is to create a lightweight and easily-installed
collection of common widgets. It is compatible with Python2 and Python3.

Installation
------------

The software is written as much as possible to make use of core Python components. It relies
on the third party library `astropy <http://astropy.org/>`_ for astronomical calculations.

Once you have installed astropy, install with the usual::

 pip install .

or if you don't have root access::

 pip install --user .

Optional package dependencies
-----------------------------

``hcam_widgets`` supports several other tools, such as the finding chart tool ``hfinder`` and the
instrument control GUI ``hdriver``. Most users will need no extra modules installed. However,
If you want to be able to run ``hdriver``, *and* you want full communication with the telescope
whilst running at the GTC, you need to install the CORBA implementation ``omniORBpy``.

Full install instructions are found at the omniORB project `homepage <http://omniorb.sourceforge.net/>`_.
Be sure to install both omniORB and omniORBpy. Also, the omniORBpy module and the lib64 variant must
both be in the ``PYTHONPATH``. Finally, communicating with the GTC requires the installation of
Interface Definition Language (IDL) files, and the python modules compiled from them. Contact S. Littlefair
for these files, which must also be in the ``PYTHONPATH``.

* Free software: MIT license



