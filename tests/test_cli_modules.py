import importlib.util
import unittest
from pathlib import Path


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

if __name__ == "__main__":
    unittest.main()
