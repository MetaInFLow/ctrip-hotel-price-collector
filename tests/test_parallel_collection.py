import importlib.util
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ctrip_hotel_prices.py"


def load_collector_module():
    spec = importlib.util.spec_from_file_location(
        "ctrip_hotel_prices_parallel",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载采集脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spawn_test_worker(payload):
    return {
        "worker_index": payload["worker_index"],
        "ok": True,
        "hotels": [],
        "output_dir": payload["output_dir"],
        "summary": [],
    }


class ParallelCollectionTests(unittest.TestCase):
    def test_parallel_instance_config_defaults_to_one_and_rejects_zero(self):
        module = load_collector_module()

        config = {"price_mode": "response"}
        module.validate_price_config(config)
        self.assertEqual(config["max_parallel_instances"], 1)

        with self.assertRaisesRegex(ValueError, "max_parallel_instances"):
            module.validate_price_config(
                {"price_mode": "response", "max_parallel_instances": 0}
            )

    def test_hotels_are_partitioned_without_duplicates(self):
        module = load_collector_module()
        hotels = [{"name": f"酒店-{index}"} for index in range(5)]

        groups = module.split_hotels_for_workers(hotels, 2)

        self.assertEqual(len(groups), 2)
        self.assertEqual(
            sorted(hotel["name"] for group in groups for hotel in group),
            sorted(hotel["name"] for hotel in hotels),
        )
        self.assertEqual(
            [hotel["name"] for hotel in groups[0]],
            ["酒店-0", "酒店-2", "酒店-4"],
        )
        self.assertTrue(all(groups))

    def test_profile_clone_excludes_chromium_runtime_locks(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source-profile"
            destination = root / "worker-profile"
            (source / "Default" / "Network").mkdir(parents=True)
            (source / "Default" / "Network" / "Cookies").write_text(
                "cookie database",
                encoding="utf-8",
            )
            (source / "SingletonLock").write_text("locked", encoding="utf-8")
            (source / "DevToolsActivePort").write_text("9222", encoding="utf-8")
            (source / "Default" / "Network" / "LOCK").write_text(
                "locked",
                encoding="utf-8",
            )

            module.copy_profile_for_worker(source, destination)

            self.assertTrue((destination / "Default" / "Network" / "Cookies").is_file())
            self.assertFalse((destination / "SingletonLock").exists())
            self.assertFalse((destination / "DevToolsActivePort").exists())
            self.assertFalse((destination / "Default" / "Network" / "LOCK").exists())

    def test_worker_results_are_merged_into_final_output(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker_output = root / "parallel-run" / "worker-1" / "results"
            source_file = worker_output / "测试酒店" / "2026-09-03_2026-09-04.json"
            source_file.parent.mkdir(parents=True)
            source_file.write_text(
                json.dumps({"hotel_name": "测试酒店"}, ensure_ascii=False),
                encoding="utf-8",
            )
            module.write_run_index(
                worker_output / "index.json",
                [
                    {
                        "hotel_name": "测试酒店",
                        "check_in": "2026-09-03",
                        "check_out": "2026-09-04",
                        "status": "ok",
                        "file": str(source_file),
                    }
                ],
                status="ready_for_export",
            )
            final_output = root / "final-output"

            items = module.merge_worker_results([worker_output], final_output)

            merged_file = (
                final_output / "测试酒店" / source_file.name
            ).resolve()
            self.assertTrue(merged_file.is_file())
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["file"], str(merged_file))
            self.assertEqual(
                json.loads(merged_file.read_text(encoding="utf-8"))["hotel_name"],
                "测试酒店",
            )

    def test_parallel_runner_uses_one_executor_slot_per_payload(self):
        module = load_collector_module()
        payloads = [
            {"worker_index": 1, "hotels": [], "output_dir": "/tmp/worker-1"},
            {"worker_index": 2, "hotels": [], "output_dir": "/tmp/worker-2"},
        ]
        observed = {"max_workers": None, "worker_indexes": []}

        def executor_factory(max_workers):
            observed["max_workers"] = max_workers
            return ThreadPoolExecutor(max_workers=max_workers)

        def worker(payload):
            observed["worker_indexes"].append(payload["worker_index"])
            return {
                "worker_index": payload["worker_index"],
                "ok": True,
                "hotels": [],
                "output_dir": payload["output_dir"],
                "summary": [],
            }

        results = module.run_parallel_workers(
            payloads,
            worker_fn=worker,
            executor_factory=executor_factory,
        )

        self.assertEqual(observed["max_workers"], 2)
        self.assertEqual(sorted(observed["worker_indexes"]), [1, 2])
        self.assertEqual([result["worker_index"] for result in results], [1, 2])

    def test_parallel_runner_uses_spawn_processes_by_default(self):
        module = load_collector_module()
        payloads = [
            {"worker_index": 1, "hotels": [], "output_dir": "/tmp/worker-1"},
            {"worker_index": 2, "hotels": [], "output_dir": "/tmp/worker-2"},
        ]

        results = module.run_parallel_workers(
            payloads,
            worker_fn=spawn_test_worker,
        )

        self.assertEqual([result["worker_index"] for result in results], [1, 2])

    def test_worker_stops_before_collection_when_cloned_profile_is_logged_out(self):
        module = load_collector_module()

        class Page:
            url = "https://www.ctrip.com/"

            def bring_to_front(self):
                pass

            def evaluate(self, _expression):
                pass

            def goto(self, _url, wait_until=None, timeout=None):
                del wait_until, timeout

        class Browser:
            def __init__(self):
                self.pages = [Page()]
                self.closed = False

            def cookies(self, _urls):
                return [{"name": "session", "value": "redacted"}]

            def close(self):
                self.closed = True

        browser = Browser()
        launcher = SimpleNamespace(
            launch_persistent_context=lambda _profile_dir, headless: browser
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "worker-results"
            payload = {
                "worker_index": 1,
                "profile_dir": str(Path(temporary_directory) / "profile"),
                "output_dir": str(output_dir),
                "hotels": [{"name": "测试酒店", "detail_url": "https://hotels.ctrip.com/hotels/1.html"}],
                "config": {
                    "session_probe_seconds": 1,
                    "price_mode": "response",
                    "random_sleep_min_seconds": 0,
                    "random_sleep_max_seconds": 0,
                    "search_timeout_seconds": 1,
                    "api_timeout_seconds": 1,
                    "settle_ms": 0,
                    "show_all_rooms_xpath": "xpath=//show-all",
                    "page_price_xpath": "",
                    "page_room_name_xpath": "",
                    "page_price_sample_size": 0,
                    "page_price_timeout_seconds": 1,
                    "adults": 2,
                    "children": 0,
                    "rooms": 1,
                    "city_id": 95,
                    "start_date": "2026-09-03",
                    "days": 1,
                    "nights": 1,
                    "hotels": [],
                    "output_dir": str(output_dir),
                },
            }
            with (
                patch.dict(sys.modules, {"ctrip_cloak_launcher": launcher}),
                patch.object(
                    module,
                    "wait_for_stable_login_status",
                    return_value={"logged_in": False},
                ),
                patch.object(module, "_collect_hotels_with_browser") as collect_mock,
            ):
                result = module._run_parallel_worker(payload)

            self.assertFalse(result["ok"])
            self.assertIn("登录状态校验", result["error"])
            collect_mock.assert_not_called()
            self.assertTrue(browser.closed)
            self.assertTrue((output_dir / "index.json").is_file())

    def test_parallel_collection_assigns_isolated_profiles_and_merges_shards(self):
        module = load_collector_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_profile = root / "source-profile"
            (source_profile / "Default").mkdir(parents=True)
            (source_profile / "Default" / "Preferences").write_text(
                "profile",
                encoding="utf-8",
            )
            (source_profile / "SingletonLock").write_text(
                "locked",
                encoding="utf-8",
            )
            output_dir = root / "final-output"
            hotels = [
                {
                    "name": "第一家酒店",
                    "detail_url": "https://hotels.ctrip.com/hotels/1.html?cityid=95",
                },
                {
                    "name": "第二家酒店",
                    "detail_url": "https://hotels.ctrip.com/hotels/2.html?cityid=95",
                },
            ]
            config = {
                "max_parallel_instances": 2,
                "price_mode": "response",
            }
            run_root = module.build_parallel_run_dir(
                source_profile,
                run_id="test-run",
            )

            def fake_run_parallel_workers(payloads):
                self.assertEqual(len(payloads), 2)
                self.assertNotEqual(
                    payloads[0]["profile_dir"],
                    payloads[1]["profile_dir"],
                )
                results = []
                for payload in payloads:
                    hotel = payload["hotels"][0]
                    worker_output = Path(payload["output_dir"])
                    source_file = (
                        worker_output
                        / module.safe_filename(hotel["name"])
                        / "2026-09-03_2026-09-04.json"
                    )
                    source_file.parent.mkdir(parents=True)
                    source_file.write_text(
                        json.dumps({"hotel_name": hotel["name"]}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    module.write_run_index(
                        worker_output / "index.json",
                        [
                            {
                                "hotel_name": hotel["name"],
                                "check_in": "2026-09-03",
                                "check_out": "2026-09-04",
                                "status": "ok",
                                "file": str(source_file),
                            }
                        ],
                        status="ready_for_export",
                    )
                    results.append(
                        {
                            "worker_index": payload["worker_index"],
                            "ok": True,
                            "hotels": payload["hotels"],
                            "output_dir": payload["output_dir"],
                            "summary": [{"status": "ok"}],
                        }
                    )
                return results

            with patch.object(
                module,
                "run_parallel_workers",
                side_effect=fake_run_parallel_workers,
            ):
                summary = module.collect_parallel_hotels(
                    config=config,
                    profile_dir=source_profile,
                    hotels=hotels,
                    output_dir=output_dir,
                    run_root=run_root,
                )

            self.assertEqual(len(summary), 2)
            self.assertTrue(
                (run_root / "worker-1" / "profile" / "Default" / "Preferences").is_file()
            )
            self.assertFalse((run_root / "worker-1" / "profile" / "SingletonLock").exists())
            self.assertTrue((output_dir / "第一家酒店").is_dir())
            self.assertTrue((output_dir / "第二家酒店").is_dir())
            module.cleanup_parallel_run_dir(run_root)
            self.assertFalse(run_root.exists())
            self.assertTrue(source_profile.is_dir())


if __name__ == "__main__":
    unittest.main()
