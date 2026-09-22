# Backend

FastAPI 기반 Backend 기본 프로젝트입니다.

## 실행

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

서버 실행 후 다음 주소를 사용할 수 있습니다.

- API: <http://localhost:8000>
- Health Check: <http://localhost:8000/api/v1/health>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

## 테스트

```bash
pytest
ruff check .
```

