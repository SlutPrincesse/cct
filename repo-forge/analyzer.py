import ast
import os
import json
import textwrap
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from loguru import logger

@dataclass
class CodeUnit:
    name: str
    type: str
    source: str
    description: str
    file_path: str
    line_start: int
    line_end: int
    imports: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    complexity: int = 0
    original_file: str = ""

class PythonAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self.units: List[CodeUnit] = []
        self.file_index: Dict[str, Path] = {}

    def analyze_repo(self) -> List[CodeUnit]:
        python_files = list(self.repo_path.rglob("*.py"))
        logger.info(f"Found {len(python_files)} Python files in {self.repo_path}")

        for py_file in python_files:
            try:
                self._analyze_file(py_file)
            except Exception as e:
                logger.warning(f"Failed to analyze {py_file}: {e}")
                continue

        logger.info(f"Extracted {len(self.units)} code units")
        return self.units

    def _analyze_file(self, file_path: Path):
        rel_path = file_path.relative_to(self.repo_path)
        source = file_path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {rel_path}: {e}")
            return

        file_imports = self._extract_imports(tree)
        module_docstring = ast.get_docstring(tree)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._process_class(node, file_path, rel_path, source, file_imports)
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                self._process_function(node, file_path, rel_path, source, file_imports, is_method=False)

    def _process_class(self, node: ast.ClassDef, file_path: Path, rel_path: Path, source: str, file_imports: List[str]):
        class_source = ast.get_source_segment(source, node) or source
        description = self._generate_description(node, "class")
        deps = self._extract_dependencies(node, source)

        unit = CodeUnit(
            name=node.name,
            type="class",
            source=textwrap.dedent(class_source),
            description=description,
            file_path=str(rel_path),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            imports=file_imports,
            dependencies=deps,
            tags=self._generate_tags(node.name, "class"),
            complexity=self._calculate_complexity(node),
            original_file=str(rel_path),
        )
        self.units.append(unit)

        for item in node.body:
            if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                method_source = ast.get_source_segment(source, item) or source
                method_desc = self._generate_description(item, "method")
                method_deps = self._extract_dependencies(item, source)

                method_unit = CodeUnit(
                    name=f"{node.name}.{item.name}",
                    type="method",
                    source=textwrap.dedent(method_source),
                    description=method_desc,
                    file_path=str(rel_path),
                    line_start=item.lineno,
                    line_end=item.end_lineno or item.lineno,
                    imports=file_imports,
                    dependencies=method_deps,
                    tags=self._generate_tags(item.name, "method") + [node.name.lower()],
                    complexity=self._calculate_complexity(item),
                    original_file=str(rel_path),
                )
                self.units.append(method_unit)

    def _process_function(self, node: ast.FunctionDef, file_path: Path, rel_path: Path, source: str, file_imports: List[str], is_method: bool = False):
        if is_method:
            return
        func_source = ast.get_source_segment(source, node) or source
        description = self._generate_description(node, "function")
        deps = self._extract_dependencies(node, source)

        unit = CodeUnit(
            name=node.name,
            type="function",
            source=textwrap.dedent(func_source),
            description=description,
            file_path=str(rel_path),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            imports=file_imports,
            dependencies=deps,
            tags=self._generate_tags(node.name, "function"),
            complexity=self._calculate_complexity(node),
            original_file=str(rel_path),
        )
        self.units.append(unit)

    def _extract_imports(self, tree: ast.AST) -> List[str]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split('.')[0])
        return list(set(imports))

    def _extract_dependencies(self, node: ast.AST, source: str) -> List[str]:
        deps = set()
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
            elif isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name):
                    names.add(child.value.id)

        for name in names:
            if name not in dir(__builtins__) and not name.startswith('_'):
                deps.add(name)
        return list(deps)[:20]

    def _generate_description(self, node: ast.AST, kind: str) -> str:
        docstring = ast.get_docstring(node)
        if docstring:
            first_line = docstring.strip().split('\n')[0]
            return textwrap.shorten(first_line, width=120, placeholder="...")

        name = getattr(node, 'name', 'unknown')
        args = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [arg.arg for arg in node.args.args]
        elif isinstance(node, ast.ClassDef):
            bases = [self._get_name(base) for base in node.bases]
            if bases:
                return f"{kind} {name} inheriting from {', '.join(bases)}"

        if args:
            return f"{kind} {name}({', '.join(args[:3])})"
        return f"{kind} {name}"

    def _get_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return "Unknown"

    def _generate_tags(self, name: str, kind: str) -> List[str]:
        tags = [kind, name.lower()]
        words = []
        current = ""
        for char in name:
            if char.isupper() and current:
                words.append(current.lower())
                current = char
            else:
                current += char
        if current:
            words.append(current.lower())
        tags.extend(words)
        return list(set(tags))

    def _calculate_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                complexity += 1
            elif isinstance(child, (ast.BoolOp, ast.comprehension)):
                complexity += 1
        return complexity

    def to_json(self) -> str:
        return json.dumps([asdict(u) for u in self.units], indent=2)

    def save_units(self, output_dir: str):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for unit in self.units:
            safe_name = unit.name.replace(".", "_")
            filename = f"{unit.type}_{safe_name}.py"
            filepath = out / filename
            content = f'"""\n{unit.description}\n"""\n\n'
            content += unit.source
            filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved {len(self.units)} units to {output_dir}")
