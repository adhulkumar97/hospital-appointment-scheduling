from flask import Flask, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from models import (db, User, Patient, Doctor, Department, AppointmentRequest,
                    DoctorQueue, Room, Bed, Admission, Treatment, SystemLog,
                    FairnessLog)
from priority_engine import (reorder_by_priority, compute_priority_score,
                              build_group_stats, is_starvation_risk,
                              get_fairness_adjustment,
                              W1_URGENCY, W2_WAIT, W3_RESOURCE,
                              STARVATION_THRESHOLD_MINUTES)
import functools

app = Flask(__name__)
app.config['SECRET_KEY'] = 'hospitalmanagementsys'
import os

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:root123@localhost/hospital_db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'index'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(*roles):
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_action(user_id, action):
    log = SystemLog(user_id=user_id, action=action)
    db.session.add(log)
    db.session.commit()

def auto_discharge():
    now = datetime.utcnow()
    expired = Admission.query.filter_by(status='active').filter(Admission.discharge_date <= now).all()
    for adm in expired:
        adm.status = 'discharged'
        bed = Bed.query.get(adm.bed_id)
        if bed:
            bed.is_occupied = False
        db.session.add(adm)
        log_action(None, f"Auto-discharged patient {adm.patient.user.name} (admission #{adm.id})")
    if expired:
        db.session.commit()

def get_available_bed(department_id):
    room_ids = [r.id for r in Room.query.filter_by(department_id=department_id, room_type='patient').all()]
    if not room_ids:
        return None
    return Bed.query.filter(Bed.room_id.in_(room_ids), Bed.is_occupied == False, Bed.is_active == True).first()

def reorder_queue_positions(doctor_id):
    """
    CORE: Priority-aware queue reorder.
    Replaces FCFS with weighted priority scores:
      Score = w1(0.45)*urgency + w2(0.30)*wait + w3(0.15)*resource + fairness_adj
    Anti-starvation: patients waiting >150 min get score=999.
    All fairness adjustments logged to FairnessLog.
    """
    entries = DoctorQueue.query.filter_by(doctor_id=doctor_id).join(AppointmentRequest).filter(
        AppointmentRequest.status == 'assigned'
    ).all()
    if not entries:
        return

    now = datetime.utcnow()
    group_stats = build_group_stats(entries)

    for entry in entries:
        req = entry.appointment_request
        at = entry.assigned_at
        if at.tzinfo:
            at = at.replace(tzinfo=None)
        wait_min = int((now - at).total_seconds() / 60)

        # Anti-starvation override
        if is_starvation_risk(entry.assigned_at, now):
            score = 999.0
            fl = FairnessLog(doctor_id=doctor_id, request_id=req.id,
                             urgency_level=req.urgency_level, wait_minutes=wait_min,
                             adjustment_type='anti_starvation',
                             score_before=entry.priority_score or 0.0, score_after=999.0)
            db.session.add(fl)
            log_action(None, f"Anti-starvation: patient {req.patient.user.name} waited {wait_min}min, forced to queue front")
        else:
            fa = get_fairness_adjustment(req.urgency_level, group_stats)
            score = compute_priority_score(
                urgency_level=req.urgency_level,
                assigned_at=entry.assigned_at,
                doctor=entry.doctor,
                group_stats=group_stats,
                now=now
            )
            if fa > 0:
                fl = FairnessLog(doctor_id=doctor_id, request_id=req.id,
                                 urgency_level=req.urgency_level, wait_minutes=wait_min,
                                 adjustment_type='group_disparity',
                                 score_before=score - fa, score_after=score)
                db.session.add(fl)

        entry.priority_score = score

    db.session.commit()

    # Now sort by score descending and assign positions
    sorted_entries = sorted(entries, key=lambda e: e.priority_score, reverse=True)
    for idx, entry in enumerate(sorted_entries, start=1):
        entry.position = idx
    db.session.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/patient/register', methods=['GET', 'POST'])
def patient_register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        age = request.form['age']
        gender = request.form['gender']
        contact = request.form['contact']
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('patient_register'))
        hashed = generate_password_hash(password)
        user = User(email=email, password_hash=hashed, role='patient', name=name)
        db.session.add(user)
        db.session.flush()
        patient = Patient(id=user.id, age=age, gender=gender, contact=contact)
        db.session.add(patient)
        db.session.commit()
        log_action(user.id, f"Registered as patient: {name} ({email})")
        flash('Registration successful. Please login.', 'success')
        return redirect(url_for('patient_login'))
    return render_template('patient/register.html')

@app.route('/patient/login', methods=['GET', 'POST'])
def patient_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='patient').first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            log_action(user.id, "Patient logged in")
            return redirect(url_for('patient_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('patient/login.html')

@app.route('/patient/dashboard')
@login_required
@role_required('patient')
def patient_dashboard():
    patient = Patient.query.get(current_user.id)
    appointments = AppointmentRequest.query.filter_by(patient_id=patient.id).order_by(AppointmentRequest.timestamp.desc()).all()
    admission = Admission.query.filter_by(patient_id=patient.id, status='active').first()
    return render_template('patient/dashboard.html', appointments=appointments, admission=admission)

@app.route('/patient/submit_request', methods=['GET', 'POST'])
@login_required
@role_required('patient')
def submit_request():
    departments = Department.query.all()
    if request.method == 'POST':
        dept_id = request.form['department_id']
        disease = request.form['disease_category']
        symptoms = request.form['symptoms']
        urgency = request.form['urgency_level']
        doctors = Doctor.query.filter_by(department_id=dept_id, is_available=True,
                                          is_logged_in=True, is_active=True).order_by(Doctor.current_queue_size).all()
        if not doctors:
            flash('No active doctors available in this department. Try later.', 'warning')
            return redirect(url_for('patient_dashboard'))
        chosen_doctor = doctors[0]
        req = AppointmentRequest(patient_id=current_user.id, department_id=dept_id,
                                  assigned_doctor_id=chosen_doctor.id, disease_category=disease,
                                  symptoms=symptoms, urgency_level=urgency, status='assigned')
        db.session.add(req)
        db.session.flush()
        chosen_doctor.current_queue_size += 1
        db.session.flush()
        queue_entry = DoctorQueue(doctor_id=chosen_doctor.id, request_id=req.id,
                                   position=chosen_doctor.current_queue_size, priority_score=0.0)
        db.session.add(queue_entry)
        db.session.commit()
        reorder_queue_positions(chosen_doctor.id)
        log_action(current_user.id, f"Submitted appointment (disease: {disease}, urgency: {urgency}) -> Dr. {chosen_doctor.user.name} [priority scored]")
        flash(f'Appointment assigned to Dr. {chosen_doctor.user.name}', 'success')
        return redirect(url_for('patient_dashboard'))
    return render_template('patient/submit_request.html', departments=departments)

@app.route('/doctor/login', methods=['GET', 'POST'])
def doctor_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='doctor').first()
        if user and check_password_hash(user.password_hash, password):
            doctor = Doctor.query.get(user.id)
            if not doctor.is_active:
                flash('Your account has been deactivated.', 'danger')
                return redirect(url_for('doctor_login'))
            doctor.is_logged_in = True
            doctor.is_available = True   # restore availability on fresh login
            db.session.commit()
            log_action(user.id, "Doctor logged in")
            login_user(user)
            return redirect(url_for('doctor_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('doctor/login.html')

@app.route('/doctor/dashboard')
@login_required
@role_required('doctor')
def doctor_dashboard():
    doctor = Doctor.query.get(current_user.id)
    if not doctor.is_active:
        logout_user()
        flash('Your account is inactive.', 'danger')
        return redirect(url_for('index'))
    reorder_queue_positions(doctor.id)
    queue_entries = DoctorQueue.query.filter_by(doctor_id=doctor.id).join(AppointmentRequest).filter(
        AppointmentRequest.status == 'assigned').order_by(DoctorQueue.position).all()
    now = datetime.utcnow()
    for entry in queue_entries:
        at = entry.assigned_at
        if at.tzinfo:
            at = at.replace(tzinfo=None)
        entry.wait_minutes = int((now - at).total_seconds() / 60)
        entry.starvation_risk = is_starvation_risk(entry.assigned_at, now)
    return render_template('doctor/dashboard.html', doctor=doctor, queue=queue_entries)

@app.route('/doctor/toggle_availability', methods=['POST'])
@login_required
@role_required('doctor')
def toggle_availability():
    doctor = Doctor.query.get(current_user.id)
    if not doctor.is_active:
        flash('Inactive doctor cannot change availability.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    if doctor.is_available:
        # Turning OFF: ensure another active logged-in doctor remains in the dept
        other_available = Doctor.query.filter(
            Doctor.department_id == doctor.department_id,
            Doctor.id != doctor.id,
            Doctor.is_active == True,
            Doctor.is_logged_in == True,
            Doctor.is_available == True
        ).count()
        if other_available < 1:
            flash(
                'Cannot pause availability: you are the only doctor currently '
                'accepting patients in this department.',
                'danger'
            )
            return redirect(url_for('doctor_dashboard'))
    doctor.is_available = not doctor.is_available
    db.session.commit()
    status = 'active (accepting patients)' if doctor.is_available else 'paused (not accepting new patients)'
    log_action(current_user.id, f"Availability toggled to {status}")
    if doctor.is_available:
        flash('You are now accepting new patients.', 'success')
    else:
        flash('Availability paused — new patients will not be assigned to you.', 'info')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/consultation/<int:request_id>', methods=['GET', 'POST'])
@login_required
@role_required('doctor')
def consultation(request_id):
    doctor = Doctor.query.get(current_user.id)
    if not doctor.is_active:
        flash('Inactive doctor cannot perform consultations.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    queue_entry = DoctorQueue.query.filter_by(request_id=request_id, doctor_id=current_user.id).first_or_404()
    appointment = queue_entry.appointment_request
    patient = Patient.query.get(appointment.patient_id)
    if request.method == 'POST':
        outcome = request.form['outcome']
        notes = request.form['notes']
        treatment = Treatment(patient_id=patient.id, doctor_id=current_user.id, type=outcome, notes=notes)
        db.session.add(treatment)
        if outcome == 'medication':
            appointment.status = 'completed'
            db.session.delete(queue_entry)
            doctor.current_queue_size = max(0, doctor.current_queue_size - 1)
            db.session.commit()
            reorder_queue_positions(doctor.id)
            log_action(current_user.id, f"Prescribed medication for {patient.user.name} (appt #{appointment.id})")
            flash('Prescription recorded.', 'success')
            return redirect(url_for('doctor_dashboard'))
        elif outcome == 'admission':
            days = int(request.form['days'])
            active_adm = Admission.query.filter_by(patient_id=patient.id, status='active').first()
            if active_adm:
                active_adm.status = 'discharged'
                bed = Bed.query.get(active_adm.bed_id)
                if bed:
                    bed.is_occupied = False
                db.session.add(active_adm)
                db.session.commit()
            bed = get_available_bed(doctor.department_id)
            if not bed:
                flash('No active beds available for admission.', 'danger')
                return redirect(url_for('consultation', request_id=request_id))
            bed.is_occupied = True
            discharge = datetime.utcnow() + timedelta(days=days)
            admission = Admission(patient_id=patient.id, doctor_id=current_user.id,
                                   bed_id=bed.id, discharge_date=discharge, status='active')
            db.session.add(admission)
            appointment.status = 'completed'
            db.session.delete(queue_entry)
            doctor.current_queue_size = max(0, doctor.current_queue_size - 1)
            db.session.commit()
            reorder_queue_positions(doctor.id)
            log_action(current_user.id, f"Admitted {patient.user.name} to bed #{bed.id} for {days} days")
            flash(f'Patient admitted to bed #{bed.id} until {discharge.date()}.', 'success')
            return redirect(url_for('doctor_dashboard'))
    return render_template('doctor/consultation.html', appointment=appointment, patient=patient)

@app.route('/doctor/request_logout')
@login_required
@role_required('doctor')
def doctor_request_logout():
    """
    Step 1 of graceful logout:
    - Block if this doctor is the only logged-in active doctor in the dept (regardless of is_available).
    - Otherwise: set is_available=False so no new patients are routed here.
    - Show a confirmation page listing remaining queue patients.
    """
    doctor = Doctor.query.get(current_user.id)

    # Guard: count OTHER doctors that are active AND logged in in this dept
    other_logged_in = Doctor.query.filter(
        Doctor.department_id == doctor.department_id,
        Doctor.id != doctor.id,
        Doctor.is_active == True,
        Doctor.is_logged_in == True
    ).count()

    if other_logged_in < 1:
        flash(
            'You cannot log out: you are the only active doctor currently logged in '
            'to this department. Another doctor must log in first.',
            'danger'
        )
        return redirect(url_for('doctor_dashboard'))

    # Mark doctor as not accepting new patients immediately
    if doctor.is_available:
        doctor.is_available = False
        db.session.commit()
        log_action(current_user.id, "Doctor set to not-accepting (pending graceful logout)")

    # Count remaining queue
    pending_entries = DoctorQueue.query.filter_by(doctor_id=doctor.id).join(AppointmentRequest).filter(
        AppointmentRequest.status == 'assigned'
    ).order_by(DoctorQueue.position).all()

    return render_template(
        'doctor/logout_confirm.html',
        doctor=doctor,
        pending_entries=pending_entries,
        pending_count=len(pending_entries)
    )


@app.route('/doctor/logout')
@login_required
@role_required('doctor')
def doctor_logout():
    """
    Step 2 of graceful logout (called from the confirm page OR directly).
    - Re-check department guard.
    - Log out the session.
    - Doctor's existing queue stays intact — they can still consult remaining patients.
      (is_available=False already prevents new assignments.)
    """
    doctor = Doctor.query.get(current_user.id)

    # Re-check guard in case situation changed
    other_logged_in = Doctor.query.filter(
        Doctor.department_id == doctor.department_id,
        Doctor.id != doctor.id,
        Doctor.is_active == True,
        Doctor.is_logged_in == True
    ).count()

    if other_logged_in < 1:
        flash(
            'Cannot log out: you are the only active doctor logged in to this department. '
            'Please wait for another doctor to log in first.',
            'danger'
        )
        # Restore availability since we blocked logout
        doctor.is_available = True
        db.session.commit()
        return redirect(url_for('doctor_dashboard'))

    # Ensure no new patients will be assigned to this doctor
    doctor.is_available = False
    doctor.is_logged_in = False
    db.session.commit()
    log_action(current_user.id, "Doctor logged out gracefully (existing queue preserved)")
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='admin').first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            log_action(user.id, "Admin logged in")
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    auto_discharge()
    doctors = Doctor.query.all()
    departments = Department.query.all()
    rooms = Room.query.all()
    beds = Bed.query.all()
    active_patients = AppointmentRequest.query.filter_by(status='assigned').count()
    total_admissions = Admission.query.filter_by(status='active').count()
    active_doctors = [d for d in doctors if d.is_active]
    inactive_doctors = [d for d in doctors if not d.is_active]
    return render_template('admin/dashboard.html', active_doctors=active_doctors,
                           inactive_doctors=inactive_doctors, departments=departments,
                           rooms=rooms, beds=beds, active_patients=active_patients,
                           total_admissions=total_admissions)

@app.route('/admin/add_doctor', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_doctor():
    departments = Department.query.all()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        department_id = request.form['department_id']
        specialization = request.form['specialization']
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return redirect(url_for('add_doctor'))
        hashed = generate_password_hash(password)
        user = User(email=email, password_hash=hashed, role='doctor', name=name)
        db.session.add(user)
        db.session.flush()
        doctor = Doctor(id=user.id, department_id=department_id, specialization=specialization, is_active=True)
        db.session.add(doctor)
        db.session.commit()
        log_action(current_user.id, f"Added doctor: {name} ({email})")
        flash('Doctor added successfully.', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/add_doctor.html', departments=departments)

@app.route('/admin/reactivate_doctor/<int:doctor_id>', methods=['POST'])
@login_required
@role_required('admin')
def reactivate_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    if not doctor.is_active:
        doctor.is_active = True
        db.session.commit()
        log_action(current_user.id, f"Reactivated doctor: {doctor.user.name}")
        flash(f'Doctor {doctor.user.name} reactivated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/deactivate_doctor/<int:doctor_id>', methods=['POST'])
@login_required
@role_required('admin')
def deactivate_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    other_active_logged = Doctor.query.filter(Doctor.department_id == doctor.department_id,
        Doctor.id != doctor.id, Doctor.is_active == True, Doctor.is_logged_in == True).first()
    if not other_active_logged:
        flash('Cannot deactivate: Only active logged-in doctor in department.', 'danger')
        return redirect(url_for('admin_dashboard'))
    pending_requests = AppointmentRequest.query.filter_by(assigned_doctor_id=doctor.id, status='assigned').all()
    if pending_requests:
        other_doctors = Doctor.query.filter(Doctor.department_id == doctor.department_id,
            Doctor.id != doctor.id, Doctor.is_active == True, Doctor.is_logged_in == True,
            Doctor.is_available == True).order_by(Doctor.current_queue_size).all()
        if not other_doctors:
            flash('Cannot deactivate: No other available doctor to reassign patients.', 'danger')
            return redirect(url_for('admin_dashboard'))
        for req in pending_requests:
            target_doctor = min(other_doctors, key=lambda d: d.current_queue_size)
            req.assigned_doctor_id = target_doctor.id
            old_queue = DoctorQueue.query.filter_by(request_id=req.id).first()
            if old_queue:
                db.session.delete(old_queue)
            new_queue = DoctorQueue(doctor_id=target_doctor.id, request_id=req.id, position=0, priority_score=0.0)
            db.session.add(new_queue)
            doctor.current_queue_size -= 1
            target_doctor.current_queue_size += 1
        db.session.commit()
        reorder_queue_positions(doctor.id)
        for tdoc in other_doctors:
            reorder_queue_positions(tdoc.id)
        flash(f'Reassigned {len(pending_requests)} patient(s).', 'info')
    doctor.is_active = False
    if doctor.is_logged_in:
        doctor.is_logged_in = False
    db.session.commit()
    log_action(current_user.id, f"Deactivated doctor: {doctor.user.name}")
    flash('Doctor deactivated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_department', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_department():
    if request.method == 'POST':
        name = request.form['name']
        if Department.query.filter_by(name=name).first():
            flash('Department already exists.', 'danger')
            return redirect(url_for('add_department'))
        dept = Department(name=name)
        db.session.add(dept)
        db.session.commit()
        log_action(current_user.id, f"Added department: {name}")
        flash('Department added.', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/add_department.html')

@app.route('/admin/departments')
@login_required
@role_required('admin')
def list_departments():
    return render_template('admin/departments.html', departments=Department.query.all())

@app.route('/admin/delete_department/<int:dept_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if Doctor.query.filter_by(department_id=dept_id).count() > 0:
        flash('Cannot delete department with assigned doctors.', 'danger')
    else:
        db.session.delete(dept)
        db.session.commit()
        log_action(current_user.id, f"Deleted department: {dept.name}")
        flash('Department deleted.', 'success')
    return redirect(url_for('list_departments'))

@app.route('/admin/add_room', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_room():
    departments = Department.query.all()
    if request.method == 'POST':
        dept_id = request.form['department_id']
        room_type = request.form['room_type']
        total_beds = int(request.form['total_beds'])
        room = Room(department_id=dept_id, room_type=room_type, total_beds=total_beds)
        db.session.add(room)
        db.session.flush()
        for _ in range(total_beds):
            db.session.add(Bed(room_id=room.id, is_occupied=False, is_active=True))
        db.session.commit()
        log_action(current_user.id, f"Added room with {total_beds} beds")
        flash('Room added.', 'success')
        return redirect(url_for('list_rooms'))
    return render_template('admin/add_room.html', departments=departments)

@app.route('/admin/rooms')
@login_required
@role_required('admin')
def list_rooms():
    return render_template('admin/rooms.html', rooms=Room.query.all())

@app.route('/admin/add_bed/<int:room_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_bed(room_id):
    room = Room.query.get_or_404(room_id)
    if request.method == 'POST':
        number = int(request.form.get('number_of_beds', 1))
        for _ in range(number):
            db.session.add(Bed(room_id=room.id, is_occupied=False, is_active=True))
        room.total_beds += number
        db.session.commit()
        log_action(current_user.id, f"Added {number} beds to room {room.id}")
        flash(f'{number} bed(s) added.', 'success')
        return redirect(url_for('list_rooms'))
    return render_template('admin/add_bed.html', room=room)

@app.route('/admin/deactivate_bed/<int:bed_id>', methods=['POST'])
@login_required
@role_required('admin')
def deactivate_bed(bed_id):
    bed = Bed.query.get_or_404(bed_id)
    if bed.is_occupied:
        flash('Cannot deactivate an occupied bed.', 'danger')
        return redirect(url_for('list_rooms'))
    bed.is_active = False
    db.session.commit()
    log_action(current_user.id, f"Deactivated bed {bed.id}")
    flash('Bed deactivated.', 'success')
    return redirect(url_for('list_rooms'))

@app.route('/admin/reactivate_bed/<int:bed_id>', methods=['POST'])
@login_required
@role_required('admin')
def reactivate_bed(bed_id):
    bed = Bed.query.get_or_404(bed_id)
    bed.is_active = True
    db.session.commit()
    log_action(current_user.id, f"Reactivated bed {bed.id}")
    flash('Bed reactivated.', 'success')
    return redirect(url_for('list_rooms'))

@app.route('/admin/patients')
@login_required
@role_required('admin')
def list_patients():
    return render_template('admin/patients.html', patients=Patient.query.all())

@app.route('/admin/patient/<int:patient_id>')
@login_required
@role_required('admin')
def patient_details(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    appointments = AppointmentRequest.query.filter_by(patient_id=patient.id).order_by(AppointmentRequest.timestamp.desc()).all()
    admissions = Admission.query.filter_by(patient_id=patient.id).order_by(Admission.admission_date.desc()).all()
    treatments = Treatment.query.filter_by(patient_id=patient.id).order_by(Treatment.date.desc()).all()
    return render_template('admin/patient_details.html', patient=patient, appointments=appointments,
                           admissions=admissions, treatments=treatments)

@app.route('/admin/appointments')
@login_required
@role_required('admin')
def list_appointments():
    return render_template('admin/appointments.html',
                           appointments=AppointmentRequest.query.order_by(AppointmentRequest.timestamp.desc()).all())

@app.route('/admin/reassign_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def reassign_appointment(appointment_id):
    appointment = AppointmentRequest.query.get_or_404(appointment_id)
    if appointment.status != 'assigned':
        flash('Only assigned appointments can be reassigned.', 'danger')
        return redirect(url_for('list_appointments'))
    if request.method == 'POST':
        new_doctor_id = request.form['doctor_id']
        new_doctor = Doctor.query.get_or_404(new_doctor_id)
        old_doctor_id = appointment.assigned_doctor_id
        appointment.assigned_doctor_id = new_doctor.id
        old_queue = DoctorQueue.query.filter_by(request_id=appointment.id).first()
        if old_queue:
            db.session.delete(old_queue)
            if old_doctor_id:
                old_doctor = Doctor.query.get(old_doctor_id)
                if old_doctor:
                    old_doctor.current_queue_size = max(0, old_doctor.current_queue_size - 1)
                    db.session.commit()
                    reorder_queue_positions(old_doctor.id)
        new_queue = DoctorQueue(doctor_id=new_doctor.id, request_id=appointment.id, position=0, priority_score=0.0)
        db.session.add(new_queue)
        new_doctor.current_queue_size += 1
        db.session.commit()
        reorder_queue_positions(new_doctor.id)
        log_action(current_user.id, f"Reassigned appointment #{appointment.id} to Dr. {new_doctor.user.name}")
        flash(f'Appointment reassigned to Dr. {new_doctor.user.name}.', 'success')
        return redirect(url_for('list_appointments'))
    doctors = Doctor.query.filter_by(department_id=appointment.department_id, is_active=True).all()
    return render_template('admin/reassign_appointment.html', appointment=appointment, doctors=doctors)

@app.route('/admin/treatments')
@login_required
@role_required('admin')
def list_treatments():
    return render_template('admin/treatments.html', treatments=Treatment.query.order_by(Treatment.date.desc()).all())

@app.route('/admin/admissions')
@login_required
@role_required('admin')
def list_admissions():
    return render_template('admin/admissions.html', admissions=Admission.query.order_by(Admission.admission_date.desc()).all())

@app.route('/admin/discharge_admission/<int:admission_id>', methods=['POST'])
@login_required
@role_required('admin')
def discharge_admission(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    if admission.status != 'active':
        flash('Already discharged.', 'warning')
        return redirect(url_for('list_admissions'))
    bed = Bed.query.get(admission.bed_id)
    if bed:
        bed.is_occupied = False
    admission.status = 'discharged'
    db.session.commit()
    log_action(current_user.id, f"Early discharge of {admission.patient.user.name} from bed #{admission.bed_id}")
    flash(f'Patient discharged from bed #{admission.bed_id}.', 'success')
    return redirect(url_for('list_admissions'))

@app.route('/admin/logs')
@login_required
@role_required('admin')
def view_logs():
    logs = db.session.query(SystemLog, User).outerjoin(User, SystemLog.user_id == User.id).order_by(SystemLog.timestamp.desc()).all()
    return render_template('admin/logs.html', logs=logs)

@app.route('/admin/fairness')
@login_required
@role_required('admin')
def fairness_dashboard():
    """Fairness audit dashboard showing priority scores, group wait times, starvation, adjustments."""
    now = datetime.utcnow()
    all_entries = DoctorQueue.query.join(AppointmentRequest).filter(AppointmentRequest.status == 'assigned').all()
    group_stats = build_group_stats(all_entries)
    entries_data = []
    starvation_count = 0
    fairness_activation_count = 0
    for entry in all_entries:
        req = entry.appointment_request
        at = entry.assigned_at
        if at.tzinfo:
            at = at.replace(tzinfo=None)
        wait_min = int((now - at).total_seconds() / 60)
        starved = is_starvation_risk(entry.assigned_at, now)
        if starved:
            starvation_count += 1
        fa = get_fairness_adjustment(req.urgency_level, group_stats)
        if fa > 0:
            fairness_activation_count += 1
        entries_data.append({
            'patient': req.patient.user.name,
            'urgency': req.urgency_level,
            'doctor': entry.doctor.user.name,
            'wait_min': wait_min,
            'priority_score': round(entry.priority_score or 0.0, 4),
            'position': entry.position,
            'starvation_risk': starved,
            'fairness_adj': round(fa, 4),
        })
    entries_data.sort(key=lambda x: x['priority_score'], reverse=True)
    total_fairness_logs = FairnessLog.query.count()
    total_starvation_logs = FairnessLog.query.filter_by(adjustment_type='anti_starvation').count()
    return render_template('admin/fairness.html',
                           entries=entries_data, group_stats=group_stats,
                           starvation_count=starvation_count,
                           fairness_activations=fairness_activation_count,
                           w1=W1_URGENCY, w2=W2_WAIT, w3=W3_RESOURCE,
                           threshold=STARVATION_THRESHOLD_MINUTES,
                           total_fairness_logs=total_fairness_logs,
                           total_starvation_logs=total_starvation_logs)

@app.route('/admin/simulation')
@login_required
@role_required('admin')
def simulation_results():
    """View pre-computed simulation results comparing FCFS vs Fairness-Aware."""
    import json, os
    results_path = os.path.join(os.path.dirname(__file__), 'simulation', 'results.json')
    results = None
    if os.path.exists(results_path):
        with open(results_path) as f:
            results = json.load(f)
    return render_template('admin/simulation.html', results=results)

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        log_action(current_user.id, "User logged out")
    logout_user()
    return redirect(url_for('index'))

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

if __name__ == '__main__':
    app.run(debug=True)
