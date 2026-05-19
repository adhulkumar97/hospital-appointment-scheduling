import os
import sys
from werkzeug.security import generate_password_hash
from models import db, User
from app import app

with app.app_context():
    if not User.query.filter_by(role='admin').first():
        admin = User(email='admin@hospital.com', password_hash=generate_password_hash('admin'), role='admin', name='Admin')
        db.session.add(admin)
        db.session.commit()
        print("Admin created: admin@hospital.com / admin")
    else:
        print("Admin already exists.")