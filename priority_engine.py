"""
priority_engine.py
==================
Fairness-Aware Priority Queue Algorithm
Based on dissertation specification: Table 2, Sections 3.6 & 4.3

Priority Score = w1*urgency_score + w2*wait_score + w3*resource_score + fairness_adjustment

Weights (from dissertation Table 2):
  w1 = 0.45  Clinical Urgency   (highest clinical impact)
  w2 = 0.30  Waiting Time       (anti-starvation: ensures no patient is indefinitely deferred)
  w3 = 0.15  Resource Availability (allocates to slots where doctors/rooms are available)
  fairness_adjustment = adaptive (dynamic correction for group-level waiting time disparities)
"""

from datetime import datetime, timezone

# ── Dissertation weights (Table 2) ──────────────────────────────────────────
W1_URGENCY   = 0.45
W2_WAIT      = 0.30
W3_RESOURCE  = 0.15

# Urgency level → numeric score
URGENCY_SCORES = {
    'emergency': 1.0,
    'high':      1.0,   # alias
    'urgent':    0.65,
    'medium':    0.65,  # alias
    'routine':   0.25,
    'low':       0.25,  # alias
}

# Anti-starvation threshold: any patient waiting beyond this gets escalation
STARVATION_THRESHOLD_MINUTES = 150

# Fairness adjustment cap so it never completely overrides clinical urgency
MAX_FAIRNESS_ADJUSTMENT = 0.20


def get_urgency_score(urgency_level: str) -> float:
    """Map urgency string to 0-1 numeric score."""
    return URGENCY_SCORES.get(urgency_level.lower(), 0.25)


def get_wait_score(assigned_at: datetime, now: datetime = None) -> float:
    """
    Waiting-time component.
    Normalised to 0-1 over a 4-hour window (240 min).
    Clamped at 1.0 beyond 4 hours so score stays bounded.
    """
    if now is None:
        now = datetime.utcnow()
    # Make both naive for comparison
    if assigned_at.tzinfo is not None:
        assigned_at = assigned_at.replace(tzinfo=None)
    wait_minutes = (now - assigned_at).total_seconds() / 60.0
    return min(wait_minutes / 240.0, 1.0)


def get_resource_score(doctor) -> float:
    """
    Resource availability component.
    Returns 1.0 if doctor is available and has capacity,
    decreasing as queue load increases.
    """
    if not (doctor.is_active and doctor.is_logged_in and doctor.is_available):
        return 0.0
    # Inverse of relative queue load: empty queue → 1.0, very full → approaches 0
    queue_size = max(doctor.current_queue_size, 0)
    return max(1.0 - (queue_size / 20.0), 0.1)


def get_fairness_adjustment(urgency_level: str, group_stats: dict) -> float:
    """
    Fairness Adjustment Factor (dissertation Section 4.3):
    Dynamically corrects imbalances across patient groups to ensure
    equitable access over time.

    group_stats: dict mapping urgency_level → average_wait_minutes for that group
                 across all currently queued patients.

    If a group's average wait significantly exceeds the overall average,
    a small positive correction is applied.
    """
    if not group_stats:
        return 0.0

    overall_avg = sum(group_stats.values()) / len(group_stats)
    group_avg = group_stats.get(urgency_level.lower(), overall_avg)

    if overall_avg == 0:
        return 0.0

    # Disparity ratio: how much worse this group is doing vs average
    disparity = (group_avg - overall_avg) / max(overall_avg, 1.0)
    # Scale to 0-MAX_FAIRNESS_ADJUSTMENT range
    adjustment = min(max(disparity * 0.10, 0.0), MAX_FAIRNESS_ADJUSTMENT)
    return adjustment


def compute_priority_score(urgency_level: str, assigned_at: datetime,
                            doctor, group_stats: dict = None,
                            now: datetime = None) -> float:
    """
    Full composite priority score per dissertation formula.

    Score = w1 * urgency_score
          + w2 * wait_score
          + w3 * resource_score
          + fairness_adjustment

    Higher score = higher priority = lower queue position number.
    """
    if now is None:
        now = datetime.utcnow()
    if group_stats is None:
        group_stats = {}

    u = get_urgency_score(urgency_level)
    w = get_wait_score(assigned_at, now)
    r = get_resource_score(doctor)
    f = get_fairness_adjustment(urgency_level, group_stats)

    score = (W1_URGENCY * u) + (W2_WAIT * w) + (W3_RESOURCE * r) + f
    return round(score, 6)


def is_starvation_risk(assigned_at: datetime, now: datetime = None) -> bool:
    """
    Anti-starvation check.
    Returns True if the patient has waited beyond STARVATION_THRESHOLD_MINUTES.
    Patients flagged here get their urgency overridden to maximum.
    """
    if now is None:
        now = datetime.utcnow()
    if assigned_at.tzinfo is not None:
        assigned_at = assigned_at.replace(tzinfo=None)
    wait_minutes = (now - assigned_at).total_seconds() / 60.0
    return wait_minutes >= STARVATION_THRESHOLD_MINUTES


def build_group_stats(queue_entries) -> dict:
    """
    Compute average wait time (minutes) per urgency group
    from a list of DoctorQueue entries (joined with AppointmentRequest).
    Used to feed the fairness adjustment calculation.
    """
    now = datetime.utcnow()
    group_waits = {}
    group_counts = {}

    for entry in queue_entries:
        req = entry.appointment_request
        urgency = req.urgency_level.lower()
        assigned_at = entry.assigned_at
        if assigned_at.tzinfo is not None:
            assigned_at = assigned_at.replace(tzinfo=None)
        wait = (now - assigned_at).total_seconds() / 60.0

        group_waits[urgency] = group_waits.get(urgency, 0.0) + wait
        group_counts[urgency] = group_counts.get(urgency, 0) + 1

    return {k: group_waits[k] / group_counts[k] for k in group_waits}


def reorder_by_priority(queue_entries):
    """
    Sort queue entries by composite priority score (descending = position 1 first).
    Applies anti-starvation override: any patient past threshold gets score 999.
    Returns list sorted highest-priority first (to be assigned positions 1, 2, 3...).
    """
    now = datetime.utcnow()
    group_stats = build_group_stats(queue_entries)

    scored = []
    for entry in queue_entries:
        req = entry.appointment_request
        urgency = req.urgency_level

        # Anti-starvation override
        if is_starvation_risk(entry.assigned_at, now):
            score = 999.0
        else:
            score = compute_priority_score(
                urgency_level=urgency,
                assigned_at=entry.assigned_at,
                doctor=entry.doctor,
                group_stats=group_stats,
                now=now
            )
        scored.append((score, entry))

    # Sort descending: highest score = first in queue
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored]
