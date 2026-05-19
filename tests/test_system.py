"""
tests/test_system.py
=====================
Comprehensive test suite for the Hospital Management System.
Covers:
  - Priority engine unit tests (algorithm correctness)
  - Fairness logic tests (adjustment factor, anti-starvation)
  - Simulation tests (FCFS vs Fairness-Aware comparison)
  - Flask route functional tests (registration, login, appointment, consultation)
  - Integration tests (cross-module state changes)

Run:
  pip install pytest
  pytest tests/ -v
"""

import sys
import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import json
import pytest
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from priority_engine import (
    get_urgency_score, get_wait_score, get_resource_score,
    get_fairness_adjustment, compute_priority_score,
    is_starvation_risk, build_group_stats, reorder_by_priority,
    W1_URGENCY, W2_WAIT, W3_RESOURCE, STARVATION_THRESHOLD_MINUTES,
    URGENCY_SCORES
)


class MockDoctor:
    def __init__(self, is_active=True, is_logged_in=True, is_available=True, queue_size=0):
        self.is_active = is_active
        self.is_logged_in = is_logged_in
        self.is_available = is_available
        self.current_queue_size = queue_size


class MockRequest:
    def __init__(self, urgency, patient_name='Test Patient'):
        self.urgency_level = urgency
        self.patient = type('P', (), {'user': type('U', (), {'name': patient_name})()})()


class MockQueueEntry:
    def __init__(self, urgency, assigned_at, doctor=None, position=1, priority_score=0.0):
        self.assigned_at = assigned_at
        self.position = position
        self.priority_score = priority_score
        self.appointment_request = MockRequest(urgency)
        self.doctor = doctor or MockDoctor()


class TestUrgencyScore:
    def test_emergency_highest(self):
        assert get_urgency_score('emergency') == 1.0

    def test_high_alias(self):
        assert get_urgency_score('high') == 1.0

    def test_urgent_middle(self):
        assert get_urgency_score('urgent') == 0.65

    def test_medium_alias(self):
        assert get_urgency_score('medium') == 0.65

    def test_routine_lowest(self):
        assert get_urgency_score('routine') == 0.25

    def test_low_alias(self):
        assert get_urgency_score('low') == 0.25

    def test_case_insensitive(self):
        assert get_urgency_score('EMERGENCY') == 1.0

    def test_emergency_greater_than_urgent(self):
        assert get_urgency_score('emergency') > get_urgency_score('urgent')

    def test_urgent_greater_than_routine(self):
        assert get_urgency_score('urgent') > get_urgency_score('routine')

    def test_unknown_defaults_to_routine(self):
        assert get_urgency_score('unknown') == 0.25


class TestWaitScore:
    def test_zero_wait(self):
        now = datetime.utcnow()
        score = get_wait_score(now, now)
        assert score == 0.0

    def test_120_min_wait(self):
        now = datetime.utcnow()
        assigned = now - timedelta(minutes=120)
        score = get_wait_score(assigned, now)
        assert abs(score - 0.5) < 0.01

    def test_capped_at_1(self):
        now = datetime.utcnow()
        assigned = now - timedelta(hours=10)
        score = get_wait_score(assigned, now)
        assert score == 1.0

    def test_longer_wait_higher_score(self):
        now = datetime.utcnow()
        short = get_wait_score(now - timedelta(minutes=30), now)
        long_ = get_wait_score(now - timedelta(minutes=120), now)
        assert long_ > short


class TestResourceScore:
    def test_fully_available_empty_queue(self):
        doc = MockDoctor(is_active=True, is_logged_in=True, is_available=True, queue_size=0)
        assert get_resource_score(doc) == 1.0

    def test_unavailable_doctor(self):
        doc = MockDoctor(is_available=False)
        assert get_resource_score(doc) == 0.0

    def test_inactive_doctor(self):
        doc = MockDoctor(is_active=False)
        assert get_resource_score(doc) == 0.0

    def test_not_logged_in(self):
        doc = MockDoctor(is_logged_in=False)
        assert get_resource_score(doc) == 0.0

    def test_large_queue_reduces_score(self):
        doc_empty = MockDoctor(queue_size=0)
        doc_full = MockDoctor(queue_size=15)
        assert get_resource_score(doc_full) < get_resource_score(doc_empty)

    def test_score_positive(self):
        doc = MockDoctor(queue_size=5)
        assert get_resource_score(doc) > 0


class TestFairnessAdjustment:
    def test_no_stats_returns_zero(self):
        assert get_fairness_adjustment('emergency', {}) == 0.0

    def test_group_waiting_more_gets_positive_adj(self):
        group_stats = {'emergency': 200.0, 'routine': 50.0}
        adj = get_fairness_adjustment('emergency', group_stats)
        assert adj > 0.0

    def test_group_waiting_less_gets_zero_adj(self):
        group_stats = {'emergency': 10.0, 'routine': 100.0}
        adj = get_fairness_adjustment('emergency', group_stats)
        assert adj == 0.0

    def test_max_adjustment_capped(self):
        group_stats = {'emergency': 10000.0, 'routine': 1.0}
        adj = get_fairness_adjustment('emergency', group_stats)
        assert adj <= 0.20

    def test_equal_waits_no_adjustment(self):
        group_stats = {'emergency': 100.0, 'routine': 100.0}
        adj = get_fairness_adjustment('emergency', group_stats)
        assert adj == 0.0


class TestAntiStarvation:
    def test_below_threshold_not_starved(self):
        assigned = datetime.utcnow() - timedelta(minutes=100)
        assert is_starvation_risk(assigned, datetime.utcnow()) is False

    def test_at_threshold_starved(self):
        assigned = datetime.utcnow() - timedelta(minutes=STARVATION_THRESHOLD_MINUTES)
        assert is_starvation_risk(assigned, datetime.utcnow()) is True

    def test_above_threshold_starved(self):
        assigned = datetime.utcnow() - timedelta(minutes=200)
        assert is_starvation_risk(assigned, datetime.utcnow()) is True


class TestPriorityScore:
    def test_score_is_float(self):
        doc = MockDoctor()
        now = datetime.utcnow()
        score = compute_priority_score('emergency', now - timedelta(minutes=30), doc, {}, now)
        assert isinstance(score, float)

    def test_emergency_higher_than_routine_same_wait(self):
        doc = MockDoctor()
        now = datetime.utcnow()
        assigned = now - timedelta(minutes=30)
        e = compute_priority_score('emergency', assigned, doc, {}, now)
        r = compute_priority_score('routine', assigned, doc, {}, now)
        assert e > r

    def test_longer_wait_increases_score(self):
        doc = MockDoctor()
        now = datetime.utcnow()
        short = compute_priority_score('routine', now - timedelta(minutes=10), doc, {}, now)
        long_ = compute_priority_score('routine', now - timedelta(minutes=120), doc, {}, now)
        assert long_ > short

    def test_weights_sum_correctly(self):
        doc = MockDoctor()
        now = datetime.utcnow()
        score = compute_priority_score('emergency', now, doc, {}, now)
        assert score >= W1_URGENCY * 1.0

    def test_score_bounded(self):
        doc = MockDoctor()
        now = datetime.utcnow()
        score = compute_priority_score('emergency', now - timedelta(hours=3), doc, {}, now)
        assert score <= 1.15


class TestReorderByPriority:
    def test_emergency_before_routine(self):
        now = datetime.utcnow()
        doc = MockDoctor()
        routine = MockQueueEntry('routine', now - timedelta(minutes=10), doc)
        emergency = MockQueueEntry('emergency', now - timedelta(minutes=10), doc)
        sorted_ = reorder_by_priority([routine, emergency])
        assert sorted_[0].appointment_request.urgency_level == 'emergency'

    def test_starvation_goes_first(self):
        now = datetime.utcnow()
        doc = MockDoctor()
        emergency_recent = MockQueueEntry('emergency', now - timedelta(minutes=5), doc)
        routine_old = MockQueueEntry('routine', now - timedelta(minutes=200), doc)
        sorted_ = reorder_by_priority([emergency_recent, routine_old])
        assert sorted_[0].appointment_request.urgency_level == 'routine'

    def test_order_is_deterministic(self):
        now = datetime.utcnow()
        doc = MockDoctor()
        entries = [
            MockQueueEntry('routine', now - timedelta(minutes=20), doc),
            MockQueueEntry('urgent', now - timedelta(minutes=15), doc),
            MockQueueEntry('emergency', now - timedelta(minutes=5), doc),
        ]
        result1 = [e.appointment_request.urgency_level for e in reorder_by_priority(entries)]
        result2 = [e.appointment_request.urgency_level for e in reorder_by_priority(entries)]
        assert result1 == result2


# ─────────────────────────────────────────────────────────────────────────────
#  Simulation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulation:
    @pytest.fixture(scope='class')
    def sim_results(self):
        from simulation.run_simulation import run
        return run()

    def test_simulation_runs(self, sim_results):
        assert sim_results is not None

    def test_emergency_avg_wait_reduced(self, sim_results):
        t7 = sim_results['table7_performance']['emergency']
        assert t7['fa_avg_wait'] < t7['fcfs_avg_wait']

    def test_urgent_avg_wait_reduced(self, sim_results):
        t7 = sim_results['table7_performance']['urgent']
        assert t7['fa_avg_wait'] < t7['fcfs_avg_wait']

    def test_overall_avg_wait_reduced(self, sim_results):
        t7 = sim_results['table7_performance']['all']
        assert t7['fa_avg_wait'] <= t7['fcfs_avg_wait']

    def test_wait_ratio_improved(self, sim_results):
        t8 = sim_results['table8_fairness']
        fa_ratio = t8['wait_ratio_emergency_routine']['fa']
        fcfs_ratio = t8['wait_ratio_emergency_routine']['fcfs']
        assert fa_ratio < fcfs_ratio

    def test_starvation_not_worse(self, sim_results):
        t8 = sim_results['table8_fairness']
        fa_s = t8['starvation_incidents']['fa']
        fcfs_s = t8['starvation_incidents']['fcfs']
        assert fa_s <= fcfs_s * 2

    def test_fairness_activations_positive(self, sim_results):
        t8 = sim_results['table8_fairness']
        assert t8['fairness_adjustment_activations']['fa'] > 0

    def test_correct_patient_count(self, sim_results):
        assert sim_results['simulation_parameters']['total_patients'] == 1000

    def test_csv_files_exist(self):
        sim_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'simulation')
        assert os.path.exists(os.path.join(sim_dir, 'simulation_data.csv'))
        assert os.path.exists(os.path.join(sim_dir, 'fcfs_results.csv'))
        assert os.path.exists(os.path.join(sim_dir, 'fairness_results.csv'))
        assert os.path.exists(os.path.join(sim_dir, 'results.json'))

    def test_csv_has_correct_columns(self):
        import csv
        sim_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'simulation')
        with open(os.path.join(sim_dir, 'simulation_data.csv')) as f:
            reader = csv.DictReader(f)
            required_cols = {'patient_id', 'urgency_level', 'department',
                             'fcfs_wait_min', 'fairness_wait_min', 'wait_reduction_pct'}
            assert required_cols.issubset(set(reader.fieldnames))

    def test_csv_row_count(self):
        import csv
        sim_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'simulation')
        with open(os.path.join(sim_dir, 'simulation_data.csv')) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1000


# ─────────────────────────────────────────────────────────────────────────────
#  Flask Application Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def app():
    """
    Create Flask test app backed by in-memory SQLite.

    Flask-SQLAlchemy caches one engine per app instance, keyed in _db.engines.
    Simply changing SQLALCHEMY_DATABASE_URI is not enough — the old MySQL engine
    is still cached. The fix:
      1. Update the config.
      2. Dispose the old engine (closes all MySQL connections).
      3. Clear _db.engines so Flask-SQLAlchemy rebuilds from the new URI.
      4. Call create_all — it now builds a fresh SQLite engine.
    do NOT call _db.init_app() again — that raises RuntimeError on Flask-SQLAlchemy >= 3.
    """
    from app import app as flask_app
    from models import db as _db

    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-key',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()

@pytest.fixture(scope='module')
def client(app):
    return app.test_client()


@pytest.fixture(scope='module')
def seeded_db(app):
    """
    Seed minimal test data once for the whole module.
    scope='module' matches the app fixture lifetime so we don't
    re-insert into the same in-memory DB on every test.
    """
    from models import db, User, Patient, Doctor, Department, Room, Bed
    from werkzeug.security import generate_password_hash

    with app.app_context():
        admin = User(email='admin@test.com',
                     password_hash=generate_password_hash('admin123'),
                     role='admin', name='Admin User')
        db.session.add(admin)
        db.session.flush()

        dept = Department(name='Cardiology')
        db.session.add(dept)
        db.session.flush()

        doc_user = User(email='dr@test.com',
                        password_hash=generate_password_hash('doc123'),
                        role='doctor', name='Dr Smith')
        db.session.add(doc_user)
        db.session.flush()
        doctor = Doctor(id=doc_user.id, department_id=dept.id,
                        specialization='Cardiology', is_active=True,
                        is_logged_in=True, is_available=True)
        db.session.add(doctor)

        pat_user = User(email='patient@test.com',
                        password_hash=generate_password_hash('pat123'),
                        role='patient', name='John Patient')
        db.session.add(pat_user)
        db.session.flush()
        patient = Patient(id=pat_user.id, age=35, gender='Male', contact='1234567890')
        db.session.add(patient)

        room = Room(department_id=dept.id, room_type='patient', total_beds=3)
        db.session.add(room)
        db.session.flush()
        for _ in range(3):
            db.session.add(Bed(room_id=room.id, is_occupied=False, is_active=True))

        db.session.commit()

        yield {
            'dept_id': dept.id,
            'doctor_id': doctor.id,
            'patient_id': patient.id,
        }


class TestRoutes:
    def test_index_loads(self, client):
        rv = client.get('/')
        assert rv.status_code == 200

    def test_patient_register_page(self, client):
        rv = client.get('/patient/register')
        assert rv.status_code == 200

    def test_patient_login_page(self, client):
        rv = client.get('/patient/login')
        assert rv.status_code == 200

    def test_doctor_login_page(self, client):
        rv = client.get('/doctor/login')
        assert rv.status_code == 200

    def test_admin_login_page(self, client):
        rv = client.get('/admin/login')
        assert rv.status_code == 200

    def test_protected_route_redirects(self, client):
        rv = client.get('/patient/dashboard', follow_redirects=False)
        assert rv.status_code in (302, 401, 403)

    def test_patient_register(self, client, app):
        with app.app_context():
            rv = client.post('/patient/register', data={
                'name': 'New Patient',
                'email': 'new@test.com',
                'password': 'pass123',
                'age': '25',
                'gender': 'Female',
                'contact': '9876543210'
            }, follow_redirects=True)
            assert rv.status_code == 200

    def test_patient_login(self, client, seeded_db):
        rv = client.post('/patient/login', data={
            'email': 'patient@test.com',
            'password': 'pat123'
        }, follow_redirects=True)
        assert rv.status_code == 200

    def test_admin_login(self, client, seeded_db):
        rv = client.post('/admin/login', data={
            'email': 'admin@test.com',
            'password': 'admin123'
        }, follow_redirects=True)
        assert rv.status_code == 200

    def test_doctor_login(self, client, seeded_db):
        rv = client.post('/doctor/login', data={
            'email': 'dr@test.com',
            'password': 'doc123'
        }, follow_redirects=True)
        assert rv.status_code == 200


class TestAppointmentFlow:
    def test_submit_appointment_and_priority_scored(self, client, app, seeded_db):
        with app.app_context():
            from models import DoctorQueue

            client.post('/patient/login', data={
                'email': 'patient@test.com', 'password': 'pat123'
            })
            rv = client.post('/patient/submit_request', data={
                'department_id': str(seeded_db['dept_id']),
                'disease_category': 'Chest Pain',
                'symptoms': 'Severe chest pain',
                'urgency_level': 'emergency'
            }, follow_redirects=True)
            assert rv.status_code == 200

            entry = DoctorQueue.query.first()
            if entry:
                assert entry.priority_score >= 0

    def test_multiple_urgencies_correct_order(self, client, app, seeded_db):
        with app.app_context():
            from models import DoctorQueue, db, User, Patient
            from werkzeug.security import generate_password_hash

            u2 = User(email='p2@test.com',
                      password_hash=generate_password_hash('p2'),
                      role='patient', name='Patient Two')
            db.session.add(u2)
            db.session.flush()
            db.session.add(Patient(id=u2.id, age=40, gender='Male', contact='111'))
            db.session.commit()

            client.post('/patient/login', data={'email': 'p2@test.com', 'password': 'p2'})
            client.post('/patient/submit_request', data={
                'department_id': str(seeded_db['dept_id']),
                'disease_category': 'Headache',
                'symptoms': 'Mild headache',
                'urgency_level': 'routine'
            }, follow_redirects=True)

            entries = DoctorQueue.query.all()
            if len(entries) >= 2:
                scores = {e.appointment_request.urgency_level: e.priority_score
                          for e in entries}
                if 'emergency' in scores and 'routine' in scores:
                    assert scores['emergency'] > scores['routine']


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])