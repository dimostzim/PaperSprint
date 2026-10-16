import tempfile
import unittest
from pathlib import Path

import fitz

from app.figures import prepare_visuals
from app.paper_processing import extract_pdf


class PrepareVisualsTests(unittest.TestCase):
    def test_detected_table_is_rendered_as_a_visual(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "table.pdf"
            with fitz.open() as doc:
                page = doc.new_page(width=300, height=300)
                for x in (40, 140, 240):
                    page.draw_line((x, 60), (x, 140))
                for y in (60, 100, 140):
                    page.draw_line((40, y), (240, y))
                for x, y, text in (
                    (50, 85, "Group"),
                    (150, 85, "Count"),
                    (50, 125, "A"),
                    (150, 125, "12"),
                ):
                    page.insert_text((x, y), text)
                doc.save(pdf_path)

            visuals = prepare_visuals(
                pdf_path, extract_pdf(pdf_path), root / "figures", "table"
            )

            self.assertEqual(len(visuals), 1)
            visual = visuals[0]
            self.assertEqual(visual["page_number"], 1)
            self.assertEqual(visual["rects"], [[40.0, 60.0, 240.0, 140.0]])
            self.assertEqual(visual["bbox_pct"], [13.33, 20.0, 80.0, 46.67])
            image = fitz.Pixmap(visual["image_path"])
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)


if __name__ == "__main__":
    unittest.main()
