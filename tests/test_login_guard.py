import importlib.util
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = PROJECT_ROOT / "scripts" / "ctrip_login_guard.py"


def load_guard_module():
    if not GUARD_PATH.is_file():
        raise AssertionError(f"登录门禁模块尚未实现：{GUARD_PATH}")
    spec = importlib.util.spec_from_file_location("ctrip_login_guard", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载登录门禁模块：{GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Locator:
    def __init__(self, visible):
        self.visible = visible

    def count(self):
        return 1

    def nth(self, _index):
        return self

    def is_visible(self):
        return self.visible


class Page:
    def __init__(self, module, *, login_visible, orders_visible):
        self.module = module
        self.login_visible = login_visible
        self.orders_visible = orders_visible
        self.url = "https://www.ctrip.com/"

    def bring_to_front(self):
        pass

    def evaluate(self, _expression):
        pass

    def wait_for_timeout(self, _milliseconds):
        pass

    def locator(self, selector):
        if selector == self.module.LOGIN_XPATH:
            return Locator(self.login_visible)
        if selector == self.module.ORDERS_XPATH:
            return Locator(self.orders_visible)
        raise AssertionError(f"未预期的选择器：{selector}")


class Browser:
    def __init__(self, page):
        self.pages = [page]


class LoginGuardTests(unittest.TestCase):
    def test_require_logged_in_waits_through_transient_login_marker(self):
        module = load_guard_module()

        class OrdersLocator:
            def count(self):
                return 1

            def nth(self, _index):
                return self

            def is_visible(self):
                return True

        class LoginLocator(OrdersLocator):
            def __init__(self, page):
                self.page = page

            def is_visible(self):
                self.page.login_checks += 1
                return self.page.login_checks <= 2

        class TransientPage:
            url = "https://hotels.ctrip.com/hotels/1.html"

            def __init__(self):
                self.login_checks = 0

            def bring_to_front(self):
                pass

            def evaluate(self, _expression):
                pass

            def locator(self, selector):
                if selector == module.LOGIN_XPATH:
                    return LoginLocator(self)
                if selector == module.ORDERS_XPATH:
                    return OrdersLocator()
                raise AssertionError(f"未预期的选择器：{selector}")

            def wait_for_timeout(self, milliseconds):
                time.sleep(milliseconds / 1000)

        page = TransientPage()

        result = module.require_logged_in(Browser(page), page, operation="房价采集")

        self.assertIs(result, page)

    def test_public_orders_marker_with_login_trigger_is_not_authenticated(self):
        module = load_guard_module()
        page = Page(module, login_visible=True, orders_visible=True)

        status = module.check_login(Browser(page), page)

        self.assertFalse(status["logged_in"])

    def test_require_logged_in_rejects_an_unauthenticated_operation(self):
        module = load_guard_module()
        page = Page(module, login_visible=True, orders_visible=True)

        with self.assertRaisesRegex(module.LoginRequiredError, "房价采集.*登录"):
            module.require_logged_in(Browser(page), page, operation="房价采集")


if __name__ == "__main__":
    unittest.main()
