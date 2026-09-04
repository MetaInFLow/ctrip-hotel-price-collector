import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ctrip_hotel_prices.py"


def load_collector_module():
    spec = importlib.util.spec_from_file_location("ctrip_hotel_prices", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载采集脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLocator:
    def __init__(self, visible):
        self.visible = visible

    def count(self):
        return 1

    def nth(self, _index):
        return self

    def is_visible(self):
        return self.visible


class FakePage:
    def __init__(self, module, *, login_visible, orders_visible):
        self.module = module
        self.login_visible = login_visible
        self.orders_visible = orders_visible

    def locator(self, selector):
        if selector == self.module.LOGIN_XPATH:
            return FakeLocator(self.login_visible)
        if selector == self.module.ORDERS_XPATH:
            return FakeLocator(self.orders_visible)
        raise AssertionError(f"未预期的选择器：{selector}")


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class LoginSessionTests(unittest.TestCase):
    def test_visible_orders_means_logged_in_even_when_login_trigger_remains(self):
        module = load_collector_module()
        page = FakePage(module, login_visible=True, orders_visible=True)
        context = FakeContext([page])

        self.assertIs(module.find_logged_in_page(context, page), page)

    def test_counts_loaded_ctrip_cookies_without_exposing_cookie_values(self):
        module = load_collector_module()

        class CookieContext:
            def cookies(self, urls):
                self.urls = urls
                return [
                    {"name": "session", "value": "redacted", "domain": ".ctrip.com"},
                    {"name": "hotel", "value": "redacted", "domain": ".hotels.ctrip.com"},
                ]

        context = CookieContext()
        count_cookies = getattr(module, "count_ctrip_cookies", None)
        self.assertIsNotNone(count_cookies)
        self.assertEqual(count_cookies(context), 2)
        self.assertEqual(
            context.urls,
            ["https://www.ctrip.com/", "https://hotels.ctrip.com/"],
        )

    def test_reuses_existing_profile_from_current_project_directory(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory) / "project"
            config_dir = Path(temporary_directory) / "installed-skill"
            project_profile = project_dir / ".cloakbrowser-profile"
            project_profile.mkdir(parents=True)
            config_dir.mkdir()

            with patch("pathlib.Path.cwd", return_value=project_dir):
                resolved = module.resolve_profile_dir(
                    {"profile_dir": ".cloakbrowser-profile"},
                    config_dir,
                )

        self.assertEqual(resolved, project_profile)


if __name__ == "__main__":
    unittest.main()
