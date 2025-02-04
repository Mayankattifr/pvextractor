from __future__ import print_function

import os
import math
import logging
import warnings

import numpy as np

from matplotlib.collections import LineCollection
from matplotlib.transforms import Bbox
from matplotlib.patches import Polygon

from .geometry.path import Path, get_endpoints
from . import extract_pv_slice


def distance(x1, y1, x2, y2, x3, y3):
    """
    Find the shortest distance between a point (x3, y3) and the line passing
    through the points (x1, y1) and (x2, y2).
    """

    px = x2-x1
    py = y2-y1

    something = px * px + py * py

    u =  ((x3 - x1) * px + (y3 - y1) * py) / float(something)

    x = x1 + u * px
    y = y1 + u * py

    dx = x - x3
    dy = y - y3

    dist = math.sqrt(dx*dx + dy*dy)

    return dist


class MovableSliceBox(object):

    def __init__(self, box, callback):
        self.box = box
        self.press = None
        self.background = None
        self.point_counter = 0
        self.callback = callback
        self.mode = 0
        self.show_poly = False
        self.cidpress = self.box.figure.canvas.mpl_connect('draw_event', self.draw_slicer)

    def connect(self):
        self.cidpress = self.box.figure.canvas.mpl_connect('key_press_event', self.key_press)
        self.cidpress = self.box.figure.canvas.mpl_connect('button_press_event', self.on_press)
        self.cidmotion = self.box.figure.canvas.mpl_connect('motion_notify_event', self.on_motion)

    def draw_slicer(self, event):

        axes = self.box.axes
        canvas = self.box.figure.canvas

        self.box.axes.draw_artist(self.box)

        if self.show_poly:

            path = Path(zip(self.box.x, self.box.y))
            path.width = self.box.width

            patches = path.to_patches(1, ec='green', fc='none',
                                          transform=self.box.axes.transData,
                                          clip_on=True, clip_box=self.box.axes.bbox)

            for patch in patches:
                self.box.axes.draw_artist(patch)

    def on_press(self, event):

        if self.box.figure.canvas.toolbar.mode != '':
            return

        if event.inaxes != self.box.axes:
            return

        if self.mode == 1:
            self.callback(self.box)
            self.mode += 1
            return

        if self.mode == 2:
            self.box.x = []
            self.box.y = []
            self.mode = 0
            self.point_counter = 0

        self.press = event.xdata, event.ydata

        self.point_counter += 1

        axes = self.box.axes
        canvas = self.box.figure.canvas

        if self.point_counter == 1:  # first point

            self.box.x.append(event.xdata)
            self.box.x.append(event.xdata)
            self.box.y.append(event.ydata)
            self.box.y.append(event.ydata)

            self.box.width = 0.

            self.box.set_animated(True)
            canvas.draw()
            self.background = canvas.copy_from_bbox(self.box.axes.bbox)

        elif self.mode == 0:

            self.box.x.append(event.xdata)
            self.box.y.append(event.ydata)

        self.box._update_segments()

        # now redraw just the lineangle
        axes.draw_artist(self.box)

    def key_press(self, event):

        if self.box.figure.canvas.toolbar.mode != '':
            return

        if event.key == 'enter' and self.mode == 0:
            self.mode += 1
            self.box.x = self.box.x[:-1]
            self.box.y = self.box.y[:-1]

        if event.key == 'y' and self.mode == 2:
            self.show_poly = not self.show_poly
            self.draw_slicer(event)
            self.box.figure.canvas.draw()

    def on_motion(self, event):

        if self.box.figure.canvas.toolbar.mode != '':
            return

        if self.point_counter == 0:
            return

        if self.mode == 2:
            return

        canvas = self.box.figure.canvas
        axes = self.box.axes
        canvas.restore_region(self.background)

        if event.inaxes != axes:
            return

        if self.mode == 0:
            self.box.x[-1] = event.xdata
            self.box.y[-1] = event.ydata
        elif self.mode == 1:
            self.box.width = distance(self.box.x[-2], self.box.y[-2], self.box.x[-1], self.box.y[-1], event.xdata, event.ydata) * 2

        self.box._update_segments()

        # redraw just the current lineangle
        axes.draw_artist(self.box)

        canvas.blit()

    def disconnect(self):
        self.box.figure.canvas.mpl_disconnect(self.cidpress)
        self.box.figure.canvas.mpl_disconnect(self.cidmotion)


class SliceCurve(LineCollection):

    def __init__(self, x=[], y=[], width=None, **kwargs):

        super(SliceCurve, self).__init__([], **kwargs)

        self.x = x
        self.y = y
        self.width = width

        self._update_segments()

    def _update_segments(self):

        if not self.x or self.width is None or len(self.x) < 2:
            return

        # Find central line
        line = zip(self.x, self.y)

        if self.width:

            x1, y1, x2, y2 = get_endpoints(self.x, self.y, self.width)

            # Find bounding rectangle
            rect = zip(np.hstack([x1,x2[::-1], x1[0]]),
                       np.hstack([y1,y2[::-1], y1[0]]))

            self.set_segments([list(line), list(rect)])
            self.set_linestyles(['solid', 'dashed'])
            self.set_linewidths([2, 1])

        else:

            self.set_segments([list(line)])
            self.set_linestyles(['solid'])
            self.set_linewidths([2,])


def unitless(x):
    if hasattr(x, 'unit'):
        return x.value
    else:
        return x

def set_mpl_backend(func):
    # Note that we need to do this as a decorator because it needs to be done
    # before the @with_rc_defaults decorator triggers an import of
    # matplotlib.pyplot
    def wrapper(self, *args, **kwargs):
        if 'backend' in kwargs:
            import matplotlib as mpl
            try:
                mpl.switch_backend(kwargs['backend'])
            except AttributeError:
                mpl.use(kwargs['backend'])
        return func(self, *args, **kwargs)
    return wrapper


def with_rc_defaults(func):
    def wrapper(self, *args, **kwargs):
        import matplotlib.pyplot as plt
        with plt.style.context({}, after_reset=True):
            return func(self, *args, **kwargs)
    return wrapper


class PVSlicer(object):

    @set_mpl_backend
    @with_rc_defaults
    def __init__(self, filename_or_cube, backend=None, clim=None, cmap=None):

        try:
            from spectral_cube.spectral_cube import SpectralCube, BaseSpectralCube
            if hasattr(filename_or_cube, 'filled_data') or issubclass(filename_or_cube, BaseSpectralCube):
                cube = filename_or_cube
            else:
                cube = SpectralCube.read(filename_or_cube, format='fits')
            self.cube = cube
            self.array = self.cube
            self.shape = cube.shape
        except ImportError:
            warnings.warn("spectral_cube package is not available - using astropy.io.fits directly")
            from astropy.io import fits
            self.array = fits.getdata(filename_or_cube)
            self.shape = array.shape
            self.ok_mask = np.isfinite(self.array)
            if self.array.ndim != 3:
                raise ValueError("dataset does not have 3 dimensions (install the spectral_cube package to avoid this error)")

        import matplotlib.pyplot as plt

        self.fig = plt.figure(figsize=(8, 5))

        self.backend = plt.get_backend()

        logger = logging.getLogger(__name__)
        logger.info("Using Matplotlib backend: {0}".format(self.backend))

        self.cmap = cmap

        self.ax1 = self.fig.add_axes([0.1, 0.1, 0.4, 0.7], aspect='equal', adjustable='datalim')

        if clim is None:
            warnings.warn("clim not defined and will be determined from the data")
            # To work with large arrays, sub-sample the data
            # (but don't do it for small arrays)
            n1 = int(np.round(max(self.shape[0] / 10, 1)))
            n2 = int(np.round(max(self.shape[1] / 10, 1)))
            n3 = int(np.round(max(self.shape[2] / 10, 1)))
            if hasattr(self,'cube'):
                sub_cube = self.cube[::n1,::n2,::n3]
                cmin = sub_cube.min().value
                cmax = sub_cube.max().value
            else:
                sub_array = self.array[::n1,::n2,::n3]
                sub_mask = self.ok_mask[::n1,::n2,::n3]
                cmin = sub_array[sub_mask].min()
                cmax = sub_array[sub_mask].max()
            crange = cmax - cmin
            self._clim = (cmin - crange, cmax + crange)
        else:
            self._clim = clim

        self.slice = int(round(self.shape[0] / 2.))

        from matplotlib.widgets import Slider

        self.slice_slider_ax = self.fig.add_axes([0.1, 0.95, 0.4, 0.03])
        self.slice_slider_ax.set_xticklabels("")
        self.slice_slider_ax.set_yticklabels("")
        self.slice_slider = Slider(self.slice_slider_ax, "3-d slice", 0, self.shape[0]-1, valinit=self.slice, valfmt="%i")
        self.slice_slider.on_changed(self.update_slice)
        self.slice_slider.drawon = False

        self.image = self.ax1.imshow(unitless(self.array[self.slice, :,:]),
                                     origin='lower', interpolation='nearest',
                                     vmin=self._clim[0], vmax=self._clim[1],
                                     cmap=self.cmap)

        self.vmin_slider_ax = self.fig.add_axes([0.1, 0.90, 0.4, 0.03])
        self.vmin_slider_ax.set_xticklabels("")
        self.vmin_slider_ax.set_yticklabels("")
        self.vmin_slider = Slider(self.vmin_slider_ax, "vmin", self._clim[0], self._clim[1], valinit=self._clim[0])
        self.vmin_slider.on_changed(self.update_vmin)
        self.vmin_slider.drawon = False

        self.vmax_slider_ax = self.fig.add_axes([0.1, 0.85, 0.4, 0.03])
        self.vmax_slider_ax.set_xticklabels("")
        self.vmax_slider_ax.set_yticklabels("")
        self.vmax_slider = Slider(self.vmax_slider_ax, "vmax", self._clim[0], self._clim[1], valinit=self._clim[1])
        self.vmax_slider.on_changed(self.update_vmax)
        self.vmax_slider.drawon = False

        self.grid1 = None
        self.grid2 = None
        self.grid3 = None

        self.ax2 = self.fig.add_axes([0.55, 0.1, 0.4, 0.7])

        # Add slicing box
        self.box = SliceCurve(colors=(0.8, 0.0, 0.0))
        self.ax1.add_collection(self.box)
        self.movable = MovableSliceBox(self.box, callback=self.update_pv_slice)
        self.movable.connect()

        # Add save button
        from matplotlib.widgets import Button
        self.save_button_ax = self.fig.add_axes([0.65, 0.90, 0.20, 0.05])
        self.save_button = Button(self.save_button_ax, 'Save slice to FITS')
        self.save_button.on_clicked(self.save_fits)
        self.file_status_text = self.fig.text(0.75, 0.875, "", ha='center', va='center')
        self.set_file_status(None)

        self.set_file_status(None)
        self.pv_slice = None

        self.cidpress = self.fig.canvas.mpl_connect('button_press_event', self.click)

    @with_rc_defaults
    def set_file_status(self, status, filename=None):
        if status == 'instructions':
            self.file_status_text.set_text('Please enter filename in terminal')
            self.file_status_text.set_color('red')
        elif status == 'saved':
            self.file_status_text.set_text('File successfully saved to {0}'.format(filename))
            self.file_status_text.set_color('green')
        else:
            self.file_status_text.set_text('')
            self.file_status_text.set_color('black')
        self.fig.canvas.draw()

    @with_rc_defaults
    def click(self, event):

        if event.inaxes != self.ax2:
            return

        self.slice_slider.set_val(event.ydata)

    @with_rc_defaults
    def save_fits(self, *args, **kwargs):

        if self.pv_slice is None:
            return

        # When using Qt, we need to use a proper Qt save dialog since input()
        # does not play nicely with the Qt event loop.
        if self.backend.lower().startswith('qt'):
            from qtpy.compat import getsavefilename
            plot_name, _ = getsavefilename()
            if not plot_name:
                return
        else:
            self.set_file_status('instructions')

            print("Enter filename: ", end='')
            plot_name = str(input())

        from astropy.io import fits
        self.pv_slice.writeto(plot_name, overwrite=True)
        print("Saved file to: ", plot_name)

        self.set_file_status('saved', filename=plot_name)

    @with_rc_defaults
    def update_pv_slice(self, box):

        path = Path(zip(box.x, box.y))
        path.width = box.width

        self.pv_slice = extract_pv_slice(self.array, path)

        self.ax2.cla()
        self.ax2.imshow(self.pv_slice.data, origin='lower', aspect='auto',
                        interpolation='nearest', cmap=self.cmap)

        self.fig.canvas.draw()

    @with_rc_defaults
    def show(self, block=True):
        import matplotlib.pyplot as plt
        plt.show(block=block)

    @with_rc_defaults
    def update_slice(self, pos=None):

        if self.array.ndim == 2:
            self.image.set_array(unitless(self.array))
        else:
            self.slice = int(round(pos))
            self.image.set_array(unitless(self.array[self.slice, :, :]))

        self.fig.canvas.draw()

    @with_rc_defaults
    def update_vmin(self, vmin):
        if vmin > self._clim[1]:
            self._clim = (self._clim[1], self._clim[1])
        else:
            self._clim = (vmin, self._clim[1])
        self.image.set_clim(*self._clim)
        self.fig.canvas.draw()

    @with_rc_defaults
    def update_vmax(self, vmax):
        if vmax < self._clim[0]:
            self._clim = (self._clim[0], self._clim[0])
        else:
            self._clim = (self._clim[0], vmax)
        self.image.set_clim(*self._clim)
        self.fig.canvas.draw()

    @with_rc_defaults
    def close(self):
        import matplotlib.pyplot as plt
        plt.close(self.fig)
