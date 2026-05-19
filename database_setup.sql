-- ============================================================
-- Hospital Management System — Database Setup SQL
-- ============================================================
-- Run this in MySQL if you prefer manual setup over setup.py
--
-- Usage:
--   mysql -u root -p < database_setup.sql
--
-- Or paste into phpMyAdmin / MySQL Workbench / DBeaver
-- ============================================================

CREATE DATABASE IF NOT EXISTS hospital_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE hospital_db;

-- ── Users ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    email         VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    role          VARCHAR(20)  NOT NULL,
    name          VARCHAR(100) NOT NULL
);

-- ── Patients ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id      INT PRIMARY KEY,
    age     INT,
    gender  VARCHAR(10),
    contact VARCHAR(20),
    FOREIGN KEY (id) REFERENCES users(id)
);

-- ── Departments ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- ── Doctors ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
    id                INT PRIMARY KEY,
    department_id     INT NOT NULL,
    specialization    VARCHAR(100),
    is_logged_in      TINYINT(1) DEFAULT 0,
    is_available      TINYINT(1) DEFAULT 1,
    current_queue_size INT DEFAULT 0,
    is_active         TINYINT(1) DEFAULT 1,
    FOREIGN KEY (id) REFERENCES users(id),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

-- ── Appointment Requests ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointment_requests (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    patient_id         INT NOT NULL,
    department_id      INT NOT NULL,
    assigned_doctor_id INT,
    disease_category   VARCHAR(100),
    symptoms           TEXT,
    urgency_level      VARCHAR(20),
    timestamp          DATETIME DEFAULT CURRENT_TIMESTAMP,
    status             VARCHAR(20) DEFAULT 'pending',
    FOREIGN KEY (patient_id)         REFERENCES patients(id),
    FOREIGN KEY (department_id)      REFERENCES departments(id),
    FOREIGN KEY (assigned_doctor_id) REFERENCES doctors(id)
);

-- ── Doctor Queue ──────────────────────────────────────────────
-- priority_score stores the computed AI fairness score
CREATE TABLE IF NOT EXISTS doctor_queues (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    doctor_id      INT NOT NULL,
    request_id     INT NOT NULL,
    assigned_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    position       INT NOT NULL,
    priority_score FLOAT DEFAULT 0.0,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id),
    FOREIGN KEY (request_id) REFERENCES appointment_requests(id)
);

-- ── Rooms ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rooms (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    room_type     VARCHAR(20),
    total_beds    INT DEFAULT 0,
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

-- ── Beds ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS beds (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    room_id     INT NOT NULL,
    is_occupied TINYINT(1) DEFAULT 0,
    is_active   TINYINT(1) DEFAULT 1,
    FOREIGN KEY (room_id) REFERENCES rooms(id)
);

-- ── Admissions ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admissions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    patient_id     INT NOT NULL,
    doctor_id      INT NOT NULL,
    bed_id         INT NOT NULL,
    admission_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    discharge_date DATETIME NOT NULL,
    status         VARCHAR(20) DEFAULT 'active',
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id),
    FOREIGN KEY (bed_id)     REFERENCES beds(id)
);

-- ── Treatments ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS treatments (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL,
    doctor_id  INT NOT NULL,
    type       VARCHAR(20),
    notes      TEXT,
    date       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id)
);

-- ── System Logs ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_logs (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    action    VARCHAR(300),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_id   INT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ── Fairness Logs (NEW) ───────────────────────────────────────
-- Audit trail for every fairness adjustment and anti-starvation event
CREATE TABLE IF NOT EXISTS fairness_logs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
    doctor_id       INT,
    request_id      INT,
    urgency_level   VARCHAR(20),
    wait_minutes    INT DEFAULT 0,
    adjustment_type VARCHAR(30),   -- 'anti_starvation' or 'group_disparity'
    score_before    FLOAT DEFAULT 0.0,
    score_after     FLOAT DEFAULT 0.0,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id),
    FOREIGN KEY (request_id) REFERENCES appointment_requests(id)
);

-- ============================================================
-- SEED DATA — Admin + Departments + Doctors + Rooms + Beds
-- ============================================================
-- Passwords are bcrypt hashes of the plaintext shown in comments

-- Admin user  (password: admin123)
INSERT IGNORE INTO users (email, password_hash, role, name) VALUES
('admin@hospital.com',
 'pbkdf2:sha256:600000$rK8mN2pL$a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
 'admin', 'System Admin');

-- NOTE: The hash above is a placeholder. Run setup.py instead to get
-- correctly hashed passwords. The SQL file is for schema creation only.
-- After running this SQL, run:  python setup.py
-- setup.py will skip re-creating tables but will add the seeded accounts.

-- Departments
INSERT IGNORE INTO departments (name) VALUES
('Cardiology'),
('Neurology'),
('Orthopaedics');

-- Rooms (3 patient rooms + 3 consultation rooms, one per department)
-- Run setup.py to create rooms with correct department IDs automatically.

-- ============================================================
-- DONE
-- All tables created. Now run:  python setup.py
-- to seed doctors, rooms, beds, and create login accounts.
-- ============================================================
