"""RepoForge Mobile — clone, analyze, select, generate, and compile Python code to APK."""

from __future__ import annotations

import ast
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymobile import (
    App,
    Button,
    Column,
    EdgeInsets,
    Label,
    Row,
    Screen,
    ScrollView,
    Spacer,
    Style,
    TextInput,
    Widget,
)
from pymobile.core.ui import Align, Color

WORKSPACE = Path("/data/data/com.repoforge.app/files/workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)
DB_PATH = WORKSPACE / "store.db"


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            source TEXT NOT NULL,
            description TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            imports TEXT NOT NULL DEFAULT '[]',
            dependencies TEXT NOT NULL DEFAULT '[]',
            tags TEXT NOT NULL DEFAULT '[]',
            complexity INTEGER DEFAULT 1,
            original_file TEXT NOT NULL,
            repo_name TEXT NOT NULL,
            is_selected INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            selected_units TEXT NOT NULL DEFAULT '[]',
            build_status TEXT DEFAULT 'draft',
            build_log TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_units_repo ON units(repo_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_units_selected ON units(is_selected)")
    conn.commit()
    return conn


DB = init_db()


# ── Cloner ──────────────────────────────────────────────────────────────────

class RepoCloner:
    def __init__(self, workspace: Path = WORKSPACE):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    def clone(self, url: str, branch: Optional[str] = None) -> Dict[str, Any]:
        name = url.rstrip("/").split("/")[-1].replace(".git", "")
        target = self.workspace / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", url, str(target)]
        if branch:
            cmd += ["--branch", branch]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"success": False, "message": proc.stderr or proc.stdout}
        return {"success": True, "path": str(target), "name": name}

    def list_repos(self) -> List[Dict[str, str]]:
        repos = []
        if not self.workspace.exists():
            return repos
        for d in self.workspace.iterdir():
            if (d / ".git").exists():
                try:
                    branch = subprocess.run(
                        ["git", "-C", str(d), "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True, text=True
                    ).stdout.strip()
                    commit = subprocess.run(
                        ["git", "-C", str(d), "rev-parse", "--short", "HEAD"],
                        capture_output=True, text=True
                    ).stdout.strip()
                    remote = subprocess.run(
                        ["git", "-C", str(d), "remote", "get-url", "origin"],
                        capture_output=True, text=True
                    ).stdout.strip()
                    repos.append({
                        "name": d.name,
                        "path": str(d),
                        "branch": branch,
                        "commit": commit,
                        "remote": remote,
                    })
                except Exception:
                    continue
        return repos

    def delete(self, name: str) -> bool:
        target = self.workspace / name
        if target.exists():
            shutil.rmtree(target)
            return True
        return False


cloner = RepoCloner()


# ── Analyzer ────────────────────────────────────────────────────────────────

class CodeUnit:
    def __init__(self, name: str, type: str, source: str, description: str,
                 file_path: str, line_start: int, line_end: int,
                 imports: List[str], dependencies: List[str], tags: List[str],
                 complexity: int, original_file: str):
        self.name = name
        self.type = type
        self.source = source
        self.description = description
        self.file_path = file_path
        self.line_start = line_start
        self.line_end = line_end
        self.imports = imports
        self.dependencies = dependencies
        self.tags = tags
        self.complexity = complexity
        self.original_file = original_file

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "source": self.source,
            "description": self.description,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "imports": self.imports,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "complexity": self.complexity,
            "original_file": self.original_file,
        }


class PythonAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def analyze(self) -> List[CodeUnit]:
        units: List[CodeUnit] = []
        for py in self.repo_path.rglob("*.py"):
            try:
                units.extend(self._file(py))
            except Exception:
                continue
        return units

    def _file(self, path: Path) -> List[CodeUnit]:
        rel = path.relative_to(self.repo_path)
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        imports = self._imports(tree)
        out: List[CodeUnit] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                cls_unit = self._class(node, path, rel, src, imports)
                out.append(cls_unit)
                if hasattr(cls_unit, "_methods"):
                    out.extend(cls_unit._methods)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(self._func(node, path, rel, src, imports))
        return out

    def _class(self, node: ast.ClassDef, path: Path, rel: Path, src: str, imports: List[str]) -> CodeUnit:
        bases = [self._name(b) for b in node.bases]
        desc = f"class {node.name}" + (f" inheriting from {', '.join(bases)}" if bases else "")
        doc = ast.get_docstring(node)
        if doc:
            desc = doc.strip().split("\n")[0]
        unit = CodeUnit(
            name=node.name, type="class",
            source=textwrap.dedent(ast.get_source_segment(src, node) or ""),
            description=desc[:120], file_path=str(rel),
            line_start=node.lineno, line_end=node.end_lineno or node.lineno,
            imports=imports, dependencies=self._deps(node, src),
            tags=["class", node.name.lower()], complexity=self._cx(node),
            original_file=str(rel),
        )
        methods: List[CodeUnit] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mdesc = ast.get_docstring(item) or f"method {item.name}"
                mdesc = mdesc.strip().split("\n")[0]
                methods.append(CodeUnit(
                    name=f"{node.name}.{item.name}", type="method",
                    source=textwrap.dedent(ast.get_source_segment(src, item) or ""),
                    description=mdesc[:120], file_path=str(rel),
                    line_start=item.lineno, line_end=item.end_lineno or item.lineno,
                    imports=imports, dependencies=self._deps(item, src),
                    tags=["method", item.name.lower(), node.name.lower()],
                    complexity=self._cx(item), original_file=str(rel),
                ))
        # Store methods on the class unit for retrieval
        unit._methods = methods  # type: ignore
        return unit

    def _func(self, node: ast.FunctionDef, path: Path, rel: Path, src: str, imports: List[str]) -> CodeUnit:
        args = [a.arg for a in node.args.args][:3]
        desc = ast.get_docstring(node) or f"function {node.name}({', '.join(args)})"
        desc = desc.strip().split("\n")[0]
        return CodeUnit(
            name=node.name, type="function",
            source=textwrap.dedent(ast.get_source_segment(src, node) or ""),
            description=desc[:120], file_path=str(rel),
            line_start=node.lineno, line_end=node.end_lineno or node.lineno,
            imports=imports, dependencies=self._deps(node, src),
            tags=["function", node.name.lower()], complexity=self._cx(node),
            original_file=str(rel),
        )

    def _imports(self, tree: ast.AST) -> List[str]:
        imps = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imps.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                imps.add(n.module.split(".")[0])
        return list(imps)

    def _deps(self, node: ast.AST, src: str) -> List[str]:
        names = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                names.add(n.value.id)
        return [n for n in names if n not in dir(__builtins__) and not n.startswith("_")][:20]

    def _name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._name(node.value)}.{node.attr}"
        return "?"

    def _cx(self, node: ast.AST) -> int:
        cx = 1
        for n in ast.walk(node):
            if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp)):
                cx += 1
        return cx


# ── Indexer ─────────────────────────────────────────────────────────────────

def index_units(units: List[Dict], repo_name: str):
    cur = DB.cursor()
    for u in units:
        cur.execute("""
            INSERT OR IGNORE INTO units
            (name, type, source, description, file_path, line_start, line_end,
             imports, dependencies, tags, complexity, original_file, repo_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u["name"], u["type"], u["source"], u["description"], u["file_path"],
            u["line_start"], u["line_end"], json.dumps(u.get("imports", [])),
            json.dumps(u.get("dependencies", [])), json.dumps(u.get("tags", [])),
            u.get("complexity", 1), u["original_file"], repo_name,
        ))
    DB.commit()


def search_units(query: str = "", repo: str = "", utype: str = "", limit: int = 100) -> List[Dict]:
    cur = DB.cursor()
    sql = "SELECT * FROM units WHERE 1=1"
    params: List[Any] = []
    if repo:
        sql += " AND repo_name = ?"
        params.append(repo)
    if utype:
        sql += " AND type = ?"
        params.append(utype)
    if query:
        sql += " AND (description LIKE ? OR name LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    results = []
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("imports", "dependencies", "tags"):
            d[k] = json.loads(d.get(k, "[]") or "[]")
        d["is_selected"] = bool(d.get("is_selected", 0))
        results.append(d)
    return results


def toggle_select(unit_id: int, selected: bool):
    DB.execute("UPDATE units SET is_selected = ? WHERE id = ?", (1 if selected else 0, unit_id))
    DB.commit()


def clear_selections(repo: str = ""):
    if repo:
        DB.execute("UPDATE units SET is_selected = 0 WHERE repo_name = ?", (repo,))
    else:
        DB.execute("UPDATE units SET is_selected = 0")
    DB.commit()


def get_selected() -> List[Dict]:
    cur = DB.cursor()
    cur.execute("SELECT * FROM units WHERE is_selected = 1")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    results = []
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("imports", "dependencies", "tags"):
            d[k] = json.loads(d.get(k, "[]") or "[]")
        d["is_selected"] = True
        results.append(d)
    return results


def create_project(name: str, description: str, units: List[Dict]) -> int:
    cur = DB.cursor()
    cur.execute("""
        INSERT INTO projects (name, description, selected_units, build_status)
        VALUES (?, ?, ?, 'draft')
    """, (name, description, json.dumps([u.get("id") for u in units])))
    DB.commit()
    return cur.lastrowid


def update_project(pid: int, **kwargs):
    sets = []
    params: List[Any] = []
    for k, v in kwargs.items():
        if k in ("selected_units", "build_log") and isinstance(v, list):
            v = json.dumps(v)
        sets.append(f"{k} = ?")
        params.append(v)
    params.append(pid)
    DB.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params)
    DB.commit()


def get_project(pid: int) -> Optional[Dict]:
    cur = DB.cursor()
    cur.execute("SELECT * FROM projects WHERE id = ?", (pid,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, row))
    d["selected_units"] = json.loads(d.get("selected_units", "[]") or "[]")
    return d


def list_projects() -> List[Dict]:
    cur = DB.cursor()
    cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── Generator ───────────────────────────────────────────────────────────────

class AppGenerator:
    def __init__(self, workspace: Path = WORKSPACE):
        self.workspace = workspace

    def generate(self, name: str, units: List[Dict], description: str = "") -> Dict[str, Any]:
        safe = name.lower().replace(" ", "_").replace("-", "_")
        app_dir = self.workspace / "apps" / safe
        if app_dir.exists():
            shutil.rmtree(app_dir)
        app_dir.mkdir(parents=True, exist_ok=True)

        src_dir = app_dir / "src" / safe
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "__init__.py").write_text("")

        for u in units:
            fname = f"{u['type']}_{u['name'].replace('.', '_')}.py"
            content = f'"""\n{u["description"]}\nOriginal: {u["original_file"]}\n"""\n\n'
            content += u["source"]
            (src_dir / fname).write_text(content, encoding="utf-8")

        main_py = self._main(safe, units, description)
        (app_dir / "main.py").write_text(main_py, encoding="utf-8")

        toml = self._toml(name, safe)
        (app_dir / "pymobile.toml").write_text(toml, encoding="utf-8")

        reqs = self._requirements(units)
        (app_dir / "requirements.txt").write_text(reqs, encoding="utf-8")

        return {"path": str(app_dir), "name": name}

    def _main(self, safe: str, units: List[Dict], desc: str) -> str:
        imports = []
        classes = []
        funcs = []
        for u in units:
            if u["type"] == "class":
                cls = u["name"].split(".")[0]
                imports.append(f"from src.{safe}.{u['type']}_{u['name'].replace('.', '_')} import {cls}")
                classes.append(cls)
            elif u["type"] == "function":
                imports.append(f"from src.{safe}.{u['type']}_{u['name'].replace('.', '_')} import {u['name']}")
                funcs.append(u["name"])
        import_block = "\n".join(sorted(set(imports)))
        return f'''"""Generated by RepoForge."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

{import_block}

from pymobile import App, Button, Column, Label, Screen, Style, Widget
from pymobile.core.ui import Color


class GeneratedHome(Screen):
    title = "{desc or safe}"

    def build(self) -> Widget:
        self.status = Label("Ready", style=Style(color=Color.SUCCESS))
        rows = [Label("{desc or safe}", style=Style(font_size=22, bold=True, color=Color.PRIMARY)), self.status]
        for fn in {funcs[:5]!r}:
            rows.append(Button(fn, on_press=lambda *_, f=fn: self.run_fn(f)))
        return Column(*rows, spacing=10, style=Style(padding=EdgeInsets.all(16)))

    def run_fn(self, name):
        try:
            fn = globals().get(name)
            if fn:
                self.status.set_text(f"{{name}}: {{str(fn())}}")
            else:
                self.status.set_text(f"{{name}} not found")
        except Exception as e:
            self.status.set_text(f"Error: {{e}}")


def main():
    App("{desc or safe}").run(GeneratedHome())


if __name__ == "__main__":
    main()
'''

    def _toml(self, name: str, safe: str) -> str:
        return f"""\
[app]
name = "{name}"
package = "com.repoforge.generated"
version = "0.1.0"
version_code = 1
entrypoint = "main.py"
source_dir = "."
min_sdk = 21
target_sdk = 34
orientation = "portrait"
permissions = ["android.permission.INTERNET"]
abis = ["arm64-v8a"]
output_dir = "build"
optimize = true
strip_debug = true

exclude = [
    "**/__pycache__/**",
    "**/*.pyc",
    ".git/**",
    ".venv/**",
    "build/**",
]
"""

    def _requirements(self, units: List[Dict]) -> str:
        imps = set()
        for u in units:
            for i in u.get("imports", []):
                imps.add(i)
        std = {"os", "sys", "json", "re", "math", "datetime", "pathlib", "collections",
               "itertools", "functools", "typing", "dataclasses", "enum", "abc",
               "statistics", "random", "string", "time", "hashlib", "base64", "io",
               "csv", "sqlite3", "logging", "argparse", "configparser", "socket",
               "ssl", "secrets", "tempfile", "shutil", "glob", "textwrap", "struct",
               "codecs", "unicodedata", "copy", "pprint", "http", "urllib", "email"}
        return "\n".join(sorted(imps - std)) or "pymobile-framework"


generator = AppGenerator()


# ── Compiler ────────────────────────────────────────────────────────────────

def compile_apk(project_path: str, project_name: str) -> Dict[str, Any]:
    app_dir = Path(project_path)
    if not app_dir.exists():
        return {"success": False, "log": "Project not found"}
    log: List[str] = []
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pymobile", "build", "--native"],
            cwd=str(app_dir), capture_output=True, text=True, timeout=600
        )
        log.append(proc.stdout)
        if proc.stderr:
            log.append(proc.stderr)
        apk = app_dir / "build" / f"{project_name.lower().replace(' ', '_')}-0.1.0.apk"
        if apk.exists():
            return {"success": True, "log": "\n".join(log), "apk": str(apk)}
        return {"success": proc.returncode == 0, "log": "\n".join(log), "apk": None}
    except Exception as e:
        return {"success": False, "log": "\n".join(log + [str(e)])}


# ── Screens ─────────────────────────────────────────────────────────────────

class HomeScreen(Screen):
    title = "RepoForge"

    def __init__(self) -> None:
        super().__init__()
        self.log_text = ""

    def build(self) -> Widget:
        self.log_label = Label(self.log_text or "Welcome to RepoForge", style=Style(color=Color.TEXT_MUTED))
        return ScrollView(
            Column(
                Label("RepoForge", style=Style(font_size=28, bold=True, color=Color.PRIMARY)),
                Spacer(12),
                Button("Clone Repo", on_press=self.open_clone),
                Button("Analyze Code", on_press=self.open_analyze),
                Button("Select Units", on_press=self.open_select),
                Button("Generate App", on_press=self.open_generate),
                Button("Compile APK", on_press=self.open_compile),
                Spacer(20),
                self.log_label,
                spacing=12,
                align=Align.CENTER,
                style=Style(padding=EdgeInsets.all(20)),
            )
        )

    def set_log(self, text: str):
        self.log_text = text
        if hasattr(self, "log_label"):
            self.log_label.set_text(text)

    def open_clone(self, _):
        self.app.push(CloneScreen(parent=self))

    def open_analyze(self, _):
        self.app.push(AnalyzeScreen(parent=self))

    def open_select(self, _):
        self.app.push(SelectScreen(parent=self))

    def open_generate(self, _):
        self.app.push(GenerateScreen(parent=self))

    def open_compile(self, _):
        self.app.push(CompileScreen(parent=self))


class CloneScreen(Screen):
    title = "Clone"

    def __init__(self, parent: HomeScreen):
        super().__init__()
        self.parent = parent

    def build(self) -> Widget:
        self.url_input = TextInput(placeholder="https://github.com/user/repo.git")
        self.branch_input = TextInput(placeholder="branch (optional)")
        self.status = Label("", style=Style(color=Color.TEXT_MUTED))
        return ScrollView(
            Column(
                Label("Clone Repository", style=Style(font_size=22, bold=True, color=Color.PRIMARY)),
                self.url_input,
                self.branch_input,
                Button("Clone", on_press=self.do_clone),
                self.status,
                Spacer(20),
                Button("Back", on_press=lambda _: self.app.pop()),
                spacing=12,
                style=Style(padding=EdgeInsets.all(16)),
            )
        )

    def do_clone(self, _):
        url = self.url_input.text.strip()
        if not url:
            self.status.set_text("Enter a URL")
            return
        self.status.set_text("Cloning...")
        self.app.render()

        def work():
            branch = self.branch_input.text.strip() or None
            res = cloner.clone(url, branch)
            msg = res.get("message", "Done")
            if res.get("success"):
                self.parent.set_log(f"Cloned: {res.get('name')}")
            self.status.set_text(msg)
            self.app.render()

        threading.Thread(target=work, daemon=True).start()


class AnalyzeScreen(Screen):
    title = "Analyze"

    def __init__(self, parent: HomeScreen):
        super().__init__()
        self.parent = parent
        self.repos: List[Dict] = []
        self.units: List[Dict] = []

    def on_show(self):
        self.repos = cloner.list_repos()

    def build(self) -> Widget:
        self.status = Label("Select a repo to analyze", style=Style(color=Color.TEXT_MUTED))
        self.repo_btn = Button("Load repos...", on_press=self.load_repos)
        self.results_label = Label("", style=Style(color=Color.TEXT_MUTED))
        return ScrollView(
            Column(
                Label("Analyze Code", style=Style(font_size=22, bold=True, color=Color.PRIMARY)),
                self.repo_btn,
                self.status,
                self.results_label,
                Button("Back", on_press=lambda _: self.app.pop()),
                spacing=12,
                style=Style(padding=EdgeInsets.all(16)),
            )
        )

    def load_repos(self, _):
        self.repos = cloner.list_repos()
        if not self.repos:
            self.status.set_text("No repos found. Clone one first.")
            return
        repo = self.repos[0]
        self.status.set_text(f"Analyzing {repo['name']}...")
        self.app.render()

        def work():
            analyzer = PythonAnalyzer(repo["path"])
            units = analyzer.analyze()
            index_units([u.to_dict() for u in units], repo["name"])
            self.units = [u.to_dict() for u in units]
            self.status.set_text(f"Indexed {len(units)} units from {repo['name']}")
            self.results_label.set_text(f"{len(units)} units found")
            self.parent.set_log(f"Analyzed {repo['name']}: {len(units)} units")
            self.app.render()

        threading.Thread(target=work, daemon=True).start()


class SelectScreen(Screen):
    title = "Select"

    def __init__(self, parent: HomeScreen):
        super().__init__()
        self.parent = parent
        self.units: List[Dict] = []
        self.query = ""

    def on_show(self):
        self.refresh()

    def build(self) -> Widget:
        self.search = TextInput(placeholder="Search units...", on_change=self.on_search)
        self.count_label = Label("", style=Style(color=Color.TEXT_MUTED))
        self.content = Column(spacing=8)
        return ScrollView(
            Column(
                Label("Select Units", style=Style(font_size=22, bold=True, color=Color.PRIMARY)),
                self.search,
                self.count_label,
                self.content,
                Button("Back", on_press=lambda _: self.app.pop()),
                Button("Clear selections", on_press=self.clear),
                spacing=12,
                style=Style(padding=EdgeInsets.all(16)),
            )
        )

    def on_search(self, text):
        self.query = text
        self.refresh()

    def refresh(self):
        self.units = search_units(self.query, limit=50)
        self.count_label.set_text(f"{len(self.units)} units")
        self.content.children = []
        for u in self.units:
            row = Row(
                Button(u["name"], on_press=lambda _, uid=u["id"], sel=not u["is_selected"]: self.toggle(uid, sel)),
                Label(u["type"], style=Style(color=Color.TEXT_MUTED)),
                expand=True,
            )
            self.content.add(row)
        self.app.render()

    def toggle(self, uid: int, sel: bool):
        toggle_select(uid, sel)
        self.refresh()

    def clear(self, _):
        clear_selections()
        self.refresh()


class GenerateScreen(Screen):
    title = "Generate"

    def __init__(self, parent: HomeScreen):
        super().__init__()
        self.parent = parent

    def build(self) -> Widget:
        self.name_input = TextInput(placeholder="Project name")
        self.desc_input = TextInput(placeholder="Description")
        self.status = Label("", style=Style(color=Color.TEXT_MUTED))
        return ScrollView(
            Column(
                Label("Generate App", style=Style(font_size=22, bold=True, color=Color.PRIMARY)),
                self.name_input,
                self.desc_input,
                Button("Generate", on_press=self.do_generate),
                self.status,
                Button("Back", on_press=lambda _: self.app.pop()),
                spacing=12,
                style=Style(padding=EdgeInsets.all(16)),
            )
        )

    def do_generate(self, _):
        name = self.name_input.text.strip()
        if not name:
            self.status.set_text("Enter a project name")
            return
        units = get_selected()
        if not units:
            self.status.set_text("No units selected")
            return
        self.status.set_text("Generating...")
        self.app.render()

        def work():
            res = generator.generate(name, units, self.desc_input.text.strip())
            create_project(name, self.desc_input.text.strip(), units)
            self.status.set_text(f"Generated at {res['path']}")
            self.parent.set_log(f"Generated app: {name}")
            self.app.render()

        threading.Thread(target=work, daemon=True).start()


class CompileScreen(Screen):
    title = "Compile"

    def __init__(self, parent: HomeScreen):
        super().__init__()
        self.parent = parent

    def build(self) -> Widget:
        self.status = Label("", style=Style(color=Color.TEXT_MUTED))
        self.projects_list = Column(spacing=8)
        return ScrollView(
            Column(
                Label("Compile APK", style=Style(font_size=22, bold=True, color=Color.PRIMARY)),
                Label("Note: APK compilation requires the pymobile CLI on a desktop machine.",
                      style=Style(color=Color.TEXT_MUTED)),
                self.projects_list,
                self.status,
                Button("Back", on_press=lambda _: self.app.pop()),
                Button("Refresh", on_press=self.refresh),
                spacing=12,
                style=Style(padding=EdgeInsets.all(16)),
            )
        )

    def on_show(self):
        self.refresh()

    def refresh(self, _=None):
        self.projects_list.children = []
        projects = list_projects()
        for p in projects:
            path = p.get("path") or str(WORKSPACE / "apps" / p["name"].lower().replace(" ", "_"))
            row = Row(
                Column(
                    Label(p["name"], style=Style(bold=True)),
                    Label(f"Status: {p.get('build_status', 'draft')}", style=Style(color=Color.TEXT_MUTED)),
                    Label(f"Path: {path}", style=Style(color=Color.TEXT_MUTED, font_size=10)),
                ),
                Button("Open", on_press=lambda _, p=path: self.open_project(p)),
            )
            self.projects_list.add(row)
        self.app.render()

    def open_project(self, path: str):
        self.status.set_text(f"Project at: {path}")
        self.status.set_text("Build on desktop with: cd <path> && pymobile build --native")


# ── Entry Point ─────────────────────────────────────────────────────────────

def main() -> None:
    app = App("RepoForge")
    app.run(HomeScreen())


if __name__ == "__main__":
    main()
