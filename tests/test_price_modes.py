import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ctrip_hotel_prices.py"


def load_collector_module():
    spec = importlib.util.spec_from_file_location("ctrip_hotel_prices_price_modes", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载采集脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Locator:
    def __init__(self, values, *, on_click=None):
        self.values = values if isinstance(values, list) else [values]
        self.on_click = on_click
        self.clicked = False

    def count(self):
        return len(self.values)

    def nth(self, index):
        if len(self.values) == 1 and index == 0:
            return self
        return Locator(self.values[index], on_click=self.on_click)

    def is_visible(self):
        return True

    def inner_text(self, timeout=None):
        del timeout
        return self.values[0]

    def click(self, timeout=None):
        del timeout
        self.clicked = True
        if self.on_click:
            self.on_click()


class Page:
    def __init__(self, module):
        self.module = module
        self.url = "https://www.ctrip.com/"
        self.show_all_button = Locator("展示所有房型")
        self.price_locator = Locator(["￥418起", "¥1,299.50"])
        self.room_locator = Locator(["豪华大床房", "行政套房"])
        self.selectors = []
        self.login_visible = False
        self.orders_visible = True

    def bring_to_front(self):
        pass

    def evaluate(self, _expression):
        pass

    def locator(self, selector):
        self.selectors.append(selector)
        if selector == self.module.LOGIN_XPATH:
            return Locator("登录") if self.login_visible else EmptyLocator()
        if selector == self.module.ORDERS_XPATH:
            return Locator("我的订单") if self.orders_visible else EmptyLocator()
        if selector == "xpath=//show-all":
            return self.show_all_button
        if selector == "xpath=//price":
            return self.price_locator
        if selector == "xpath=//room":
            return self.room_locator
        raise AssertionError(f"未预期的选择器：{selector}")

    def wait_for_timeout(self, milliseconds):
        del milliseconds


class ResponseRequest:
    method = "POST"
    post_data = "{}"


class Response:
    url = "https://hotels.ctrip.com/restapi/soa2/33278/getHotelRoomListInland"
    status = 200
    request = ResponseRequest()

    def json(self):
        return {"data": {}}


class EmptyLocator(Locator):
    def __init__(self):
        super().__init__([])


class CapturingPage(Page):
    def __init__(self, module):
        super().__init__(module)
        self.response_handler = None
        self.removed_handler = None

    def on(self, event, handler):
        self.assert_response_event(event)
        self.response_handler = handler

    def assert_response_event(self, event):
        if event != "response":
            raise AssertionError(f"未预期的事件：{event}")

    def goto(self, url, wait_until=None, timeout=None):
        del url, wait_until, timeout
        if self.response_handler:
            self.response_handler(Response())

    def remove_listener(self, event, handler):
        self.assert_response_event(event)
        self.removed_handler = handler


class Browser:
    def __init__(self, page):
        self.pages = [page]


class PriceModeTests(unittest.TestCase):
    def test_response_is_the_default_and_page_mode_requires_price_xpath(self):
        module = load_collector_module()
        response_config = {"price_mode": "response"}

        module.validate_price_config(response_config)

        self.assertEqual(response_config["price_mode"], "response")
        self.assertEqual(response_config["page_price_sample_size"], 3)
        self.assertEqual(response_config["page_price_xpath"], "")

        with self.assertRaisesRegex(ValueError, "page_price_xpath"):
            module.validate_price_config({"price_mode": "page_xpath"})

    def test_page_xpath_clicks_show_all_rooms_before_reading_prices(self):
        module = load_collector_module()
        page = Page(module)

        rows = module.extract_page_price_rows(
            page,
            show_all_rooms_xpath="//show-all",
            page_price_xpath="//price",
            page_room_name_xpath="//room",
            timeout_seconds=1,
        )

        self.assertTrue(page.show_all_button.clicked)
        self.assertEqual(page.selectors[-3:], [
            "xpath=//show-all",
            "xpath=//price",
            "xpath=//room",
        ])
        self.assertEqual([row["页面价格"] for row in rows], [418, 1299.5])
        self.assertEqual([row["房型"] for row in rows], ["豪华大床房", "行政套房"])

    def test_page_mode_uses_page_price_and_keeps_interface_price_for_audit(self):
        module = load_collector_module()
        response_rows = [
            {
                "酒店名称": "测试酒店",
                "入住日期": "2026-09-03",
                "离店日期": "2026-09-04",
                "房型": "豪华大床房",
                "价格": 418,
                "接口价格": 418,
            }
        ]
        page_rows = [
            {
                "页面序号": 1,
                "房型": "豪华大床房",
                "页面价格文本": "￥399起",
                "页面价格": 399,
                "页面价格XPath": "xpath=//price",
                "展示所有房型XPath": "xpath=//show-all",
            }
        ]

        room_rows = module.build_page_room_rows(
            hotel_name="测试酒店",
            check_in="2026-09-03",
            check_out="2026-09-04",
            detail_url="https://hotels.ctrip.com/hotels/1.html?cityid=95",
            captured_at="2026-09-03T00:00:00+00:00",
            source_file="room.json",
            response_rows=response_rows,
            page_price_rows=page_rows,
        )
        checks = module.build_page_price_checks(
            response_rows,
            page_rows,
            sample_size=1,
        )

        self.assertEqual(room_rows[0]["价格"], 399)
        self.assertEqual(room_rows[0]["接口价格"], 418)
        self.assertEqual(room_rows[0]["价格来源"], "page_xpath")
        self.assertEqual(checks[0]["结果"], "mismatch")
        annotated_rows = module.annotate_response_room_rows(response_rows, page_rows)
        self.assertEqual(annotated_rows[0]["价格"], 418)
        self.assertEqual(annotated_rows[0]["页面价格文本"], "￥399起")
        self.assertEqual(
            module.page_price_check_status(
                page_price_rows=page_rows,
                checks=checks,
            ),
            "mismatch",
        )

    def test_response_mode_keeps_listener_active_during_page_spot_check(self):
        module = load_collector_module()
        page = CapturingPage(module)

        collection = module.capture_room_data(
            page,
            "https://hotels.ctrip.com/hotels/1.html?cityid=95",
            browser=Browser(page),
            api_timeout_seconds=1,
            settle_ms=0,
            price_mode="response",
            show_all_rooms_xpath="//show-all",
            page_price_xpath="//price",
            page_price_sample_size=1,
            page_price_timeout_seconds=1,
        )

        self.assertEqual(len(collection["responses"]), 1)
        self.assertEqual(len(collection["page_price_rows"]), 1)
        self.assertIsNotNone(page.removed_handler)

    def test_capture_room_data_requires_a_browser_for_the_login_gate(self):
        module = load_collector_module()
        page = CapturingPage(module)

        with self.assertRaisesRegex(TypeError, "browser"):
            module.capture_room_data(
                page,
                "https://hotels.ctrip.com/hotels/1.html",
                api_timeout_seconds=1,
                settle_ms=0,
            )


if __name__ == "__main__":
    unittest.main()
