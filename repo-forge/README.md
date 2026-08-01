# RepoForge

Clone GitHub repos, analyze and split code into pure Python SRP files, index them, select units, generate an app scaffold with AI-assisted frontend, and compile to APK.

## Architecture

```
repo-forge/
  app.py           - FastAPI backend with all routes
  cloner.py        - Git clone/delete repo management
  analyzer.py      - AST-based Python code splitter into SRP units
  indexer.py       - SQLite full-text search store for code units
  generator.py     - App scaffold generator (FastAPI + HTML frontend)
  compiler.py      - APK compiler via Briefcase/Kivy+Briefcase+BeeWare
  templates/       - Jinja2 HTML templates
  static/          - CSS and JS
  data/            - SQLite store and exports
  workspace/       - Cloned repos and generated apps
  requirements.txt - Python dependencies
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
# Open http://localhost:8000
```

## Workflow

1. **Clone** - Paste a GitHub URL to clone a repo
2. **Analyze** - Parse Python files with AST, split into classes/functions/methods
3. **Select** - Search and select code units from the indexed store
4. **Generate** - AI-assisted scaffold with FastAPI backend + HTML frontend
5. **Compile** - Build APK using Briefcase (BeeWare) or Kivy + Buildozer

## API Endpoints

- `POST /api/clone` - Clone a repository
- `POST /api/analyze` - Analyze and index a repo
- `GET /api/units` - Search indexed units
- `POST /api/select` - Toggle unit selection
- `POST /api/generate` - Generate app scaffold
- `POST /api/compile` - Compile APK

## Notes

- APK compilation requires Android SDK, NDK, and Java 11+
- For Kivy builds, `buildozer` requires a Linux environment with Android NDK
- Briefcase handles dependencies via TOML config
