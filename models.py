import uuid
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

def gen_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# sm.users
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'sm'}

    user_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_name = db.Column(db.String(12), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    middel_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    mobile = db.Column(db.String(20), nullable=True)
    work_phone = db.Column(db.String(20), nullable=True)
    gender = db.Column(db.String(1), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    department = db.Column(db.String(255), nullable=True)
    company = db.Column(db.String(255), nullable=True)
    manager_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    work_status = db.Column(db.String(20), nullable=True)
    is_vip = db.Column(db.Boolean, default=False)
    is_deactivated = db.Column(db.Boolean, default=False)
    is_temp_deactivated = db.Column(db.Boolean, default=False)
    last_loggon_date = db.Column(db.DateTime, nullable=True)
    password_expires = db.Column(db.DateTime, nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)
    update_date = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_by = db.Column(db.String(36), nullable=False)
    update_by = db.Column(db.String(36), nullable=True)

    password_record = db.relationship('Password', backref='user', uselist=False,
                                      foreign_keys='Password.user_uid')
    work_group_links = db.relationship('UserWorkGroup', backref='user', lazy='dynamic',
                                       foreign_keys='UserWorkGroup.user_uid')
    role_record = db.relationship('UserRole', backref='user', uselist=False,
                                  foreign_keys='UserRole.user_uid')

    tickets_as_requester = db.relationship('Ticket', foreign_keys='Ticket.requester_uid',
                                           backref='requester', lazy='dynamic')
    tickets_as_recipient = db.relationship('Ticket', foreign_keys='Ticket.recipient_uid',
                                           backref='recipient', lazy='dynamic')
    tickets_as_performer = db.relationship('Ticket', foreign_keys='Ticket.performer_uid',
                                           backref='performer', lazy='dynamic')

    def get_id(self):
        return str(self.user_uid)

    def full_name(self):
        parts = [self.last_name, self.first_name]
        if self.middel_name:
            parts.append(self.middel_name)
        return ' '.join(parts)

    @property
    def role(self):
        if self.role_record:
            return self.role_record.role
        return 'user'

    @property
    def is_active(self):
        return not self.is_deactivated and not self.is_temp_deactivated

    def primary_work_group(self):
        link = self.work_group_links.filter_by(is_primary=True).first()
        if link:
            return link.work_group
        link = self.work_group_links.first()
        if link:
            return link.work_group
        return None

    def all_work_groups(self):
        return [l.work_group for l in self.work_group_links.order_by(UserWorkGroup.assigned_date).all()]

      
# ---------------------------------------------------------------------------
# sm.passwords
# ---------------------------------------------------------------------------
class Password(db.Model):
    __tablename__ = 'passwords'
    __table_args__ = {'schema': 'sm'}

    user_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'),
                         primary_key=True, nullable=False)
    passwordhash = db.Column(db.Text, nullable=True)
    # App-level fields
    is_first_login = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False)
    failed_attempts = db.Column(db.Integer, default=0)


# ---------------------------------------------------------------------------
# User roles (app-level, outside original schema but within sm.)
# ---------------------------------------------------------------------------
class UserRole(db.Model):
    __tablename__ = 'user_roles'
    __table_args__ = {'schema': 'sm'}

    user_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), primary_key=True)
    role = db.Column(db.String(32), nullable=False, default='user')


# ---------------------------------------------------------------------------
# sm.work_groups
# ---------------------------------------------------------------------------
class WorkGroup(db.Model):
    __tablename__ = 'work_groups'
    __table_args__ = {'schema': 'sm'}

    work_group_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    group_name = db.Column(db.String(100), nullable=False)
    isactive = db.Column(db.Boolean, default=True)
    group_description = db.Column(db.Text, nullable=True)
    group_owner_uid = db.Column(db.String(36), nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)
    update_date = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_by = db.Column(db.String(36), nullable=False)
    update_by = db.Column(db.String(36), nullable=True)

    member_links = db.relationship('UserWorkGroup', backref='work_group', lazy='dynamic',
                                   foreign_keys='UserWorkGroup.work_group_uid')
    catalog_items = db.relationship('ServiceCatalog', backref='work_group', lazy='dynamic',
                                    foreign_keys='ServiceCatalog.work_group_uid')


# ---------------------------------------------------------------------------
# sm.user_work_groups
# ---------------------------------------------------------------------------
class UserWorkGroup(db.Model):
    __tablename__ = 'user_work_groups'
    __table_args__ = {'schema': 'sm'}

    user_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), primary_key=True)
    work_group_uid = db.Column(db.String(36), db.ForeignKey('sm.work_groups.work_group_uid'),
                               primary_key=True)
    assigned_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_primary = db.Column(db.Boolean, default=False)


# ---------------------------------------------------------------------------
# sm.sla_policies
# ---------------------------------------------------------------------------
class SlaPolicy(db.Model):
    __tablename__ = 'sla_policies'
    __table_args__ = {'schema': 'sm'}

    sla_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    policy_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    response_time_hours = db.Column(db.Integer, nullable=False, default=8)
    resolution_time_hours = db.Column(db.Integer, nullable=False, default=24)
    is_active = db.Column(db.Boolean, default=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)
    create_by = db.Column(db.String(36), nullable=False)


# ---------------------------------------------------------------------------
# sm.service_catalog
# ---------------------------------------------------------------------------
class ServiceCatalog(db.Model):
    __tablename__ = 'service_catalog'
    __table_args__ = {'schema': 'sm'}

    catalog_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    catalog_name = db.Column(db.String(200), nullable=False)
    catalog_path = db.Column(db.Text, nullable=False)
    parent_uid = db.Column(db.String(36), db.ForeignKey('sm.service_catalog.catalog_uid'),
                           nullable=True)
    catalog_type = db.Column(db.String(50), nullable=False, default='category')
    work_group_uid = db.Column(db.String(36), db.ForeignKey('sm.work_groups.work_group_uid'),
                               nullable=True)
    ticket_type = db.Column(db.String(100), default='service_request')
    priority = db.Column(db.String(20), default='medium')
    approval_required = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    sla_uid = db.Column(db.String(36), db.ForeignKey('sm.sla_policies.sla_uid'), nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)
    update_date = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_by = db.Column(db.String(36), nullable=False)
    update_by = db.Column(db.String(36), nullable=True)
    catalog_description = db.Column(db.Text, nullable=True)
    catalog_icon = db.Column(db.String(64), nullable=True, default='briefcase')

    children = db.relationship('ServiceCatalog',
                               backref=db.backref('parent', remote_side='ServiceCatalog.catalog_uid'),
                               lazy='dynamic')
    tickets = db.relationship('Ticket', backref='catalog', lazy='dynamic',
                              foreign_keys='Ticket.catalog_uid')
    sla = db.relationship('SlaPolicy', backref='catalog_items', foreign_keys=[sla_uid])


# ---------------------------------------------------------------------------
# sm.tickets
# ---------------------------------------------------------------------------
class Ticket(db.Model):
    __tablename__ = 'tickets'
    __table_args__ = {'schema': 'sm'}

    ticket_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ticket_number = db.Column(db.String(50), unique=True, nullable=False)
    catalog_uid = db.Column(db.String(36), db.ForeignKey('sm.service_catalog.catalog_uid'),
                            nullable=False)
    summary = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requester_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    recipient_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    performer_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    status = db.Column(db.String(50), default='new', nullable=False)
    priority = db.Column(db.String(20), default='medium')
    deadline_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    updated_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)

    history = db.relationship('TicketHistory', backref='ticket', lazy='dynamic',
                              cascade='all, delete-orphan',
                              foreign_keys='TicketHistory.ticket_uid')
    param_values = db.relationship('TicketParamValue', backref='ticket', lazy='dynamic',
                                   cascade='all, delete-orphan',
                                   foreign_keys='TicketParamValue.ticket_uid')
    attachments = db.relationship('Attachment', backref='ticket', lazy='dynamic',
                                  foreign_keys='Attachment.ticket_uid')

    creator = db.relationship('User', foreign_keys=[created_by])

    approvals = db.relationship('TicketApproval', backref='ticket', lazy='dynamic',
                                cascade='all, delete-orphan',
                                foreign_keys='TicketApproval.ticket_uid')

    def is_overdue(self):
        if not self.deadline_at or self.status in ('resolved', 'closed', 'cancelled'):
            return False
        now = (datetime.now(self.deadline_at.tzinfo)
               if self.deadline_at.tzinfo
               else datetime.utcnow())
        return self.deadline_at < now


# ---------------------------------------------------------------------------
# sm.ticket_history
# ---------------------------------------------------------------------------
class TicketHistory(db.Model):
    __tablename__ = 'ticket_history'
    __table_args__ = {'schema': 'sm'}

    history_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ticket_uid = db.Column(db.String(36), db.ForeignKey('sm.tickets.ticket_uid',
                           ondelete='CASCADE'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    changed_date = db.Column(db.DateTime, default=datetime.utcnow)

    changer = db.relationship('User', foreign_keys=[changed_by])


# ---------------------------------------------------------------------------
# sm.ticket_param_values  (comments, approval decisions, internal notes)
# ---------------------------------------------------------------------------
class TicketParamValue(db.Model):
    __tablename__ = 'ticket_param_values'
    __table_args__ = {'schema': 'sm'}

    param_value_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ticket_uid = db.Column(db.String(36), db.ForeignKey('sm.tickets.ticket_uid',
                           ondelete='CASCADE'), nullable=False)
    param_name = db.Column(db.String(100), nullable=False)
    param_value = db.Column(db.Text, nullable=True)
    param_type = db.Column(db.String(50), nullable=True)
    author_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)

    author_rel = db.relationship('User', foreign_keys=[author_uid])


# ---------------------------------------------------------------------------
# sm.attachments
# ---------------------------------------------------------------------------
class Attachment(db.Model):
    __tablename__ = 'attachments'
    __table_args__ = {'schema': 'sm'}

    attachment_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ticket_uid = db.Column(db.String(36), db.ForeignKey('sm.tickets.ticket_uid'), nullable=True)
    attachment_name = db.Column(db.Text, nullable=True)
    attachment_path = db.Column(db.Text, nullable=True)
    mime_type = db.Column(db.Text, nullable=True)
    file_size = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])


class ApprovalRoute(db.Model):
    __tablename__ = 'approval_routes'
    __table_args__ = {'schema': 'sm'}

    route_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    catalog_uid = db.Column(db.String(36), db.ForeignKey('sm.service_catalog.catalog_uid'), nullable=False)
    route_name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)
    create_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)

    steps = db.relationship('ApprovalStep', backref='route', lazy='dynamic',
                            cascade='all, delete-orphan',
                            foreign_keys='ApprovalStep.route_uid')


class ApprovalStep(db.Model):
    __tablename__ = 'approval_steps'
    __table_args__ = {'schema': 'sm'}

    step_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    route_uid = db.Column(db.String(36), db.ForeignKey('sm.approval_routes.route_uid'), nullable=False)
    step_order = db.Column(db.Integer, nullable=False, default=1)
    step_name = db.Column(db.String(200), nullable=True)
    approver_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    approver_role = db.Column(db.String(32), nullable=True)

    approver = db.relationship('User', foreign_keys=[approver_uid])


class TicketApproval(db.Model):
    __tablename__ = 'ticket_approvals'
    __table_args__ = {'schema': 'sm'}

    approval_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ticket_uid = db.Column(db.String(36), db.ForeignKey('sm.tickets.ticket_uid', ondelete='CASCADE'), nullable=False)
    step_order = db.Column(db.Integer, nullable=False, default=1)
    step_name = db.Column(db.String(200), nullable=True)
    approver_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    comment = db.Column(db.Text, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)

    approver = db.relationship('User', foreign_keys=[approver_uid])


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = {'schema': 'sm'}

    notification_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    ticket_uid = db.Column(db.String(36), db.ForeignKey('sm.tickets.ticket_uid'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)

    ticket_rel = db.relationship('Ticket', foreign_keys=[ticket_uid])


class TicketTemplate(db.Model):
    __tablename__ = 'ticket_templates'
    __table_args__ = {'schema': 'sm'}

    template_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    template_name = db.Column(db.String(200), nullable=False)
    catalog_uid = db.Column(db.String(36), db.ForeignKey('sm.service_catalog.catalog_uid'), nullable=False)
    summary = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=True)
    is_public = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=False)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    __table_args__ = {'schema': 'sm'}

    audit_uid = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_uid = db.Column(db.String(36), db.ForeignKey('sm.users.user_uid'), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(64), nullable=True)
    entity_uid = db.Column(db.String(36), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    create_date = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# DB HELPERS (moved from db_functions.py)
# ---------------------------------------------------------------------------
import re
import random
import string
from datetime import timedelta
from sqlalchemy import text, func
from werkzeug.security import generate_password_hash, check_password_hash

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
    """Generate a strong temporary password."""
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
    count = db.session.query(func.count(Ticket.ticket_uid)).scalar() or 0
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
    Creates a user.

    Returns (user_name, temp_password).
    """
    temp_password = generate_password()
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
    Returns the plain-text temporary password.
    """
    user = User.query.filter_by(user_name=user_name).first()
    if not user:
        return None

    temp_password = generate_password()

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
