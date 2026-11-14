"""Regenerate preview-independent equation SVGs with Matplotlib."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
plt.rcParams.update({"svg.fonttype": "path", "svg.hashsalt": "road-closure-equations"})


def equation(name, expression):
    fig = plt.figure(figsize=(9, 1))
    fig.text(.02, .5, expression, fontsize=19, color="black", va="center")
    save(fig, name)


def piecewise(name, prefix, first, second):
    fig = plt.figure(figsize=(9, 1.6))
    label = fig.text(.02, .5, prefix, fontsize=19, color="black", va="center")
    fig.canvas.draw()
    right = label.get_window_extent().transformed(fig.transFigure.inverted()).x1
    fig.text(right + .012, .5, "{", fontsize=65, color="black", va="center")
    fig.text(right + .065, .76, first, fontsize=19, color="black", va="center")
    fig.text(right + .065, .25, second, fontsize=19, color="black", va="center")
    save(fig, name)


def save(fig, name):
    target = OUT / f"{name}.svg"
    fig.savefig(target, bbox_inches="tight", pad_inches=.16,
                facecolor="white", metadata={"Date": None})
    plt.close(fig)
    target.write_text("\n".join(line.rstrip() for line in target.read_text().splitlines()) + "\n")


if __name__ == "__main__":
    equation("rainfall", r"$P = \bar{r}T$")
    equation("retention", r"$S = \frac{25400}{\mathrm{CN}} - 254,\qquad I_a = 0.2S$")
    piecewise("runoff", r"$Q(P) =$", r"$0,\quad P\leq I_a$",
              r"$\frac{(P-I_a)^2}{P+0.8S},\quad P>I_a$")
    equation("road_depth", r"$d_i = \max_{x\in i,\,t} D(x,t)$")
    equation("threshold", r"$C_i \sim \mathrm{Lognormal}(\ln\theta,\,\beta^2)$")
    piecewise("fragility", r"$q_i = \Pr(C_i\leq d_i) =$", r"$0,\quad d_i=0$",
              r"$\Phi\left(\frac{\ln(d_i/\theta)}{\beta}\right),\quad d_i>0$")
    equation("partial_coverage", r"$p_i = q_i + (1-q_i)p_u = 1-(1-q_i)(1-p_u)$")
