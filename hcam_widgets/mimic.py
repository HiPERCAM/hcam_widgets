from matplotlib import pyplot as plt


class Mimic(object):
    def __init__(self, height, width):
        dpi = 100
        figsize = (width/dpi, height/dpi)
        self.figure = plt.Figure(figsize=figsize, dpi=dpi)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_axis_off()

    def update_mimic(self, telemetry):
        raise NotImplementedError
