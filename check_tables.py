"""List SQLite tables using SQLAlchemy (same engine as the Flask app)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from app import app
from models.models import db


def main():
    with app.app_context():
        with db.engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
            tables = [r[0] for r in rows]
        print(f"Tables in app database: {tables}")


if __name__ == "__main__":
    main()
