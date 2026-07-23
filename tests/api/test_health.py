from importlib import import_module

from fastapi.testclient import TestClient


def test_health_check_returns_service_metadata():
    main = import_module("inspire_flow_backend.main")

    with TestClient(main.app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Inspire Flow Backend",
        "environment": "development",
    }
