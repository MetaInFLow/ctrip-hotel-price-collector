import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"


def load_module(name: str, filename: str):
    path = SCRIPTS_ROOT / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePage:
    def __init__(self, url: str):
        self.url = url
        self.calls = []

    def bring_to_front(self):
        self.calls.append(("bring_to_front",))

    def evaluate(self, expression):
        self.calls.append(("evaluate", expression))


class CliModuleTests(unittest.TestCase):
    def test_focus_page_bring_to_front_and_request_window_focus(self):
        browser_module = load_module("ctrip_cli_browser", "ctrip_cli_browser.py")
        page = FakePage("https://www.ctrip.com/")

        result = browser_module.focus_page(page)

        self.assertIs(result, page)
        self.assertEqual(page.calls[0], ("bring_to_front",))
        self.assertEqual(page.calls[1], ("evaluate", "window.focus()"))

    def test_focus_page_keeps_page_usable_when_window_focus_is_unavailable(self):
        browser_module = load_module("ctrip_cli_browser_fallback", "ctrip_cli_browser.py")

        class NoWindowFocusPage(FakePage):
            def evaluate(self, expression):
                self.calls.append(("evaluate", expression))
                raise RuntimeError("window focus unavailable")

        page = NoWindowFocusPage("https://hotels.ctrip.com/")

        self.assertIs(browser_module.focus_page(page), page)
        self.assertEqual(
            page.calls,
            [("bring_to_front",), ("evaluate", "window.focus()")],
        )

    def test_cli_parser_exposes_atomic_ctrip_commands(self):
        cli_module = load_module("ctrip_cli", "ctrip_cli.py")
        parser = cli_module.build_parser()

        self.assertEqual(
            cli_module.command_names(parser),
            ["login", "login-status", "search", "price", "collect"],
        )

    def test_page_selection_options_are_accepted_after_the_subcommand(self):
        cli_module = load_module("ctrip_cli_page_options", "ctrip_cli.py")
        parser = cli_module.build_parser()

        args = parser.parse_args(
            [
                "login-status",
                "--page-index",
                "2",
                "--page-url-contains",
                "hotels.ctrip.com",
            ]
        )

        self.assertEqual(args.page_index, 2)
        self.assertEqual(args.page_url_contains, "hotels.ctrip.com")

    def test_collect_command_accepts_parallel_instance_override(self):
        cli_module = load_module("ctrip_cli_parallel_instances", "ctrip_cli.py")
        parser = cli_module.build_parser()

        args = parser.parse_args(
            ["collect", "--max-parallel-instances", "3"]
        )

        self.assertEqual(args.max_parallel_instances, 3)

    def test_price_command_requires_mode_specific_xpath(self):
        cli_module = load_module("ctrip_cli_price_validation", "ctrip_cli.py")
        parser = cli_module.build_parser()

        args = parser.parse_args(
            [
                "price",
                "--detail-url",
                "https://hotels.ctrip.com/hotels/1.html?cityid=95",
                "--start-date",
                "2026-09-06",
                "--price-mode",
                "page_xpath",
            ]
        )
        with self.assertRaises(SystemExit):
            cli_module.validate_args(args)

    def test_profile_launch_failure_explains_profile_conflict(self):
        browser_module = load_module("ctrip_cli_browser_launch_error", "ctrip_cli_browser.py")

        def failing_launcher(*_args, **_kwargs):
            raise RuntimeError("TargetClosedError")

        session = browser_module.CtripBrowserSession(
            "/tmp/ctrip-profile-test",
            launcher=failing_launcher,
        )

        with self.assertRaisesRegex(RuntimeError, "Profile.*占用|启动失败"):
            session.open()

    def test_close_other_pages_keeps_the_selected_page(self):
        browser_module = load_module("ctrip_cli_browser_close_pages", "ctrip_cli_browser.py")

        class ClosablePage:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        selected = ClosablePage()
        extra = ClosablePage()
        browser = SimpleNamespace(pages=[selected, extra])

        closed_count = browser_module.close_other_pages(browser, selected)

        self.assertEqual(closed_count, 1)
        self.assertFalse(selected.closed)
        self.assertTrue(extra.closed)

    def test_macos_launcher_uses_launch_services_and_cdp(self):
        launcher_module = load_module("ctrip_cloak_launcher_args", "ctrip_cloak_launcher.py")

        command = launcher_module.build_macos_open_command(
            "/tmp/Chromium.app",
            "/tmp/ctrip-profile",
            19229,
            headless=False,
            chrome_args=["--fingerprint=12345"],
        )

        self.assertEqual(command[:4], ["open", "-na", "/tmp/Chromium.app", "--args"])
        self.assertIn("--user-data-dir=/tmp/ctrip-profile", command)
        self.assertIn("--remote-debugging-port=19229", command)
        self.assertIn("--fingerprint=12345", command)

    def test_macos_launcher_cleans_chromium_if_playwright_initialization_fails(self):
        launcher_module = load_module(
            "ctrip_cloak_launcher_cleanup",
            "ctrip_cloak_launcher.py",
        )
        cleanup_calls = []

        class FailingPlaywright:
            def start(self):
                raise RuntimeError("playwright initialization failed")

        fake_cloak = type(sys)("cloakbrowser")
        fake_cloak.__path__ = []
        fake_download = type(sys)("cloakbrowser.download")
        fake_download.ensure_binary = lambda **_kwargs: (
            "/tmp/Chromium.app/Contents/MacOS/Chromium"
        )
        fake_cloak.download = fake_download
        fake_playwright = type(sys)("playwright")
        fake_playwright.__path__ = []
        fake_sync_api = type(sys)("playwright.sync_api")
        fake_sync_api.sync_playwright = lambda: FailingPlaywright()
        fake_playwright.sync_api = fake_sync_api

        with (
            patch.object(launcher_module, "_find_app_bundle", return_value=Path("/tmp/Chromium.app")),
            patch.object(launcher_module, "_free_local_port", return_value=19229),
            patch.object(launcher_module, "_wait_for_cdp", return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:19229"}),
            patch.object(launcher_module.subprocess, "run"),
            patch.object(
                launcher_module,
                "_cleanup_macos_process",
                side_effect=lambda profile, port: cleanup_calls.append((profile, port)),
                create=True,
            ),
            patch.dict(
                sys.modules,
                {
                    "cloakbrowser": fake_cloak,
                    "cloakbrowser.download": fake_download,
                    "playwright": fake_playwright,
                    "playwright.sync_api": fake_sync_api,
                },
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "playwright initialization"):
                launcher_module._launch_macos(
                    "/tmp/ctrip-profile",
                    headless=False,
                    args=None,
                    stealth_args=True,
                    timezone=None,
                    locale=None,
                    extension_paths=None,
                    start_maximized=False,
                    license_key=None,
                    browser_version=None,
                    release_channel=None,
                )

        self.assertEqual(cleanup_calls, [(Path("/tmp/ctrip-profile").resolve(), 19229)])

    def test_login_status_waits_through_transient_login_marker(self):
        auth_module = load_module(
            "ctrip_cli_auth_status_stability",
            "ctrip_cli_auth.py",
        )

        class SequenceLocator:
            def __init__(self, page, signal):
                self.page = page
                self.signal = signal

            def count(self):
                return 1

            def nth(self, _index):
                return self

            def is_visible(self):
                state = self.page.states[self.page.state_index]
                visible = state[self.signal]
                if self.signal == "login":
                    self.page.state_index = min(
                        self.page.state_index + 1,
                        len(self.page.states) - 1,
                    )
                return visible

        class SequencePage:
            url = "https://www.ctrip.com/"

            def __init__(self):
                self.states = [
                    {"orders": True, "login": True},
                    {"orders": True, "login": False},
                ]
                self.state_index = 0

            def locator(self, selector):
                if selector == "xpath=//*[normalize-space()='我的订单']":
                    return SequenceLocator(self, "orders")
                if selector == "xpath=//span[normalize-space()='登录']":
                    return SequenceLocator(self, "login")
                raise AssertionError(f"未预期的选择器：{selector}")

            def bring_to_front(self):
                pass

            def evaluate(self, _expression):
                pass

            def wait_for_timeout(self, milliseconds):
                import time

                time.sleep(milliseconds / 1000)

        page = SequencePage()
        status = auth_module.login_status(
            SimpleNamespace(pages=[page]),
            page,
            timeout_seconds=3.5,
        )

        self.assertTrue(status["logged_in"])
        self.assertFalse(status["login_visible"])

    def test_login_keep_open_eof_is_a_normal_close(self):
        cli_module = load_module(
            "ctrip_cli_keep_open_eof",
            "ctrip_cli.py",
        )

        class FakeSession:
            profile_dir = Path("/tmp/ctrip-profile")
            browser = object()

            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def focus(self, page=None):
                return page or "page"

        args = SimpleNamespace(
            profile_dir=Path("/tmp/ctrip-profile"),
            page_index=0,
            page_url_contains="",
            timeout=10,
            session_probe_seconds=1,
            keep_open=True,
        )
        with (
            patch.object(cli_module, "CtripBrowserSession", FakeSession),
            patch.object(cli_module, "ensure_login", return_value="page"),
            patch.object(
                cli_module,
                "login_status",
                return_value={"logged_in": True},
            ),
            patch("builtins.input", side_effect=EOFError),
        ):
            result = cli_module.run_login(args)

        self.assertEqual(result, 0)

if __name__ == "__main__":
    unittest.main()
