from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    patient = db.relationship('Patient', backref='user', uselist=False)
    doctor = db.relationship('Doctor', backref='user', uselist=False)

class Patient(db.Model):
    __tablename__ = 'patients'
    id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    contact = db.Column(db.String(20))

class Doctor(db.Model):
    __tablename__ = 'doctors'
    id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    specialization = db.Column(db.String(100))
    is_logged_in = db.Column(db.Boolean, default=False)
    is_available = db.Column(db.Boolean, default=True)
    current_queue_size = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    department = db.relationship('Department')

class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class AppointmentRequest(db.Model):
    __tablename__ = 'appointment_requests'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    assigned_doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=True)
    disease_category = db.Column(db.String(100))
    symptoms = db.Column(db.Text)
    urgency_level = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')
    patient = db.relationship('Patient')
    department = db.relationship('Department')
    assigned_doctor = db.relationship('Doctor')
    doctor_queues = db.relationship('DoctorQueue', back_populates='appointment_request')

class DoctorQueue(db.Model):
    __tablename__ = 'doctor_queues'
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey('appointment_requests.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    position = db.Column(db.Integer, nullable=False)
    # NEW: stores the computed priority score for this queue entry
    priority_score = db.Column(db.Float, default=0.0)
    doctor = db.relationship('Doctor')
    appointment_request = db.relationship('AppointmentRequest', back_populates='doctor_queues')

class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    room_type = db.Column(db.String(20))
    total_beds = db.Column(db.Integer, default=0)
    department = db.relationship('Department')
    beds = db.relationship('Bed', backref='room', lazy=True)

class Bed(db.Model):
    __tablename__ = 'beds'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

class Admission(db.Model):
    __tablename__ = 'admissions'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=False)
    admission_date = db.Column(db.DateTime, default=datetime.utcnow)
    discharge_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')
    patient = db.relationship('Patient')
    doctor = db.relationship('Doctor')
    bed = db.relationship('Bed')

class Treatment(db.Model):
    __tablename__ = 'treatments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    type = db.Column(db.String(20))
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    patient = db.relationship('Patient')
    doctor = db.relationship('Doctor')

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

# NEW: FairnessLog — audit trail of every fairness adjustment and anti-starvation event
class FairnessLog(db.Model):
    __tablename__ = 'fairness_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=True)
    request_id = db.Column(db.Integer, db.ForeignKey('appointment_requests.id'), nullable=True)
    urgency_level = db.Column(db.String(20))
    wait_minutes = db.Column(db.Integer, default=0)
    adjustment_type = db.Column(db.String(30))   # 'anti_starvation' | 'group_disparity'
    score_before = db.Column(db.Float, default=0.0)
    score_after = db.Column(db.Float, default=0.0)
