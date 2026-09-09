import importlib.util
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
BUILD_SCRIPT = PROJECT_ROOT / "tools" / "build_customer_release.py"
RUNTIME_SCRIPT = SCRIPTS_ROOT / "ctrip_runtime.py"
SETUP_SCRIPT = SCRIPTS_ROOT / "ctrip_runtime_setup.py"
LAUNCHER_SCRIPT = SCRIPTS_ROOT / "ctrip_cloak_launcher.py"


def load_module(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CustomerReleaseTests(unittest.TestCase):
    @staticmethod
    def make_browser_bundle(root: Path) -> tuple[Path, Path]:
        bundle = root / "browser-source"
        browser_binary = (
            bundle / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
        )
        browser_binary.parent.mkdir(parents=True)
        browser_binary.write_bytes(b"browser-binary")
        browser_binary.chmod(0o755)
        return bundle, browser_binary

    def test_compiled_layout_resolves_the_customer_package_root(self):
        runtime = load_module("ctrip_runtime_release_path", RUNTIME_SCRIPT)
        package_root = Path("/tmp/customer-skill")

        resolved = runtime.resolve_skill_dir(
            environ={},
            executable_path=package_root / "bin" / "ctrip-agent",
            module_path=Path("/tmp/onefile-extract/ctrip_runtime.py"),
        )

        self.assertEqual(resolved, package_root.resolve())

    def test_explicit_skill_dir_takes_priority_over_binary_location(self):
        runtime = load_module("ctrip_runtime_override", RUNTIME_SCRIPT)

        resolved = runtime.resolve_skill_dir(
            environ={"CTRIP_SKILL_DIR": "/tmp/explicit-skill"},
            executable_path="/tmp/other/bin/ctrip-agent",
            module_path="/tmp/source/scripts/ctrip_runtime.py",
        )

        self.assertEqual(resolved, Path("/tmp/explicit-skill").resolve())

    def test_runtime_finds_the_browser_shipped_in_the_customer_package(self):
        runtime = load_module("ctrip_runtime_bundled_browser", RUNTIME_SCRIPT)
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            _, expected = self.make_browser_bundle(package_root)
            (package_root / "browser-source").rename(package_root / "browser")
            expected = package_root / "browser" / expected.relative_to(
                package_root / "browser-source"
            )

            resolved = runtime.bundled_browser_binary(
                skill_dir=package_root,
                system="Darwin",
            )

        self.assertEqual(resolved, expected.resolve())

    def test_native_setup_checks_browser_binary_and_playwright_driver(self):
        setup = load_module("ctrip_runtime_setup_success", SETUP_SCRIPT)

        class Playwright:
            stopped = False

            def stop(self):
                self.stopped = True

        playwright = Playwright()

        class Manager:
            def start(self):
                return playwright

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            browser_binary = root / "Chromium"
            browser_binary.write_text("binary", encoding="utf-8")
            commands = []

            def run_command(command, **_kwargs):
                commands.append(command)
                return SimpleNamespace(returncode=0, stdout="Chromium", stderr="")

            with patch.dict(os.environ, {}, clear=True):
                result = setup.setup_runtime(
                    cache_dir=root / "cache",
                    ensure_binary_fn=lambda: str(browser_binary),
                    run_command=run_command,
                    playwright_factory=Manager,
                )

        self.assertEqual(result, browser_binary.resolve())
        self.assertEqual(commands[0][0], str(browser_binary.resolve()))
        self.assertTrue(playwright.stopped)

    def test_native_setup_uses_bundled_browser_without_reading_proxy_settings(self):
        setup = load_module("ctrip_runtime_setup_offline", SETUP_SCRIPT)

        class Manager:
            def start(self):
                return SimpleNamespace(stop=lambda: None)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            browser_binary = root / "Chromium"
            browser_binary.write_text("binary", encoding="utf-8")

            def ensure_binary():
                self.assertEqual(
                    os.environ.get("CLOAKBROWSER_BINARY_PATH"),
                    str(browser_binary),
                )
                return str(browser_binary)

            with (
                patch.dict(
                    os.environ,
                    {"NO_PROXY": "http://[::1"},
                    clear=True,
                ),
                patch.object(
                    setup,
                    "bundled_browser_binary",
                    return_value=browser_binary,
                ),
                patch.object(
                    setup,
                    "invalid_proxy_environment_variable",
                    side_effect=AssertionError("offline setup read proxy settings"),
                ),
            ):
                result = setup.setup_runtime(
                    cache_dir=root / "cache",
                    ensure_binary_fn=ensure_binary,
                    run_command=lambda *_args, **_kwargs: SimpleNamespace(
                        returncode=0,
                        stdout="Chromium",
                        stderr="",
                    ),
                    playwright_factory=Manager,
                )

        self.assertEqual(result, browser_binary.resolve())

    def test_launcher_prefers_the_browser_shipped_in_the_customer_package(self):
        launcher = load_module("ctrip_cloak_launcher_offline", LAUNCHER_SCRIPT)
        browser_binary = Path("/tmp/customer/browser/chrome")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                launcher,
                "bundled_browser_binary",
                return_value=browser_binary,
            ),
        ):
            launcher.configure_cloakbrowser_cache()
            configured = os.environ.get("CLOAKBROWSER_BINARY_PATH")

        self.assertEqual(configured, str(browser_binary))

    def test_native_setup_rejects_invalid_no_proxy_without_exposing_value(self):
        setup = load_module("ctrip_runtime_setup_proxy", SETUP_SCRIPT)
        invalid_value = "http://[::1"

        with (
            patch.dict(os.environ, {"NO_PROXY": invalid_value}, clear=True),
            patch("httpx.Client", side_effect=ValueError("invalid proxy")),
        ):
            variable = setup.invalid_proxy_environment_variable()

        self.assertEqual(variable, "NO_PROXY")
        self.assertNotIn(invalid_value, str(variable))

    def test_native_setup_turns_download_failure_into_customer_guidance(self):
        setup = load_module("ctrip_runtime_setup_download", SETUP_SCRIPT)

        class Manager:
            def start(self):
                return SimpleNamespace(stop=lambda: None)

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "下载失败.*TimeoutError") as context,
        ):
            setup.setup_runtime(
                cache_dir=Path(temporary_directory),
                ensure_binary_fn=lambda: (_ for _ in ()).throw(
                    TimeoutError("https://secret.example.invalid")
                ),
                playwright_factory=Manager,
            )

        self.assertNotIn("secret.example.invalid", str(context.exception))

    def test_native_setup_excel_probe_writes_and_reads_a_workbook(self):
        setup = load_module("ctrip_runtime_setup_excel", SETUP_SCRIPT)

        setup._probe_excel_engine()

    def test_release_zip_has_runner_and_no_python_source(self):
        builder = load_module("build_customer_release_stage", BUILD_SCRIPT)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            binary = root / "ctrip-agent"
            binary.write_bytes(b"native-binary")
            browser_bundle, _ = self.make_browser_bundle(root)
            stage = root / "stage"
            builder.stage_release(
                binary,
                stage,
                "macos-arm64",
                browser_bundle=browser_bundle,
            )
            archive = builder.create_zip(
                stage,
                root / "customer.zip",
                "macos-arm64",
            )

            with zipfile.ZipFile(archive) as release_zip:
                names = release_zip.namelist()

        self.assertIn(
            "ctrip-hotel-price-collector/bin/ctrip-agent",
            names,
        )
        self.assertIn(
            "ctrip-hotel-price-collector/browser/Chromium.app/Contents/MacOS/Chromium",
            names,
        )
        self.assertIn("ctrip-hotel-price-collector/install.sh", names)
        self.assertFalse(any(name.endswith((".py", ".pyc", ".pyo")) for name in names))
        self.assertFalse(any("/tests/" in name or "/tools/" in name for name in names))
        self.assertFalse(any("requirements-" in name for name in names))

    def test_release_zip_preserves_browser_directory_symlinks(self):
        builder = load_module("build_customer_release_symlink", BUILD_SCRIPT)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            binary = root / "ctrip-agent"
            binary.write_bytes(b"native-binary")
            browser_bundle, _ = self.make_browser_bundle(root)
            versions = (
                browser_bundle
                / "Chromium.app"
                / "Contents"
                / "Frameworks"
                / "Test.framework"
                / "Versions"
            )
            (versions / "145").mkdir(parents=True)
            (versions / "Current").symlink_to("145", target_is_directory=True)
            stage = root / "stage"
            builder.stage_release(
                binary,
                stage,
                "macos-arm64",
                browser_bundle=browser_bundle,
            )
            archive = builder.create_zip(stage, root / "customer.zip", "macos-arm64")
            symlink_name = (
                "ctrip-hotel-price-collector/browser/Chromium.app/Contents/"
                "Frameworks/Test.framework/Versions/Current"
            )

            with zipfile.ZipFile(archive) as release_zip:
                info = release_zip.getinfo(symlink_name)
                link_target = release_zip.read(symlink_name).decode("utf-8")

        self.assertTrue(stat.S_ISLNK(info.external_attr >> 16))
        self.assertEqual(link_target, "145")

    def test_release_validator_requires_the_bundled_browser(self):
        builder = load_module("build_customer_release_browser_required", BUILD_SCRIPT)
        with self.assertRaisesRegex(RuntimeError, "browser/Chromium"):
            builder.validate_release_members(
                [
                    "README.md",
                    "SKILL.md",
                    "ctrip_hotel_config.json",
                    "install.sh",
                    "bin/ctrip-agent",
                ],
                "macos-arm64",
            )

    def test_release_validator_rejects_source_files(self):
        builder = load_module("build_customer_release_validator", BUILD_SCRIPT)
        with self.assertRaisesRegex(RuntimeError, "Python"):
            builder.validate_release_members(
                [
                    "README.md",
                    "SKILL.md",
                    "ctrip_hotel_config.json",
                    "install.sh",
                    "bin/ctrip-agent",
                    "scripts/ctrip_cli.py",
                ],
                "macos-arm64",
            )

    def test_nuitka_build_embeds_runtime_packages_and_playwright_driver(self):
        builder = load_module("build_customer_release_command", BUILD_SCRIPT)
        command = builder.nuitka_command(Path("/tmp/build"), "windows-x64")
        command_text = "\n".join(map(str, command))

        self.assertIn("--mode=onefile", command)
        self.assertIn("--include-package=cloakbrowser", command)
        self.assertIn("--include-package=playwright.sync_api", command)
        self.assertIn("--include-package=playwright._impl", command)
        self.assertIn("--include-package=openpyxl", command)
        self.assertIn("--include-package=socksio", command)
        self.assertNotIn("--include-data-dir", command_text)
        self.assertIn("--output-filename=ctrip-agent.exe", command)

    def test_customer_installers_do_not_invoke_python(self):
        shell_installer = (PROJECT_ROOT / "packaging" / "install.sh").read_text(
            encoding="utf-8"
        )
        windows_installer = (PROJECT_ROOT / "packaging" / "install.cmd").read_text(
            encoding="utf-8"
        )

        self.assertIn('"$RUNNER" setup', shell_installer)
        self.assertIn('"%RUNNER%" setup', windows_installer)
        self.assertIn("BROWSER_DIR", shell_installer)
        self.assertIn("browser\\chrome.exe", windows_installer)
        self.assertNotIn("python", shell_installer.lower())
        self.assertNotIn("python", windows_installer.lower())


if __name__ == "__main__":
    unittest.main()
