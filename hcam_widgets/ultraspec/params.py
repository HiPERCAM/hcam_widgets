# Timing, gain, noise parameters for ULTRASPEC
# Lifted from java usdriver

VCLOCK = 14.4e-6        # vertical clocking time
HCLOCK_NORM = 0.48e-6   # normal mode horizontal clock
HCLOCK_AV = 0.96e-6     # avalanche mode horizontal clock
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
AVALANCHE_GAIN_9 = 1200.0   # dimensionless gain, hvgain=9
AVALANCHE_SATURATE = 80000  # electrons

# avalanche gains assume HVGain = 9
GAIN_NORM_FAST = 0.8    # electrons per count
GAIN_NORM_MED = 0.7     # electrons per count
GAIN_NORM_SLOW = 0.8    # electrons per count
GAIN_AV_FAST = 0.0034   # electrons per count
GAIN_AV_MED = 0.0013    # electrons per count
GAIN_AV_SLOW = 0.0016   # electrons per count

# readout noise (electrons per pixel); avalanche values assume HVGain = 9
RNO_NORM_FAST = 4.8
RNO_NORM_MED = 2.8
RNO_NORM_SLOW = 2.2
RNO_AV_FAST = 6.5
RNO_AV_MED = 7.8
RNO_AV_SLOW = 5.6

# other noise sources
DARK_E = 0.001  # electrons/pix/sec
CIC = 0.010     # Clock induced charge, electrons/pix
