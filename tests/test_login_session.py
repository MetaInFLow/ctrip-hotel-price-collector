import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ctrip_hotel_prices.py"
OPEN_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "open_ctrip.py"
BOOTSTRAP_PATH = PROJECT_ROOT / "scripts" / "bootstrap_ctrip_hotel_skill.py"
SKILL_PATH = PROJECT_ROOT / "SKILL.md"
METADATA_PATH = PROJECT_ROOT / "agents" / "openai.yaml"


def load_collector_module():
    spec = importlib.util.spec_from_file_location("ctrip_hotel_prices", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载采集脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_bootstrap_module():
    spec = importlib.util.spec_from_file_location("bootstrap_ctrip_hotel_skill", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载部署脚本：{BOOTSTRAP_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_open_module():
    spec = importlib.util.spec_from_file_location("open_ctrip", OPEN_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载打开脚本：{OPEN_SCRIPT_PATH}")
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
    def test_skill_has_fde_chinese_name_and_structured_description(self):
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        metadata_text = METADATA_PATH.read_text(encoding="utf-8")

        self.assertIn("FDE特供携程比价技能", skill_text)
        self.assertIn("适用：", skill_text)
        self.assertIn("输入：", skill_text)
        self.assertIn("输出：", skill_text)
        self.assertIn('display_name: "FDE特供携程比价技能"', metadata_text)
        self.assertIn("short_description:", metadata_text)

    def test_skill_uses_fast_path_when_required_parameters_are_present(self):
        skill_text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("## 快速执行路径", skill_text)
        self.assertIn("直接传入 `--hotel` 、`--city-id` 、`--start-date` 和 `--days`", skill_text)
        self.assertIn("不先调用 `login-status` 、`setup` 、`search`", skill_text)
        self.assertIn("只追问缺失的必填字段", skill_text)

    def test_skill_requires_direct_script_execution_without_inline_python(self):
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        metadata_text = METADATA_PATH.read_text(encoding="utf-8")

        self.assertIn("scripts/ctrip_cli.py collect --hotel", skill_text)
        self.assertIn(".runtime/python-3.12/bin/python", skill_text)
        self.assertIn("python -c", skill_text)
        self.assertIn("here-document", skill_text)
        self.assertIn("scripts/ctrip_cli.py collect --hotel", metadata_text)
        self.assertIn("python -c", metadata_text)

    def test_skill_requires_cloakbrowser_script_as_the_only_browser_entrypoint(self):
        skill_text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("浏览器唯一入口", skill_text)
        self.assertIn("所有携程页面操作", skill_text)
        self.assertIn("系统默认浏览器", skill_text)
        self.assertIn("launch_persistent_context", skill_text)
        self.assertIn("脚本是唯一执行入口", skill_text)
        self.assertIn("open_ctrip.py", skill_text)

    def test_open_ctrip_uses_the_shared_persistent_profile(self):
        module = load_open_module()
        open_script_text = OPEN_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("launch_persistent_context", open_script_text)
        self.assertNotIn("from cloakbrowser import launch\n", open_script_text)
        calls = []

        class Page:
            url = "about:blank"

            def goto(self, url, wait_until=None, timeout=None):
                del wait_until, timeout
                self.url = url

            def title(self):
                return "携程"

        class Context:
            def __init__(self):
                self.pages = [Page()]
                self.closed = False

            def close(self):
                self.closed = True

        context = Context()

        def launcher(profile_dir, *, headless):
            calls.append((profile_dir, headless))
            return context

        result = module.main([], launcher=launcher, input_fn=lambda _prompt: "")

        self.assertEqual(result, 0)
        self.assertEqual(
            calls,
            [(str(module.default_profile_dir()), False)],
        )
        self.assertTrue(context.closed)

    def test_loaded_profile_is_probed_before_login_prompt(self):
        module = load_collector_module()

        class Locator:
            def __init__(self, visible):
                self.visible = visible
                self.clicked = False

            def count(self):
                return 1

            def nth(self, _index):
                return self

            def is_visible(self):
                return self.visible()

            def click(self, timeout=None):
                del timeout
                self.clicked = True

        class DelayedPage:
            def __init__(self):
                self.orders_checks = 0
                self.login_locator = Locator(lambda: self.orders_checks < 3)

            def locator(self, selector):
                if selector == module.ORDERS_XPATH:
                    def orders_visible():
                        self.orders_checks += 1
                        return self.orders_checks >= 3

                    return Locator(orders_visible)
                if selector == module.LOGIN_XPATH:
                    return self.login_locator
                raise AssertionError(f"未预期的选择器：{selector}")

            def wait_for_timeout(self, milliseconds):
                time.sleep(milliseconds / 1000)

        page = DelayedPage()
        context = FakeContext([page])

        result = module.wait_for_login(
            context,
            page,
            timeout_seconds=3,
            session_probe_seconds=3,
            has_persisted_cookies=True,
        )

        self.assertIs(result, page)
        self.assertFalse(page.login_locator.clicked)

    def test_visible_login_trigger_overrides_the_orders_marker(self):
        module = load_collector_module()
        page = FakePage(module, login_visible=True, orders_visible=True)
        context = FakeContext([page])

        self.assertIsNone(module.find_logged_in_page(context, page))

    def test_visible_orders_without_login_trigger_means_logged_in(self):
        module = load_collector_module()
        page = FakePage(module, login_visible=False, orders_visible=True)
        context = FakeContext([page])

        self.assertIs(module.find_logged_in_page(context, page), page)

    def test_stale_other_tab_cannot_authenticate_the_current_page(self):
        module = load_collector_module()
        stale_logged_in_page = FakePage(module, login_visible=False, orders_visible=True)
        current_logged_out_page = FakePage(module, login_visible=True, orders_visible=False)
        context = FakeContext([stale_logged_in_page, current_logged_out_page])

        self.assertIsNone(module.find_logged_in_page(context, current_logged_out_page))

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

    def test_run_index_checkpoint_preserves_partial_progress(self):
        module = load_collector_module()
        item = {
            "hotel_name": "测试酒店",
            "check_in": "2026-09-04",
            "check_out": "2026-09-05",
            "status": "ok",
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            index_path = Path(temporary_directory) / "output" / "index.json"
            module.write_run_index(index_path, [item], status="running")
            payload = json.loads(index_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["items"], [item])

    def test_detail_list_url_is_not_accepted_as_detail_page(self):
        module = load_collector_module()

        self.assertTrue(
            module.is_valid_detail_url(
                "http://hotels.ctrip.com/hotel/346405.html?cityid=2"
            )
        )
        self.assertFalse(
            module.is_valid_detail_url(
                "https://hotels.ctrip.com/hotels/list?city=2"
            )
        )

    def test_accepts_explicit_absolute_profile_path(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_profile = Path(temporary_directory) / "profile"
            resolved = module.resolve_profile_dir(
                {"profile_dir": str(project_profile)},
                Path(temporary_directory),
            )

        self.assertEqual(resolved, project_profile)

    def test_default_session_root_is_absolute(self):
        module = load_collector_module()

        self.assertTrue(module.default_session_root().is_absolute())

    def test_default_storage_locations_follow_each_supported_platform(self):
        module = load_collector_module()
        home = Path("/tmp/test-home")

        mac_root = module.session_root_for_platform(
            os_name="posix",
            platform="darwin",
            home=home,
            environ={},
        )
        windows_root = module.session_root_for_platform(
            os_name="nt",
            platform="win32",
            home=home,
            environ={"LOCALAPPDATA": "/tmp/test-local-app-data"},
        )
        linux_root = module.session_root_for_platform(
            os_name="posix",
            platform="linux",
            home=home,
            environ={},
        )

        self.assertEqual(
            mac_root,
            (home / "Library" / "Application Support" / module.SESSION_APP_NAME).resolve(),
        )
        self.assertEqual(
            windows_root,
            (Path("/tmp/test-local-app-data") / module.SESSION_APP_NAME).resolve(),
        )
        self.assertEqual(
            linux_root,
            (home / ".local" / "state" / module.SESSION_APP_NAME).resolve(),
        )

    def test_virtual_environment_python_path_is_platform_specific(self):
        module = load_bootstrap_module()
        venv_dir = Path("/tmp/ctrip-venv")

        self.assertEqual(
            module.venv_python(venv_dir, os_name="nt"),
            venv_dir / "Scripts" / "python.exe",
        )
        self.assertEqual(
            module.venv_python(venv_dir, os_name="posix"),
            venv_dir / "bin" / "python",
        )

    def test_rejects_relative_profile_path(self):
        module = load_collector_module()

        with self.assertRaises(ValueError):
            module.resolve_profile_dir(
                {"profile_dir": ".cloakbrowser-profile"},
                Path("/tmp/installed-skill"),
            )

    def test_config_defaults_to_absolute_storage_paths(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "hotels": [{"name": "测试酒店"}],
                        "start_date": "2026-09-03",
                        "days": 1,
                        "nights": 1,
                    }
                ),
                encoding="utf-8",
            )
            config = module.load_config(config_path)

        self.assertTrue(Path(config["profile_dir"]).is_absolute())
        self.assertTrue(Path(config["detail_url_cache_file"]).is_absolute())
        self.assertTrue(Path(config["output_dir"]).is_absolute())
        self.assertFalse(config["keep_browser_open"])

    def test_sample_config_closes_browser_after_collection(self):
        config = json.loads(
            (PROJECT_ROOT / "ctrip_hotel_config.json").read_text(encoding="utf-8")
        )

        self.assertFalse(config["keep_browser_open"])


if __name__ == "__main__":
    unittest.main()
