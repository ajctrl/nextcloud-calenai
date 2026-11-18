import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

spec = importlib.util.spec_from_file_location("planner", Path(__file__).with_name("plan-images.py"))
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


class ImagePolicyTests(unittest.TestCase):
    schedule = (
        "## Currently supported versions\n"
        "| **49** | Hub | 2030-01-01 | 2031-01 | **49.0.1** (2030-01-15)\n"
        "## EOL Versions\n"
        "| **47** | Hub | 2028-01-01 | 2029-01 | 47.0.10\n"
    )

    def test_future_major_and_invalid_schedule(self):
        self.assertEqual(planner.support(self.schedule), ({49: (49, 0, 1)}, {47}))
        for invalid in ("", self.schedule.replace("**47**", "**49**"),
                        self.schedule.replace("49.0.1", "49.0.1-rc1")):
            with self.assertRaises(ValueError):
                planner.support(invalid)

    def test_latest_compatible_archive_per_major(self):
        archives = {}
        releases = []
        for version, low, high in (("2.0.0", "49.0.2", "49"), ("1.10.0", "49", "49"),
                                   ("1.9.0", "48", "49"), ("1.8.0", "47", "47")):
            manifest = (f"<info><id>calenai</id><version>{version}</version><dependencies>"
                        f'<nextcloud min-version="{low}" max-version="{high}"/></dependencies></info>').encode()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                entry = tarfile.TarInfo("calenai/appinfo/info.xml")
                entry.size = len(manifest)
                tar.addfile(entry, io.BytesIO(manifest))
            archives[version] = buf.getvalue()
            asset = {"name": f"calenai-{version}.tar.gz", "state": "uploaded",
                     "browser_download_url": version,
                     "digest": "sha256:" + hashlib.sha256(archives[version]).hexdigest()}
            releases.append({"tag_name": "v" + version, "draft": False, "prerelease": False,
                             "assets": [asset]})
        active = {48: (48, 0, 1), 49: (49, 0, 1), 50: (50, 0, 0)}
        with patch.object(planner, "get", side_effect=archives.__getitem__):
            chosen = planner.compatible_releases(active, list(reversed(releases)))
            self.assertEqual({major: pair[0] for major, pair in chosen.items()}, {48: "1.9.0", 49: "1.10.0"})
            def image(major, base):
                patch_version = 1 if base == "fpm-alpine" else 2
                return "sha256:" + "a" * 64, (major, 0, patch_version)

            with patch.object(planner, "base_image", side_effect=image):
                jobs = planner.plan({49: (49, 0, 2)}, releases, {})
                self.assertEqual({j["base"]: j["version"] for j in jobs},
                                 {"apache": "2.0.0", "fpm": "2.0.0", "fpm-alpine": "1.10.0"})
            archives["2.0.0"] += b"modified"
            with self.assertRaisesRegex(ValueError, "digest"):
                planner.compatible_releases(active, releases)

    def test_eol_versions_must_have_exclusively_expired_managed_tags(self):
        for tags, expected in [
            (["47", "47-apache", "47-calenai-1.2.7-apache-r3"], True),
            (["47-calenai-1.2.7-fpm-b" + "a" * 64], True),
            (["47", "49"], False), (["47", "manual"], False), ([], False),
        ]:
            item = {"metadata": {"container": {"tags": tags}}}
            self.assertEqual(planner.expired(item, {47}), expected)

    def test_cleanup_rechecks_each_version_before_deleting(self):
        def version(i, tags):
            return {"id": i, "metadata": {"container": {"tags": tags}}}

        original = [version(1, ["47"]), version(2, ["47-fpm"]), version(3, ["49"])]
        current = [json.dumps(version(1, ["47", "manual"])), json.dumps(original[1])]
        with (patch("sys.argv", ["plan-images.py", "--cleanup"]),
              patch.object(planner, "get", return_value=self.schedule.encode()),
              patch.object(planner, "pages", return_value=original),
              patch("subprocess.check_output", side_effect=current),
              patch("subprocess.run") as api):
            planner.main()
            api.assert_called_once_with(["gh", "api", "-X", "DELETE", planner.PACKAGE + "/2"], check=True)

    def test_cleanup_continues_after_delete_failure(self):
        versions = [{"id": number, "metadata": {"container": {"tags": [tag]}}}
                    for number, tag in ((1, "47"), (2, "47-fpm"))]
        with (patch("sys.argv", ["plan-images.py", "--cleanup"]),
              patch.object(planner, "get", return_value=self.schedule.encode()),
              patch.object(planner, "pages", return_value=versions),
              patch("subprocess.check_output", side_effect=map(json.dumps, versions)),
              patch("subprocess.run", side_effect=[subprocess.CalledProcessError(1, "gh"), None]) as api,
              self.assertRaisesRegex(SystemExit, r"version IDs: 1$")):
            planner.main()
        self.assertEqual(api.call_args_list, [
            call(["gh", "api", "-X", "DELETE", planner.PACKAGE + "/1"], check=True),
            call(["gh", "api", "-X", "DELETE", planner.PACKAGE + "/2"], check=True),
        ])

    def test_core_rollback_keeps_rolling_tags(self):
        published = {"35": "current", "35-apache": "current", "35-calenai-1.2.7-apache": "current"}
        with patch.object(planner, "published_core", return_value=(35, 0, 4)):
            for patch_number, expected in ((3, False), (4, True), (5, True)):
                allowed = planner.can_promote(["35-apache", "35"], 35, "-apache", "1.2.7",
                                              (35, 0, patch_number), published)
                self.assertEqual(allowed, expected)

    def test_core_rollback_keeps_fixed_tag_without_rolling_tags(self):
        fixed = "35-calenai-1.2.7-apache"
        published = {fixed: "current"}
        selected = {(35, "apache"): ("1.2.7", "checksum")}
        with (patch.object(planner, "published_core", return_value=(35, 0, 4)),
              patch.object(planner, "compatible_releases", return_value=selected),
              patch.object(planner, "base_image") as base_image):
            for patch_number in (3, 4, 5):
                with self.subTest(patch_number=patch_number):
                    base_image.return_value = ("sha256:" + "a" * 64, (35, 0, patch_number))
                    job, = planner.plan([35], [], published, ["apache"])
                    self.assertEqual(fixed in job["aliases"], patch_number >= 4)

    @patch.object(planner, "published_core", return_value=(49, 0, 1))
    def test_base_changes_and_alias_repair(self, _core):
        selected = {(49, base): ("1.2.7", "test-checksum") for base in planner.VARIANTS}
        chooser = patch.object(planner, "compatible_releases", return_value=selected)
        chooser.start()
        self.addCleanup(chooser.stop)
        with patch.object(planner, "base_image", return_value=("sha256:" + "a" * 64, (49, 0, 1))):
            jobs = planner.plan([49], [], {})
            self.assertEqual({j["base"] for j in jobs}, {"apache", "fpm", "fpm-alpine"})
            published = {tag: j["revision"] for j in jobs for tag in [*j["aliases"], j["revision"]]}
            self.assertEqual(planner.plan([49], [], published), [])
            del published["49"]
            repair, = planner.plan([49], [], published)
            self.assertFalse(repair["build"])
            self.assertEqual(repair["aliases"], ["49"])
            published["49"] = published["49-apache"] = "newer"
            published["49-calenai-1.10.0-apache-r3"] = "newer"
            self.assertEqual(planner.plan([49], [], published), [])
        with patch.object(planner, "base_image", return_value=("sha256:" + "b" * 64, (49, 0, 2))):
            self.assertTrue(all(job["build"] for job in planner.plan([49], [], published)))


if __name__ == "__main__":
    unittest.main()
