import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from loguru import logger

Base = declarative_base()

class CodeUnitModel(Base):
    __tablename__ = "code_units"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    source = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    file_path = Column(String(500), nullable=False)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    imports = Column(Text, nullable=False, default="[]")
    dependencies = Column(Text, nullable=False, default="[]")
    tags = Column(Text, nullable=False, default="[]")
    complexity = Column(Integer, default=1)
    original_file = Column(String(500), nullable=False)
    repo_name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_selected = Column(Boolean, default=False)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "source": self.source,
            "description": self.description,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "imports": json.loads(self.imports),
            "dependencies": json.loads(self.dependencies),
            "tags": json.loads(self.tags),
            "complexity": self.complexity,
            "original_file": self.original_file,
            "repo_name": self.repo_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_selected": self.is_selected,
        }

class AppProject(Base):
    __tablename__ = "app_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    frontend_code = Column(Text, nullable=True)
    main_py = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    selected_units = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    build_status = Column(String(50), default="draft")
    build_log = Column(Text, nullable=True)

class FileStore:
    def __init__(self, db_path: str = "./data/store.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def index_units(self, units: List[Dict], repo_name: str):
        session = self.Session()
        try:
            for unit_data in units:
                existing = session.query(CodeUnitModel).filter_by(
                    name=unit_data["name"],
                    original_file=unit_data["original_file"],
                    repo_name=repo_name
                ).first()
                if existing:
                    continue
                model = CodeUnitModel(
                    name=unit_data["name"],
                    type=unit_data["type"],
                    source=unit_data["source"],
                    description=unit_data["description"],
                    file_path=unit_data["file_path"],
                    line_start=unit_data["line_start"],
                    line_end=unit_data["line_end"],
                    imports=json.dumps(unit_data.get("imports", [])),
                    dependencies=json.dumps(unit_data.get("dependencies", [])),
                    tags=json.dumps(unit_data.get("tags", [])),
                    complexity=unit_data.get("complexity", 1),
                    original_file=unit_data["original_file"],
                    repo_name=repo_name,
                )
                session.add(model)
            session.commit()
            logger.info(f"Indexed {len(units)} units for repo {repo_name}")
        finally:
            session.close()

    def search(self, query: str, repo_name: Optional[str] = None, unit_type: Optional[str] = None, limit: int = 100) -> List[Dict]:
        session = self.Session()
        try:
            q = session.query(CodeUnitModel)
            if repo_name:
                q = q.filter(CodeUnitModel.repo_name == repo_name)
            if unit_type:
                q = q.filter(CodeUnitModel.type == unit_type)
            if query:
                q = q.filter(CodeUnitModel.description.contains(query) | CodeUnitModel.name.contains(query))
            results = q.limit(limit).all()
            return [r.to_dict() for r in results]
        finally:
            session.close()

    def get_by_id(self, unit_id: int) -> Optional[Dict]:
        session = self.Session()
        try:
            model = session.query(CodeUnitModel).filter_by(id=unit_id).first()
            return model.to_dict() if model else None
        finally:
            session.close()

    def toggle_selection(self, unit_id: int, selected: bool):
        session = self.Session()
        try:
            model = session.query(CodeUnitModel).filter_by(id=unit_id).first()
            if model:
                model.is_selected = selected
                session.commit()
        finally:
            session.close()

    def get_selected(self, repo_name: Optional[str] = None) -> List[Dict]:
        session = self.Session()
        try:
            q = session.query(CodeUnitModel).filter_by(is_selected=True)
            if repo_name:
                q = q.filter(CodeUnitModel.repo_name == repo_name)
            return [r.to_dict() for r in q.all()]
        finally:
            session.close()

    def clear_selections(self, repo_name: Optional[str] = None):
        session = self.Session()
        try:
            q = session.query(CodeUnitModel).filter_by(is_selected=True)
            if repo_name:
                q = q.filter(CodeUnitModel.repo_name == repo_name)
            q.update({"is_selected": False})
            session.commit()
        finally:
            session.close()

    def create_project(self, name: str, description: str, selected_units: List[Dict], frontend_code: str, main_py: str, requirements: str) -> int:
        session = self.Session()
        try:
            project = AppProject(
                name=name,
                description=description,
                frontend_code=frontend_code,
                main_py=main_py,
                requirements=requirements,
                selected_units=json.dumps([u.get("id") for u in selected_units]),
            )
            session.add(project)
            session.commit()
            return project.id
        finally:
            session.close()

    def update_project(self, project_id: int, **kwargs):
        session = self.Session()
        try:
            project = session.query(AppProject).filter_by(id=project_id).first()
            if project:
                for key, value in kwargs.items():
                    if key == "selected_units" and isinstance(value, list):
                        value = json.dumps(value)
                    elif key in ("frontend_code", "main_py", "requirements", "build_log"):
                        value = str(value) if value else None
                    elif key == "build_status":
                        value = str(value)
                    setattr(project, key, value)
                session.commit()
        finally:
            session.close()

    def get_project(self, project_id: int) -> Optional[Dict]:
        session = self.Session()
        try:
            project = session.query(AppProject).filter_by(id=project_id).first()
            if not project:
                return None
            return {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "frontend_code": project.frontend_code,
                "main_py": project.main_py,
                "requirements": project.requirements,
                "selected_units": json.loads(project.selected_units),
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "build_status": project.build_status,
                "build_log": project.build_log,
            }
        finally:
            session.close()

    def list_projects(self) -> List[Dict]:
        session = self.Session()
        try:
            return [self.get_project(p.id) for p in session.query(AppProject).order_by(AppProject.created_at.desc()).all()]
        finally:
            session.close()
