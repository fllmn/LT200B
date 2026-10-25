from lt200b.geometry import DEFAULT_GEOMETRY, PrintGeometry


def test_calibration_values() -> None:
    geometry = DEFAULT_GEOMETRY
    assert geometry.tape_width_mm == 12.0
    assert geometry.head_dots == 32
    assert geometry.dots_per_mm == 32 / 5.16
    assert geometry.across_dot_mm == 5.16 / 32
    # each raster column is doubled for the stepper cadence
    assert geometry.data_feed_mm == geometry.across_dot_mm / 2


def test_margin_rows_match_two_mm() -> None:
    geometry = DEFAULT_GEOMETRY
    assert geometry.margin_mm == 2.0
    assert geometry.margin_rows == 25  # 2 mm / 0.0806 mm per data row


def test_canvas_height_is_full_head_column() -> None:
    assert DEFAULT_GEOMETRY.canvas_height_px == 32 * 4


def test_tape_dots_total_covers_full_tape() -> None:
    geometry = DEFAULT_GEOMETRY
    assert geometry.tape_dots_total == round(12.0 / geometry.across_dot_mm)
    # the full tape is wider than the printable span
    assert geometry.tape_dots_total > geometry.head_dots


def test_mm_to_canvas_px() -> None:
    geometry = PrintGeometry()
    assert geometry.mm_to_canvas_px(1.0) == round(geometry.dots_per_mm * geometry.render_scale)
    # the full print span maps onto the full head width
    assert geometry.mm_to_canvas_px(geometry.print_span_mm) == geometry.head_dots * geometry.render_scale
