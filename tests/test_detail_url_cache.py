import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PACKAGE_ROOT / "scripts" / "ctrip_hotel_prices.py"


def load_collector_module():
    spec = importlib.util.spec_from_file_location("installed_ctrip_hotel_prices", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载采集脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DetailUrlCacheTests(unittest.TestCase):
    def test_saving_cache_appends_without_removing_existing_records(self):
        module = load_collector_module()
        first_url = "https://hotels.ctrip.com/hotels/101.html?cityid=2"
        second_url = "https://hotels.ctrip.com/hotels/202.html?cityid=95"

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "detail-url-cache.json"
            first_cache = {}
            module.cache_detail_url(first_cache, "第一家酒店", first_url, city_id=2)
            module.save_detail_url_cache(cache_path, first_cache)
            second_cache = {}
            module.cache_detail_url(second_cache, "第二家酒店", second_url, city_id=95)
            module.save_detail_url_cache(cache_path, second_cache)
            loaded = module.load_detail_url_cache(cache_path)

        self.assertEqual(
            module.get_cached_detail_url(loaded, "第一家酒店", city_id=2),
            first_url,
        )
        self.assertEqual(
            module.get_cached_detail_url(loaded, "第二家酒店", city_id=95),
            second_url,
        )

    def test_stale_cache_save_preserves_records_added_by_another_writer(self):
        module = load_collector_module()
        first_url = "https://hotels.ctrip.com/hotels/303.html?cityid=2"
        second_url = "https://hotels.ctrip.com/hotels/404.html?cityid=95"
        third_url = "https://hotels.ctrip.com/hotels/505.html?cityid=1"

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "detail-url-cache.json"
            initial_cache = {}
            module.cache_detail_url(initial_cache, "初始酒店", first_url, city_id=2)
            module.save_detail_url_cache(cache_path, initial_cache)
            stale_cache = module.load_detail_url_cache(cache_path)
            latest_cache = module.load_detail_url_cache(cache_path)
            module.cache_detail_url(latest_cache, "另一进程酒店", second_url, city_id=95)
            module.save_detail_url_cache(cache_path, latest_cache)
            module.cache_detail_url(stale_cache, "陈旧进程酒店", third_url, city_id=1)
            module.save_detail_url_cache(cache_path, stale_cache)
            loaded = module.load_detail_url_cache(cache_path)

        self.assertEqual(len(loaded), 3)
        self.assertEqual(
            module.get_cached_detail_url(loaded, "另一进程酒店", city_id=95),
            second_url,
        )
        self.assertEqual(
            module.get_cached_detail_url(loaded, "陈旧进程酒店", city_id=1),
            third_url,
        )

    def test_stale_cache_does_not_replace_a_newer_record_for_same_hotel(self):
        module = load_collector_module()
        old_url = "https://hotels.ctrip.com/hotels/909.html?cityid=2"
        new_url = "https://hotels.ctrip.com/hotels/1001.html?cityid=2"

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "detail-url-cache.json"
            initial_cache = {}
            module.cache_detail_url(initial_cache, "同一酒店", old_url, city_id=2)
            module.save_detail_url_cache(cache_path, initial_cache)
            stale_cache = module.load_detail_url_cache(cache_path)
            latest_cache = module.load_detail_url_cache(cache_path)
            module.cache_detail_url(latest_cache, "同一酒店", new_url, city_id=2)
            latest_cache[next(iter(latest_cache))]["updated_at"] = (
                "2099-01-01T00:00:00+00:00"
            )
            module.save_detail_url_cache(cache_path, latest_cache)
            module.save_detail_url_cache(cache_path, stale_cache)
            loaded = module.load_detail_url_cache(cache_path)

        self.assertEqual(
            module.get_cached_detail_url(loaded, "同一酒店", city_id=2),
            new_url,
        )

    def test_same_hotel_name_in_different_cities_keeps_separate_records(self):
        module = load_collector_module()
        shanghai_url = "https://hotels.ctrip.com/hotels/606.html?cityid=2"
        leshan_url = "https://hotels.ctrip.com/hotels/707.html?cityid=95"

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "detail-url-cache.json"
            cache = {}
            module.cache_detail_url(cache, "同名酒店", shanghai_url, city_id=2)
            module.cache_detail_url(cache, "同名酒店", leshan_url, city_id=95)
            module.save_detail_url_cache(cache_path, cache)
            loaded = module.load_detail_url_cache(cache_path)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(
            module.get_cached_detail_url(loaded, "同名酒店", city_id=2),
            shanghai_url,
        )
        self.assertEqual(
            module.get_cached_detail_url(loaded, "同名酒店", city_id=95),
            leshan_url,
        )

    def test_legacy_name_key_cache_still_loads(self):
        module = load_collector_module()
        detail_url = "https://hotels.ctrip.com/hotels/808.html?cityid=95"

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "detail-url-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "items": {
                            "历史酒店": {
                                "hotel_name": "历史酒店",
                                "detail_url": detail_url,
                                "city_id": 95,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            loaded = module.load_detail_url_cache(cache_path)

        self.assertEqual(
            module.get_cached_detail_url(loaded, "历史酒店", city_id=95),
            detail_url,
        )


if __name__ == "__main__":
    unittest.main()
