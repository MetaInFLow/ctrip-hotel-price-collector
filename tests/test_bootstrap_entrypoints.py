import os
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHELL_BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap_ctrip_hotel_skill.sh"
DIRECT_REQUIREMENTS = PROJECT_ROOT / "requirements-cloak.txt"
LOCKED_REQUIREMENTS = PROJECT_ROOT / "requirements-cloak.lock"
PREFLIGHT_SCRIPT = PROJECT_ROOT / "scripts" / "verify_ctrip_hotel_environment.py"
POWERSHELL_BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap_ctrip_hotel_skill.ps1"
WINDOWS_BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap_ctrip_hotel_skill.cmd"
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "ctrip_cloak_launcher.py"
SAMPLE_CONFIG = PROJECT_ROOT / "ctrip_hotel_config.json"
LEGACY_BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap_ctrip_hotel_skill.py"
README_PATH = PROJECT_ROOT / "README.md"
SKILL_PATH = PROJECT_ROOT / "SKILL.md"
CLEAN_SCRIPT = PROJECT_ROOT / "scripts" / "clean_ctrip_hotel_environment.py"
GITIGNORE_PATH = PROJECT_ROOT / ".gitignore"


def load_preflight_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_ctrip_hotel_environment", PREFLIGHT_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载预检脚本：{PREFLIGHT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_launcher_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ctrip_cloak_launcher", LAUNCHER_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载浏览器启动器：{LAUNCHER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_legacy_bootstrap_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bootstrap_ctrip_hotel_skill", LEGACY_BOOTSTRAP
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载 Python 安装脚本：{LEGACY_BOOTSTRAP}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_clean_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("clean_ctrip_hotel_environment", CLEAN_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载环境清理脚本：{CLEAN_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapEntrypointTests(unittest.TestCase):
    def test_shell_dry_run_does_not_require_system_python(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_bin = Path(temporary_directory)
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 93\n", encoding="utf-8")
            fake_python.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            result = subprocess.run(
                ["bash", str(SHELL_BOOTSTRAP), "--dry-run"],
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("uv", result.stdout)
        self.assertIn(".runtime", result.stdout)
        self.assertIn("Python 3.12", result.stdout)
        self.assertIn(".venv", result.stdout)

    def test_runtime_dependencies_are_pinned_in_a_lock_file(self):
        direct_requirements = DIRECT_REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("cloakbrowser==0.5.10", direct_requirements)
        self.assertIn("openpyxl==3.1.5", direct_requirements)
        self.assertIn("socksio==1.0.0", direct_requirements)
        self.assertNotIn(">=", direct_requirements)
        self.assertTrue(LOCKED_REQUIREMENTS.is_file())
        locked_requirements = LOCKED_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("cloakbrowser==0.5.10", locked_requirements)
        self.assertIn("openpyxl==3.1.5", locked_requirements)
        self.assertIn("playwright==1.62.0", locked_requirements)
        self.assertIn("socksio==1.0.0", locked_requirements)

    def test_shell_installer_uses_a_local_runtime_and_runs_preflight(self):
        shell_script = SHELL_BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('UV_VERSION="0.12.11"', shell_script)
        self.assertIn('https://astral.sh/uv/$UV_VERSION/install.sh', shell_script)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fake_uv = temporary_root / "uv"
            log_path = temporary_root / "installer.log"
            fake_uv.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf 'uv %s\\n' "$*" >> "$CTRIP_TEST_LOG"
                    if [[ "$1" == "venv" ]]; then
                      venv_dir="${!#}"
                      mkdir -p "$venv_dir/bin"
                      cat > "$venv_dir/bin/python" <<'PYTHON'
                    #!/usr/bin/env bash
                    printf 'python %s\\n' "$*" >> "$CTRIP_TEST_LOG"
                    PYTHON
                      chmod +x "$venv_dir/bin/python"
                    fi
                    """
                ),
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            fake_bin = temporary_root / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 93\n", encoding="utf-8")
            fake_python.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "CTRIP_TEST_LOG": str(log_path),
                    "CTRIP_UV_BIN": str(fake_uv),
                    "CTRIP_RUNTIME_DIR": str(temporary_root / "runtime"),
                    "CTRIP_VENV_DIR": str(temporary_root / "venv"),
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", str(SHELL_BOOTSTRAP)],
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            installer_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("uv python install --no-bin 3.12.6", installer_log)
        self.assertIn("uv venv --clear --managed-python --python 3.12.6", installer_log)
        self.assertIn("uv pip sync --strict --require-hashes", installer_log)
        self.assertIn("requirements-cloak.lock", installer_log)
        self.assertIn("verify_ctrip_hotel_environment.py", installer_log)

    def test_shell_reports_the_failed_stage_when_runtime_download_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fake_bin = temporary_root / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
            fake_curl.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "CTRIP_RUNTIME_DIR": str(temporary_root / "runtime"),
                    "CTRIP_VENV_DIR": str(temporary_root / "venv"),
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", str(SHELL_BOOTSTRAP)],
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("安装未完成：下载本地 uv 运行时。", result.stdout)
        self.assertIn("PyPI、Astral 和 CloakBrowser", result.stdout)

    def test_shell_runtime_download_cleans_its_temp_file_before_function_exit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fake_bin = temporary_root / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    while [[ "$#" -gt 0 ]]; do
                      if [[ "$1" == "--output" ]]; then
                        output="$2"
                        shift 2
                        continue
                      fi
                      shift
                    done
                    cat > "$output" <<'INSTALLER'
                    #!/bin/sh
                    set -eu
                    mkdir -p "$UV_UNMANAGED_INSTALL"
                    cat > "$UV_UNMANAGED_INSTALL/uv" <<'UV'
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "$1" == "venv" ]]; then
                      venv_dir="${!#}"
                      mkdir -p "$venv_dir/bin"
                      cat > "$venv_dir/bin/python" <<'PYTHON'
                    #!/usr/bin/env bash
                    exit 0
                    PYTHON
                      chmod +x "$venv_dir/bin/python"
                    fi
                    UV
                    chmod +x "$UV_UNMANAGED_INSTALL/uv"
                    INSTALLER
                    """
                ),
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            runtime_dir = temporary_root / "runtime"
            environment = os.environ.copy()
            environment.update(
                {
                    "CTRIP_RUNTIME_DIR": str(runtime_dir),
                    "CTRIP_VENV_DIR": str(temporary_root / "venv"),
                    "TMPDIR": str(temporary_root),
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", str(SHELL_BOOTSTRAP)],
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            temporary_installers = list(temporary_root.glob("ctrip-uv-installer.*"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unbound variable", result.stderr)
        self.assertNotIn("unbound variable", result.stdout)
        self.assertEqual(temporary_installers, [])

    def test_preflight_downloads_browser_to_local_cache_and_checks_cli(self):
        self.assertTrue(PREFLIGHT_SCRIPT.is_file())
        module = load_preflight_module()
        fake_cloakbrowser = type(sys)("cloakbrowser")
        fake_openpyxl = type(sys)("openpyxl")
        fake_httpx = type(sys)("httpx")

        class FakeHttpxClient:
            def close(self):
                return None

        fake_httpx.Client = FakeHttpxClient

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            cache_dir = temporary_root / "cloakbrowser"
            browser_binary = temporary_root / "Chromium"
            browser_binary.write_text("binary", encoding="utf-8")
            commands = []

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.dict(
                    sys.modules,
                    {
                        "cloakbrowser": fake_cloakbrowser,
                        "openpyxl": fake_openpyxl,
                        "httpx": fake_httpx,
                    },
                ),
            ):
                result = module.verify_environment(
                    PROJECT_ROOT,
                    cache_dir,
                    ensure_binary_fn=lambda: str(browser_binary),
                    run_command=lambda command, **_kwargs: commands.append(command),
                )
                configured_cache_dir = os.environ["CLOAKBROWSER_CACHE_DIR"]
                configured_auto_update = os.environ["CLOAKBROWSER_AUTO_UPDATE"]

        self.assertEqual(result, browser_binary.resolve())
        self.assertEqual(configured_cache_dir, str(cache_dir.resolve()))
        self.assertEqual(configured_auto_update, "false")
        self.assertIn(
            [module.sys.executable, "-m", "cloakbrowser", "doctor", "--quick"],
            commands,
        )
        self.assertIn(
            [
                module.sys.executable,
                str(PROJECT_ROOT / "scripts" / "ctrip_cli.py"),
                "--help",
            ],
            commands,
        )

    def test_preflight_reports_an_invalid_proxy_without_exposing_its_value(self):
        module = load_preflight_module()
        invalid_proxy = "http://127.0.0.1::1"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            browser_binary = temporary_root / "Chromium"
            browser_binary.write_text("binary", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"HTTPS_PROXY": invalid_proxy},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "HTTPS_PROXY") as context:
                    module.verify_environment(
                        PROJECT_ROOT,
                        temporary_root / "cloakbrowser",
                        ensure_binary_fn=lambda: str(browser_binary),
                        run_command=lambda *_args, **_kwargs: None,
                    )

        self.assertNotIn(invalid_proxy, str(context.exception))

    def test_preflight_reports_an_invalid_no_proxy_without_exposing_its_value(self):
        module = load_preflight_module()
        invalid_no_proxy = "http://[::1"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            browser_binary = temporary_root / "Chromium"
            browser_binary.write_text("binary", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"NO_PROXY": invalid_no_proxy},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "NO_PROXY") as context:
                    module.verify_environment(
                        PROJECT_ROOT,
                        temporary_root / "cloakbrowser",
                        ensure_binary_fn=lambda: str(browser_binary),
                        run_command=lambda *_args, **_kwargs: None,
                    )

        self.assertNotIn(invalid_no_proxy, str(context.exception))

    def test_windows_entrypoints_use_the_same_local_runtime_contract(self):
        self.assertTrue(POWERSHELL_BOOTSTRAP.is_file())
        self.assertTrue(WINDOWS_BOOTSTRAP.is_file())
        powershell_script = POWERSHELL_BOOTSTRAP.read_text(encoding="utf-8")
        command_script = WINDOWS_BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn("UV_UNMANAGED_INSTALL", powershell_script)
        self.assertIn("UV_PYTHON_INSTALL_DIR", powershell_script)
        self.assertIn('$UvVersion = "0.12.11"', powershell_script)
        self.assertIn("https://astral.sh/uv/$UvVersion/install.ps1", powershell_script)
        self.assertIn('"python", "install", "--no-bin", $PythonVersion', powershell_script)
        self.assertIn('"venv", "--clear", "--managed-python"', powershell_script)
        self.assertIn('"pip", "sync", "--strict", "--require-hashes"', powershell_script)
        self.assertIn("verify_ctrip_hotel_environment.py", powershell_script)
        self.assertIn("CLOAKBROWSER_CACHE_DIR", powershell_script)
        self.assertIn("bootstrap_ctrip_hotel_skill.ps1", command_script)

    def test_collector_reuses_the_skill_local_browser_cache(self):
        launcher = load_launcher_module()
        self.assertTrue(hasattr(launcher, "configure_cloakbrowser_cache"))
        observed = {}
        fake_cloakbrowser = type(sys)("cloakbrowser")

        def fake_launch(*_args, **_kwargs):
            observed["cache_dir"] = os.environ.get("CLOAKBROWSER_CACHE_DIR")
            observed["auto_update"] = os.environ.get("CLOAKBROWSER_AUTO_UPDATE")
            return "browser"

        fake_cloakbrowser.launch_persistent_context = fake_launch
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(launcher.platform, "system", return_value="Linux"),
            patch.dict(sys.modules, {"cloakbrowser": fake_cloakbrowser}),
        ):
            result = launcher.launch_persistent_context("/tmp/ctrip-profile")

        self.assertEqual(result, "browser")
        self.assertEqual(
            observed["cache_dir"],
            str(PROJECT_ROOT / ".runtime" / "cloakbrowser"),
        )
        self.assertEqual(observed["auto_update"], "false")

    def test_customer_package_contains_an_editable_sample_configuration(self):
        self.assertTrue(SAMPLE_CONFIG.is_file())
        configuration = json.loads(SAMPLE_CONFIG.read_text(encoding="utf-8"))

        self.assertIsInstance(configuration["hotels"], list)
        self.assertGreater(len(configuration["hotels"]), 0)
        self.assertIsInstance(configuration["city_id"], int)
        self.assertIn("start_date", configuration)
        self.assertIn("days", configuration)
        self.assertNotIn("cookie", json.dumps(configuration).lower())
        self.assertNotIn("password", json.dumps(configuration).lower())

    def test_legacy_python_bootstrap_uses_locked_preflight(self):
        bootstrap = load_legacy_bootstrap_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            venv_dir = temporary_root / "venv"
            venv_python = temporary_root / "venv-python"
            venv_python.write_text("python", encoding="utf-8")
            commands = []

            with (
                patch.object(bootstrap, "resolve_python", return_value="/usr/bin/python3"),
                patch.object(bootstrap, "venv_python", return_value=venv_python),
                patch.object(bootstrap, "run", side_effect=commands.append),
            ):
                result = bootstrap.main(["--venv-dir", str(venv_dir)])

        self.assertEqual(result, 0)
        self.assertIn(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--require-hashes",
                "-r",
                str(LOCKED_REQUIREMENTS),
            ],
            commands,
        )
        self.assertIn(
            [
                str(venv_python),
                str(PREFLIGHT_SCRIPT),
                "--skill-dir",
                str(PROJECT_ROOT),
                "--cache-dir",
                str(PROJECT_ROOT / ".runtime" / "cloakbrowser"),
            ],
            commands,
        )

    def test_customer_readme_uses_native_install_entrypoints(self):
        readme = README_PATH.read_text(encoding="utf-8")
        skill_contract = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("install.sh", readme)
        self.assertIn("install.cmd", readme)
        self.assertIn("bin/ctrip-agent", readme)
        self.assertIn("无需预装 Python", readme)
        self.assertIn("安装与环境验证不需要访问外部下载服务", readme)
        self.assertIn("install.sh", skill_contract)
        self.assertIn("install.cmd", skill_contract)
        self.assertIn("bin/ctrip-agent", skill_contract)
        self.assertIn("无需依赖系统 Python", skill_contract)
        self.assertIn("安装验证无需外部下载", skill_contract)
        self.assertNotIn("代理环境变量", readme)
        self.assertNotIn(".venv", readme)
        self.assertNotIn("scripts/ctrip_cli.py", skill_contract)

    def test_reset_cleans_local_runtime_without_removing_customer_configuration(self):
        clean = load_clean_module()
        targets = clean.default_runtime_paths()

        self.assertIn(PROJECT_ROOT / ".runtime", targets)
        self.assertNotIn(SAMPLE_CONFIG, targets)
        self.assertTrue(clean._is_allowed_target(PROJECT_ROOT / ".runtime"))

    def test_generated_runtime_is_not_a_source_artifact(self):
        gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")

        self.assertIn(".runtime/", gitignore)


if __name__ == "__main__":
    unittest.main()
