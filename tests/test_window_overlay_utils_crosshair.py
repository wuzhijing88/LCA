import unittest

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from ui.widgets.window_overlay_utils import (
    compute_dynamic_center_crosshair_style,
    draw_dynamic_center_crosshair,
)


class WindowOverlayUtilsCrosshairTests(unittest.TestCase):
    def test_compute_dynamic_center_crosshair_style_scales_with_rect_size(self):
        self.assertEqual(
            compute_dynamic_center_crosshair_style(QRect(0, 0, 10, 10)),
            (3, 1),
        )
        self.assertEqual(
            compute_dynamic_center_crosshair_style(QRect(0, 0, 100, 100)),
            (20, 3),
        )
        self.assertEqual(
            compute_dynamic_center_crosshair_style(QRect(0, 0, 400, 400)),
            (28, 3),
        )

    def test_draw_dynamic_center_crosshair_handles_tiny_rect_without_overflow(self):
        image = QImage(12, 12, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))

        painter = QPainter(image)
        draw_dynamic_center_crosshair(
            painter,
            QRect(2, 2, 4, 4),
            color=QColor(255, 0, 0),
            inset=1,
        )
        painter.end()

        drawn_pixels = 0
        for x in range(image.width()):
            for y in range(image.height()):
                if image.pixelColor(x, y).alpha() > 0:
                    drawn_pixels += 1

        self.assertGreater(drawn_pixels, 0)


if __name__ == "__main__":
    unittest.main()
