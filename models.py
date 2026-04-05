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
    mobile = db.Column(db.String(15), nullable=True)
    work_phone = db.Column(db.String(15), nullable=True)
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
