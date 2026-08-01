import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from git import Repo
from loguru import logger

class RepoCloner:
    def __init__(self, workspace_dir: str = "./workspace"):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(exist_ok=True)

    def clone(self, repo_url: str, branch: Optional[str] = None) -> str:
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target_dir = self.workspace_dir / repo_name

        if target_dir.exists():
            shutil.rmtree(target_dir)

        logger.info(f"Cloning {repo_url} into {target_dir}")
        try:
            repo = Repo.clone_from(repo_url, target_dir)
            if branch:
                repo.git.checkout(branch)
            logger.info(f"Successfully cloned {repo_url}")
            return str(target_dir)
        except Exception as e:
            logger.error(f"Failed to clone {repo_url}: {e}")
            raise

    def get_repo_info(self, repo_path: str) -> dict:
        repo = Repo(repo_path)
        return {
            "path": repo_path,
            "name": Path(repo_path).name,
            "branch": repo.active_branch.name,
            "commit": repo.head.commit.hexsha,
            "remote_url": repo.remotes.origin.url if repo.remotes else None,
        }

    def list_cloned_repos(self) -> list:
        repos = []
        for item in self.workspace_dir.iterdir():
            if item.is_dir() and (item / ".git").exists():
                try:
                    info = self.get_repo_info(str(item))
                    repos.append(info)
                except Exception:
                    continue
        return repos

    def delete_repo(self, repo_name: str) -> bool:
        target_dir = self.workspace_dir / repo_name
        if target_dir.exists():
            shutil.rmtree(target_dir)
            return True
        return False
