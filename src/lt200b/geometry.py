"""Physical print geometry of the Dymo LetraTag LT200B.

The values are calibrated against measured printouts:

* the 32-dot thermal head prints a ~5.2 mm band on the 12 mm tape
  (0.161 mm per dot); the remaining tape width stays blank
* each raster column is doubled in the print data to match the stepper
  motor cadence, so one data row covers half a physical feed line
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintGeometry:
    """Dimensions and conversion factors between millimeters and print dots."""

    tape_width_mm: float = 12.0
    print_span_mm: float = 5.16
    head_dots: int = 32
    margin_mm: float = 2.0
    render_scale: int = 4
    preview_px_per_mm: int = 8

    @property
    def dots_per_mm(self) -> float:
        """Print head dots per millimeter of the printed band."""
        return self.head_dots / self.print_span_mm

    @property
    def across_dot_mm(self) -> float:
        """Size of one head dot across the tape."""
        return self.print_span_mm / self.head_dots

    @property
    def data_feed_mm(self) -> float:
        """Paper advance covered by one row of print data."""
        return self.across_dot_mm / 2

    @property
    def margin_rows(self) -> int:
        """Blank data rows fed before and after the label."""
        return round(self.margin_mm / self.data_feed_mm)

    @property
    def canvas_height_px(self) -> int:
        """Height of the render canvas: one head column at render scale."""
        return self.head_dots * self.render_scale

    @property
    def tape_dots_total(self) -> int:
        """Full tape width expressed in head-dot sized units."""
        return round(self.tape_width_mm / self.across_dot_mm)

    def mm_to_canvas_px(self, mm: float) -> int:
        """Convert millimeters to canvas pixels at the render scale."""
        return round(mm * self.dots_per_mm * self.render_scale)


DEFAULT_GEOMETRY = PrintGeometry()
