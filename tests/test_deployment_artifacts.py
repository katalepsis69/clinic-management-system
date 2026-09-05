import os
import yaml

def test_deployment_files_exist():
    assert os.path.exists("Dockerfile")
    assert os.path.exists("Procfile")
    assert os.path.exists("render.yaml")
    assert os.path.exists(".dockerignore")

def test_procfile_content():
    with open("Procfile", "r", encoding="utf-8") as f:
        content = f.read().strip()
    assert content == "web: uvicorn app.main:app --host 0.0.0.0 --port $PORT"

def test_dockerfile_content():
    with open("Dockerfile", "r", encoding="utf-8") as f:
        content = f.read()
    assert "FROM python:3.12-slim" in content
    assert "WORKDIR /app" in content
    assert "COPY requirements.txt ." in content
    assert "pip install --no-cache-dir -r requirements.txt" in content
    assert "mkdir -p /app/data" in content
    assert "EXPOSE 8000" in content
    assert "uvicorn app.main:app" in content

def test_render_yaml_syntax_and_structure():
    with open("render.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "services" in data
    assert len(data["services"]) == 1
    svc = data["services"][0]
    assert svc["type"] == "web"
    assert svc["name"] == "clinic-management-system"
    assert svc["env"] == "python"
    assert "pip install -r requirements.txt" in svc["buildCommand"]
    assert "uvicorn app.main:app --host 0.0.0.0 --port $PORT" in svc["startCommand"]
    
    assert svc.get("plan") == "free"
    
    # Check env vars
    env_keys = {item["key"]: item for item in svc.get("envVars", [])}
    assert "DEMO_MODE" in env_keys
    assert env_keys["DEMO_MODE"]["value"] == "true"
    assert "SECRET_KEY" in env_keys
    assert env_keys["SECRET_KEY"]["generateValue"] is True

def test_dockerignore_content():
    with open(".dockerignore", "r", encoding="utf-8") as f:
        content = f.read()
    assert "__pycache__" in content
    assert ".git" in content
    assert "tests" in content
    assert ".venv" in content or "venv" in content