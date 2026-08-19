import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "tools" / "icon_convertor.py"


class IconConvertorTests(unittest.TestCase):
    def test_resizes_jpg_and_converts_png_without_rewriting_128_jpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()

            Image.new("RGB", (256, 256), (255, 0, 0)).save(nested / "large.jpg", quality=100)
            Image.new("RGB", (128, 128), (0, 255, 0)).save(nested / "ready.jpg", quality=100)
            ready_before = (nested / "ready.jpg").read_bytes()
            Image.new("RGBA", (256, 256), (0, 0, 255, 128)).save(nested / "alpha.png")
            Image.new("RGB", (64, 64), (255, 255, 0)).save(nested / "small.jpeg")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            with Image.open(nested / "large.jpg") as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.format, "JPEG")
            self.assertEqual((nested / "ready.jpg").read_bytes(), ready_before)
            self.assertFalse((nested / "alpha.png").exists())
            self.assertFalse((nested / "small.jpeg").exists())
            with Image.open(nested / "alpha.jpg") as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.format, "JPEG")
            with Image.open(nested / "small.jpg") as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.format, "JPEG")


if __name__ == "__main__":
    unittest.main()
