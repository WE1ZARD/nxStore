import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "gen_manifest.py"


class GenManifestRemovalTests(unittest.TestCase):
    def test_removed_upload_package_is_deleted_from_outputs_and_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "upload").mkdir()
            (root / "zips").mkdir()
            removed_package = root / "packages" / "removed"
            removed_package.mkdir(parents=True)
            (removed_package / "info.json").write_text('{"version":"1"}', encoding="utf-8")
            (removed_package / "manifest.install").write_text("U: old.nro\n", encoding="utf-8")
            (removed_package / "icon.jpg").write_bytes(b"old icon")

            with zipfile.ZipFile(root / "zips" / "keep.zip", "w") as archive:
                archive.writestr("switch/keep/keep.nro", b"keep")
            with zipfile.ZipFile(root / "zips" / "removed.zip", "w") as archive:
                archive.writestr("switch/removed/removed.nro", b"removed")

            (root / "upload" / "keep.json").write_text(
                json.dumps(
                    {
                        "name": "keep",
                        "category": "nro",
                        "title": "Keep",
                        "description": "kept package",
                        "author": "author",
                        "version": "1",
                    }
                ),
                encoding="utf-8",
            )
            (root / "upload" / "remote.json").write_text(
                json.dumps(
                    {
                        "name": "remote",
                        "category": "nro",
                        "title": "Remote",
                        "description": "remote package",
                        "author": "author",
                        "version": "1",
                        "quark_url": "share-id",
                        "custom_dir": "switch/remote",
                        "uninstall_dir": "switch/remote",
                    }
                ),
                encoding="utf-8",
            )
            (root / "packages" / "remote").mkdir(parents=True)
            (root / "packages" / "remote" / "info.json").write_text(
                '{"version":"1"}', encoding="utf-8"
            )
            (root / "repo.json").write_text(
                json.dumps(
                    {
                        "packages": [
                            {"name": "keep", "title": "old"},
                            {"name": "remote", "title": "Remote"},
                            {"name": "removed", "title": "Removed"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(root)],
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("removed", result.stdout)
            self.assertFalse((root / "packages" / "removed").exists())
            self.assertFalse((root / "zips" / "removed.zip").exists())
            names = [
                entry["name"]
                for entry in json.loads((root / "repo.json").read_text(encoding="utf-8"))["packages"]
            ]
            self.assertEqual(names, ["keep", "remote"])
            self.assertTrue((root / "packages" / "keep" / "manifest.install").exists())
            self.assertTrue((root / "packages" / "remote" / "info.json").exists())


if __name__ == "__main__":
    unittest.main()
