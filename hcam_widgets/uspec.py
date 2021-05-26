# -*- coding: utf-8 -*-
"""
uspec provides classes and data specific to ULTRASPEC
"""
from __future__ import print_function, absolute_import, unicode_literals, division
import six
import math

# internal imports
from .tkutils import get_root
from . import widgets as w

if not six.PY3:
    import Tkinter as tk
else:
    import tkinter as tk

# Timing, gain, noise parameters lifted from java usdriver
VCLOCK = 14.4e-6  # vertical clocking time
HCLOCK_NORM = 0.48e-6  # normal mode horizontal clock
HCLOCK_AV = 0.96e-6  # avalanche mode horizontal clock
VIDEO_NORM_SLOW = 11.20e-6
VIDEO_NORM_MED = 6.24e-6
VIDEO_NORM_FAST = 3.20e-6
VIDEO_AV_SLOW = 11.20e-6
VIDEO_AV_MED = 6.24e-6
VIDEO_AV_FAST = 3.20e-6
FFX = 1072
FFY = 1072
IFY = 1072
IFX = 1072
AVALANCHE_PIXELS = 1072
AVALANCHE_GAIN_9 = 1200.0  # dimensionless gain, hvgain=9
AVALANCHE_SATURATE = 80000   # electrons

# avalanche gains assume HVGain = 9. We can adapt this later when we decide
# how gain should be set at TNO. Might be better to make gain a function if
# we allow 0 < HVgain < 9 (SL)

GAIN_NORM_FAST = 0.8   # electrons per count
GAIN_NORM_MED = 0.7    # electrons per count
GAIN_NORM_SLOW = 0.8   # electrons per count
GAIN_AV_FAST = 0.0034  # electrons per count
GAIN_AV_MED = 0.0013   # electrons per count
GAIN_AV_SLOW = 0.0016  # electrons per count

# Note - avalanche RNO assume HVGain = 9. We can adapt this later when we
# decide how gain should be set at TNO. Might be better to make RNO a function
# if we allow 0 < HVgain < 9 (SL)

RNO_NORM_FAST = 4.8  # electrons per pixel
RNO_NORM_MED = 2.8   # electrons per pixel
RNO_NORM_SLOW = 2.2  # electrons per pixel
RNO_AV_FAST = 6.5    # electrons per pixel
RNO_AV_MED = 7.8     # electrons per pixel
RNO_AV_SLOW = 5.6    # electrons per pixel

# other noise sources
DARK_E = 0.001  # electrons/pix/sec
CIC = 0.010     # Clock induced charge, electrons/pix


class InstPars(tk.LabelFrame):
    """
    Ultraspec instrument parameters block.
    """

    def __init__(self, master):
        """
        master : enclosing widget
        """
        tk.LabelFrame.__init__(self, master, text='Instrument parameters',
                               padx=10, pady=10)

        # left hand side
        lhs = tk.Frame(self)

        # Application (mode)
        tk.Label(lhs, text='Mode').grid(row=0, column=0, sticky=tk.W)
        self.app = w.Radio(lhs, ('Wins', 'Drift'), 2, self.check,
                           ('Windows', 'Drift'))
        self.app.grid(row=0, column=1, sticky=tk.W)

        # Clear enabled
        self.clearLab = tk.Label(lhs, text='Clear')
        self.clearLab.grid(row=1, column=0, sticky=tk.W)
        self.clear = w.OnOff(lhs, True, self.check)
        self.clear.grid(row=1, column=1, sticky=tk.W)

        # Avalanche settings
        tk.Label(lhs, text='Avalanche').grid(row=2, column=0, sticky=tk.W)
        aframe = tk.Frame(lhs)
        self.avalanche = w.OnOff(aframe, False, self.check)
        self.avalanche.pack(side=tk.LEFT)
        self.avgainLabel = tk.Label(aframe, text='gain ')
        self.avgainLabel.pack(side=tk.LEFT)
        self.avgain = w.RangedInt(aframe, 0, 0, 9, self.check,
                                  False, width=2)
        self.avgain.pack(side=tk.LEFT)
        aframe.grid(row=2, column=1, pady=2, sticky=tk.W)

        # Readout speed
        tk.Label(lhs, text='Readout speed').grid(row=3, column=0, sticky=tk.NW)
        self.readSpeed = w.Radio(lhs, ('Slow', 'Medium', 'Fast'), 1,
                                 self.check, ('Slow', 'Medium', 'Fast'))
        self.readSpeed.grid(row=3, column=1, pady=2, sticky=tk.W)

        # Exposure delay
        tk.Label(lhs, text='Exposure delay (s)').grid(row=4, column=0,
                                                      sticky=tk.W)

        g = get_root(self).globals
        elevel = g.cpars['expert_level']
        if elevel == 0:
            self.expose = w.Expose(lhs, 0.0007, 0.0007, 1677.7207,
                                   self.check, width=7)
        elif elevel == 1:
            self.expose = w.Expose(lhs, 0.0007, 0.0003, 1677.7207,
                                   self.check, width=7)
        else:
            self.expose = w.Expose(lhs, 0.0007, 0., 1677.7207,
                                   self.check, width=7)
        self.expose.grid(row=4, column=1, pady=2, sticky=tk.W)

        # Number of exposures
        tk.Label(lhs, text='Num. exposures  ').grid(row=5, column=0, sticky=tk.W)
        self.number = w.PosInt(lhs, 1, None, False, width=7)
        self.number.grid(row=5, column=1, pady=2, sticky=tk.W)

        # LED setting
        self.ledLab = tk.Label(lhs, text='LED setting')
        self.ledLab.grid(row=6, column=0, sticky=tk.W)
        self.led = w.RangedInt(lhs, 0, 0, 4095, None, False, width=7)
        self.led.grid(row=6, column=1, pady=2, sticky=tk.W)
        self.ledValue = self.led.value()

        # Right-hand side: the window parameters
        rhs = tk.Frame(self)

        # window mode frame (initially full frame)
        xs = (1, 101, 201, 301)
        xsmin = (1, 1, 1, 1)
        xsmax = (1056, 1056, 1056, 1056)
        ys = (1, 101, 201, 301)
        ysmin = (1, 1, 1, 1)
        ysmax = (1072, 1072, 1072, 1072)
        nx = (1056, 100, 100, 100)
        ny = (1072, 100, 100, 100)
        xbfac = (1, 2, 3, 4, 5, 6, 8)
        ybfac = (1, 2, 3, 4, 5, 6, 8)
        self.wframe = w.Windows(rhs, xs, xsmin, xsmax, ys, ysmin, ysmax,
                                nx, ny, xbfac, ybfac, self.check)
        self.wframe.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.N)

        # drift mode frame (just one pair)
        xsl = (100,)
        xslmin = (1,)
        xslmax = (1024,)
        xsr = (600,)
        xsrmin = (1,)
        xsrmax = (1024,)
        ys = (1,)
        ysmin = (1,)
        ysmax = (1024,)
        nx = (50,)
        ny = (50,)
        xbfac = (1, 2, 3, 4, 5, 6, 8)
        ybfac = (1, 2, 3, 4, 5, 6, 8)
        self.pframe = w.WinPairs(rhs, xsl, xslmin, xslmax, xsr, xsrmin,
                                 xsrmax, ys, ysmin, ysmax, nx, ny,
                                 xbfac, ybfac, self.check, hcam=False)

        # Pack two halfs
        lhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)
        rhs.pack(side=tk.LEFT, anchor=tk.N, padx=5)

        # Store freeze state
        self.frozen = False

        # stores current avalanche setting to check for changes
        self.oldAvalanche = False

        self.setExpertLevel()

    def setExpertLevel(self):
        """
        Modifies widget according to expertise level, which in this
        case is just matter of hiding or revealing the LED option
        and changing the lower limit on the exposure button.
        """
        g = get_root(self).globals
        level = g.cpars['expert_level']

        if level == 0:
            self.expose.fmin = 0.0007
            self.ledLab.grid_forget()
            self.led.grid_forget()
            self.ledValue = self.led.value()
            self.led.set(0)

        elif level == 1:
            self.expose.fmin = 0.0003
            self.led.set(self.ledValue)
            self.ledLab.grid(row=6, column=0, sticky=tk.W)
            self.led.grid(row=6, column=1, pady=2, sticky=tk.W)

        elif level == 2:
            self.expose.fmin = 0.0
            self.led.set(self.ledValue)
            self.ledLab.grid(row=6, column=0, sticky=tk.W)
            self.led.grid(row=6, column=1, pady=2, sticky=tk.W)

    def isDrift(self):
        """
        Returns True if we are in drift mode
        """
        if self.app.value() == 'Drift':
            return True
        elif self.app.value() == 'Windows':
            return False
        else:
            raise ValueError('uspec.InstPars.isDrift: application = ' +
                             self.app.value() + ' not recognised.')

    def loadXML(self, xml):
        """
        Sets the values of instrument parameters given an
        ElementTree containing suitable XML
        """
        g = get_root(self).globals
        # find application
        xmlid = xml.attrib['id']
        for app, d in g.cpars['templates'].iteritems():
            if xmlid == d['id']:
                break
        else:
            raise ValueError('Do not recognize application id = ' + xmlid)

        # find parameters
        cconfig = xml.find('configure_camera')
        pdict = {}
        for param in cconfig.findall('set_parameter'):
            pdict[param.attrib['ref']] = param.attrib['value']

        xbin, ybin = int(pdict['X_BIN']), int(pdict['Y_BIN'])

        # Set them.

        # Number of exposures
        self.number.set(pdict['NUM_EXPS'] if pdict['NUM_EXPS'] != '-1' else 0)

        # LED level
        self.led.set(pdict['LED_FLSH'])

        # Avalanche or normal
        self.avalanche.set(pdict['OUTPUT'])

        # Avalanche gain
        self.avgain.set(pdict['HV_GAIN'])

        # Dwell
        self.expose.set(str(float(pdict['DWELL'])/10000.))

        # Readout speed
        speed = pdict['SPEED']
        self.readSpeed.set('Slow' if
                           speed == '0' else 'Medium' if speed == '1'
                           else 'Fast')

        if app == 'Windows':
            # Clear or not
            self.clear.set(pdict['EN_CLR'])

            # now for the windows which come in two flavours
            self.app.set('Windows')
            w = self.wframe

            # X-binning factor
            w.xbin.set(xbin)

            # Y-binning factor
            w.ybin.set(ybin)

            # Load up windows
            nwin = 0
            for nw in range(4):
                xs = 'X' + str(nw+1) + '_START'
                ys = 'Y' + str(nw+1) + '_START'
                nx = 'X' + str(nw+1) + '_SIZE'
                ny = 'Y' + str(nw+1) + '_SIZE'
                if xs in pdict and ys in pdict and nx in pdict and ny in pdict \
                        and pdict[nx] != '0' and pdict[ny] != 0:
                    xsv, ysv, nxv, nyv = int(pdict[xs]), int(pdict[ys]), int(pdict[nx]), int(pdict[ny])
                    nxv *= xbin
                    nyv *= ybin

                    nchop = max(0, 17-xsv)
                    if nchop % xbin != 0:
                        nchop = xbin * (nchop // xbin + 1)

                    if self.avalanche():
                        xsv = max(1, 1074 - xsv - nxv)
                    else:
                        xsv = max(1, xsv + nchop - 16)
                    nxv -= nchop

                    w.xs[nw].set(xsv)
                    w.ys[nw].set(ysv)
                    w.nx[nw].set(nxv)
                    w.ny[nw].set(nyv)
                    nwin += 1
                else:
                    break

            # Set the number of windows
            w.nwin.set(nwin)

        else:
            self.clear.set(0)

            # now for drift mode
            self.app.set('Drift')
            p = self.pframe

            # X-binning factor
            p.xbin.set(xbin)

            # Y-binning factor
            p.ybin.set(ybin)

            # Load up window pair values
            xslv, xsrv, ysv, nxv, nyv = (
                int(pdict['X1_START']), int(pdict['X2_START']),
                int(pdict['Y1_START']), int(pdict['X1_SIZE']), int(pdict['Y1_SIZE'])
            )
            nxv *= xbin
            nyv *= ybin

            nchop = max(0, 17-xslv)
            if nchop % xbin != 0:
                nchop = xbin * (nchop // xbin + 1)

            if self.avalanche():
                xslv = max(1, 1074-xslv-nxv)
                xsrv = max(1, 1074-xsrv-nxv)
            else:
                xslv = max(1, xslv+nchop-16)
                xsrv = max(1, xsrv+nchop-16)

            nxv -= nchop
            if xslv > xsrv:
                xsrv, xslv = xslv, xsrv

            # finally set the values
            p.xsl[0].set(xslv)
            p.xsr[0].set(xsrv)
            p.ys[0].set(ysv)
            p.nx[0].set(nxv)
            p.ny[0].set(nyv)
            p.npair.set(1)

    def check(self, *args):
        """Callback function for running validity checks on the CCD
        parameters. It spots and flags overlapping windows, windows with null
        parameters, windows with invalid dimensions given the binning
        factors. It sets the correct number of windows according to the
        selected application and enables or disables the avalanche gain
        setting according to whether the avalanche output is being used.
        Finally it checks that the windows are synchronised and sets the
        status of the 'Sync' button accordingly.

        Returns True/False according to whether the settings are judged to be
        OK. True means they are thought to be in a fit state to be sent to the
        camera.

        This can only be run once the 'observe' are defined.
        """
        g = get_root(self).globals
        # Switch visible widget according to the application
        if self.isDrift():
            self.wframe.grid_forget()
            self.pframe.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.N)
            self.clearLab.config(state='disable')
            if not self.frozen:
                self.clear.config(state='disable')
                self.pframe.enable()
        else:
            self.pframe.grid_forget()
            self.wframe.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.N)
            self.clearLab.config(state='normal')
            if not self.frozen:
                self.clear.config(state='normal')
                self.wframe.enable()

        if self.avalanche():
            if not self.frozen:
                self.avgain.enable()
            if not self.oldAvalanche:
                # only update status if there has been a change
                # this is needed because any change to avGain causes
                # this check to be run and we must prevent the gain
                # automatically being set back to zero
                self.avgainLabel.configure(state='normal')
                self.avgain.set(0)
                self.oldAvalanche = True
        else:
            self.avgain.disable()
            self.avgainLabel.configure(state='disable')
            self.oldAvalanche = False

        # check the window settings
        if self.isDrift():
            status = self.pframe.check()
        else:
            status = self.wframe.check()

        # exposure delay
        if self.expose.ok():
            self.expose.config(bg=g.COL['main'])
        else:
            self.expose.config(bg=g.COL['warn'])
            status = False

        if status:
            # if valid, update timing and SN info
            g.count.update()

        return status

    def freeze(self):
        """
        Freeze all settings so that they can't be altered
        """
        self.app.disable()
        self.clear.disable()
        self.avalanche.disable()
        self.avgain.disable()
        self.readSpeed.disable()
        self.led.disable()
        self.expose.disable()
        self.number.disable()
        self.wframe.freeze()
        self.pframe.freeze()
        self.frozen = True

    def unfreeze(self):
        """
        Reverse of freeze
        """
        self.app.enable()
        self.clear.enable()
        self.avalanche.enable()
        self.readSpeed.enable()
        self.led.enable()
        self.expose.enable()
        self.number.enable()
        self.wframe.unfreeze()
        self.pframe.unfreeze()
        self.frozen = False
        self.check()

    def getRtplotWins(self):
        """
        Returns a string suitable to sending off to rtplot when
        it asks for window parameters. Returns null string '' if
        the windows are not OK. This operates on the basis of
        trying to send something back, even if it might not be
        OK as a window setup. Note that we have to take care
        here not to update any GUI components because this is
        called outside of the main thread.
        """
        try:
            xbin = self.wframe.xbin.value()
            ybin = self.wframe.ybin.value()
            if self.app.value() == 'Windows':
                nwin = self.wframe.nwin.value()
                ret = str(xbin) + ' ' + str(ybin) + ' ' + str(nwin) + '\r\n'
                for xs, ys, nx, ny in self.wframe:
                    ret += (str(xs) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
            elif self.app.value() == 'Drift':
                ret = str(xbin) + ' ' + str(ybin) + ' 2\r\n'
                for xsl, xsr, ys, nx, ny in self.pframe:
                    ret += (str(xsl) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')
                    ret += (str(xsr) + ' ' + str(ys) + ' ' + str(nx) + ' ' +
                            str(ny) + '\r\n')

            return ret
        except Exception:
            return ''

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

        # avalanche mode y/n?
        lnormal = not self.avalanche()
        HCLOCK = HCLOCK_NORM if lnormal else HCLOCK_AV

        # drift mode y/n?
        isDriftMode = self.app.value() == 'Drift'

        # Set the readout speed
        readSpeed = self.readSpeed.value()

        if readSpeed == 'Fast':
            video = VIDEO_NORM_FAST if lnormal else VIDEO_AV_FAST
        elif readSpeed == 'Medium':
            video = VIDEO_NORM_MED if lnormal else VIDEO_AV_MED
        elif readSpeed == 'Slow':
            video = VIDEO_NORM_SLOW if lnormal else VIDEO_AV_SLOW
        else:
            raise ValueError('uspec.InstPars.timing: readout speed = '
                             + readSpeed + ' not recognised.')

        # clear chip on/off?
        lclear = not isDriftMode and self.clear()

        # get exposure delay
        expose = self.expose.value()

        # window parameters
        if isDriftMode:
            xbin = self.pframe.xbin.value()
            ybin = self.pframe.ybin.value()
            dxleft = self.pframe.xsl[0].value()
            dxright = self.pframe.xsr[0].value()
            dys = self.pframe.ys[0].value()
            dnx = self.pframe.nx[0].value()
            dny = self.pframe.ny[0].value()
        else:
            xbin = self.wframe.xbin.value()
            ybin = self.wframe.ybin.value()
            xs, ys, nx, ny = [], [], [], []
            nwin = self.wframe.nwin.value()
            for xsv, ysv, nxv, nyv in self.wframe:
                xs.append(xsv)
                ys.append(ysv)
                nx.append(nxv)
                ny.append(nyv)

        if lnormal:
            # normal mode convert xs by ignoring 16 overscan pixel
            if isDriftMode:
                dxleft += 16
                dxright += 16
            else:
                for nw in range(nwin):
                    xs[nw] += 16
        else:
            if isDriftMode:
                dxright = FFX - (dxright-1) - (dnx-1)
                dxleft = FFX - (dxleft-1) - (dnx-1)
                # in drift mode, also need to swap the windows around
                dxright, dxleft = dxleft, dxright
            else:
                # in avalanche mode, need to swap windows around
                for nw in range(nwin):
                    xs[nw] = FFX - (xs[nw]-1) - (nx[nw]-1)

        # convert timing parameters to seconds
        expose_delay = expose

        # clear chip by VCLOCK-ing the image and storage areas
        if lclear:
            # accomodate changes to clearing made by DA to fix dark current
            # when clearing charge along normal output
            clear_time = (2.0*(FFY*VCLOCK+39.e-6) + FFX*HCLOCK_NORM +
                          2162.0*HCLOCK_AV)
        else:
            clear_time = 0.0

        hclockFactor = 1.0 if lnormal else 2.0

        if isDriftMode:
            # for drift mode, we need the number of windows in the pipeline
            # and the pipeshift
            pnwin = int(((1037. / dny) + 1.)/2.)
            pshift = 1037. - (2.*pnwin-1.)*dny
            frame_transfer = (dny+dys-1.)*VCLOCK + 49.0e-6

            yshift = [0.]
            yshift[0] = (dys-1.0)*VCLOCK

            # After placing the window adjacent to the serial register, the
            # register must be cleared by clocking out the entire register,
            # taking FFX hclocks (we no longer open the dump gates, which
            # took only 8 hclock cycles to complete, but gave ramps and
            # bright rows in the bias). We think dave does 2*FFX hclocks
            # in avalanche mode, but need to check this with him.
            line_clear = [0.]
            if yshift[0] != 0:
                line_clear[0] = hclockFactor*FFX*HCLOCK

            numhclocks = [0]
            numhclocks[0] = FFX
            if not lnormal:
                numhclocks[0] += AVALANCHE_PIXELS

            line_read = [0.]
            line_read[0] = (VCLOCK*ybin + numhclocks[0]*HCLOCK +
                            video*2.0*dnx/xbin)

            readout = [0.]
            readout[0] = (dny/ybin) * line_read[0]

        else:
            # If not drift mode, move entire image into storage area
            # the -35 component is because Derek only shifts 1037 pixels
            # (composed of 1024 active rows, 5 dark reference rows, 2
            # transition rows and 6 extra overscan rows for good measure)
            # If drift mode, just move the window into the storage area
            frame_transfer = (FFY-35)*VCLOCK + 49.0e-6

            yshift = nwin*[0.]
            yshift[0] = (ys[0]-1.0)*VCLOCK
            for nw in range(1, nwin):
                yshift[nw] = (ys[nw]-ys[nw-1]-ny[nw-1])*VCLOCK

            line_clear = nwin*[0.]
            for nw in range(nwin):
                if yshift[nw] != 0:
                    line_clear[nw] = hclockFactor*FFX*HCLOCK

            # calculate how long it takes to shift one row into the serial
            # register shift along serial register and then read out the data.
            # The charge in a row after a window used to be dumped, taking
            # 8 HCLOCK cycles. This created ramps and bright rows/columns in
            # the images, so was removed.
            numhclocks = nwin*[0]
            for nw in range(nwin):
                numhclocks[nw] = FFX
                if not lnormal:
                    numhclocks[nw] += AVALANCHE_PIXELS

            line_read = nwin*[0.]
            for nw in range(nwin):
                line_read[nw] = (VCLOCK*ybin + numhclocks[nw]*HCLOCK +
                                 video*nx[nw]/xbin)

            # multiply time to shift one row into serial register by
            # number of rows for total readout time
            readout = nwin*[0.]
            for nw in range(nwin):
                readout[nw] = (ny[nw]/ybin) * line_read[nw]

        # now get the total time to read out one exposure.
        cycleTime = expose_delay + clear_time + frame_transfer
        if isDriftMode:
            cycleTime += pshift*VCLOCK+yshift[0]+line_clear[0]+readout[0]
        else:
            for nw in range(nwin):
                cycleTime += yshift[nw] + line_clear[nw] + readout[nw]

        frameRate = 1.0/cycleTime
        expTime = expose_delay if lclear else cycleTime - frame_transfer
        deadTime = cycleTime - expTime
        dutyCycle = 100.0*expTime/cycleTime

        return (expTime, deadTime, cycleTime, dutyCycle, frameRate)


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
            g.clog.warn('Current observing parameters are not valid.')
            return False

        if not g.ipars.check():
            g.clog.warn('Current instrument parameters are not valid.')
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
        # avalanche mode y/n?
        lnormal = not g.ipars.avalanche()

        # Set the readout speed
        readSpeed = g.ipars.readSpeed.value()

        if g.ipars.app == 'Windows':
            xbin, ybin = g.ipars.wframe.xbin.value(), g.ipars.wframe.ybin.value()
        else:
            xbin, ybin = g.ipars.pframe.xbin.value(), g.ipars.pframe.ybin.value()

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
            gain = GAIN_NORM_FAST if lnormal else GAIN_AV_FAST
            read = RNO_NORM_FAST if lnormal else RNO_AV_FAST

        elif readSpeed == 'Medium':
            gain = GAIN_NORM_MED if lnormal else GAIN_AV_MED
            read = RNO_NORM_MED if lnormal else RNO_AV_MED

        elif readSpeed == 'Slow':
            gain = GAIN_NORM_SLOW if lnormal else GAIN_AV_SLOW
            read = RNO_NORM_SLOW if lnormal else RNO_AV_SLOW

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
        # peak    = total*xbin*ybin*(plateScale/(seeing/EFAC))**2/(2.*math.pi)

        # Work out fraction of flux in aperture with radius AP_SCALE*seeing
        correct = 1. - math.exp(-(g.EFAC*ap_scale)**2/2.)

        # expected sky e- per arcsec
        skyPerArcsec = 10.**((zero-sky)/2.5)*expTime
        # skyPerPixel = skyPerArcsec*plateScale**2*xbin*ybin
        narcsec = math.pi*(ap_scale*seeing)**2
        skyTot = skyPerArcsec*narcsec
        npix = math.pi*(ap_scale*seeing/plateScale)**2/xbin/ybin

        signal = correct*total        # in electrons
        darkTot = npix*DARK_E*expTime  # in electrons
        readTot = npix*read**2         # in electrons
        cic = 0 if lnormal else CIC

        # noise, in electrons
        if lnormal:
            noise = math.sqrt(readTot + darkTot + skyTot + signal + cic)
        else:
            # assume high gain observations in proportional mode
            noise = math.sqrt(readTot/AVALANCHE_GAIN_9**2 +
                              2.0*(darkTot + skyTot + signal) + cic)

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

        if not lnormal:
            sat = AVALANCHE_SATURATE/AVALANCHE_GAIN_9/5/gain
            warn = AVALANCHE_SATURATE/AVALANCHE_GAIN_9/3/gain

        peakSat = peak > sat
        peakWarn = peak > warn

        return (total, peak, peakSat, peakWarn, signal/noise, signalToNoise3)
