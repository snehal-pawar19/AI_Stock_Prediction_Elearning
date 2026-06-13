
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, instance_relative_config=True)
db_path = os.path.join(app.instance_path, 'site.db')
print(f"Absolute Instance Path: {app.instance_path}")
print(f"DB Path exists: {os.path.exists(db_path)}")
