"""
Service Desk v3 — app.py
Flask + PostgreSQL + SQLAlchemy
"""
import os
import re
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask import (Flask, render_template, request, redirect, jsonify,
                   flash, url_for, send_from_directory)
from flask_login import (LoginManager, login_user, login_required,
                         logout_user, current_user)

from models import (db, User, Password, UserRole, WorkGroup, UserWorkGroup,
                    SlaPolicy, ServiceCatalog, ApprovalRoute, ApprovalStep,
                    TicketApproval, Ticket, TicketHistory, TicketParamValue,
                    Attachment, Notification, TicketTemplate, AuditLog, gen_uuid)
from db_functions import (
    create_user_db, reset_password_db, verify_password,
    _set_password_hash, _ensure_role, _ensure_work_group,
    generate_ticket_number, compute_deadline,
    add_ticket_history, notify, notify_ticket_update, audit,
    create_approval_chain, process_approval_decision,
    generate_password, format_mobile, normalize_gender,
)

# ============================================================
# APP INIT
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sd-secret-key-change-in-prod')

DB_CONFIG = {
    "user": "service_desk_user",
    "password": "service123",
    "host": "127.0.0.1",
    "port": "5432",
    "database": "service_desk_db",
}
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
    f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx',
                      'xls', 'xlsx', 'txt', 'zip', 'rar', '7z'}
MAX_FILE_MB = 20
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = ''
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_uid):
    return User.query.get(str(user_uid))


# ============================================================
# CONSTANTS
# ============================================================
SPECIALIST_ROLES = {'specialist', 'manager', 'admin'}
BOARD_COLUMNS = {
    'new':         ('Новые',          ['new', 'assigned', 'approved']),
    'in_progress': ('В работе',        ['in_progress']),
    'on_hold':     ('Приостановлено',  ['on_hold', 'pending_approval', 'rejected']),
    'done':        ('Завершено',       ['resolved', 'closed', 'cancelled']),
}
PRIORITIES = {'low': 'Низкий', 'medium': 'Средний', 'high': 'Высокий', 'critical': 'Критический'}
# ============================================================
# HELPERS
# ============================================================
def is_strong_password(pw):
    return (len(pw) >= 8
            and re.search(r'[A-Z]', pw)
            and re.search(r'[a-z]', pw)
            and re.search(r'[0-9]', pw)
            and re.search(r'[!@#$%^&*(),.?":{}|<>]', pw))


def is_specialist(user=None):
    u = user or current_user
    return u.role in SPECIALIST_ROLES


def _wg_uids(user):
    return [l.work_group_uid for l in user.work_group_links.all()]


def _can_view_ticket(ticket):
    if current_user.role == 'admin':
        return True
    if ticket.requester_uid == current_user.user_uid:
        return True
    if is_specialist():
        if current_user.role in ('manager', 'admin'):
            return True
        return ticket.catalog and ticket.catalog.work_group_uid in _wg_uids(current_user)
    return False


def _can_edit_ticket(ticket):
    if current_user.role == 'admin':
        return True
    if is_specialist():
        if current_user.role == 'manager':
            return True
        return ticket.catalog and ticket.catalog.work_group_uid in _wg_uids(current_user)
    return (ticket.requester_uid == current_user.user_uid and ticket.status == 'new')


def _allowed_file(filename):
    return ('.' in filename
            and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)


def _unread_count():
    if current_user.is_authenticated:
        return Notification.query.filter_by(
            user_uid=current_user.user_uid, is_read=False).count()
    return 0


# ============================================================
# JINJA2 FILTERS & GLOBALS
# ============================================================
@app.template_filter('status_label')
def status_label_filter(s):
    return {
        'new': 'Новая', 'assigned': 'Назначено', 'in_progress': 'В работе',
        'on_hold': 'Приостановлено', 'pending_approval': 'На согласовании',
        'approved': 'Согласовано', 'rejected': 'Отклонено',
        'resolved': 'Решена', 'closed': 'Закрыта', 'cancelled': 'Отменено',
    }.get(s, s)


@app.template_filter('priority_label')
def priority_label_filter(p):
    return PRIORITIES.get(p, p)


@app.template_filter('datefmt')
def datefmt_filter(dt, fmt='%d.%m.%Y %H:%M'):
    if not dt:
        return '—'
    return dt.strftime(fmt)


@app.context_processor
def inject_globals():
    return {
        'unread_count': _unread_count(),
        'is_specialist': is_specialist,
        'now': datetime.utcnow(),
        'PRIORITIES': PRIORITIES,
        'User': User,
    }


# ============================================================
# DB INIT CLI
# ============================================================
@app.cli.command('init-db')
def init_db():
    """Initialize schema and default data."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    db.session.execute(text('CREATE SCHEMA IF NOT EXISTS sm'))
    db.session.commit()
    try:
        db.create_all()
    except SQLAlchemyError:
        # Existing installations can have UUID columns in base tables while
        # ORM models use String(36). In that case create_all() may fail when
        # creating new FK tables. Continue with explicit SQL below.
        db.session.rollback()

    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.approval_routes (
            route_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            route_name varchar(200) NOT NULL,
            catalog_uid uuid NOT NULL REFERENCES sm.service_catalog(catalog_uid) ON DELETE CASCADE,
            is_active bool DEFAULT true NULL,
            create_date timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
            create_by uuid NOT NULL REFERENCES sm.users(user_uid)
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.approval_steps (
            step_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            route_uid uuid NOT NULL REFERENCES sm.approval_routes(route_uid) ON DELETE CASCADE,
            step_order int4 NOT NULL DEFAULT 1,
            step_name varchar(200) NULL,
            approver_uid uuid NULL REFERENCES sm.users(user_uid),
            approver_role varchar(32) NULL
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.ticket_approvals (
            approval_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ticket_uid uuid NOT NULL REFERENCES sm.tickets(ticket_uid) ON DELETE CASCADE,
            step_order int4 NOT NULL DEFAULT 1,
            step_name varchar(200) NULL,
            approver_uid uuid NULL REFERENCES sm.users(user_uid),
            status varchar(20) NOT NULL DEFAULT 'pending',
            comment text NULL,
            decided_at timestamptz NULL,
            create_date timestamptz DEFAULT CURRENT_TIMESTAMP NULL
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.notifications (
            notification_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_uid uuid NOT NULL REFERENCES sm.users(user_uid) ON DELETE CASCADE,
            message text NOT NULL,
            ticket_uid uuid NULL REFERENCES sm.tickets(ticket_uid) ON DELETE SET NULL,
            is_read bool DEFAULT false NULL,
            create_date timestamptz DEFAULT CURRENT_TIMESTAMP NULL
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.ticket_templates (
            template_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            template_name varchar(200) NOT NULL,
            catalog_uid uuid NOT NULL REFERENCES sm.service_catalog(catalog_uid) ON DELETE CASCADE,
            summary varchar(500) NOT NULL,
            description text NOT NULL,
            priority varchar(20) NULL,
            created_by uuid NOT NULL REFERENCES sm.users(user_uid),
            is_public bool DEFAULT false NULL,
            create_date timestamptz DEFAULT CURRENT_TIMESTAMP NULL
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS sm.audit_log (
            audit_uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_uid uuid NULL REFERENCES sm.users(user_uid) ON DELETE SET NULL,
            action varchar(64) NOT NULL,
            entity_type varchar(64) NULL,
            entity_uid uuid NULL,
            details text NULL,
            ip_address varchar(64) NULL,
            create_date timestamptz DEFAULT CURRENT_TIMESTAMP NULL
        )
    """))
    # Lightweight compatibility migration for older databases.
    db.session.execute(text("""
        ALTER TABLE IF EXISTS sm.users
            ADD COLUMN IF NOT EXISTS manager_uid uuid NULL
    """))
    db.session.execute(text("""
        ALTER TABLE IF EXISTS sm.service_catalog
            ADD COLUMN IF NOT EXISTS is_active bool DEFAULT true,
            ADD COLUMN IF NOT EXISTS approval_required bool DEFAULT false
    """))
    db.session.execute(text("""
        ALTER TABLE IF EXISTS sm.tickets
            ADD COLUMN IF NOT EXISTS deadline_at timestamptz NULL
    """))
    db.session.execute(text("""
        ALTER TABLE IF EXISTS sm.users
            ALTER COLUMN mobile TYPE varchar(20),
            ALTER COLUMN work_phone TYPE varchar(20)
    """))
    db.session.commit()

    SYS = '00000000-0000-0000-0000-000000000001'

    if not User.query.filter_by(user_name='admin').first():
        uid = gen_uuid()
        db.session.add(User(user_uid=uid, user_name='admin',
                            first_name='Администратор', last_name='Системный',
                            email='admin@company.ru', create_by=SYS))
        db.session.flush()
        db.session.add(Password(user_uid=uid,
                                passwordhash=generate_password_hash('Admin123!'),
                                is_first_login=False))
        db.session.add(UserRole(user_uid=uid, role='admin'))

    if not SlaPolicy.query.first():
        for name, resp, res in [
            ('Критический', 1, 4), ('Высокий', 4, 8),
            ('Стандартный', 8, 24), ('Низкий', 24, 72),
        ]:
            db.session.add(SlaPolicy(policy_name=name,
                                     response_time_hours=resp,
                                     resolution_time_hours=res,
                                     create_by=SYS))
        db.session.flush()

    sla_std = SlaPolicy.query.filter_by(policy_name='Стандартный').first()
    sla_hi  = SlaPolicy.query.filter_by(policy_name='Высокий').first()

    wg_defs = [('IT', 'IT-поддержка'), ('HR', 'Кадры и персонал'),
               ('Security', 'Безопасность'), ('AHO', 'АХО'), ('Finance', 'Бухгалтерия')]
    wg_map = {}
    for name, desc in wg_defs:
        wg = WorkGroup.query.filter_by(group_name=name).first()
        if not wg:
            wg = WorkGroup(group_name=name, group_description=desc, create_by=SYS)
            db.session.add(wg)
            db.session.flush()
        wg_map[name] = wg.work_group_uid

    catalog_data = [
        ('IT',       'IT-услуги',              'monitor',        'Техническая поддержка, оборудование и ПО', 'IT',      None,  None,              None,     False),
        ('IT_SUP',   'Локальная поддержка',    'tool',           'Компьютер, принтер, периферия',            'IT',      'IT',  'incident',        'medium', False),
        ('IT_ACC',   'Доступы и права',         'key',            'Учётные записи, VPN, почта',               'IT',      'IT',  'service_request', 'medium', True),
        ('IT_SW',    'Программное обеспечение', 'package',        'Установка, лицензии, обновление',          'IT',      'IT',  'service_request', 'low',    False),
        ('HR',       'Кадры',                   'users',          'Кадровые вопросы, документы и отпуска',    'HR',      None,  None,              None,     False),
        ('HR_VAC',   'Отпуск',                  'sun',            'Оформление отпуска и отгулов',             'HR',      'HR',  'service_request', 'low',    True),
        ('HR_DOC',   'Справки',                 'file-text',      'Справка о работе, копии документов',       'HR',      'HR',  'service_request', 'low',    False),
        ('HR_REG',   'Оформление',              'clipboard',      'Приём, перевод, увольнение',               'HR',      'HR',  'service_request', 'medium', True),
        ('AHO',      'АХО',                     'home',           'АХО',                                      'AHO',     None,  None,              None,     False),
        ('AHO_FRN',  'Мебель и оборудование',   'layers',         'Заявки на мебель и инвентарь',             'AHO',     'AHO', 'service_request', 'low',    False),
        ('AHO_SUP',  'Канцелярия',              'pen-tool',       'Канцелярские товары',                      'AHO',     'AHO', 'service_request', 'low',    False),
        ('AHO_MOV',  'Переезд',                 'truck',          'Переезд отдела или сотрудника',            'AHO',     'AHO', 'service_request', 'medium', True),
        ('FIN',      'Бухгалтерия',             'dollar-sign',    'Финансовые вопросы и документы',           'Finance', None,  None,              None,     False),
        ('FIN_REF',  'Справка о доходах',        'bar-chart-2',    'Справка о доходах, НДФЛ',                  'Finance', 'FIN', 'service_request', 'low',    False),
        ('FIN_RPT',  'Авансовый отчёт',          'credit-card',    'Оформление авансового отчёта',             'Finance', 'FIN', 'service_request', 'medium', True),
        ('SEC',      'Безопасность',             'shield',         'ИБ и физическая безопасность',             'Security',None,  None,              None,     False),
        ('SEC_PASS', 'Пропуск',                  'credit-card',    'Оформление и восстановление пропуска',     'Security','SEC', 'service_request', 'medium', True),
        ('SEC_INC',  'Инцидент безопасности',    'alert-triangle', 'Сообщение об инциденте',                   'Security','SEC', 'incident',        'high',   False),
    ]

    cat_map = {}
    for row in catalog_data:
        key, name, icon, desc, wg_key, parent_key, ttype, prio, appr = row
        path = f'/{key}'
        cat = ServiceCatalog.query.filter_by(catalog_path=path).first()
        if not cat:
            parent_uid = cat_map.get(parent_key)
            if prio == 'high':
                picked_sla_uid = sla_hi.sla_uid if sla_hi else (sla_std.sla_uid if sla_std else None)
            else:
                picked_sla_uid = sla_std.sla_uid if sla_std else (sla_hi.sla_uid if sla_hi else None)

            cat = ServiceCatalog(
                catalog_name=name, catalog_path=path,
                catalog_type='service' if parent_key else 'category',
                parent_uid=parent_uid,
                work_group_uid=wg_map.get(wg_key),
                ticket_type=ttype or 'service_request',
                priority=prio or 'medium',
                sla_uid=picked_sla_uid,
                catalog_icon=icon, catalog_description=desc,
                approval_required=appr, create_by=SYS,
            )
            db.session.add(cat)
            db.session.flush()
        cat_map[key] = cat.catalog_uid

    db.session.commit()
    print('OK Database initialized.')


# ============================================================
# AUTH
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/')
    error = None
    show_forgot = False
    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        password  = request.form.get('password', '')
        user = User.query.filter(
            db.func.lower(User.user_name) == login_val.lower()
        ).first()
        if not user or user.is_deactivated or user.is_temp_deactivated:
            error = 'Неверный логин или пароль'
        else:
            pwd = user.password_record
            if not pwd or not pwd.passwordhash:
                error = 'Ошибка учётной записи. Обратитесь к администратору'
            elif not verify_password(user, password):
                pwd.failed_attempts = (pwd.failed_attempts or 0) + 1
                db.session.commit()
                if pwd.failed_attempts >= 3:
                    error = 'Превышено количество попыток. Обратитесь к администратору.'
                    show_forgot = True
                else:
                    error = f'Неверный логин или пароль. Осталось попыток: {3 - pwd.failed_attempts}'
            else:
                pwd.failed_attempts = 0
                user.last_loggon_date = datetime.utcnow()
                db.session.commit()
                audit(user.user_uid, 'login', ip=request.remote_addr)
                db.session.commit()
                login_user(user)
                if pwd.is_first_login or pwd.must_change_password:
                    return redirect('/change-password')
                return redirect('/')
    return render_template('login.html', error=error, show_forgot=show_forgot)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if password != confirm:
            error = 'Пароли не совпадают'
        elif not is_strong_password(password):
            error = 'Пароль должен содержать минимум 8 символов, заглавные и строчные буквы, цифру и спецсимвол'
        else:
            pwd = current_user.password_record
            pwd.passwordhash      = generate_password_hash(password)
            pwd.is_first_login    = False
            pwd.must_change_password = False
            pwd.failed_attempts   = 0
            db.session.commit()
            flash('Пароль успешно изменён', 'success')
            return redirect('/')
    return render_template('change_password.html', error=error)


@app.route('/logout')
@login_required
def logout():
    audit(current_user.user_uid, 'logout', ip=request.remote_addr)
    db.session.commit()
    logout_user()
    return redirect('/login')


# ============================================================
# HOME
# ============================================================

@app.route('/')
@login_required
def home():
    q    = request.args.get('q', '').strip()
    view = request.args.get('view', 'catalog')

    categories = ServiceCatalog.query.filter_by(
        catalog_type='category', parent_uid=None, is_active=True
    ).order_by(ServiceCatalog.catalog_name).all()
    for cat in categories:
        cat._children = cat.children.filter_by(is_active=True).all()

    my_tickets     = None
    search_results = None

    if view == 'my_tickets':
        my_tickets = Ticket.query.filter(
            db.or_(Ticket.requester_uid == current_user.user_uid,
                   Ticket.recipient_uid == current_user.user_uid)
        ).order_by(Ticket.created_at.desc()).limit(50).all()

    if q:
        tq = Ticket.query.join(ServiceCatalog)
        if not is_specialist():
            tq = tq.filter(db.or_(
                Ticket.requester_uid == current_user.user_uid,
                Ticket.recipient_uid == current_user.user_uid,
            ))
        search_results = tq.filter(db.or_(
            Ticket.ticket_number.ilike(f'%{q}%'),
            Ticket.summary.ilike(f'%{q}%'),
            ServiceCatalog.catalog_name.ilike(f'%{q}%'),
        )).order_by(Ticket.created_at.desc()).limit(30).all()

    return render_template('home.html', categories=categories,
                           my_tickets=my_tickets, search_results=search_results,
                           view=view, q=q)


# ============================================================
# CATALOG API
# ============================================================

@app.route('/api/catalog/<catalog_uid>')
@login_required
def get_catalog_item(catalog_uid):
    cat = ServiceCatalog.query.get_or_404(catalog_uid)
    templates = TicketTemplate.query.filter_by(catalog_uid=catalog_uid, is_public=True).all()
    return jsonify({
        'catalog_uid': cat.catalog_uid,
        'catalog_name': cat.catalog_name,
        'catalog_description': cat.catalog_description,
        'ticket_type': cat.ticket_type,
        'priority': cat.priority,
        'approval_required': cat.approval_required,
        'templates': [{'uid': t.template_uid, 'name': t.template_name,
                        'summary': t.summary, 'description': t.description}
                      for t in templates],
    })


# ============================================================
# PROFILE
# ============================================================

@app.route('/profile')
@login_required
def profile():
    tickets = Ticket.query.filter(
        db.or_(Ticket.requester_uid == current_user.user_uid,
               Ticket.recipient_uid == current_user.user_uid)
    ).order_by(Ticket.created_at.desc()).limit(20).all()
    manager = User.query.get(current_user.manager_uid) if current_user.manager_uid else None
    return render_template('profile.html', tickets=tickets, manager=manager)


@app.route('/profile/password', methods=['POST'])
@login_required
def profile_password():
    old_pw  = request.form.get('old_password', '')
    new_pw  = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not verify_password(current_user, old_pw):
        flash('Текущий пароль неверен', 'error')
        return redirect('/profile')
    if new_pw != confirm:
        flash('Пароли не совпадают', 'error')
        return redirect('/profile')
    if not is_strong_password(new_pw):
        flash('Пароль слишком слабый', 'error')
        return redirect('/profile')
    _set_password_hash(current_user.user_uid, new_pw)
    db.session.commit()
    flash('Пароль изменён', 'success')
    return redirect('/profile')


# ============================================================
# PUBLIC PROFILE
# ============================================================

@app.route('/user/<user_uid>')
@login_required
def user_public_profile(user_uid):
    user = User.query.get_or_404(user_uid)
    manager = User.query.get(user.manager_uid) if user.manager_uid else None
    return render_template('user_profile.html', user=user, manager=manager,
                           work_groups=user.all_work_groups())


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route('/api/notifications')
@login_required
def api_notifications():
    notes = Notification.query.filter_by(
        user_uid=current_user.user_uid, is_read=False
    ).order_by(Notification.create_date.desc()).limit(20).all()
    return jsonify({
        'count': len(notes),
        'items': [{
            'uid': n.notification_uid,
            'message': n.message,
            'ticket_uid': n.ticket_uid,
            'ticket_number': n.ticket_rel.ticket_number if n.ticket_rel else None,
            'created_at': n.create_date.strftime('%d.%m.%Y %H:%M'),
        } for n in notes]
    })


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    data = request.get_json() or {}
    uid = data.get('uid')
    if uid:
        note = Notification.query.filter_by(
            notification_uid=uid, user_uid=current_user.user_uid).first()
        if note:
            note.is_read = True
    else:
        Notification.query.filter_by(
            user_uid=current_user.user_uid, is_read=False
        ).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# TICKETS BOARD
# ============================================================

@app.route('/tickets')
@login_required
def tickets_board():
    if not is_specialist():
        flash('Доступ запрещён', 'error')
        return redirect('/')

    view_mode = request.args.get('view', 'board')
    fs   = request.args.get('status', '')
    fa   = request.args.get('assignee', '')
    fd_from = request.args.get('date_from', '')
    fd_to   = request.args.get('date_to', '')
    fwg  = request.args.get('work_group', '')
    fp   = request.args.get('priority', '')

    query = Ticket.query.join(ServiceCatalog, Ticket.catalog_uid == ServiceCatalog.catalog_uid)

    if current_user.role == 'admin':
        all_wgs = WorkGroup.query.filter_by(isactive=True).order_by(WorkGroup.group_name).all()
        if fwg:
            query = query.filter(ServiceCatalog.work_group_uid == fwg)
    else:
        my_uids = _wg_uids(current_user)
        all_wgs = WorkGroup.query.filter(
            WorkGroup.work_group_uid.in_(my_uids)
        ).order_by(WorkGroup.group_name).all()
        if fwg and fwg in my_uids:
            query = query.filter(ServiceCatalog.work_group_uid == fwg)
        else:
            query = query.filter(ServiceCatalog.work_group_uid.in_(my_uids))

    if fs:
        query = query.filter(Ticket.status == fs)
    if fp:
        query = query.filter(Ticket.priority == fp)
    if fa == 'me':
        query = query.filter(Ticket.performer_uid == current_user.user_uid)
    elif fa == 'unassigned':
        query = query.filter(Ticket.performer_uid == None)
    elif fa:
        query = query.filter(Ticket.performer_uid == fa)
    if fd_from:
        try:
            query = query.filter(Ticket.created_at >= datetime.strptime(fd_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if fd_to:
        try:
            query = query.filter(
                Ticket.created_at < datetime.strptime(fd_to, '%Y-%m-%d') + timedelta(days=1)
            )
        except ValueError:
            pass

    tickets = query.order_by(Ticket.created_at.desc()).all()

    board = {}
    for col_key, (col_name, col_statuses) in BOARD_COLUMNS.items():
        board[col_key] = {
            'name': col_name,
            'tickets': [t for t in tickets if t.status in col_statuses],
        }

    sq_base = Ticket.query.join(ServiceCatalog, Ticket.catalog_uid == ServiceCatalog.catalog_uid)
    if current_user.role != 'admin':
        sq_base = sq_base.filter(ServiceCatalog.work_group_uid.in_(_wg_uids(current_user)))

    all_active = sq_base.filter(
        Ticket.status.in_(['new', 'assigned', 'in_progress']),
        Ticket.deadline_at != None,
    ).all()
    stats = {
        'total':       sq_base.count(),
        'new':         sq_base.filter(Ticket.status == 'new').count(),
        'in_progress': sq_base.filter(Ticket.status == 'in_progress').count(),
        'on_hold':     sq_base.filter(Ticket.status == 'on_hold').count(),
        'resolved':    sq_base.filter(Ticket.status == 'resolved').count(),
        'overdue':     sum(1 for t in all_active if t.is_overdue()),
    }

    if current_user.role == 'admin':
        specialists = User.query.join(UserRole).filter(
            UserRole.role.in_(['specialist', 'manager', 'admin']),
            User.is_deactivated == False,
        ).order_by(User.last_name).all()
    else:
        specialists = User.query.join(UserWorkGroup).filter(
            UserWorkGroup.work_group_uid.in_(_wg_uids(current_user))
        ).join(UserRole, User.user_uid == UserRole.user_uid).filter(
            UserRole.role.in_(['specialist', 'manager']),
            User.is_deactivated == False,
        ).order_by(User.last_name).all()

    return render_template('tickets.html',
                           board=board, tickets=tickets, stats=stats,
                           specialists=specialists, all_wgs=all_wgs,
                           view_mode=view_mode,
                           filters={'status': fs, 'assignee': fa,
                                    'date_from': fd_from, 'date_to': fd_to,
                                    'work_group': fwg, 'priority': fp})


# ============================================================
# TICKET API — CREATE
# ============================================================

@app.route('/api/tickets', methods=['POST'])
@login_required
def create_ticket():
    data = request.get_json() or {}
    summary     = (data.get('summary') or '').strip()
    description = (data.get('description') or '').strip()
    catalog_uid = data.get('catalog_uid')

    if not summary or not description or not catalog_uid:
        return jsonify({'error': 'Заполните все обязательные поля'}), 400

    catalog = ServiceCatalog.query.get(catalog_uid)
    if not catalog or not catalog.is_active:
        return jsonify({'error': 'Услуга не найдена'}), 400
    if catalog.catalog_type == 'category':
        return jsonify({'error': 'Выберите конкретную услугу'}), 400

    ticket_number  = generate_ticket_number()
    deadline       = compute_deadline(catalog)
    initial_status = 'pending_approval' if catalog.approval_required else 'new'

    ticket = Ticket(
        ticket_number=ticket_number,
        catalog_uid=catalog_uid,
        summary=summary,
        description=description,
        requester_uid=current_user.user_uid,
        recipient_uid=current_user.user_uid,
        status=initial_status,
        priority=catalog.priority or data.get('priority', 'medium'),
        deadline_at=deadline,
        created_by=current_user.user_uid,
        updated_by=current_user.user_uid,
    )
    db.session.add(ticket)
    db.session.flush()

    add_ticket_history(ticket.ticket_uid, 'status', None, initial_status, current_user.user_uid)

    if catalog.approval_required:
        create_approval_chain(ticket, catalog, current_user)
        first = TicketApproval.query.filter_by(
            ticket_uid=ticket.ticket_uid, status='pending'
        ).order_by(TicketApproval.step_order).first()
        if first and first.approver_uid:
            notify(first.approver_uid,
                   f'Требуется согласование заявки {ticket.ticket_number}',
                   ticket_uid=ticket.ticket_uid)

    tpl_name = (data.get('save_as_template') or '').strip()
    if tpl_name:
        db.session.add(TicketTemplate(
            template_name=tpl_name, catalog_uid=catalog_uid,
            summary=summary, description=description,
            priority=ticket.priority, created_by=current_user.user_uid, is_public=False,
        ))

    db.session.commit()
    return jsonify({'success': True, 'ticket_number': ticket.ticket_number,
                    'ticket_uid': ticket.ticket_uid})


# ============================================================
# TICKET API — GET
# ============================================================

@app.route('/api/tickets/<ticket_uid>', methods=['GET'])
@login_required
def get_ticket(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_view_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403

    comments = []
    for pv in ticket.param_values.filter(
            TicketParamValue.param_type.in_(['comment', 'internal_comment'])
    ).order_by(TicketParamValue.create_date).all():
        if pv.param_type == 'internal_comment' and not is_specialist():
            continue
        comments.append({
            'uid': pv.param_value_uid,
            'author': pv.author_rel.full_name() if pv.author_rel else '—',
            'author_uid': pv.author_uid,
            'text': pv.param_value,
            'is_internal': pv.param_type == 'internal_comment',
            'created_at': pv.create_date.strftime('%d.%m.%Y %H:%M'),
        })

    history = [{
        'field': h.field_name,
        'old': h.old_value,
        'new': h.new_value,
        'by': h.changer.full_name() if h.changer else '—',
        'date': h.changed_date.strftime('%d.%m.%Y %H:%M'),
    } for h in ticket.history.order_by(TicketHistory.changed_date).all()]

    approvals = [{
        'uid': a.approval_uid,
        'step': a.step_name or f'Шаг {a.step_order}',
        'approver': a.approver.full_name() if a.approver else 'Руководитель',
        'approver_uid': a.approver_uid,
        'status': a.status,
        'comment': a.comment,
        'decided_at': a.decided_at.strftime('%d.%m.%Y %H:%M') if a.decided_at else None,
    } for a in ticket.approvals.order_by(TicketApproval.step_order).all()]

    attachments = [{
        'uid': att.attachment_uid,
        'name': att.attachment_name,
        'size': att.file_size,
        'url': f'/uploads/{att.attachment_path}',
        'uploader': att.uploader.full_name() if att.uploader else '—',
        'date': att.upload_date.strftime('%d.%m.%Y %H:%M'),
    } for att in ticket.attachments.order_by(Attachment.upload_date).all()]

    my_approval = None
    if ticket.status == 'pending_approval':
        my_approval = TicketApproval.query.filter_by(
            ticket_uid=ticket_uid, approver_uid=current_user.user_uid, status='pending',
        ).first()

    return jsonify({
        'ticket_uid':       ticket.ticket_uid,
        'ticket_number':    ticket.ticket_number,
        'summary':          ticket.summary,
        'description':      ticket.description,
        'status':           ticket.status,
        'priority':         ticket.priority,
        'catalog':          ticket.catalog.catalog_name if ticket.catalog else '—',
        'catalog_uid':      ticket.catalog_uid,
        'requester':        ticket.requester.full_name() if ticket.requester else '—',
        'requester_uid':    ticket.requester_uid,
        'performer':        ticket.performer.full_name() if ticket.performer else None,
        'performer_uid':    ticket.performer_uid,
        'deadline':         ticket.deadline_at.strftime('%d.%m.%Y %H:%M') if ticket.deadline_at else None,
        'is_overdue':       ticket.is_overdue(),
        'created_at':       ticket.created_at.strftime('%d.%m.%Y %H:%M'),
        'updated_at':       ticket.updated_at.strftime('%d.%m.%Y %H:%M'),
        'resolved_at':      ticket.resolved_at.strftime('%d.%m.%Y %H:%M') if ticket.resolved_at else None,
        'comments':         comments,
        'history':          history,
        'approvals':        approvals,
        'attachments':      attachments,
        'can_edit':         _can_edit_ticket(ticket),
        'can_assign':       current_user.role in ('admin', 'manager'),
        'can_approve':      my_approval is not None,
        'my_approval_uid':  my_approval.approval_uid if my_approval else None,
    })


# ============================================================
# TICKET API — UPDATE
# ============================================================

@app.route('/api/tickets/<ticket_uid>/update', methods=['POST'])
@login_required
def update_ticket(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    data   = request.get_json() or {}
    action = data.get('action')

    # Approve only needs the user to be a pending approver — checked inside the branch.
    # All other mutating actions require edit permission.
    if action != 'approve' and not _can_edit_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403
    now    = datetime.utcnow()

    if action == 'take':
        if not is_specialist():
            return jsonify({'error': 'Только специалист может взять заявку'}), 403
        old_perf = ticket.performer_uid
        old_st   = ticket.status
        ticket.performer_uid = current_user.user_uid
        ticket.status = 'in_progress'
        add_ticket_history(ticket_uid, 'performer', old_perf, current_user.user_uid, current_user.user_uid)
        add_ticket_history(ticket_uid, 'status', old_st, 'in_progress', current_user.user_uid)
        notify_ticket_update(ticket,
                             f'Заявку {ticket.ticket_number} взял в работу {current_user.full_name()}',
                             exclude_uid=current_user.user_uid)

    elif action == 'assign':
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'error': 'Недостаточно прав'}), 403
        new_perf = data.get('performer_uid') or None
        old_st   = ticket.status
        add_ticket_history(ticket_uid, 'performer', ticket.performer_uid, new_perf, current_user.user_uid)
        ticket.performer_uid = new_perf
        ticket.status = 'assigned' if new_perf else 'new'
        if old_st != ticket.status:
            add_ticket_history(ticket_uid, 'status', old_st, ticket.status, current_user.user_uid)
        if new_perf:
            notify(new_perf, f'Вам назначена заявка {ticket.ticket_number}',
                   ticket_uid=ticket.ticket_uid)

    elif action == 'status':
        new_status = data.get('status')
        valid = ['new', 'assigned', 'in_progress', 'on_hold',
                 'pending_approval', 'resolved', 'closed', 'cancelled']
        if new_status not in valid:
            return jsonify({'error': 'Недопустимый статус'}), 400
        old_st = ticket.status
        add_ticket_history(ticket_uid, 'status', old_st, new_status, current_user.user_uid)
        ticket.status = new_status
        if new_status == 'resolved':
            ticket.resolved_at = now
        if new_status == 'closed':
            ticket.closed_at = now
        notify_ticket_update(ticket,
                             f'Статус заявки {ticket.ticket_number} изменён',
                             exclude_uid=current_user.user_uid)

    elif action == 'approve':
        approval_uid = data.get('approval_uid')
        decision     = data.get('decision')
        comment      = (data.get('comment') or '').strip()
        approval = TicketApproval.query.filter_by(
            approval_uid=approval_uid, approver_uid=current_user.user_uid, status='pending',
        ).first()
        if not approval:
            return jsonify({'error': 'Запись согласования не найдена'}), 404
        process_approval_decision(ticket, approval, decision, comment, current_user.user_uid)

    elif action == 'edit':
        new_summary = (data.get('summary') or '').strip()
        new_desc    = (data.get('description') or '').strip()
        new_prio    = data.get('priority')
        if new_summary and new_summary != ticket.summary:
            add_ticket_history(ticket_uid, 'summary', ticket.summary, new_summary, current_user.user_uid)
            ticket.summary = new_summary
        if new_desc and new_desc != ticket.description:
            add_ticket_history(ticket_uid, 'description',
                               ticket.description[:80], new_desc[:80], current_user.user_uid)
            ticket.description = new_desc
        if new_prio and new_prio != ticket.priority:
            add_ticket_history(ticket_uid, 'priority', ticket.priority, new_prio, current_user.user_uid)
            ticket.priority = new_prio

    elif action == 'delete':
        if current_user.role != 'admin':
            return jsonify({'error': 'Только администратор может удалять заявки'}), 403
        db.session.delete(ticket)
        db.session.commit()
        return jsonify({'success': True, 'deleted': True})

    else:
        return jsonify({'error': 'Неизвестное действие'}), 400

    ticket.updated_at = now
    ticket.updated_by = current_user.user_uid
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# TICKET API — BULK UPDATE
# ============================================================

@app.route('/api/tickets/bulk', methods=['POST'])
@login_required
def bulk_update_tickets():
    if not is_specialist():
        return jsonify({'error': 'Доступ запрещён'}), 403
    data       = request.get_json() or {}
    action     = data.get('action')
    new_status = data.get('status')
    uids       = data.get('ticket_uids', [])
    valid_statuses = ['in_progress', 'on_hold', 'resolved', 'closed', 'cancelled']
    if action != 'bulk_status':
        return jsonify({'error': 'Неизвестное действие'}), 400
    if new_status not in valid_statuses:
        return jsonify({'error': 'Недопустимый статус'}), 400
    if not uids:
        return jsonify({'error': 'Нет заявок для обновления'}), 400
    now = datetime.utcnow()
    Ticket.query.filter(Ticket.ticket_uid.in_(uids)).update(
        {'status': new_status, 'updated_at': now, 'updated_by': current_user.user_uid},
        synchronize_session=False,
    )
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# TICKET — COMMENT
# ============================================================

@app.route('/api/tickets/<ticket_uid>/comment', methods=['POST'])
@login_required
def add_comment(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_view_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Комментарий не может быть пустым'}), 400
    is_internal = data.get('is_internal', False) and is_specialist()
    ptype = 'internal_comment' if is_internal else 'comment'
    db.session.add(TicketParamValue(
        ticket_uid=ticket_uid, param_name='comment',
        param_value=text, param_type=ptype,
        author_uid=current_user.user_uid,
    ))
    ticket.updated_at = datetime.utcnow()
    ticket.updated_by = current_user.user_uid
    notify_ticket_update(ticket, f'Новый комментарий к заявке {ticket.ticket_number}',
                         exclude_uid=current_user.user_uid)
    db.session.commit()
    return jsonify({
        'success': True,
        'comment': {
            'author': current_user.full_name(),
            'author_uid': current_user.user_uid,
            'text': text,
            'is_internal': is_internal,
            'created_at': datetime.utcnow().strftime('%d.%m.%Y %H:%M'),
        }
    })


# ============================================================
# TICKET — ATTACHMENTS
# ============================================================

@app.route('/api/tickets/<ticket_uid>/attach', methods=['POST'])
@login_required
def upload_attachment(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_view_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400
    f = request.files['file']
    if not f.filename or not _allowed_file(f.filename):
        return jsonify({'error': 'Недопустимый тип файла'}), 400
    filename   = secure_filename(f.filename)
    saved_name = f"{gen_uuid()}_{filename}"
    save_path  = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
    f.save(save_path)
    size_kb = round(os.path.getsize(save_path) / 1024, 1)
    att = Attachment(
        ticket_uid=ticket_uid, attachment_name=filename,
        attachment_path=saved_name, mime_type=f.content_type,
        file_size=f'{size_kb} KB', uploaded_by=current_user.user_uid,
    )
    db.session.add(att)
    db.session.commit()
    return jsonify({'success': True, 'attachment': {
        'uid': att.attachment_uid, 'name': filename,
        'size': att.file_size, 'url': f'/uploads/{saved_name}',
    }})


@app.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ============================================================
# TEMPLATES API
# ============================================================

@app.route('/api/templates')
@login_required
def list_templates():
    catalog_uid = request.args.get('catalog_uid')
    q = TicketTemplate.query.filter(
        db.or_(TicketTemplate.is_public == True,
               TicketTemplate.created_by == current_user.user_uid)
    )
    if catalog_uid:
        q = q.filter_by(catalog_uid=catalog_uid)
    return jsonify([{
        'uid': t.template_uid, 'name': t.template_name,
        'catalog_uid': t.catalog_uid, 'summary': t.summary,
        'description': t.description, 'priority': t.priority,
    } for t in q.order_by(TicketTemplate.template_name).all()])


# ============================================================
# SPECIALISTS API
# ============================================================

@app.route('/api/specialists')
@login_required
def get_specialists():
    if not is_specialist():
        return jsonify({'error': 'Доступ запрещён'}), 403
    if current_user.role == 'admin':
        users = User.query.join(UserRole).filter(
            UserRole.role.in_(['specialist', 'manager', 'admin']),
            User.is_deactivated == False,
        ).order_by(User.last_name).all()
    else:
        users = User.query.join(UserWorkGroup).filter(
            UserWorkGroup.work_group_uid.in_(_wg_uids(current_user))
        ).join(UserRole, User.user_uid == UserRole.user_uid).filter(
            UserRole.role.in_(['specialist', 'manager']),
            User.is_deactivated == False,
        ).order_by(User.last_name).all()
    return jsonify([{
        'user_uid': u.user_uid, 'full_name': u.full_name(),
        'role': u.role,
    } for u in users])


# ============================================================
# MY TICKETS API
# ============================================================

@app.route('/api/my-tickets')
@login_required
def my_tickets():
    tickets = Ticket.query.filter(
        db.or_(Ticket.requester_uid == current_user.user_uid,
               Ticket.recipient_uid == current_user.user_uid)
    ).order_by(Ticket.created_at.desc()).all()
    return jsonify([{
        'ticket_uid':    t.ticket_uid,
        'ticket_number': t.ticket_number,
        'summary':       t.summary,
        'status':        t.status,
        'priority':      t.priority,
        'catalog':       t.catalog.catalog_name if t.catalog else '—',
        'created_at':    t.created_at.strftime('%d.%m.%Y %H:%M'),
        'deadline':      t.deadline_at.strftime('%d.%m.%Y %H:%M') if t.deadline_at else None,
        'is_overdue':    t.is_overdue(),
    } for t in tickets])


# ============================================================
# SPECIALIST DASHBOARD
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    if not is_specialist():
        return redirect('/')

    my_wg_uids = _wg_uids(current_user) if current_user.role != 'admin' else None
    base = Ticket.query.join(ServiceCatalog, Ticket.catalog_uid == ServiceCatalog.catalog_uid)
    if my_wg_uids:
        base = base.filter(ServiceCatalog.work_group_uid.in_(my_wg_uids))

    my_active = base.filter(
        Ticket.performer_uid == current_user.user_uid,
        Ticket.status.in_(['assigned', 'in_progress'])
    ).order_by(Ticket.deadline_at.asc().nullslast()).all()

    all_new = base.filter(Ticket.status == 'new', Ticket.performer_uid == None
              ).order_by(Ticket.created_at.desc()).limit(10).all()

    overdue_list = [t for t in base.filter(
        Ticket.status.in_(['new', 'assigned', 'in_progress']),
        Ticket.deadline_at != None,
        Ticket.deadline_at < datetime.utcnow(),
    ).order_by(Ticket.deadline_at).limit(20).all()]

    pending_approval = []
    if current_user.role in ('admin', 'manager'):
        pending_approval = TicketApproval.query.filter_by(
            approver_uid=current_user.user_uid, status='pending').limit(10).all()

    stats = {
        'my_active':         len(my_active),
        'all_new':           base.filter(Ticket.status == 'new').count(),
        'overdue':           len(overdue_list),
        'pending_approval':  len(pending_approval),
    }

    return render_template('dashboard.html',
                           my_active=my_active, all_new=all_new,
                           all_overdue=overdue_list, pending_approval=pending_approval,
                           stats=stats)


# ============================================================
# ADMIN — USERS
# ============================================================

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    users = User.query.order_by(User.last_name, User.first_name).all()
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    return render_template('admin_users.html', users=users, work_groups=work_groups)


@app.route('/admin/create-user', methods=['GET', 'POST'])
@login_required
def create_user():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    all_users   = User.query.filter_by(is_deactivated=False).order_by(User.last_name).all()

    if request.method == 'POST':
        last_name   = request.form['last_name'].strip()
        first_name  = request.form['first_name'].strip()
        middle_name = request.form.get('middle_name', '').strip() or None
        email       = request.form['email'].strip()
        mobile      = request.form.get('mobile', '').strip() or None
        work_phone  = request.form.get('work_phone', '').strip() or None
        gender      = request.form.get('gender', '').strip() or None
        title       = request.form.get('title', '').strip() or None
        department  = request.form.get('department', '').strip() or None
        company     = request.form.get('company', '').strip() or None
        role        = request.form.get('role', 'user')
        wg_uid      = request.form.get('work_group_uid') or None
        manager_uid = request.form.get('manager_uid') or None

        form_data = {
            'last_name': last_name, 'first_name': first_name,
            'middle_name': middle_name or '', 'email': email,
            'mobile': request.form.get('mobile', '').strip(),
            'work_phone': request.form.get('work_phone', '').strip(),
            'gender': gender or '', 'title': title or '',
            'department': department or '', 'company': company or '',
            'role': role, 'work_group_uid': wg_uid or '',
            'manager_uid': manager_uid or '',
        }
        if User.query.filter_by(email=email).first():
            return render_template('create_user.html', work_groups=work_groups,
                                   all_users=all_users, form_data=form_data,
                                   error='Пользователь с таким email уже существует')
        try:
            user_name, temp_pw = create_user_db(
                last_name, first_name, middle_name, email, mobile,
                work_phone, gender, title, department, company,
                role=role, work_group_uid=wg_uid, manager_uid=manager_uid,
                creator_uid=current_user.user_uid,
            )
            audit(current_user.user_uid, 'create_user', 'user', None,
                  f'Создан пользователь {user_name}', request.remote_addr)
            db.session.commit()
            return render_template('create_user.html', work_groups=work_groups,
                                   all_users=all_users, success=True,
                                   temp_login=user_name, temp_password=temp_pw)
        except Exception as e:
            db.session.rollback()
            err_str = str(e)
            if 'value too long' in err_str or 'StringDataRightTruncation' in err_str:
                error = 'Одно из полей слишком длинное (телефон, должность и т.п.). Проверьте данные.'
            elif 'unique' in err_str.lower() or 'UniqueViolation' in err_str:
                if 'email' in err_str:
                    error = 'Пользователь с таким email уже существует.'
                elif 'user_name' in err_str:
                    error = 'Сгенерированный логин уже занят, попробуйте ещё раз.'
                else:
                    error = 'Нарушение уникальности: такие данные уже есть в системе.'
            elif 'not-null' in err_str.lower() or 'null value' in err_str.lower():
                error = 'Не заполнено обязательное поле. Проверьте Фамилию, Имя и Email.'
            else:
                error = 'Ошибка при создании пользователя. Проверьте введённые данные.'
            return render_template('create_user.html', work_groups=work_groups,
                                   all_users=all_users, form_data=form_data, error=error)

    return render_template('create_user.html', work_groups=work_groups,
                           all_users=all_users, error=None)


@app.route('/admin/edit-user/<user_uid>', methods=['GET', 'POST'])
@login_required
def edit_user(user_uid):
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    user = User.query.get_or_404(user_uid)
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    all_users   = User.query.filter(
        User.is_deactivated == False,
        User.user_uid != user_uid,
    ).order_by(User.last_name).all()

    if request.method == 'POST':
        # Required fields: keep old value only if form sends empty string
        user.first_name  = request.form.get('first_name', '').strip() or user.first_name
        user.last_name   = request.form.get('last_name', '').strip() or user.last_name
        user.email       = request.form.get('email', '').strip() or user.email
        # Optional fields: allow clearing by setting to None when blank
        user.middel_name = request.form.get('middle_name', '').strip() or None
        user.mobile      = format_mobile(request.form.get('mobile', '').strip()) or None
        user.work_phone  = request.form.get('work_phone', '').strip() or None
        user.title       = request.form.get('title', '').strip() or None
        user.department  = request.form.get('department', '').strip() or None
        user.company     = request.form.get('company', '').strip() or None
        user.manager_uid    = request.form.get('manager_uid') or None
        user.is_deactivated = 'is_deactivated' in request.form
        user.update_date    = datetime.utcnow()
        user.update_by      = current_user.user_uid
        _ensure_role(user.user_uid, request.form.get('role', user.role))
        new_wg = request.form.get('work_group_uid') or None
        if new_wg:
            UserWorkGroup.query.filter_by(user_uid=user.user_uid).delete()
            _ensure_work_group(user.user_uid, new_wg)
        db.session.commit()
        flash('Пользователь обновлён', 'success')
        return redirect('/admin/users')

    return render_template('edit_user.html', user=user,
                           work_groups=work_groups, all_users=all_users)


@app.route('/admin/delete-user/<user_uid>', methods=['POST'])
@login_required
def delete_user(user_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    user = User.query.get_or_404(user_uid)
    if user.user_uid == current_user.user_uid:
        return jsonify({'error': 'Нельзя деактивировать себя'}), 400
    user.is_deactivated = True
    user.update_date = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/reset-password/<user_uid>', methods=['POST'])
@login_required
def admin_reset_password(user_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    user = User.query.get_or_404(user_uid)
    new_pass = reset_password_db(user.user_name)
    if not new_pass:
        return jsonify({'error': 'Не удалось сбросить пароль'}), 500
    return jsonify({'success': True, 'new_password': new_pass})


# ============================================================
# ADMIN — CATEGORIES
# ============================================================

@app.route('/admin/categories')
@login_required
def admin_categories():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    cats = ServiceCatalog.query.filter_by(parent_uid=None).order_by(ServiceCatalog.catalog_name).all()
    for c in cats:
        c._services = c.children.order_by(ServiceCatalog.catalog_name).all()
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    slas = SlaPolicy.query.filter_by(is_active=True).all()
    return render_template('admin_categories.html', categories=cats,
                           work_groups=work_groups, slas=slas)


@app.route('/admin/create-category', methods=['GET', 'POST'])
@login_required
def create_category():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    top_cats = ServiceCatalog.query.filter_by(catalog_type='category', parent_uid=None, is_active=True).all()
    slas = SlaPolicy.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        name       = request.form['catalog_name'].strip()
        desc       = request.form.get('catalog_description', '').strip() or None
        icon       = request.form.get('catalog_icon', 'briefcase')
        wg_uid     = request.form.get('work_group_uid') or None
        parent_uid = request.form.get('parent_uid') or None
        ttype      = request.form.get('ticket_type', 'service_request')
        prio       = request.form.get('priority', 'medium')
        sla_uid    = request.form.get('sla_uid') or None
        appr       = 'approval_required' in request.form
        cat_type   = 'service' if parent_uid else 'category'
        db.session.add(ServiceCatalog(
            catalog_name=name, catalog_path=f'/{name.replace(" ","_")}',
            catalog_type=cat_type, catalog_description=desc, catalog_icon=icon,
            work_group_uid=wg_uid, parent_uid=parent_uid, ticket_type=ttype,
            priority=prio, sla_uid=sla_uid, approval_required=appr,
            create_by=current_user.user_uid,
        ))
        db.session.commit()
        flash('Запись каталога создана', 'success')
        return redirect('/admin/categories')

    return render_template('create_category.html', work_groups=work_groups,
                           top_cats=top_cats, slas=slas, error=None)


@app.route('/admin/edit-category/<cat_uid>', methods=['GET', 'POST'])
@login_required
def edit_category(cat_uid):
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    cat = ServiceCatalog.query.get_or_404(cat_uid)
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    top_cats = ServiceCatalog.query.filter(
        ServiceCatalog.catalog_type == 'category',
        ServiceCatalog.parent_uid == None,
        ServiceCatalog.catalog_uid != cat_uid,
    ).all()
    slas = SlaPolicy.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        cat.catalog_name        = request.form.get('catalog_name', '').strip() or cat.catalog_name
        cat.catalog_description = request.form.get('catalog_description', '').strip() or cat.catalog_description
        cat.catalog_icon        = request.form.get('catalog_icon', cat.catalog_icon)
        cat.work_group_uid      = request.form.get('work_group_uid') or cat.work_group_uid
        cat.parent_uid          = request.form.get('parent_uid') or cat.parent_uid
        cat.ticket_type         = request.form.get('ticket_type', cat.ticket_type)
        cat.priority            = request.form.get('priority', cat.priority)
        cat.sla_uid             = request.form.get('sla_uid') or cat.sla_uid
        cat.approval_required   = 'approval_required' in request.form
        cat.is_active           = 'is_active' in request.form
        cat.update_date         = datetime.utcnow()
        cat.update_by           = current_user.user_uid
        db.session.commit()
        flash('Запись обновлена', 'success')
        return redirect('/admin/categories')

    return render_template('edit_category.html', cat=cat,
                           work_groups=work_groups, top_cats=top_cats, slas=slas)


@app.route('/admin/toggle-category/<cat_uid>', methods=['POST'])
@login_required
def toggle_category(cat_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    cat = ServiceCatalog.query.get_or_404(cat_uid)
    cat.is_active = not cat.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': cat.is_active})


@app.route('/admin/delete-category/<cat_uid>', methods=['POST'])
@login_required
def delete_category(cat_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    cat = ServiceCatalog.query.get_or_404(cat_uid)
    ticket_count = Ticket.query.filter_by(catalog_uid=cat_uid).count()
    if ticket_count > 0:
        return jsonify({
            'error': f'Нельзя удалить: к этой категории привязано {ticket_count} заявок. '
                     f'Сначала скройте её (глазик), чтобы запретить новые заявки.'
        }), 400
    # Also delete child services if this is a top-level category
    for child in cat.children.all():
        if Ticket.query.filter_by(catalog_uid=child.catalog_uid).count() == 0:
            db.session.delete(child)
        else:
            return jsonify({
                'error': f'Нельзя удалить: дочерняя услуга «{child.catalog_name}» имеет привязанные заявки.'
            }), 400
    audit(current_user.user_uid, 'delete_category', 'service_catalog', cat_uid,
          f'Удалена категория {cat.catalog_name}', request.remote_addr)
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# ADMIN — WORK GROUPS
# ============================================================

@app.route('/admin/work-groups')
@login_required
def admin_work_groups():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    groups = WorkGroup.query.order_by(WorkGroup.group_name).all()
    return render_template('admin_work_groups.html', groups=groups)


@app.route('/admin/create-work-group', methods=['POST'])
@login_required
def create_work_group():
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    data = request.get_json() or {}
    name = (data.get('group_name') or '').strip()
    desc = (data.get('group_description') or '').strip() or None
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400
    if WorkGroup.query.filter_by(group_name=name).first():
        return jsonify({'error': 'Группа уже существует'}), 400
    wg = WorkGroup(group_name=name, group_description=desc, create_by=current_user.user_uid)
    db.session.add(wg)
    db.session.commit()
    return jsonify({'success': True, 'work_group_uid': wg.work_group_uid})


@app.route('/admin/delete-work-group/<wg_uid>', methods=['POST'])
@login_required
def delete_work_group(wg_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    wg = WorkGroup.query.get_or_404(wg_uid)
    wg.isactive = False
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# ADMIN — AUDIT LOG
# ============================================================

@app.route('/admin/audit-log')
@login_required
def admin_audit_log():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    page = request.args.get('page', 1, type=int)
    logs = AuditLog.query.order_by(AuditLog.create_date.desc()).paginate(
        page=page, per_page=50, error_out=False)
    uids = {log.user_uid for log in logs.items if log.user_uid}
    users_by_uid = {u.user_uid: u for u in User.query.filter(User.user_uid.in_(uids)).all()}
    return render_template('admin_audit_log.html', logs=logs, users_by_uid=users_by_uid)


# ============================================================
# RUN
# ============================================================

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=5000)
