# Timing, gain, noise parameters for ULTRACAM

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
INVERSION_DELAY = 110.0
VCLOCK_FRAME = 23.3
VCLOCK_STORAGE = 23.3
HCLOCK = 0.48
CDS_TIME_FDD = 1.84
CDS_TIME_FBB = 4.4
CDS_TIME_CDD = 9.76
SWITCH_TIME = 0.56

# Filter names for each arm, matching the Java Udriver GUI defaults.
# The three arms are commonly referred to as blue, green, and red.
BLUE_FILTER_NAMES = ("Super u'", "u'", "NBF3500", "Clear", "Lab", "Special", "(None)")
GREEN_FILTER_NAMES = (
    "Super g'",
    "g'",
    "HeII",
    "BCont",
    "NBF4170",
    "Clear",
    "Lab",
    "Special",
    "(None)",
)
RED_FILTER_NAMES = (
    "Super r'",
    "Super i'",
    "Super z'",
    "r'",
    "i'",
    "z'",
    "RCont",
    "NaI",
    "HA-N",
    "HA-B",
    "Clear",
    "Lab",
    "Special",
    "(None)",
)

# Special values of NY when pipe shift hits a minimum
SPECIAL_NY = [
    8,
    10,
    13,
    18,
    21,
    24,
    31,
    38,
    41,
    49,
    54,
    60,
    68,
    79,
    93,
    114,
    147,
    206,
    344,
]
