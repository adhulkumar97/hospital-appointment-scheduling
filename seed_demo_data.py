"""
seed_demo_data.py
=================
Injects 20 Doctors + 100 Patients into the hospital database.
Also injects 120 appointment requests with varied urgency levels
so the Fairness-Aware Priority Queue has real data to work on.

Run from the hospital-final folder:
    python seed_demo_data.py

Requires the DB and tables to already exist (run setup.py first).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User, Patient, Doctor, Department, AppointmentRequest, DoctorQueue
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

# ─── Doctor Data ──────────────────────────────────────────────────────────────
DOCTORS = [
    # Cardiology
    {"name": "Dr. Amara Khan",      "email": "dr.amara.khan@hospital.com",      "dept": "Cardiology",    "spec": "Interventional Cardiology"},
    {"name": "Dr. Samuel Wright",   "email": "dr.samuel.wright@hospital.com",   "dept": "Cardiology",    "spec": "Cardiac Electrophysiology"},
    {"name": "Dr. Priya Sharma",    "email": "dr.priya.sharma@hospital.com",    "dept": "Cardiology",    "spec": "Heart Failure & Transplant"},
    {"name": "Dr. James O'Brien",   "email": "dr.james.obrien@hospital.com",    "dept": "Cardiology",    "spec": "Echocardiography"},
    {"name": "Dr. Fatima Al-Hassan","email": "dr.fatima.alhassan@hospital.com", "dept": "Cardiology",    "spec": "Preventive Cardiology"},
    {"name": "Dr. Liam Patel",      "email": "dr.liam.patel@hospital.com",      "dept": "Cardiology",    "spec": "Structural Heart Disease"},
    # Neurology
    {"name": "Dr. Elena Vasquez",   "email": "dr.elena.vasquez@hospital.com",   "dept": "Neurology",     "spec": "Stroke & Cerebrovascular"},
    {"name": "Dr. Kwame Asante",    "email": "dr.kwame.asante@hospital.com",    "dept": "Neurology",     "spec": "Epilepsy & Seizure Disorders"},
    {"name": "Dr. Sofia Rossi",     "email": "dr.sofia.rossi@hospital.com",     "dept": "Neurology",     "spec": "Movement Disorders"},
    {"name": "Dr. Aiden Murphy",    "email": "dr.aiden.murphy@hospital.com",    "dept": "Neurology",     "spec": "Headache & Migraine"},
    {"name": "Dr. Zara Hussain",    "email": "dr.zara.hussain@hospital.com",    "dept": "Neurology",     "spec": "Neuromuscular Disease"},
    {"name": "Dr. Thomas Müller",   "email": "dr.thomas.muller@hospital.com",   "dept": "Neurology",     "spec": "Cognitive Neurology"},
    # Orthopaedics
    {"name": "Dr. Raj Nair",        "email": "dr.raj.nair@hospital.com",        "dept": "Orthopaedics",  "spec": "Joint Replacement"},
    {"name": "Dr. Grace Okonkwo",   "email": "dr.grace.okonkwo@hospital.com",   "dept": "Orthopaedics",  "spec": "Sports Medicine"},
    {"name": "Dr. Ivan Petrov",     "email": "dr.ivan.petrov@hospital.com",     "dept": "Orthopaedics",  "spec": "Spine Surgery"},
    {"name": "Dr. Maria Santos",    "email": "dr.maria.santos@hospital.com",    "dept": "Orthopaedics",  "spec": "Trauma & Fractures"},
    {"name": "Dr. Chen Wei",        "email": "dr.chen.wei@hospital.com",        "dept": "Orthopaedics",  "spec": "Paediatric Orthopaedics"},
    {"name": "Dr. Niamh Brennan",   "email": "dr.niamh.brennan@hospital.com",   "dept": "Orthopaedics",  "spec": "Hand & Wrist Surgery"},
    {"name": "Dr. Alex Thompson",   "email": "dr.alex.thompson@hospital.com",   "dept": "Orthopaedics",  "spec": "Foot & Ankle Surgery"},
    {"name": "Dr. Yasmin Osman",    "email": "dr.yasmin.osman@hospital.com",    "dept": "Orthopaedics",  "spec": "Knee Reconstruction"},
]

DOCTOR_PASSWORD = "Doctor@123"

# ─── Patient Data ──────────────────────────────────────────────────────────────
PATIENT_NAMES = [
    "Oliver Bennett", "Amelia Clarke", "Noah Williams", "Isla Johnson", "Ethan Brown",
    "Sophia Davies", "Lucas Evans", "Emily Thomas", "Mason Roberts", "Grace White",
    "Liam Jackson", "Chloe Harris", "Logan Martin", "Ava Thompson", "James Wilson",
    "Lily Moore", "Benjamin Taylor", "Charlotte Anderson", "Henry Lee", "Mia Lewis",
    "Alexander Walker", "Ella Hall", "Daniel Allen", "Scarlett Young", "Samuel King",
    "Abigail Wright", "Sebastian Scott", "Hannah Baker", "Jack Nelson", "Aria Carter",
    "William Mitchell", "Zoey Perez", "Julian Morgan", "Penelope Roberts", "Dylan Green",
    "Layla Cook", "Oscar Stewart", "Riley Sanchez", "Isaac Morris", "Aubrey Rogers",
    "Caleb Reed", "Nora Kelly", "Ryan Cooper", "Lily Howard", "Nathan Bailey",
    "Ellie Cox", "Eli Richardson", "Madeline Ward", "Grayson Torres", "Leah Peterson",
    "Andrew Gray", "Victoria Ramirez", "Christopher James", "Stella Watson", "Xavier Brooks",
    "Aurora Sanders", "Jaxon Price", "Naomi Bennett", "Luke Murphy", "Brooklyn Rivera",
    "Anthony Coleman", "Samantha Foster", "Wyatt Griffin", "Savannah Hayes", "Hunter Diaz",
    "Addison Myers", "Lincoln Ford", "Bella Hamilton", "Christian Graham", "Natalie Sullivan",
    "Jonathan Wallace", "Hazel Woods", "David West", "Elena Burns", "Joseph Wood",
    "Violet Cole", "Carter Barnes", "Luna Ross", "Isaiah Henderson", "Paisley Powell",
    "Owen Long", "Chloe Nguyen", "Elias Patterson", "Mila Hughes", "Jeremiah Flores",
    "Ariana Russell", "Colton Washington", "Emilia Butler", "Ezekiel Simmons", "Lydia Foster",
    "Micah Perry", "Evelyn Hamilton", "Vincent Bryant", "Autumn Alexander", "Bryson Sanders",
    "Natalia Griffin", "Emmanuel Stone", "Serenity Reyes", "Zachary Tucker", "Layla Jenkins",
    "Landon Webb", "Faith Gray", "Jordan Fisher", "Kinsley Hunter", "Hudson Mills",
]

DISEASES = ["Chest Pain", "Shortness of Breath", "Dizziness", "Palpitations", "Headache",
            "Back Pain", "Joint Pain", "Numbness", "Muscle Weakness", "Fatigue",
            "Neck Pain", "Knee Pain", "Hip Pain", "Tremors", "Memory Loss",
            "Seizure", "Fracture", "Ankle Sprain", "Shoulder Pain", "Migraine"]

SYMPTOMS = [
    "Persistent chest tightness and shortness of breath on exertion",
    "Sharp stabbing pain radiating to left arm, sweating",
    "Recurring severe headache with nausea and visual aura",
    "Sudden weakness in left arm and slurred speech",
    "Lower back pain worsening over 3 weeks, difficulty standing",
    "Swollen and painful right knee, unable to bear weight",
    "Tingling and numbness in hands, worse at night",
    "Frequent episodes of dizziness and near-fainting",
    "Uncontrolled tremors in hands affecting daily tasks",
    "Hip pain radiating to groin, limping gait",
    "Chronic fatigue and muscle weakness for 2 months",
    "Sudden severe headache described as worst of life",
    "Memory lapses and confusion, progressively worsening",
    "Burning sensation along spine with radiating leg pain",
    "Heart palpitations occurring multiple times daily",
    "Right shoulder pain with restricted range of motion",
    "Persistent ankle swelling after sports injury",
    "Jaw pain with clicking sounds on mouth opening",
    "Wrist pain and stiffness worse in mornings",
    "Foot and heel pain worsening when walking",
]

URGENCY_LEVELS = ['emergency', 'urgent', 'medium', 'low', 'routine']
URGENCY_WEIGHTS = [0.12, 0.22, 0.33, 0.20, 0.13]

PATIENT_PASSWORD = "Patient@123"


def seed():
    with app.app_context():
        print("=" * 60)
        print("HOSPITAL DEMO DATA SEEDER")
        print("=" * 60)

        # ── Ensure departments exist ─────────────────────────────────────
        dept_names = ["Cardiology", "Neurology", "Orthopaedics"]
        dept_map = {}
        for dname in dept_names:
            dept = Department.query.filter_by(name=dname).first()
            if not dept:
                dept = Department(name=dname)
                db.session.add(dept)
                db.session.flush()
            dept_map[dname] = dept

        db.session.commit()
        print(f"[OK] Departments ready: {', '.join(dept_names)}")

        # ── Seed Doctors ─────────────────────────────────────────────────
        created_doctors = []
        skipped_doctors = 0
        for d in DOCTORS:
            if User.query.filter_by(email=d["email"]).first():
                skipped_doctors += 1
                continue
            user = User(
                email=d["email"],
                password_hash=generate_password_hash(DOCTOR_PASSWORD),
                role="doctor",
                name=d["name"]
            )
            db.session.add(user)
            db.session.flush()

            dept = dept_map[d["dept"]]
            doctor = Doctor(
                id=user.id,
                department_id=dept.id,
                specialization=d["spec"],
                is_logged_in=False,
                is_available=True,
                current_queue_size=0,
                is_active=True
            )
            db.session.add(doctor)
            created_doctors.append({"name": d["name"], "email": d["email"], "dept": d["dept"], "spec": d["spec"]})

        db.session.commit()
        print(f"[OK] Doctors created: {len(created_doctors)}  |  Already existed: {skipped_doctors}")

        # ── Seed Patients ─────────────────────────────────────────────────
        created_patients = []
        skipped_patients = 0
        for i, pname in enumerate(PATIENT_NAMES[:100]):
            email = pname.lower().replace(" ", ".") + f"{i+1}@patient.com"
            if User.query.filter_by(email=email).first():
                skipped_patients += 1
                continue

            user = User(
                email=email,
                password_hash=generate_password_hash(PATIENT_PASSWORD),
                role="patient",
                name=pname
            )
            db.session.add(user)
            db.session.flush()

            patient = Patient(
                id=user.id,
                age=random.randint(18, 80),
                gender=random.choice(["Male", "Female"]),
                contact=f"07{random.randint(100000000, 999999999)}"
            )
            db.session.add(patient)
            created_patients.append({"name": pname, "email": email})

        db.session.commit()
        print(f"[OK] Patients created: {len(created_patients)}  |  Already existed: {skipped_patients}")

        # ── Inject Appointment Requests for Priority Queue Demo ──────────
        # Get all patients and doctors in DB
        all_patients = Patient.query.all()
        all_doctors = Doctor.query.all()
        all_depts = list(dept_map.values())

        if not all_patients or not all_doctors:
            print("[SKIP] No patients or doctors found — skipping appointment injection.")
            return

        req_count = 0
        for p in all_patients[:80]:  # Create appointments for first 80 patients
            dept = random.choice(all_depts)
            urgency = random.choices(URGENCY_LEVELS, weights=URGENCY_WEIGHTS)[0]
            disease = random.choice(DISEASES)
            symptom = random.choice(SYMPTOMS)

            # Stagger timestamps over last 3 hours for realistic wait times
            offset_mins = random.randint(2, 180)
            ts = datetime.utcnow() - timedelta(minutes=offset_mins)

            # Check if patient already has a pending request
            existing = AppointmentRequest.query.filter_by(
                patient_id=p.id, status='pending'
            ).first()
            if existing:
                continue

            req = AppointmentRequest(
                patient_id=p.id,
                department_id=dept.id,
                disease_category=disease,
                symptoms=symptom,
                urgency_level=urgency,
                timestamp=ts,
                status='pending'
            )
            db.session.add(req)
            db.session.flush()

            # Assign to least-loaded doctor in department
            dept_doctors = [doc for doc in all_doctors if doc.department_id == dept.id]
            if dept_doctors:
                assigned_doc = min(dept_doctors, key=lambda d: d.current_queue_size)

                req.assigned_doctor_id = assigned_doc.id
                req.status = 'assigned'

                # Determine queue position
                current_max = db.session.query(
                    db.func.max(DoctorQueue.position)
                ).filter_by(doctor_id=assigned_doc.id).scalar() or 0

                queue_entry = DoctorQueue(
                    doctor_id=assigned_doc.id,
                    request_id=req.id,
                    assigned_at=ts,
                    position=current_max + 1,
                    priority_score=0.0
                )
                db.session.add(queue_entry)
                assigned_doc.current_queue_size += 1
            req_count += 1

        db.session.commit()
        print(f"[OK] Appointment requests injected: {req_count}")

        # ── Run Priority Engine over all queues ──────────────────────────
        from priority_engine import reorder_by_priority
        from app import reorder_queue_positions

        for doc in all_doctors:
            reorder_queue_positions(doc.id)

        print("[OK] Priority scores computed and queues reordered")
        print("=" * 60)
        print("SEEDING COMPLETE!")
        print("=" * 60)


if __name__ == "__main__":
    seed()
