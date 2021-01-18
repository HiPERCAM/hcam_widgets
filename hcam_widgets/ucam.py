#!/usr/bin/env python
"""
ucam provides classes and data specific to ULTRACAM
"""
from __future__ import print_function, absolute_import, unicode_literals, division
import six
import math

# internal imports
from . import widgets as w
from .tkutils import get_root

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk


# Timing, gain, noise parameters
# gains in electrons per count
GAIN_FAST = 1.4
GAIN_SLOW = 1.3
GAIN_TURBO = 1.5

# readout noise in electrons for 1x1, 2x2, 4x4, 8x8
READ_NOISE_TURBO = [7.0, 7.0, 7.0, 7.0]
READ_NOISE_FAST = [4.9, 4.9, 5.1, 6.4]
READ_NOISE_SLOW = [3.6, 3.6, 4.0, 5.4]
DARK_COUNT = 0.1  # counts/sec/pixel

# timing parameters in microseconds
INVERSION_DELAY = 110.
VCLOCK_FRAME = 23.3
VCLOCK_STORAGE = 23.3
HCLOCK = 0.48
CDS_TIME_FDD = 1.84
CDS_TIME_FBB = 4.4
CDS_TIME_CDD = 10.
SWITCH_TIME = 1.2


class InstPars(tk.LabelFrame):
    """
    Ultracam instrument parameters block.
    """

    def __init__(self, master):
        tk.LabelFrame.__init__(self, master, text='Instrument setup', padx=10, pady=10)

        # left hand side
        lhs = tk.Frame(self)
        # Application (mode)
        tk.Label(lhs, text='Mode').grid(row=0, column=0, sticky=tk.W)
        self.app = w.Radio(lhs, ('FF', 'Wins', 'Drift'), 3, self.check,
                           ('FullFrame', 'Windows', 'Drift'))
        self.app.grid(row=0, column=1, sticky=tk.W)

        # Clear enabled
        self.clearLab = tk.Label(lhs, text='Clear')
        self.clearLab.grid(row=1, column=0, sticky=tk.W)
        self.clear = w.OnOff(lhs, True, self.check)
        self.clear.grid(row=1, column=1, sticky=tk.W)

        # o/scan enabled
        self.oscanLab = tk.Label(lhs, text='O/Scan')
        self.oscanLab.grid(row=2, column=0, sticky=tk.W)
        self.oscan = w.OnOff(lhs, False, self.check)
        self.oscan.grid(row=2, column=1, sticky=tk.W)

        # Readout speed
        tk.Label(lhs, text='Readout speed').grid(row=3, column=0, sticky=tk.NW)
        self.readSpeed = w.Radio(lhs, ('Slow', 'Fast', 'Turbo'), 1,
                                 self.check, ('Slow', 'Fast', 'Turbo'))
        self.readSpeed.grid(row=3, column=1, pady=2, sticky=tk.W)

        # Exposure delay
        tk.Label(lhs, text='Exp. delay (ms)').grid(row=4, column=0,
                                                   sticky=tk.W)
        # exposure delay
        self.expose = w.PosInt(lhs, 0, None, True, width=6)
        self.expose.grid(row=4, column=1, columnspan=5, sticky=tk.W, pady=5)

        # Right-hand side: the window parameters
        rhs = tk.Frame(self)
        # window parameters
        xsl = (100, 100, 100)
        xslmin = (1, 1, 1)
        xslmax = (512, 512, 512)
        xsr = (600, 600, 600)
        xsrmin = (513, 513, 513)
        xsrmax = (1024, 1024, 1024)
        ys = (1, 201, 401)
        ysmin = (1, 1, 1)
        ysmax = (1024, 1024, 1024)
        nx = (50, 50, 50)
        ny = (50, 50, 50)
        xbfac = (1, 2, 3, 4, 5, 6, 8)
        ybfac = (1, 2, 3, 4, 5, 6, 8)
        self.wframe = w.WinPairs(rhs, xsl, xslmin, xslmax, xsr, xsrmin,
                                 xsrmax, ys, ysmin, ysmax, nx, ny,
                                 xbfac, ybfac, self.check, hcam=False)
        self.wframe.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=5)

        # Pack two halfs
        lhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)
        rhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)

        self.check()

    @property
    def isFF(self):
        return self.app.value() == 'FullFrame'

    @property
    def isDriftMode(self):
        return self.app.value() == 'Drift'

    def check(self, *args):
        """
        Checks the validity of the parameters.
        """
        g = get_root(self).globals

        status = True
        if self.isDriftMode:
            self.wframe.npair.set(1)

        if self.isFF:
            self.wframe.disable()
        else:
            self.wframe.enable()

        # can only have overscan with FF mode
        if self.oscan() and not self.isFF:
            g.clog.error('can only enable overscan in FF mode')
            status = False
            self.oscan.set(False)

        if self.app.value == "Windows" and self.wframe.npair.value() > 1 and self.clear():
            g.clog.error('clear mode only allowed with 1 pair')
            status = False
            self.clear.set(False)

        if status and hasattr(g, 'count'):
            # if valid, update timing and SN info
            if hasattr(g.count, 'update'):
                g.count.update()
            else:
                print('no count update')

        # check windows
        return self.wframe.check() and status

    def timing(self):
        """
        Estimates timing information for the current setup. You should
        run a check on the instrument parameters before calling this.

        Returns: (expTime, deadTime, cycleTime, dutyCycle)

        expTime   : exposure time per frame (seconds)
        deadTime  : dead time per frame (seconds)
        cycleTime : sampling time (cadence), (seconds)
        dutyCycle : percentage time exposing.
        frameRate : number of frames per second
        """
        # video timing
        readSpeed = self.readSpeed.value()
        if readSpeed == 'Fast':
            cdsTime = CDS_TIME_FBB
        elif readSpeed == 'Turbo':
            cdsTime = CDS_TIME_FDD
        elif readSpeed == 'Slow':
            cdsTime = CDS_TIME_CDD
        else:
            raise RuntimeError('unknown read speed')
        video = cdsTime + SWITCH_TIME

        # exposure delay in microsecs
        expose = self.expose.value() * 1000

        # binning values
        xbin = self.wframe.xbin.value()
        ybin = self.wframe.ybin.value()

        # check all the mode cases
        if self.isFF and not self.oscan():
            frameTransfer = 1033*VCLOCK_FRAME
            readout = (VCLOCK_STORAGE*ybin + 536*HCLOCK + (512/xbin+2)*video)*(1024/ybin)
            if self.clear():
                clearTime = (1033 + 1027)*VCLOCK_STORAGE
                cycleTime = (INVERSION_DELAY + expose + clearTime + frameTransfer + readout)/1.e6
                exposureTime = expose/1e6
            else:
                cycleTime = (INVERSION_DELAY + expose + frameTransfer + readout)/1.e6
                exposureTime = cycleTime - frameTransfer/1.0e6
            readout /= 1.0e6

        elif self.isFF and self.oscan():
            clearTime = (1033 + 1032) * VCLOCK_FRAME
            frameTransfer = 1033*VCLOCK_FRAME
            readout = (VCLOCK_STORAGE*ybin + 540*HCLOCK + ((540/xbin)+2)*video)*(1032/ybin)
            cycleTime = (INVERSION_DELAY + expose + clearTime + frameTransfer + readout)/1.e6
            exposureTime = expose/1e6
            readout /= 1.e6

        elif self.isDriftMode:
            xsl, xsr, ys, nx, ny = self.wframe.params(0)
            # number of windows stacked in storage
            nwins = int(0.5*(1.0 + 1033/ny))
            # pipe shift
            pshift = int(1033 - (2*nwins-1)*ny)

            frameTransfer = (ny + ys - 1)*VCLOCK_FRAME
            diffshift = abs(xsl - 1 - (1034-xsr-nx+1))

            if xsl - 1 > 1024 - xsr - nx + 1:
                numHclocks = nx + diffshift + (1024 - xsr - nx + 1) + 8
            else:
                numHclocks = nx + diffshift + (xsl - 1) + 8
            lineread = VCLOCK_STORAGE*ybin + numHclocks*HCLOCK + (nx/xbin+2)*video
            read = lineread * ny/ybin

            cycleTime = (INVERSION_DELAY + pshift*VCLOCK_STORAGE +
                         expose + frameTransfer + read)/1.e6
            exposureTime = cycleTime - frameTransfer/1.e6
            readout = (read + pshift*VCLOCK_STORAGE)/1.e6
        else:
            # windowed mode
            clearTime = (1033 + 1027)*VCLOCK_STORAGE if self.clear() else 0
            frameTransfer = 1033.*VCLOCK_FRAME
            cycleTime = INVERSION_DELAY + expose + frameTransfer + clearTime
            readout = 0.0
            # loop over all pairs
            for i in range(self.wframe.npair.value()):
                xsl, xsr, ys, nx, ny = self.wframe.params(i)

                # y params of previous window
                if i > 0:
                    ystart_m = self.wframe.ys[i-1].value()
                    ny_m = self.wframe.ny[i-1].value()
                else:
                    ystart_m = 1
                    ny_m = 0

                # Time taken to shift the window next to the storage area
                yshift = (ys-ystart_m-ny_m)*VCLOCK_STORAGE

                # Number of columns to shift whichever window is further from
                # the edge of the readout to get ready for simultaneous readout.
                diffshift = abs(xsl - 1 - (1024 - xsr - nx + 1))

                """
                Time taken to dump any pixels in a row that come after the ones we want.
                The '8' is the number of HCLOCKs needed to open the serial register dump gates
                If the left window is further from the left edge than the right window is from the
                right edge, then the diffshift will move it to be the same as the right window, and
                so we use the right window parameters to determine the number of hclocks needed, and
                vice versa.
                """
                if xsl - 1 > 1024 - xsr - nx + 1:
                    numHclocks = nx + diffshift + (1024 - xsr - nx + 1) + 8
                else:
                    numHclocks = nx + diffshift + (xsl - 1) + 8

                # Time taken to read one line.
                # The extra 2 is required to fill the video pipeline buffer
                lineRead = VCLOCK_STORAGE*ybin + numHclocks*HCLOCK + (nx/xbin+2)*video

                # time to read the window
                read = (ny/ybin)*lineRead

                cycleTime += read + yshift
                readout += read + yshift

            if self.clear():
                exposureTime = expose/1e6
            else:
                exposureTime = (cycleTime - frameTransfer)/1e6
            cycleTime /= 1e6

        deadTime = cycleTime - exposureTime
        frameRate = 1./cycleTime
        dutyCycle = 100.0*exposureTime/cycleTime
        return exposureTime, deadTime, cycleTime, dutyCycle, frameRate


class CountsFrame(tk.LabelFrame):
    """
    Frame for count rate estimates
    """
    def __init__(self, master):
        """
        master : enclosing widget
        """
        tk.LabelFrame.__init__(
            self, master, pady=2, text='Count & S-to-N estimator')

        # divide into left and right frames
        lframe = tk.Frame(self, padx=2)
        rframe = tk.Frame(self, padx=2)

        # entries
        self.filter = w.Radio(
            lframe, ('u', 'g', 'r', 'i', 'z'), 3, self.checkUpdate, initial=1)
        self.mag = w.RangedFloat(
            lframe, 18., 0., 30., self.checkUpdate, True, width=5)
        self.seeing = w.RangedFloat(
            lframe, 1.0, 0.2, 20., self.checkUpdate, True, True, width=5)
        self.airmass = w.RangedFloat(
            lframe, 1.5, 1.0, 5.0, self.checkUpdate, True, width=5)
        self.moon = w.Radio(lframe, ('d', 'g', 'b'),  3, self.checkUpdate)

        # results
        self.cadence = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.exposure = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.duty = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.peak = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.total = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.ston = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)
        self.ston3 = w.Ilabel(rframe, text='UNDEF', width=10, anchor=tk.W)

        # layout
        # left
        tk.Label(lframe, text='Filter:').grid(
            row=0, column=0, padx=5, pady=3, sticky=tk.W+tk.N)
        self.filter.grid(row=0, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text='Mag:').grid(
            row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.mag.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text='Seeing:').grid(
            row=2, column=0, padx=5, pady=3, sticky=tk.W)
        self.seeing.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text='Airmass:').grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W)
        self.airmass.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(lframe, text='Moon:').grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W)
        self.moon.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)

        # right
        tk.Label(rframe, text='Cadence:').grid(
            row=0, column=0, padx=5, pady=3, sticky=tk.W)
        self.cadence.grid(row=0, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='Exposure:').grid(
            row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.exposure.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='Duty cycle:').grid(
            row=2, column=0, padx=5, pady=3, sticky=tk.W)
        self.duty.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='Peak:').grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W)
        self.peak.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='Total:').grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W)
        self.total.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='S/N:').grid(
            row=5, column=0, padx=5, pady=3, sticky=tk.W)
        self.ston.grid(row=5, column=1, padx=5, pady=3, sticky=tk.W)

        tk.Label(rframe, text='S/N (3h):').grid(
            row=6, column=0, padx=5, pady=3, sticky=tk.W)
        self.ston3.grid(row=6, column=1, padx=5, pady=3, sticky=tk.W)

        # slot frames in
        lframe.grid(row=0, column=0, sticky=tk.W+tk.N)
        rframe.grid(row=0, column=1, sticky=tk.W+tk.N)

    def checkUpdate(self, *args):
        """
        Updates values after first checking instrument parameters are OK.
        This is not integrated within update to prevent ifinite recursion
        since update gets called from ipars.
        """
        g = get_root(self).globals
        if not self.check():
            g.clog.error('Current observing parameters are not valid.')
            return False

        if not g.ipars.check():
            g.clog.error('Current instrument parameters are not valid.')
            return False

    def check(self):
        """
        Checks values
        """
        status = True
        g = get_root(self).globals
        if self.mag.ok():
            self.mag.config(bg=g.COL['main'])
        else:
            self.mag.config(bg=g.COL['warn'])
            status = False

        if self.airmass.ok():
            self.airmass.config(bg=g.COL['main'])
        else:
            self.airmass.config(bg=g.COL['warn'])
            status = False

        if self.seeing.ok():
            self.seeing.config(bg=g.COL['main'])
        else:
            self.seeing.config(bg=g.COL['warn'])
            status = False

        return status

    def update(self, *args):
        """
        Updates values. You should run a check on the instrument and
        target parameters before calling this.
        """
        g = get_root(self).globals
        expTime, deadTime, cycleTime, dutyCycle, frameRate = g.ipars.timing()

        total, peak, peakSat, peakWarn, ston, ston3 = \
            self.counts(expTime, cycleTime)

        if cycleTime < 0.01:
            self.cadence.config(text='{0:7.5f} s'.format(cycleTime))
        elif cycleTime < 0.1:
            self.cadence.config(text='{0:6.4f} s'.format(cycleTime))
        elif cycleTime < 1.:
            self.cadence.config(text='{0:5.3f} s'.format(cycleTime))
        elif cycleTime < 10.:
            self.cadence.config(text='{0:4.2f} s'.format(cycleTime))
        elif cycleTime < 100.:
            self.cadence.config(text='{0:4.1f} s'.format(cycleTime))
        elif cycleTime < 1000.:
            self.cadence.config(text='{0:4.0f} s'.format(cycleTime))
        else:
            self.cadence.config(text='{0:5.0f} s'.format(cycleTime))

        if expTime < 0.01:
            self.exposure.config(text='{0:7.5f} s'.format(expTime))
        elif expTime < 0.1:
            self.exposure.config(text='{0:6.4f} s'.format(expTime))
        elif expTime < 1.:
            self.exposure.config(text='{0:5.3f} s'.format(expTime))
        elif expTime < 10.:
            self.exposure.config(text='{0:4.2f} s'.format(expTime))
        elif expTime < 100.:
            self.exposure.config(text='{0:4.1f} s'.format(expTime))
        elif expTime < 1000.:
            self.exposure.config(text='{0:4.0f} s'.format(expTime))
        else:
            self.exposure.config(text='{0:5.0f} s'.format(expTime))

        self.duty.config(text='{0:4.1f} %'.format(dutyCycle))
        self.peak.config(text='{0:d} cts'.format(int(round(peak))))
        if peakSat:
            self.peak.config(bg=g.COL['error'])
        elif peakWarn:
            self.peak.config(bg=g.COL['warn'])
        else:
            self.peak.config(bg=g.COL['main'])

        self.total.config(text='{0:d} cts'.format(int(round(total))))
        self.ston.config(text='{0:.1f}'.format(ston))
        self.ston3.config(text='{0:.1f}'.format(ston3))

    def counts(self, expTime, cycleTime, ap_scale=1.6, ndiv=5):
        """
        Computes counts per pixel, total counts, sky counts
        etc given current magnitude, seeing etc. You should
        run a check on the instrument parameters before calling
        this.

        expTime   : exposure time per frame (seconds)
        cycleTime : sampling, cadence (seconds)
        ap_scale  : aperture radius as multiple of seeing

        Returns: (total, peak, peakSat, peakWarn, ston, ston3)

        total    -- total number of object counts in aperture
        peak     -- peak counts in a pixel
        peakSat  -- flag to indicate saturation
        peakWarn -- flag to indication level approaching saturation
        ston     -- signal-to-noise per exposure
        ston3    -- signal-to-noise after 3 hours on target
        """
        # code directly translated from Java equivalent.
        g = get_root(self).globals

        # Set the readout speed
        readSpeed = g.ipars.readSpeed.value()
        xbin, ybin = g.ipars.wframe.xbin.value(), g.ipars.wframe.ybin.value()
        # index for readout noise array
        if xbin == 1:
            read_idx = 0
        elif xbin < 4:
            read_idx = 1
        elif xbin < 4:
            read_idx = 2
        else:
            read_idx = 3

        # calculate SN info.
        zero, sky, skyTot, gain, read, darkTot = 0., 0., 0., 0., 0., 0.
        total, peak, correct, signal, readTot, seeing = 0., 0., 0., 0., 0., 0.
        noise, _, narcsec, npix, signalToNoise3 = 1., 0., 0., 0., 0.

        tinfo = g.TINS[g.cpars['telins_name']]
        filtnam = self.filter.value()
        zero = tinfo['zerop'][filtnam]
        mag = self.mag.value()
        seeing = self.seeing.value()
        sky = g.SKY[self.moon.value()][filtnam]
        airmass = self.airmass.value()

        # GAIN, RNO
        if readSpeed == 'Fast':
            gain = GAIN_FAST
            read = READ_NOISE_FAST[read_idx]
        elif readSpeed == 'Turbo':
            gain = GAIN_TURBO
            read = READ_NOISE_TURBO[read_idx]
        elif readSpeed == 'Slow':
            gain = GAIN_SLOW
            read = READ_NOISE_SLOW[read_idx]

        plateScale = tinfo['plateScale']

        # calculate expected electrons
        total = 10.**((zero-mag-airmass*g.EXTINCTION[filtnam])/2.5)*expTime

        # compute fraction that fall in central pixel
        # assuming target exactly at its centre. Do this
        # by splitting each pixel of the central (potentially
        # binned) pixel into ndiv * ndiv points at
        # which the seeing profile is added. sigma is the
        # RMS seeing in terms of pixels.
        sigma = seeing/g.EFAC/plateScale

        sum = 0.
        for iyp in range(ybin):
            yoff = -ybin/2.+iyp
            for ixp in range(xbin):
                xoff = -xbin/2.+ixp
                for iys in range(ndiv):
                    y = (yoff + (iys+0.5)/ndiv)/sigma
                    for ixs in range(ndiv):
                        x = (xoff + (ixs+0.5)/ndiv)/sigma
                        sum += math.exp(-(x*x+y*y)/2.)
        peak = total*sum/(2.*math.pi*sigma**2*ndiv**2)

        # Work out fraction of flux in aperture with radius AP_SCALE*seeing
        correct = 1. - math.exp(-(g.EFAC*ap_scale)**2/2.)

        # expected sky e- per arcsec
        skyPerArcsec = 10.**((zero-sky)/2.5)*expTime
        # skyPerPixel = skyPerArcsec*plateScale**2*xbin*ybin
        narcsec = math.pi*(ap_scale*seeing)**2
        skyTot = skyPerArcsec*narcsec
        npix = math.pi*(ap_scale*seeing/plateScale)**2/xbin/ybin

        signal = correct*total        # in electrons
        darkTot = npix*DARK_COUNT*expTime  # in electrons
        readTot = npix*read**2         # in electrons

        # noise, in electrons
        noise = math.sqrt(readTot + darkTot + skyTot + signal)

        # Now compute signal-to-noise in 3 hour seconds run
        signalToNoise3 = signal/noise*math.sqrt(3*3600./cycleTime)

        # if using the avalanche mode, check that the signal level
        # is safe. A single electron entering the avalanche register
        # results in a distribution of electrons at the output with
        # mean value given by the parameter avalanche_gain. The
        # distribution is close to exponential, hence the probability
        # of obtaining an amplification n times higher than the mean is
        # given by e**-n. A value of 3/5 for n is adopted here for
        # warning/safety, which will occur once in every ~20/100
        # amplifications

        # convert from electrons to counts
        total /= gain
        peak /= gain

        warn = 25000
        sat = 60000

        peakSat = peak > sat
        peakWarn = peak > warn

        return (total, peak, peakSat, peakWarn, signal/noise, signalToNoise3)
