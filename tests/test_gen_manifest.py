import json
import os
import io
import importlib.util
import sys
import subprocess
import tempfile
from unittest import mock
import unittest
import zipfile
import zlib
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "gen_manifest.py"
SPEC = importlib.util.spec_from_file_location("gen_manifest", SCRIPT)
GEN_MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN_MANIFEST)



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
                            {"name": "remote", "title": "Remote", "crc32": "deadbeef"},
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
            entries = json.loads(
                (root / "repo.json").read_text(encoding="utf-8")
            )["packages"]
            names = [entry["name"] for entry in entries]
            self.assertEqual(names, ["keep", "remote"])
            keep = next(entry for entry in entries if entry["name"] == "keep")
            expected_crc = f"{zlib.crc32((root / 'zips' / 'keep.zip').read_bytes()) & 0xFFFFFFFF:08x}"
            self.assertEqual(keep["crc32"], expected_crc)
            remote = next(entry for entry in entries if entry["name"] == "remote")
            self.assertNotIn("crc32", remote)
            self.assertTrue((root / "packages" / "keep" / "manifest.install").exists())
            self.assertTrue((root / "packages" / "remote" / "info.json").exists())

    def test_non_quark_package_without_archive_fails_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "upload").mkdir()
            (root / "upload" / "missing.json").write_text(
                json.dumps(
                    {
                        "name": "missing",
                        "category": "nro",
                        "title": "Missing",
                        "description": "missing archive",
                        "author": "author",
                        "version": "1",
                    }
                ),
                encoding="utf-8",
            )
            (root / "zips").mkdir()
            (root / "repo.json").write_text(
                json.dumps({"packages": [{"name": "missing", "title": "Missing"}]}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nxStore 托管条目缺少 zips/missing.zip", result.stderr)

    def test_quark_package_without_archive_passes_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "upload").mkdir()
            (root / "zips").mkdir()
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
            (root / "repo.json").write_text('{"packages": []}', encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            entry = json.loads((root / "repo.json").read_text(encoding="utf-8"))["packages"][0]
            self.assertEqual(entry["name"], "remote")
            self.assertNotIn("crc32", entry)
    def test_github_token_prefers_environment_and_falls_back_to_local_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gh_token.txt"
            token_path.write_text("file-token\n", encoding="utf-8")
            original_path = GEN_MANIFEST.GITHUB_TOKEN_FILE
            original_env = os.environ.get("GH_TOKEN")
            try:
                GEN_MANIFEST.GITHUB_TOKEN_FILE = str(token_path)
                os.environ.pop("GH_TOKEN", None)
                self.assertEqual(GEN_MANIFEST.github_auth_token(), "file-token")
                os.environ["GH_TOKEN"] = "env-token"
                self.assertEqual(GEN_MANIFEST.github_auth_token(), "env-token")
            finally:
                GEN_MANIFEST.GITHUB_TOKEN_FILE = original_path
                if original_env is None:
                    os.environ.pop("GH_TOKEN", None)
                else:
                    os.environ["GH_TOKEN"] = original_env

    def test_default_repo_root_is_script_parent(self):
        self.assertEqual(
            Path(GEN_MANIFEST.GITHUB_TOKEN_FILE).parent,
            SCRIPT.parents[1],
        )

    def test_same_version_replaced_github_asset_refreshes_archive_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "upload").mkdir()
            (root / "zips").mkdir()
            package_dir = root / "packages" / "pkg"
            package_dir.mkdir(parents=True)
            (root / "upload" / "pkg.json").write_text(
                json.dumps(
                    {
                        "name": "pkg",
                        "category": "nro",
                        "title": "Package",
                        "description": "package",
                        "author": "owner",
                        "github_url": "https://github.com/owner/pkg",
                    }
                ),
                encoding="utf-8",
            )
            with zipfile.ZipFile(root / "zips" / "pkg.zip", "w") as archive:
                archive.writestr("switch/pkg/pkg.nro", b"old")
            (package_dir / "info.json").write_text(
                json.dumps({"version": "1.0.0"}), encoding="utf-8"
            )
            cache_path = root / ".github" / "github-asset-cache.json"
            cache_path.parent.mkdir()
            cache_path.write_text(
                json.dumps(
                    {"packages": {"pkg": {"version": "1.0.0", "asset_id": 100}}}
                ),
                encoding="utf-8",
            )

            updated = io.BytesIO()
            with zipfile.ZipFile(updated, "w") as archive:
                archive.writestr("switch/pkg/pkg.nro", b"new")

            with mock.patch.object(
                GEN_MANIFEST,
                "github_latest_assets",
                return_value=(
                    "1.0.0",
                    [("pkg.zip", "https://example.invalid/pkg.zip", 200)],
                ),
            ), mock.patch.object(
                GEN_MANIFEST.urllib.request,
                "urlopen",
                return_value=io.BytesIO(updated.getvalue()),
            ):
                GEN_MANIFEST.process_upload(str(root), False)

            with zipfile.ZipFile(root / "zips" / "pkg.zip") as archive:
                self.assertEqual(archive.read("switch/pkg/pkg.nro"), b"new")
            info = json.loads((package_dir / "info.json").read_text(encoding="utf-8"))
            self.assertEqual(info, {"version": "1.0.0"})
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(
                cache,
                {"packages": {"pkg": {"version": "1.0.0", "asset_id": 200}}},
            )

    def test_same_github_asset_id_skips_archive_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "upload").mkdir()
            (root / "zips").mkdir()
            package_dir = root / "packages" / "pkg"
            package_dir.mkdir(parents=True)
            (root / "upload" / "pkg.json").write_text(
                json.dumps(
                    {
                        "name": "pkg",
                        "category": "nro",
                        "title": "Package",
                        "description": "package",
                        "author": "owner",
                        "github_url": "https://github.com/owner/pkg",
                    }
                ),
                encoding="utf-8",
            )
            with zipfile.ZipFile(root / "zips" / "pkg.zip", "w") as archive:
                archive.writestr("switch/pkg/pkg.nro", b"current")
            (package_dir / "info.json").write_text(
                json.dumps({"version": "1.0.0"}), encoding="utf-8"
            )
            cache_path = root / ".github" / "github-asset-cache.json"
            cache_path.parent.mkdir()
            cache_path.write_text(
                json.dumps(
                    {"packages": {"pkg": {"version": "1.0.0", "asset_id": 200}}}
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                GEN_MANIFEST,
                "github_latest_assets",
                return_value=(
                    "1.0.0",
                    [("pkg.zip", "https://example.invalid/pkg.zip", 200)],
                ),
            ), mock.patch.object(
                GEN_MANIFEST.urllib.request,
                "urlopen",
                side_effect=AssertionError("unchanged asset must not download"),
            ):
                GEN_MANIFEST.process_upload(str(root), False)

            with zipfile.ZipFile(root / "zips" / "pkg.zip") as archive:
                self.assertEqual(archive.read("switch/pkg/pkg.nro"), b"current")
            info = json.loads((package_dir / "info.json").read_text(encoding="utf-8"))
            self.assertEqual(info, {"version": "1.0.0"})
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(
                cache,
                {"packages": {"pkg": {"version": "1.0.0", "asset_id": 200}}},
            )

    def test_migrates_legacy_asset_id_out_of_info_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "packages" / "pkg"
            package_dir.mkdir(parents=True)
            info_path = package_dir / "info.json"
            info_path.write_text(
                json.dumps({"version": "1.0.0", "github_asset_id": 200}),
                encoding="utf-8",
            )

            cache = GEN_MANIFEST.load_github_asset_cache(str(root))
            changed = GEN_MANIFEST.migrate_info_asset_ids(str(root), cache, False)
            GEN_MANIFEST.write_github_asset_cache(str(root), cache)

            self.assertTrue(changed)
            self.assertEqual(
                json.loads(info_path.read_text(encoding="utf-8")),
                {"version": "1.0.0"},
            )
            self.assertEqual(
                json.loads(
                    (root / ".github" / "github-asset-cache.json").read_text(
                        encoding="utf-8"
                    )
                ),
                {"packages": {"pkg": {"version": "1.0.0", "asset_id": 200}}},
            )

if __name__ == "__main__":
    unittest.main()
