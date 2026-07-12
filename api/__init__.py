"""StarShield Lite HTTP API (FastAPI).

Run:
  python main.py api
  uvicorn api.main:app --reload
"""

__all__ = ["create_app"]


def create_app():
    from api.main import app

    return app
