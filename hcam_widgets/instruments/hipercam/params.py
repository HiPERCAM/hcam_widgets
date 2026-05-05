# Timing, Gain, Noise parameters for HiPERCAM
# Times in seconds
VCLOCK_FRAME_SLOW = 15e-6      # vertical clocking time in image area
VCLOCK_STORAGE_SLOW = 20e-6    # vertical clocking time in storage area
HCLOCK_SLOW = 0.24e-6          # horizontal clocking time
VCLOCK_FAST = 13e-6            # faster mode with poorer CTE
HCLOCK_FAST = 0.12e-6          # faster mode with poorer CTE
SETUP_READ = 9.0e-7            # time required for Naidu's setup_read SR
DUMP_TIME_SLOW = 18e-6         # time to dump extra pixels, slow clocking
DUMP_TIME_FAST = 3.6e-6        # time to dump extra pixels, fast clocking
VIDEO_SLOW_SE = 8.72e-6        # ~113 kHz, Naidu's clock speed for single output mode
VIDEO_SLOW = 5.2e-6            # ~192 kHz, same clock speed as fast, but 4 samples
VIDEO_FAST = 1.9e-6            # ~520 kHz
GAIN_FAST = 1.1                # electrons/ADU
GAIN_SLOW = 1.1
RNO_FAST = 5.0                 # e- / pixel
RNO_SLOW = 4.5
DARK_E = 0.02                  # e/pix/s

FFX = 1024                     # X pixels per output
FFY = 520                      # Y pixels per output
PRSCX = 50                     # number of pre-scan pixels
