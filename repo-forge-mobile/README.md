# RepoForge Mobile

PyMobile-native Android version of RepoForge. Clone repos, analyze Python code, select units, generate apps, and build APKs — all from your phone.

## Requirements

- Python 3.10+
- `pymobile-framework` (`pip install pymobile-framework`)
- Android SDK (auto-downloaded by `pymobile setup-sdk`)

## Quick Start

```bash
pip install pymobile-framework
pymobile setup-sdk
pymobile run          # desktop preview
pymobile build --native   # produce APK
```

## What It Does

| Screen | Action |
|--------|--------|
| **Clone** | Paste a GitHub URL to clone a repo via `git` |
| **Analyze** | Parse Python files with `ast` and index classes/functions/methods into SQLite |
| **Select** | Full-text search indexed units, toggle selection |
| **Generate** | Create a new PyMobile app scaffold from selected units |
| **Compile** | Shows generated project path; build on desktop with `pymobile build --native` |

## Notes

- APK compilation requires the Android SDK and JDK 17 on your build machine. The mobile app itself cannot compile APKs because the `pymobile` CLI is a development tool.
- Git must be available on the device for cloning (e.g., via Termux or a rooted environment with git installed).
- The runtime uses only the Python standard library to keep APK size small (~16.6 MB).
