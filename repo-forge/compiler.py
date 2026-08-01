import os
import json
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict
from loguru import logger

class ApkCompiler:
    def __init__(self, workspace_dir: str = "./workspace/apps"):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def compile_apk(self, project_path: str, project_name: str) -> Dict:
        app_dir = Path(project_path)
        if not app_dir.exists():
            return {"success": False, "log": "Project directory not found"}

        module_name = project_name.replace("-", "_").replace(" ", "_").lower()
        log_lines = []

        def run(cmd, cwd=None, env=None):
            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=cwd or app_dir,
                    capture_output=True, text=True, timeout=600
                )
                log_lines.append(f">>> {cmd}")
                log_lines.append(result.stdout)
                if result.stderr:
                    log_lines.append(result.stderr)
                return result.returncode == 0
            except subprocess.TimeoutExpired:
                log_lines.append("TIMEOUT")
                return False
            except Exception as e:
                log_lines.append(str(e))
                return False

        log_lines.append("Starting APK compilation pipeline...")

        if not run(f"briefcase create android"):
            return {"success": False, "log": "\n".join(log_lines)}

        log_lines.append("Create succeeded, building...")
        if not run(f"briefcase build android"):
            return {"success": False, "log": "\n".join(log_lines)}

        apk_path = app_dir / "build" / "android" / "gradle" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if apk_path.exists():
            log_lines.append(f"APK built successfully: {apk_path}")
            return {"success": True, "log": "\n".join(log_lines), "apk_path": str(apk_path)}
        else:
            log_lines.append("Build completed but APK not found at expected path")
            return {"success": True, "log": "\n".join(log_lines), "apk_path": None}

    def compile_apk_kivy(self, project_path: str, project_name: str) -> Dict:
        app_dir = Path(project_path)
        if not app_dir.exists():
            return {"success": False, "log": "Project directory not found"}

        log_lines = []
        log_lines.append("Starting Kivy/Buildozer APK compilation pipeline...")

        buildozer_spec = self._generate_buildozer_spec(project_name)
        (app_dir / "buildozer.spec").write_text(buildozer_spec, encoding="utf-8")

        main_py_content = (app_dir / "main.py").read_text(encoding="utf-8")
        kivy_main = self._generate_kivy_main(main_py_content, project_name)
        (app_dir / "main.py").write_text(kivy_main, encoding="utf-8")

        try:
            result = subprocess.run(
                ["buildozer", "-v", "android", "debug"],
                cwd=app_dir,
                capture_output=True,
                text=True,
                timeout=900
            )
            log_lines.append(result.stdout)
            if result.stderr:
                log_lines.append(result.stderr)

            apk_path = app_dir / "bin" / f"{project_name}-0.1-debug.apk"
            if apk_path.exists():
                return {"success": True, "log": "\n".join(log_lines), "apk_path": str(apk_path)}
            return {"success": result.returncode == 0, "log": "\n".join(log_lines), "apk_path": None}
        except Exception as e:
            return {"success": False, "log": "\n".join(log_lines + [str(e)])}

    def _generate_kivy_main(self, original_main: str, project_name: str) -> str:
        return f'''
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.uix.togglebutton import ToggleButton
import requests
import json
import threading

try:
    from src.{project_name.replace("-", "_").replace(" ", "_")} import *
except ImportError:
    pass


class RepoForgeApp(App):
    def build(self):
        self.title = "{project_name}"
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        
        header = BoxLayout(size_hint_y=None, height=50)
        title = Label(text="{project_name}", font_size=24, color=(0.4, 0.5, 0.9, 1))
        header.add_widget(title)
        layout.add_widget(header)
        
        self.output = TextInput(text="Starting {project_name}...\\n", readonly=True, size_hint_y=0.6)
        layout.add_widget(self.output)
        
        btn_layout = BoxLayout(size_hint_y=None, height=50, spacing=10)
        health_btn = Button(text="Check Health", background_color=(0.2, 0.6, 0.3, 1))
        health_btn.bind(on_press=self.check_health)
        btn_layout.add_widget(health_btn)
        
        run_btn = Button(text="Run Analysis", background_color=(0.3, 0.4, 0.8, 1))
        run_btn.bind(on_press=self.run_analysis)
        btn_layout.add_widget(run_btn)
        
        layout.add_widget(btn_layout)
        return layout

    def log(self, message):
        Clock.schedule_once(lambda dt: self._update_log(message))

    def _update_log(self, message):
        self.output.text += message + "\\n"

    def check_health(self, instance):
        self.log("Checking system health...")
        threading.Thread(target=self._health_worker, daemon=True).start()

    def _health_worker(self):
        try:
            resp = requests.get("http://localhost:8000/api/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                Clock.schedule_once(lambda dt: self.log(f"Status: {{data['status']}} - {{data['units']}} units loaded"))
            else:
                Clock.schedule_once(lambda dt: self.log("Health check failed"))
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log(f"Error: {{e}}"))

    def run_analysis(self, instance):
        self.log("Running analysis...")


if __name__ == "__main__":
    RepoForgeApp().run()
'''

    def _generate_buildozer_spec(self, project_name: str) -> str:
        return f'''
[app]
title = {project_name}
package.name = com.repoforge
package.domain = com.repoforge
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
orientation = portrait
fullscreen = 0
android.api = 34
android.ndk = 25b
android.minapi = 21
android.sdk = 34
android.private_storage = True
log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1

[requirements]
python3 = kivy
requests = *
fastapi = *
uvicorn = *
'''
