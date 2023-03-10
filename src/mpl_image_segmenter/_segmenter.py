from __future__ import annotations

from numbers import Integral
from typing import TYPE_CHECKING

import numpy as np
from matplotlib import __version__ as mpl_version
from matplotlib import get_backend
from matplotlib.colors import TABLEAU_COLORS, XKCD_COLORS, to_rgba_array
from matplotlib.path import Path
from matplotlib.pyplot import ioff, subplots
from matplotlib.widgets import LassoSelector
from mpl_pan_zoom import PanManager, zoom_factory

if TYPE_CHECKING:
    from typing import Any


class ImageSegmenter:
    """Manually segment an image with the lasso selector."""

    def __init__(  # type: ignore
        self,
        img,
        classes=1,
        mask=None,
        mask_colors=None,
        mask_alpha=0.75,
        props=None,
        lasso_mousebutton="left",
        pan_mousebutton="middle",
        ax=None,
        figsize=(10, 10),
        **kwargs,
    ):
        """
        Manually segment an image.

        Parameters
        ----------
        img : array_like
            A valid argument to imshow
        classes : int, iterable[string], default 1
            If a number How many classes to have in the mask.
        mask : arraylike, optional
            If you want to pre-seed the mask
        mask_colors : None, color, or array of colors, optional
            the colors to use for each class. Unselected regions will always be
            totally transparent
        mask_alpha : float, default .75
            The alpha values to use for selected regions. This will always override
            the alpha values in mask_colors if any were passed
        props : dict, default: None
            props passed to LassoSelector. If None the default values are:
            {"color": "black", "linewidth": 1, "alpha": 0.8}
        lasso_mousebutton : str, or int, default: "left"
            The mouse button to use for drawing the selecting lasso.
        pan_mousebutton : str, or int, default: "middle"
            The button to use for `~mpl_interactions.generic.panhandler`. One of
            'left', 'middle', 'right', or 1, 2, 3 respectively.
        ax : `matplotlib.axes.Axes`, optional
            The axis on which to plot. If *None* a new figure will be created.
        figsize : (float, float), optional
            passed to plt.figure. Ignored if *ax* is given.
        **kwargs
            All other kwargs will passed to the imshow command for the image
        """
        # ensure mask colors is iterable and the same length as the number of classes
        # choose colors from default color cycle?

        self.mask_alpha = mask_alpha

        if isinstance(classes, Integral):
            self._classes: list[str | int] = list(range(classes))
        else:
            self._classes = classes
        self._n_classes = len(self._classes)
        if mask_colors is None:
            if self._n_classes <= 10:
                # There are only 10 tableau colors
                self.mask_colors = to_rgba_array(
                    list(TABLEAU_COLORS)[: self._n_classes]
                )
            else:
                # up to 949 classes. Hopefully that is always enough....
                self.mask_colors = to_rgba_array(list(XKCD_COLORS)[: self._n_classes])
        else:
            self.mask_colors = to_rgba_array(np.atleast_1d(mask_colors))
            # should probably check the shape here
        self.mask_colors[:, -1] = self.mask_alpha

        self._img = np.asarray(img)

        if mask is None:
            self.mask = np.zeros(self._img.shape[:2])
            """See :doc:`/examples/image-segmentation`."""
        else:
            self.mask = mask

        self._overlay = np.zeros((*self._img.shape[:2], 4))
        for i in range(self._n_classes + 1):
            idx = self.mask == i
            if i == 0:
                self._overlay[idx] = [0, 0, 0, 0]
            else:
                self._overlay[idx] = self.mask_colors[i - 1]
        if ax is not None:
            self.ax = ax
            self.fig = self.ax.figure
        else:
            with ioff():
                self.fig, self.ax = subplots(figsize=figsize)
        self.displayed = self.ax.imshow(self._img, **kwargs)
        self._mask = self.ax.imshow(self._overlay)

        default_props = {"color": "black", "linewidth": 1, "alpha": 0.8}
        if props is None:
            props = default_props

        useblit = False if "ipympl" in get_backend().lower() else True
        button_dict = {"left": 1, "middle": 2, "right": 3}
        if isinstance(pan_mousebutton, str):
            pan_mousebutton = button_dict[pan_mousebutton.lower()]
        if isinstance(lasso_mousebutton, str):
            lasso_mousebutton = button_dict[lasso_mousebutton.lower()]

        if mpl_version < "3.7":
            self.lasso = LassoSelector(
                self.ax,
                self._onselect,
                lineprops=props,
                useblit=useblit,
                button=lasso_mousebutton,
            )
        else:
            self.lasso = LassoSelector(
                self.ax,
                self._onselect,
                props=props,
                useblit=useblit,
                button=lasso_mousebutton,
            )
        self.lasso.set_visible(True)

        pix_x = np.arange(self._img.shape[0])
        pix_y = np.arange(self._img.shape[1])
        xv, yv = np.meshgrid(pix_y, pix_x)
        self.pix = np.vstack((xv.flatten(), yv.flatten())).T

        self._pm = PanManager(self.fig, button=pan_mousebutton)
        self.disconnect_zoom = zoom_factory(self.ax)
        self.current_class = 1
        self._erasing = False
        self._paths: dict[str, list[Path]] = {"adding": [], "erasing": []}

    @property
    def panmanager(self) -> PanManager:
        return self._pm

    @property
    def erasing(self) -> bool:
        return self._erasing

    @erasing.setter
    def erasing(self, val: bool) -> None:
        if not isinstance(val, bool):
            raise TypeError(f"Erasing must be a bool - got type {type(val)}")
        self._erasing = val

    @property
    def current_class(self) -> int | str:
        return self._classes[self._cur_class_idx - 1]

    @current_class.setter
    def current_class(self, val: int | str) -> None:
        if isinstance(val, str):
            if val not in self._classes:
                raise ValueError(f"{val} is not one of the classes: {self._classes}")
            # offset by one for the background
            self._cur_class_idx = self._classes.index(val) + 1
        elif isinstance(val, Integral):
            if 0 < val < self._n_classes + 1:
                self._cur_class_idx = val
            else:
                raise ValueError(
                    f"Current class must be bewteen 1 and {self._n_classes}."
                    " It cannot be 0 as 0 is the background."
                )

    def get_paths(self) -> dict[str, list[Path]]:
        """
        Get a dictionary of all the paths used to create the mask.

        Returns
        -------
        dict :
            With keys *adding* and *erasing* each containing a list of paths.
        """
        return self._paths

    def _onselect(self, verts: Any) -> None:
        p = Path(verts)
        self.indices = p.contains_points(self.pix, radius=0).reshape(self.mask.shape)
        if self._erasing:
            self.mask[self.indices] = 0
            self._overlay[self.indices] = [0, 0, 0, 0]
            self._paths["erasing"].append(p)
        else:
            self.mask[self.indices] = self._cur_class_idx
            self._overlay[self.indices] = self.mask_colors[self._cur_class_idx - 1]
            self._paths["adding"].append(p)

        self._mask.set_data(self._overlay)
        self.fig.canvas.draw_idle()

    def _ipython_display_(self) -> None:
        display(self.fig.canvas)  # type: ignore # noqa: F821
