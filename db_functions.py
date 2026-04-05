"""
db_functions.py — Python wrappers for sm.* PostgreSQL stored functions.

Where the DB function exists and works correctly, we call it via
db.session.execute(text(...)).  Where the DB function has minor bugs
(e.g. hashpassword_postgen argument order, missing array_shuffle) we
provide a pure-Python fallback so the app works even before those
functions are fixed in Postgres.
"""

import re
import random
import string
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from models import (db, User, Password, UserRole, WorkGroup, UserWorkGroup,
                    Notification, AuditLog, TicketApproval, ApprovalRoute, ApprovalStep,
                    gen_uuid)
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# TRANSLITERATION  (mirrors sm.translit)
# ---------------------------------------------------------------------------
_RUS = list('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЫЭЮЯЬЪ')
_ENG = ['A','B','V','G','D','E','YO','ZH','Z','I','Y','K','L','M','N','O',
        'P','R','S','T','U','F','KH','C','CH','SH','SHH','Y','E','YU','YA','','']

def translit(text_ru: str) -> str:
    """Python equivalent of sm.translit()."""
    if not text_ru:
        return ''
    result = []
    for ch in text_ru.upper():
        try:
            idx = _RUS.index(ch)
            result.append(_ENG[idx])
        except ValueError:
            pass
    return ''.join(result)


# ---------------------------------------------------------------------------
# LOGIN GENERATION  (mirrors sm.generate_login)
# ---------------------------------------------------------------------------
def generate_login(last_name: str, first_name: str, middle_name: str = None) -> str:
    """
    Try to call sm.generate_login() in Postgres first.
    Falls back to Python implementation if the function is not available.
    """
    try:
        row = db.session.execute(
            text("SELECT sm.generate_login(:ln, :fn, :mn)"),
            {'ln': last_name, 'fn': first_name, 'mn': middle_name}
        ).scalar()
        if row and not row.startswith('ERROR'):
            return row
    except Exception:
        db.session.rollback()

    # Python fallback
    base_ln = translit(last_name)[:8]
    base_fn = translit(first_name)[:1]
    base_mn = translit(middle_name)[:1] if middle_name else ''
    base = f"{base_ln}.{base_fn}{base_mn}"
    login = base
    cnt = 0
    while User.query.filter_by(user_name=login).first():
        cnt += 1
        login = f"{base}{cnt}"
    return login


# ---------------------------------------------------------------------------
# PASSWORD GENERATION  (mirrors sm.generate_password)
# ---------------------------------------------------------------------------
def generate_password() -> str:
    """
    Try sm.generate_password() first; fall back to Python.
    """
    try:
        row = db.session.execute(text("SELECT sm.generate_password()")).scalar()
        if row:
            return row
    except Exception:
        db.session.rollback()

    # Python fallback: guaranteed to have upper, lower, digit, special
    chars = string.ascii_letters + string.digits + '!@#$%&*'
    parts = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice('!@#$%&*'),
    ]
    parts += [random.choice(chars) for _ in range(8)]
    random.shuffle(parts)
    return ''.join(parts)


# ---------------------------------------------------------------------------
# MOBILE FORMATTING  (mirrors logic in sm.create_user)
# ---------------------------------------------------------------------------
def format_mobile(mobile: str):
    if not mobile:
        return None
    digits = re.sub(r'\D', '', mobile)
    if len(digits) >= 10:
        digits = digits[-10:]
        return f"+7 ({digits[0:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
    return None


# ---------------------------------------------------------------------------
# GENDER NORMALISATION  (mirrors logic in sm.create_user)
# ---------------------------------------------------------------------------
def normalize_gender(gender: str):
    if not gender:
        return None
    g = gender.upper().strip()
    if g.startswith('М') or g.startswith('M'):
        return 'M'
    if g.startswith('Ж') or g.startswith('F'):
        return 'F'
    return 'O'


# ---------------------------------------------------------------------------
# TICKET NUMBER GENERATION
# ---------------------------------------------------------------------------
def generate_ticket_number() -> str:
    """Generate a sequential ticket number like SD-20240001."""
    from models import Ticket
    # NOTE: COUNT(*) is non-atomic — under concurrent load two requests may
    # receive the same number. Consider using a DB sequence for uniqueness.
    count = db.session.execute(text("SELECT COUNT(*) FROM sm.tickets")).scalar() or 0
    year = datetime.utcnow().year
    return f"SD-{year}-{(count + 1):04d}"


# ---------------------------------------------------------------------------
# CREATE USER  (mirrors sm.create_user — calls DB func or Python fallback)
# ---------------------------------------------------------------------------
def create_user_db(last_name, first_name, middle_name, email, mobile,
                   work_phone, gender, title, department, company,
                   role='user', work_group_uid=None, manager_uid=None,
                   creator_uid=None) -> tuple:
    """
    Creates a user.  Tries sm.create_user() first; falls back to manual INSERT.

    Returns (user_name, temp_password).
    """
    temp_password = generate_password()

    try:
        # Try the stored procedure
        row = db.session.execute(
            text("SELECT sm.create_user(:ln,:fn,:mn,:email,:mob,:wp,:gen,:title,:dept,:comp)"),
            {
                'ln': last_name, 'fn': first_name, 'mn': middle_name,
                'email': email, 'mob': mobile, 'wp': work_phone,
                'gen': gender, 'title': title, 'dept': department, 'comp': company,
            }
        ).scalar()

        if row and not str(row).startswith('ERROR'):
            # sm.create_user returned the login and already inserted into sm.passwords
            user_name = row
            user = User.query.filter_by(user_name=user_name).first()
            if user:
                # Overwrite the Postgres-generated hash with Werkzeug hash
                _set_password_hash(user.user_uid, temp_password)
                _ensure_role(user.user_uid, role, creator_uid)
                _ensure_work_group(user.user_uid, work_group_uid)
                user.manager_uid = manager_uid
                db.session.commit()
                return user_name, temp_password

    except Exception as e:
        db.session.rollback()
        # Fall through to Python path
        print(f"[db_functions] sm.create_user failed ({e}), using Python fallback")

    # ---- Python fallback ----
    user_name = generate_login(last_name, first_name, middle_name)
    uid = gen_uuid()
    sys_uid = creator_uid or uid   # self-reference for system bootstrap

    user = User(
        user_uid=uid,
        user_name=user_name,
        first_name=first_name,
        last_name=last_name,
        middel_name=middle_name or None,
        email=email,
        mobile=format_mobile(mobile),
        work_phone=work_phone or None,
        gender=normalize_gender(gender),
        title=title or None,
        department=department or None,
        company=company or None,
        manager_uid=manager_uid,
        create_by=sys_uid,
        update_by=sys_uid,
    )
    db.session.add(user)
    db.session.flush()  # get user_uid

    _set_password_hash(user.user_uid, temp_password)
    _ensure_role(user.user_uid, role, creator_uid)
    _ensure_work_group(user.user_uid, work_group_uid)
    db.session.commit()

    return user_name, temp_password


# ---------------------------------------------------------------------------
# RESET PASSWORD  (mirrors sm.reset_password — with Python fallback)
# ---------------------------------------------------------------------------
def reset_password_db(user_name: str):
    """
    Generates a new temp password and stores its Werkzeug hash.
    Tries sm.reset_password() first; falls back to Python.
    Returns the plain-text temporary password.
    """
    user = User.query.filter_by(user_name=user_name).first()
    if not user:
        return None

    temp_password = generate_password()

    try:
        db.session.execute(
            text("SELECT sm.reset_password(:uname)"),
            {'uname': user_name}
        )
        # The PG function stores a bcrypt hash — but we need Werkzeug hash for Flask.
        # Overwrite with Werkzeug hash so check_password_hash() works.
    except Exception:
        db.session.rollback()

    _set_password_hash(user.user_uid, temp_password)

    pwd = Password.query.filter_by(user_uid=user.user_uid).first()
    if pwd:
        pwd.is_first_login = True
        pwd.must_change_password = True
        pwd.failed_attempts = 0

    db.session.commit()
    return temp_password


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------
def _set_password_hash(user_uid: str, plain_password: str):
    pwd = Password.query.filter_by(user_uid=user_uid).first()
    hashed = generate_password_hash(plain_password)
    if pwd:
        pwd.passwordhash = hashed
    else:
        pwd = Password(user_uid=user_uid, passwordhash=hashed,
                       is_first_login=True, must_change_password=False, failed_attempts=0)
        db.session.add(pwd)


def _ensure_role(user_uid: str, role: str, creator_uid: str = None):
    existing = UserRole.query.filter_by(user_uid=user_uid).first()
    if existing:
        existing.role = role
    else:
        db.session.add(UserRole(user_uid=user_uid, role=role))


def _ensure_work_group(user_uid: str, work_group_uid: str = None):
    if not work_group_uid:
        return
    existing = UserWorkGroup.query.filter_by(
        user_uid=user_uid, work_group_uid=work_group_uid).first()
    if not existing:
        db.session.add(UserWorkGroup(
            user_uid=user_uid,
            work_group_uid=work_group_uid,
            is_primary=True
        ))


def verify_password(user: User, plain_password: str) -> bool:
    """Check plain password against stored Werkzeug hash."""
    if not user.password_record or not user.password_record.passwordhash:
        return False
    return check_password_hash(user.password_record.passwordhash, plain_password)


def add_ticket_history(ticket_uid, field_name, old_value, new_value, changed_by_uid):
    from models import TicketHistory
    h = TicketHistory(
        ticket_uid=ticket_uid,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        changed_by=changed_by_uid,
    )
    db.session.add(h)


def compute_deadline(catalog):
    """Estimate ticket deadline from linked SLA policy."""
    hours = 24
    if getattr(catalog, 'sla', None) and getattr(catalog.sla, 'resolution_time_hours', None):
        hours = catalog.sla.resolution_time_hours
    elif getattr(catalog, 'priority', None) == 'critical':
        hours = 4
    elif getattr(catalog, 'priority', None) == 'high':
        hours = 8
    elif getattr(catalog, 'priority', None) == 'low':
        hours = 72
    return datetime.utcnow() + timedelta(hours=hours)


def notify(user_uid, message, ticket_uid=None):
    db.session.add(Notification(
        user_uid=user_uid,
        message=message,
        ticket_uid=ticket_uid,
    ))


def notify_ticket_update(ticket, message, exclude_uid=None):
    recipients = {ticket.requester_uid, ticket.recipient_uid, ticket.performer_uid}
    recipients = {uid for uid in recipients if uid and uid != exclude_uid}
    for uid in recipients:
        notify(uid, message, ticket_uid=ticket.ticket_uid)


def audit(user_uid, action, entity_type=None, entity_uid=None, details=None, ip=None):
    db.session.add(AuditLog(
        user_uid=user_uid,
        action=action,
        entity_type=entity_type,
        entity_uid=entity_uid,
        details=details,
        ip_address=ip,
    ))


def create_approval_chain(ticket, catalog, requester):
    from models import User
    route = ApprovalRoute.query.filter_by(catalog_uid=catalog.catalog_uid, is_active=True).first()
    if route:
        steps = ApprovalStep.query.filter_by(route_uid=route.route_uid).order_by(ApprovalStep.step_order).all()
        for step in steps:
            approver_uid = step.approver_uid
            if not approver_uid and step.approver_role:
                candidate = User.query.join(UserRole).filter(
                    UserRole.role == step.approver_role,
                    User.is_deactivated == False
                ).first()
                approver_uid = candidate.user_uid if candidate else None
            db.session.add(TicketApproval(
                ticket_uid=ticket.ticket_uid,
                step_order=step.step_order,
                step_name=step.step_name or f'Шаг {step.step_order}',
                approver_uid=approver_uid,
                status='pending',
            ))
        return

    approver_uid = requester.manager_uid
    if not approver_uid:
        manager = User.query.join(UserRole).filter(UserRole.role.in_(['manager', 'admin'])).first()
        approver_uid = manager.user_uid if manager else None
    db.session.add(TicketApproval(
        ticket_uid=ticket.ticket_uid,
        step_order=1,
        step_name='Согласование руководителя',
        approver_uid=approver_uid,
        status='pending',
    ))


def process_approval_decision(ticket, approval, decision, comment, actor_uid):
    valid = {'approved', 'rejected'}
    if decision not in valid:
        raise ValueError('Недопустимое решение согласования')
    old_status = approval.status
    approval.status = decision
    approval.comment = comment or None
    approval.decided_at = datetime.utcnow()
    add_ticket_history(ticket.ticket_uid, 'approval', old_status, decision, actor_uid)

    if decision == 'rejected':
        previous = ticket.status
        ticket.status = 'rejected'
        add_ticket_history(ticket.ticket_uid, 'status', previous, 'rejected', actor_uid)
        notify_ticket_update(ticket, f'Заявка {ticket.ticket_number} отклонена', exclude_uid=actor_uid)
        return

    pending = TicketApproval.query.filter_by(ticket_uid=ticket.ticket_uid, status='pending').order_by(
        TicketApproval.step_order
    ).all()
    if pending:
        nxt = pending[0]
        if nxt.approver_uid:
            notify(nxt.approver_uid,
                   f'Требуется согласование заявки {ticket.ticket_number}',
                   ticket_uid=ticket.ticket_uid)
    else:
        previous = ticket.status
        ticket.status = 'approved'
        add_ticket_history(ticket.ticket_uid, 'status', previous, 'approved', actor_uid)
        notify_ticket_update(ticket, f'Заявка {ticket.ticket_number} согласована', exclude_uid=actor_uid)
