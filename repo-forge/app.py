from fastapi import FastAPI, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Optional
import json
import uuid
import os

from cloner import RepoCloner
from analyzer import PythonAnalyzer
from indexer import FileStore
from generator import AppGenerator
from compiler import ApkCompiler
from loguru import logger

app = FastAPI(title="RepoForge")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

cloner = RepoCloner(str(BASE_DIR / "workspace"))
store = FileStore(str(DATA_DIR / "store.db"))
generator = AppGenerator(str(BASE_DIR / "workspace" / "apps"))
compiler = ApkCompiler(str(BASE_DIR / "workspace" / "apps"))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    repos = cloner.list_cloned_repos()
    projects = store.list_projects()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "repos": repos,
        "projects": projects,
    })


@app.get("/clone", response_class=HTMLResponse)
async def clone_page(request: Request):
    repos = cloner.list_cloned_repos()
    return templates.TemplateResponse("clone.html", {"request": request, "repos": repos})


@app.post("/api/clone")
async def clone_repo(repo_url: str = Form(...), branch: Optional[str] = Form(None)):
    try:
        path = cloner.clone(repo_url, branch)
        return JSONResponse({"success": True, "path": path, "message": "Repository cloned successfully"})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)})


@app.delete("/api/repos/{repo_name}")
async def delete_repo(repo_name: str):
    success = cloner.delete_repo(repo_name)
    if success:
        return JSONResponse({"success": True})
    raise HTTPException(status_code=404, detail="Repo not found")


@app.get("/analyze", response_class=HTMLResponse)
async def analyze_page(request: Request):
    repos = cloner.list_cloned_repos()
    return templates.TemplateResponse("analyze.html", {"request": request, "repos": repos})


@app.post("/api/analyze")
async def analyze_repo(repo_path: str = Form(...), repo_name: str = Form(...)):
    try:
        analyzer = PythonAnalyzer(repo_path)
        units = analyzer.analyze_repo()
        units_data = [{
            "name": u.name,
            "type": u.type,
            "source": u.source,
            "description": u.description,
            "file_path": u.file_path,
            "line_start": u.line_start,
            "line_end": u.line_end,
            "imports": u.imports,
            "dependencies": u.dependencies,
            "tags": u.tags,
            "complexity": u.complexity,
            "original_file": u.original_file,
        } for u in units]

        analyzer.save_units(str(DATA_DIR / "exports" / repo_name))
        store.index_units(units_data, repo_name)

        return JSONResponse({"success": True, "count": len(units_data), "units": units_data[:50]})
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/select", response_class=HTMLResponse)
async def select_page(request: Request, repo: Optional[str] = None, q: Optional[str] = None):
    repos = cloner.list_cloned_repos()
    units = store.search(q or "", repo_name=repo, limit=200)
    return templates.TemplateResponse("select.html", {
        "request": request,
        "repos": repos,
        "units": units,
        "selected_repo": repo,
        "query": q or "",
    })


@app.post("/api/select")
async def toggle_select(unit_id: int = Form(...), selected: bool = Form(...)):
    store.toggle_selection(unit_id, selected)
    return JSONResponse({"success": True})


@app.post("/api/select/clear")
async def clear_selections(repo_name: Optional[str] = Form(None)):
    store.clear_selections(repo_name)
    return JSONResponse({"success": True})


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    selected = store.get_selected()
    return templates.TemplateResponse("generate.html", {
        "request": request,
        "units": selected,
    })


@app.post("/api/generate")
async def generate_app(project_name: str = Form(...), description: str = Form("")):
    selected = store.get_selected()
    if not selected:
        return JSONResponse({"success": False, "message": "No units selected"})

    result = generator.generate_app(project_name, selected, description)
    project_id = store.create_project(project_name, description, selected, result["frontend"], result["main_py"], result["requirements"])
    return JSONResponse({"success": True, "project_id": project_id, "path": result["path"]})


@app.get("/compile", response_class=HTMLResponse)
async def compile_page(request: Request):
    projects = store.list_projects()
    return templates.TemplateResponse("compile.html", {"request": request, "projects": projects})


@app.post("/api/compile")
async def compile_project(project_id: int = Form(...)):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    store.update_project(project_id, build_status="building", build_log="Starting compilation...")

    result = compiler.compile_apk(project["path"], project["name"])
    status = "success" if result["success"] else "failed"
    store.update_project(project_id, build_status=status, build_log=result["log"])

    return JSONResponse(result)


@app.get("/api/repos")
async def list_repos():
    repos = cloner.list_cloned_repos()
    return JSONResponse(repos)


@app.get("/api/units")
async def search_units(repo: Optional[str] = None, q: Optional[str] = None, type: Optional[str] = None):
    units = store.search(q or "", repo_name=repo, unit_type=type, limit=100)
    return JSONResponse(units)


@app.get("/api/projects")
async def list_projects():
    return JSONResponse(store.list_projects())


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404)
    return JSONResponse(project)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
