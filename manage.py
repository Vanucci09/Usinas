from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from app import app, db

migrate = Migrate(app, db)

if __name__ == '__main__':
    app.run()
