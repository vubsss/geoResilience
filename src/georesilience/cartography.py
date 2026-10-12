"""Shared map extent, metre scale bar, grid-north arrow and export styling."""

import math
import textwrap

import numpy as np
from pyproj import CRS


def map_canvas(frame):
    import matplotlib.pyplot as plt

    bounds = frame.total_bounds
    if not np.isfinite(bounds).all():
        bounds = (0, 0, 1, 1)
    xmin, ymin, xmax, ymax = bounds
    width, height = max(xmax-xmin, 1), max(ymax-ymin, 1)
    size = ((9, max(3.8, 9*height/width)) if width >= height else (max(3.8, 9*width/height), 9))
    fig, ax = plt.subplots(figsize=size)
    padding = max(width, height)*.08
    ax.set_xlim(xmin-padding, xmax+padding)
    ax.set_ylim(ymin-padding, ymax+padding)
    ax.set_aspect("equal")
    ax.set_autoscale_on(False)
    return fig, ax


def decorate_map(ax, crs, title, run_name=None):
    """Decorate the current fixed extent; scale uses projected CRS linear units."""
    name = str(run_name or "network run").encode("ascii", "backslashreplace").decode()
    name = " ".join(name.split())
    ax.set_title(textwrap.fill(title, 64) + "\n" + textwrap.fill(name, 64), fontsize=11, pad=12)
    ax.annotate("", xy=(.94, .88), xytext=(.94, .72), xycoords="axes fraction",
                arrowprops={"facecolor": "#222222", "edgecolor": "#222222", "width": 2, "headwidth": 8})
    ax.text(.94, .91, "N", transform=ax.transAxes, ha="center", fontsize=11, fontweight="bold")
    crs = CRS.from_user_input(crs)
    if crs.is_projected:
        factor = crs.axis_info[0].unit_conversion_factor
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        target = (xmax-xmin)*factor*.22
        exponent = 10**math.floor(math.log10(target))
        length = max(step*exponent for step in (1, 2, 5, 10) if step*exponent <= target)
        x, y = xmin+.06*(xmax-xmin), ymin+.06*(ymax-ymin)
        height = .008*(ymax-ymin)
        ax.plot([x, x+length/factor], [y, y], color="#222222", linewidth=3, solid_capstyle="butt", zorder=10)
        ax.plot([x, x], [y-height, y+height], color="#222222", linewidth=1, zorder=10)
        ax.plot([x+length/factor]*2, [y-height, y+height], color="#222222", linewidth=1, zorder=10)
        label = f"{length/1000:g} km" if length >= 1000 else f"{length:g} m"
        ax.text(x+length/factor/2, y+height*2, label, ha="center", va="bottom", fontsize=9, zorder=11,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85, "pad": 2})
    else:
        ax.text(.05, .06, "Scale unavailable: geographic CRS", transform=ax.transAxes, fontsize=8)
    ax.set_aspect("equal")
    ax.set_axis_off()


def finish_map(fig, ax, frame, title, path, run_name=None):
    import matplotlib.pyplot as plt

    decorate_map(ax, frame.crs, title, run_name)
    fig.savefig(path, bbox_inches="tight", dpi=180, facecolor="white")
    plt.close(fig)
