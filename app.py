from flask import Flask, render_template, request, redirect, jsonify, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime
import re

from models import (db, User, Password, UserRole, WorkGroup, UserWorkGroup,
                    ServiceCatalog, SlaPolicy, Ticket, TicketHistory,
                    TicketParamValue, Attachment, gen_uuid)
from db_functions import (create_user_db, reset_password_db, verify_password,
                           _set_password_hash, _ensure_role, _ensure_work_group,
                           generate_ticket_number, add_ticket_history,
                           generate_password, format_mobile, normalize_gender)

app = Flask(__name__)
app.secret_key = 'secret_key'

# -------------------------
# CONFIG БАЗЫ
# -------------------------
DB_CONFIG = {
    "user": "service_desk_user",
    "password": "service123",
    "host": "127.0.0.1",
    "port": "5432",
    "database": "service_desk_db"
}

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
    f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# -------------------------
# LOGIN MANAGER
# -------------------------
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_uid):
    return User.query.get(str(user_uid))


# -------------------------
# HELPERS
# -------------------------
def is_strong_password(password):
    return (
        len(password) >= 8 and
        re.search(r"[A-Z]", password) and
        re.search(r"[a-z]", password) and
        re.search(r"[0-9]", password) and
        re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)
    )


SPECIALIST_ROLES = {'specialist', 'manager', 'admin'}


def is_specialist(user=None):
    u = user or current_user
    return u.role in SPECIALIST_ROLES


def _user_work_group_uids(user):
    return [link.work_group_uid for link in user.work_group_links.all()]


# -------------------------
# JINJA2 FILTERS
# -------------------------
@app.template_filter('status_label')
def status_label_filter(status):
    labels = {
        'new': 'Новая', 'assigned': 'Назначено', 'in_progress': 'В работе',
        'resolved': 'Решена', 'closed': 'Закрыта', 'cancelled': 'Отменено',
        'approved': 'Одобрено', 'rejected': 'Отклонено',
        'pending_approval': 'На согласовании',
    }
    return labels.get(status, status)


# -------------------------
# ИНИЦИАЛИЗАЦИЯ БД
# -------------------------
@app.cli.command('init-db')
def init_db():
    from sqlalchemy import text
    db.session.execute(text('CREATE SCHEMA IF NOT EXISTS sm'))
    db.session.commit()
    db.create_all()

    sys_uid = 'system-0000-0000-0000-000000000000'

    if not User.query.filter_by(user_name='admin').first():
        admin_uid = gen_uuid()
        admin = User(
            user_uid=admin_uid,
            user_name='admin',
            first_name='Администратор',
            last_name='Системный',
            email='admin@company.ru',
            create_by=sys_uid,
        )
        db.session.add(admin)
        db.session.flush()
        db.session.add(Password(user_uid=admin_uid,
                                passwordhash=generate_password_hash('Admin123!'),
                                is_first_login=False, must_change_password=False))
        db.session.add(UserRole(user_uid=admin_uid, role='admin'))

    # Default SLA
    if not SlaPolicy.query.first():
        db.session.add(SlaPolicy(
            policy_name='Стандартный',
            description='Стандартный SLA: ответ 8ч, решение 24ч',
            response_time_hours=8, resolution_time_hours=24,
            create_by=sys_uid
        ))
        db.session.flush()

    sla = SlaPolicy.query.first()

    # Default work groups
    default_wg = [
        ('IT', 'IT-поддержка'),
        ('HR', 'Кадры'),
        ('Security', 'Безопасность'),
        ('AHO', 'АХО'),
        ('Finance', 'Бухгалтерия'),
    ]
    wg_map = {}
    for name, desc in default_wg:
        wg = WorkGroup.query.filter_by(group_name=name).first()
        if not wg:
            wg = WorkGroup(group_name=name, group_description=desc, create_by=sys_uid)
            db.session.add(wg)
            db.session.flush()
        wg_map[name] = wg.work_group_uid

    # Default service catalog categories
    icons = {'IT': 'monitor', 'HR': 'users', 'Security': 'shield', 'AHO': 'home', 'Finance': 'dollar-sign'}
    descs = {
        'IT': 'Техническая поддержка, оборудование и ПО',
        'HR': 'Вопросы по кадровому учёту, отпускам и документам',
        'Security': 'Вопросы информационной и физической безопасности',
        'AHO': 'Административно-хозяйственное обеспечение',
        'Finance': 'Финансовые вопросы, справки и документы',
    }
    display_names = {
        'IT': 'IT-услуги', 'HR': 'Кадры', 'Security': 'Безопасность',
        'AHO': 'АХО', 'Finance': 'Бухгалтерия'
    }
    for key, wg_uid in wg_map.items():
        if not ServiceCatalog.query.filter_by(catalog_path=f'/{key}').first():
            db.session.add(ServiceCatalog(
                catalog_name=display_names[key],
                catalog_path=f'/{key}',
                catalog_type='category',
                work_group_uid=wg_uid,
                sla_uid=sla.sla_uid,
                catalog_description=descs[key],
                catalog_icon=icons[key],
                create_by=sys_uid,
            ))

    db.session.commit()
    print('База данных инициализирована.')


# =========================================================================
# AUTH ROUTES
# =========================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/')

    if request.method == 'POST':
        login_val = request.form['login'].strip()
        password = request.form['password']

        user = User.query.filter_by(user_name=login_val).first()

        if not user or user.is_deactivated or user.is_temp_deactivated:
            return render_template('login.html', error='Неверный логин или пароль')

        pwd = user.password_record
        if not pwd or not pwd.passwordhash:
            return render_template('login.html', error='Ошибка аккаунта. Обратитесь к администратору')

        if not verify_password(user, password):
            pwd.failed_attempts = (pwd.failed_attempts or 0) + 1
            db.session.commit()
            if pwd.failed_attempts >= 3:
                pwd.must_change_password = True
                db.session.commit()
                return render_template('login.html',
                    error='Превышено количество попыток. Необходима смена пароля.',
                    show_forgot=True)
            left = 3 - pwd.failed_attempts
            return render_template('login.html',
                error=f'Неверный логин или пароль. Осталось попыток: {left}')

        pwd.failed_attempts = 0
        user.last_loggon_date = datetime.utcnow()
        db.session.commit()

        login_user(user)

        if pwd.is_first_login or pwd.must_change_password:
            return redirect('/change-password')

        return redirect('/')

    return render_template('login.html', error=None)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        password = request.form['password']
        confirm = request.form['confirm_password']

        if password != confirm:
            return render_template('change_password.html', error='Пароли не совпадают')
        if not is_strong_password(password):
            return render_template('change_password.html',
                error='Пароль должен содержать минимум 8 символов, заглавные и строчные буквы, цифру и спецсимвол')

        pwd = current_user.password_record
        pwd.passwordhash = generate_password_hash(password)
        pwd.is_first_login = False
        pwd.must_change_password = False
        pwd.failed_attempts = 0
        db.session.commit()

        flash('Пароль успешно изменён', 'success')
        return redirect('/')

    return render_template('change_password.html', error=None)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


# =========================================================================
# HOME
# =========================================================================

@app.route('/')
@login_required
def home():
    categories = ServiceCatalog.query.filter_by(
        catalog_type='category', parent_uid=None
    ).order_by(ServiceCatalog.catalog_name).all()
    return render_template('home.html', categories=categories)


# =========================================================================
# PROFILE
# =========================================================================

@app.route('/profile')
@login_required
def profile():
    tickets = Ticket.query.filter_by(
        requester_uid=current_user.user_uid
    ).order_by(Ticket.created_at.desc()).all()
    return render_template('profile.html', tickets=tickets)


@app.route('/profile/edit', methods=['POST'])
@login_required
def profile_edit():
    u = current_user
    u.first_name = request.form.get('first_name', u.first_name).strip() or u.first_name
    u.last_name = request.form.get('last_name', u.last_name).strip() or u.last_name
    u.middel_name = request.form.get('middle_name', '').strip() or u.middel_name
    u.mobile = format_mobile(request.form.get('mobile', '')) or u.mobile
    u.work_phone = request.form.get('work_phone', '').strip() or u.work_phone
    u.title = request.form.get('title', '').strip() or u.title
    u.update_date = datetime.utcnow()
    u.update_by = current_user.user_uid
    db.session.commit()
    flash('Профиль обновлён', 'success')
    return redirect('/profile')


# =========================================================================
# TICKETS API
# =========================================================================

@app.route('/api/tickets', methods=['POST'])
@login_required
def create_ticket():
    data = request.get_json()
    summary = (data.get('summary') or '').strip()
    description = (data.get('description') or '').strip()
    catalog_uid = data.get('catalog_uid')
    priority = data.get('priority', 'medium')
    ticket_type = data.get('ticket_type', 'service_request')

    if not summary or not description or not catalog_uid:
        return jsonify({'error': 'Заполните все обязательные поля'}), 400

    catalog = ServiceCatalog.query.get(catalog_uid)
    if not catalog:
        return jsonify({'error': 'Категория не найдена'}), 400

    ticket_number = generate_ticket_number()

    ticket = Ticket(
        ticket_number=ticket_number,
        catalog_uid=catalog_uid,
        summary=summary,
        description=description,
        requester_uid=current_user.user_uid,
        recipient_uid=current_user.user_uid,
        status='new',
        priority=priority,
        created_by=current_user.user_uid,
        updated_by=current_user.user_uid,
    )
    db.session.add(ticket)
    db.session.flush()

    add_ticket_history(ticket.ticket_uid, 'status', None, 'new', current_user.user_uid)

    # If request type — mark for approval
    if ticket_type in ('service_request', 'request'):
        db.session.add(TicketParamValue(
            ticket_uid=ticket.ticket_uid,
            param_name='requires_approval',
            param_value='true',
            param_type='approval_flag',
            author_uid=current_user.user_uid,
        ))

    db.session.commit()
    return jsonify({'success': True, 'ticket_number': ticket.ticket_number,
                    'ticket_uid': ticket.ticket_uid})


def _can_view_ticket(ticket):
    if current_user.role == 'admin':
        return True
    if ticket.requester_uid == current_user.user_uid:
        return True
    if is_specialist():
        my_wg_uids = _user_work_group_uids(current_user)
        if ticket.catalog and ticket.catalog.work_group_uid in my_wg_uids:
            return True
        if current_user.role == 'manager':
            return True
    return False


def _can_edit_ticket(ticket):
    if current_user.role == 'admin':
        return True
    if is_specialist():
        my_wg_uids = _user_work_group_uids(current_user)
        if ticket.catalog and ticket.catalog.work_group_uid in my_wg_uids:
            return True
        if current_user.role == 'manager':
            return True
    if ticket.requester_uid == current_user.user_uid and ticket.status == 'new':
        return True
    return False


@app.route('/api/tickets/<ticket_uid>', methods=['GET'])
@login_required
def get_ticket(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_view_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403

    # Comments: param_type='comment' or 'internal_comment'
    comments = []
    for pv in ticket.param_values.filter(
            TicketParamValue.param_type.in_(['comment', 'internal_comment'])
        ).order_by(TicketParamValue.create_date.asc()).all():
        if pv.param_type == 'internal_comment' and not is_specialist():
            continue
        comments.append({
            'author': pv.author_rel.full_name() if pv.author_rel else '—',
            'text': pv.param_value,
            'is_internal': pv.param_type == 'internal_comment',
            'created_at': pv.create_date.strftime('%d.%m.%Y %H:%M'),
        })

    # History
    history = []
    for h in ticket.history.order_by(TicketHistory.changed_date.asc()).all():
        history.append({
            'field': h.field_name,
            'old': h.old_value,
            'new': h.new_value,
            'by': h.changer.full_name() if h.changer else '—',
            'date': h.changed_date.strftime('%d.%m.%Y %H:%M'),
        })

    # Approval flag
    req_appr = ticket.param_values.filter_by(
        param_name='requires_approval', param_value='true').first() is not None
    appr_rec = ticket.param_values.filter_by(param_name='approval_decision').first()

    return jsonify({
        'ticket_uid': ticket.ticket_uid,
        'ticket_number': ticket.ticket_number,
        'summary': ticket.summary,
        'description': ticket.description,
        'status': ticket.status,
        'priority': ticket.priority,
        'catalog': ticket.catalog.catalog_name if ticket.catalog else '—',
        'catalog_path': ticket.catalog.catalog_path if ticket.catalog else '—',
        'requester': ticket.requester.full_name() if ticket.requester else '—',
        'performer': ticket.performer.full_name() if ticket.performer else None,
        'performer_uid': ticket.performer_uid,
        'created_at': ticket.created_at.strftime('%d.%m.%Y %H:%M'),
        'updated_at': ticket.updated_at.strftime('%d.%m.%Y %H:%M'),
        'resolved_at': ticket.resolved_at.strftime('%d.%m.%Y %H:%M') if ticket.resolved_at else None,
        'requires_approval': req_appr,
        'approval_decision': appr_rec.param_value if appr_rec else None,
        'approval_comment': appr_rec.param_name if appr_rec else None,
        'comments': comments,
        'history': history,
        'can_edit': _can_edit_ticket(ticket),
        'can_assign': current_user.role in ('admin', 'manager'),
        'can_approve': current_user.role in ('admin', 'manager') and req_appr,
    })


@app.route('/api/tickets/<ticket_uid>/update', methods=['POST'])
@login_required
def update_ticket(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_edit_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403

    data = request.get_json()
    action = data.get('action')
    now = datetime.utcnow()

    if action == 'take':
        if not is_specialist():
            return jsonify({'error': 'Только специалист может взять заявку'}), 403
        old_perf = ticket.performer_uid
        ticket.performer_uid = current_user.user_uid
        ticket.status = 'in_progress'
        add_ticket_history(ticket_uid, 'performer_uid', old_perf, current_user.user_uid, current_user.user_uid)
        add_ticket_history(ticket_uid, 'status', 'new', 'in_progress', current_user.user_uid)

    elif action == 'assign':
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'error': 'Недостаточно прав'}), 403
        new_perf = data.get('performer_uid')
        add_ticket_history(ticket_uid, 'performer_uid', ticket.performer_uid, new_perf, current_user.user_uid)
        ticket.performer_uid = new_perf or None
        ticket.status = 'assigned' if new_perf else 'new'
        add_ticket_history(ticket_uid, 'status', ticket.status, ticket.status, current_user.user_uid)

    elif action == 'status':
        new_status = data.get('status')
        allowed = ['new', 'assigned', 'in_progress', 'resolved', 'closed', 'cancelled']
        if new_status not in allowed:
            return jsonify({'error': 'Недопустимый статус'}), 400
        add_ticket_history(ticket_uid, 'status', ticket.status, new_status, current_user.user_uid)
        ticket.status = new_status
        if new_status == 'resolved':
            ticket.resolved_at = now
        if new_status == 'closed':
            ticket.closed_at = now

    elif action == 'approve':
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'error': 'Недостаточно прав'}), 403
        decision = data.get('decision')
        comment = data.get('comment', '')
        new_status = 'approved' if decision == 'approve' else 'rejected'
        add_ticket_history(ticket_uid, 'status', ticket.status, new_status, current_user.user_uid)
        ticket.status = new_status
        db.session.add(TicketParamValue(
            ticket_uid=ticket_uid,
            param_name='approval_decision',
            param_value=decision,
            param_type='approval',
            author_uid=current_user.user_uid,
        ))
        if comment:
            db.session.add(TicketParamValue(
                ticket_uid=ticket_uid,
                param_name='approval_comment',
                param_value=comment,
                param_type='internal_comment',
                author_uid=current_user.user_uid,
            ))

    elif action == 'edit':
        if ticket.requester_uid != current_user.user_uid and current_user.role not in ('admin', 'manager'):
            return jsonify({'error': 'Нельзя редактировать чужую заявку'}), 403
        if ticket.status not in ('new',) and current_user.role not in ('admin', 'manager'):
            return jsonify({'error': 'Заявку нельзя редактировать в текущем статусе'}), 400
        new_summary = (data.get('summary') or '').strip()
        new_desc = (data.get('description') or '').strip()
        if new_summary:
            add_ticket_history(ticket_uid, 'summary', ticket.summary, new_summary, current_user.user_uid)
            ticket.summary = new_summary
        if new_desc:
            add_ticket_history(ticket_uid, 'description', ticket.description[:50], new_desc[:50], current_user.user_uid)
            ticket.description = new_desc
        new_prio = data.get('priority')
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


@app.route('/api/tickets/<ticket_uid>/comment', methods=['POST'])
@login_required
def add_comment(ticket_uid):
    ticket = Ticket.query.get_or_404(ticket_uid)
    if not _can_view_ticket(ticket):
        return jsonify({'error': 'Доступ запрещён'}), 403

    data = request.get_json()
    text_val = (data.get('text') or '').strip()
    if not text_val:
        return jsonify({'error': 'Комментарий не может быть пустым'}), 400

    is_internal = data.get('is_internal', False) and is_specialist()
    ptype = 'internal_comment' if is_internal else 'comment'

    db.session.add(TicketParamValue(
        ticket_uid=ticket_uid,
        param_name='comment',
        param_value=text_val,
        param_type=ptype,
        author_uid=current_user.user_uid,
    ))
    ticket.updated_at = datetime.utcnow()
    ticket.updated_by = current_user.user_uid
    db.session.commit()

    return jsonify({
        'success': True,
        'comment': {
            'author': current_user.full_name(),
            'text': text_val,
            'is_internal': is_internal,
            'created_at': datetime.utcnow().strftime('%d.%m.%Y %H:%M'),
        }
    })


# =========================================================================
# TICKETS BOARD
# =========================================================================

@app.route('/tickets')
@login_required
def tickets_board():
    if not is_specialist():
        flash('Доступ запрещён', 'error')
        return redirect('/')

    query = Ticket.query.join(ServiceCatalog, Ticket.catalog_uid == ServiceCatalog.catalog_uid)

    if current_user.role != 'admin':
        my_wg_uids = _user_work_group_uids(current_user)
        query = query.filter(ServiceCatalog.work_group_uid.in_(my_wg_uids))

    fs = request.args.get('status', '')
    ft = request.args.get('type', '')
    fa = request.args.get('assignee', '')
    fd_from = request.args.get('date_from', '')
    fd_to = request.args.get('date_to', '')

    if fs:
        query = query.filter(Ticket.status == fs)
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
            query = query.filter(Ticket.created_at <= datetime.strptime(fd_to, '%Y-%m-%d'))
        except ValueError:
            pass

    tickets = query.order_by(Ticket.created_at.desc()).all()

    board = {
        'new': [t for t in tickets if t.status in ('new', 'assigned', 'pending_approval', 'approved', 'rejected')],
        'in_progress': [t for t in tickets if t.status == 'in_progress'],
        'done': [t for t in tickets if t.status in ('resolved', 'closed', 'cancelled')],
    }

    # Stats
    sq = Ticket.query.join(ServiceCatalog, Ticket.catalog_uid == ServiceCatalog.catalog_uid)
    if current_user.role != 'admin':
        my_wg_uids = _user_work_group_uids(current_user)
        sq = sq.filter(ServiceCatalog.work_group_uid.in_(my_wg_uids))

    stats = {
        'total': sq.count(),
        'new': sq.filter(Ticket.status == 'new').count(),
        'in_progress': sq.filter(Ticket.status == 'in_progress').count(),
        'resolved': sq.filter(Ticket.status == 'resolved').count(),
        'closed': sq.filter(Ticket.status == 'closed').count(),
        'cancelled': sq.filter(Ticket.status == 'cancelled').count(),
    }

    if current_user.role == 'admin':
        specialists = User.query.join(UserRole).filter(
            UserRole.role.in_(['specialist', 'manager', 'admin'])
        ).all()
    else:
        my_wg_uids = _user_work_group_uids(current_user)
        specialists = User.query.join(UserWorkGroup,
            User.user_uid == UserWorkGroup.user_uid).filter(
            UserWorkGroup.work_group_uid.in_(my_wg_uids)
        ).join(UserRole, User.user_uid == UserRole.user_uid).filter(
            UserRole.role.in_(['specialist', 'manager'])
        ).all()

    return render_template('tickets.html', board=board, stats=stats,
                           specialists=specialists,
                           filters={'status': fs, 'type': ft,
                                    'assignee': fa, 'date_from': fd_from, 'date_to': fd_to})


# =========================================================================
# ADMIN — USERS
# =========================================================================

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    users = User.query.order_by(User.last_name, User.first_name).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/create-user', methods=['GET', 'POST'])
@login_required
def create_user():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403

    work_groups = WorkGroup.query.filter_by(isactive=True).all()

    if request.method == 'POST':
        last_name = request.form['last_name'].strip()
        first_name = request.form['first_name'].strip()
        middle_name = request.form.get('middle_name', '').strip() or None
        email = request.form['email'].strip()
        mobile = request.form.get('mobile', '').strip() or None
        work_phone = request.form.get('work_phone', '').strip() or None
        gender = request.form.get('gender', '').strip() or None
        title = request.form.get('title', '').strip() or None
        department = request.form.get('department', '').strip() or None
        company = request.form.get('company', '').strip() or None
        role = request.form.get('role', 'user')
        work_group_uid = request.form.get('work_group_uid') or None

        if User.query.filter_by(email=email).first():
            return render_template('create_user.html', work_groups=work_groups,
                                   error='Пользователь с таким email уже существует')

        try:
            user_name, temp_password = create_user_db(
                last_name, first_name, middle_name, email, mobile,
                work_phone, gender, title, department, company,
                role=role, work_group_uid=work_group_uid,
                creator_uid=current_user.user_uid
            )
            return render_template('create_user.html', work_groups=work_groups,
                                   success=True, temp_login=user_name,
                                   temp_password=temp_password)
        except Exception as e:
            db.session.rollback()
            return render_template('create_user.html', work_groups=work_groups,
                                   error=f'Ошибка при создании: {e}')

    return render_template('create_user.html', work_groups=work_groups, error=None)


@app.route('/admin/edit-user/<user_uid>', methods=['GET', 'POST'])
@login_required
def edit_user(user_uid):
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    user = User.query.get_or_404(user_uid)
    work_groups = WorkGroup.query.filter_by(isactive=True).all()

    if request.method == 'POST':
        user.first_name = request.form.get('first_name', '').strip() or user.first_name
        user.last_name = request.form.get('last_name', '').strip() or user.last_name
        user.middel_name = request.form.get('middle_name', '').strip() or user.middel_name
        user.email = request.form.get('email', '').strip() or user.email
        user.mobile = format_mobile(request.form.get('mobile', '')) or user.mobile
        user.work_phone = request.form.get('work_phone', '').strip() or user.work_phone
        user.title = request.form.get('title', '').strip() or user.title
        user.department = request.form.get('department', '').strip() or user.department
        user.company = request.form.get('company', '').strip() or user.company
        user.is_deactivated = 'is_deactivated' in request.form
        user.update_date = datetime.utcnow()
        user.update_by = current_user.user_uid

        new_role = request.form.get('role', user.role)
        _ensure_role(user.user_uid, new_role)

        new_wg_uid = request.form.get('work_group_uid') or None
        if new_wg_uid:
            UserWorkGroup.query.filter_by(user_uid=user.user_uid).delete()
            _ensure_work_group(user.user_uid, new_wg_uid)

        db.session.commit()
        flash('Пользователь обновлён', 'success')
        return redirect('/admin/users')

    return render_template('edit_user.html', user=user, work_groups=work_groups)


@app.route('/admin/delete-user/<user_uid>', methods=['POST'])
@login_required
def delete_user(user_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    user = User.query.get_or_404(user_uid)
    if user.user_uid == current_user.user_uid:
        return jsonify({'error': 'Нельзя удалить себя'}), 400
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


# =========================================================================
# ADMIN — CATEGORIES & WORK GROUPS
# =========================================================================

@app.route('/admin/categories')
@login_required
def admin_categories():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    cats = ServiceCatalog.query.filter_by(parent_uid=None).order_by(ServiceCatalog.catalog_name).all()
    work_groups = WorkGroup.query.filter_by(isactive=True).all()
    return render_template('admin_categories.html', categories=cats, work_groups=work_groups)


@app.route('/admin/create-category', methods=['GET', 'POST'])
@login_required
def create_category():
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    work_groups = WorkGroup.query.filter_by(isactive=True).all()

    if request.method == 'POST':
        name = request.form['catalog_name'].strip()
        desc = request.form.get('catalog_description', '').strip() or None
        icon = request.form.get('catalog_icon', 'briefcase')
        wg_uid = request.form.get('work_group_uid') or None
        path = f"/{name.replace(' ', '_')}"

        if ServiceCatalog.query.filter_by(catalog_name=name, parent_uid=None).first():
            return render_template('create_category.html', work_groups=work_groups,
                                   error='Категория с таким названием уже существует')

        db.session.add(ServiceCatalog(
            catalog_name=name, catalog_path=path, catalog_type='category',
            catalog_description=desc, catalog_icon=icon, work_group_uid=wg_uid,
            create_by=current_user.user_uid,
        ))
        db.session.commit()
        flash('Категория создана', 'success')
        return redirect('/admin/categories')

    return render_template('create_category.html', work_groups=work_groups, error=None)


@app.route('/admin/edit-category/<cat_uid>', methods=['GET', 'POST'])
@login_required
def edit_category(cat_uid):
    if current_user.role != 'admin':
        return 'Доступ запрещён', 403
    cat = ServiceCatalog.query.get_or_404(cat_uid)
    work_groups = WorkGroup.query.filter_by(isactive=True).all()

    if request.method == 'POST':
        cat.catalog_name = request.form.get('catalog_name', '').strip() or cat.catalog_name
        cat.catalog_description = request.form.get('catalog_description', '').strip() or cat.catalog_description
        cat.catalog_icon = request.form.get('catalog_icon', cat.catalog_icon)
        cat.work_group_uid = request.form.get('work_group_uid') or cat.work_group_uid
        cat.update_date = datetime.utcnow()
        cat.update_by = current_user.user_uid
        db.session.commit()
        flash('Категория обновлена', 'success')
        return redirect('/admin/categories')

    return render_template('edit_category.html', cat=cat, work_groups=work_groups)


@app.route('/admin/delete-category/<cat_uid>', methods=['POST'])
@login_required
def delete_category(cat_uid):
    if current_user.role != 'admin':
        return jsonify({'error': 'Доступ запрещён'}), 403
    cat = ServiceCatalog.query.get_or_404(cat_uid)
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True})


# =========================================================================
# ADMIN — WORK GROUPS
# =========================================================================

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
    data = request.get_json()
    name = (data.get('group_name') or '').strip()
    desc = (data.get('group_description') or '').strip() or None
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400
    if WorkGroup.query.filter_by(group_name=name).first():
        return jsonify({'error': 'Группа с таким названием уже существует'}), 400
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


# =========================================================================
# API — SPECIALISTS
# =========================================================================

@app.route('/api/specialists')
@login_required
def get_specialists():
    if not is_specialist():
        return jsonify({'error': 'Доступ запрещён'}), 403

    if current_user.role == 'admin':
        users = User.query.join(UserRole).filter(
            UserRole.role.in_(['specialist', 'manager', 'admin'])
        ).all()
    else:
        my_wg_uids = _user_work_group_uids(current_user)
        users = User.query.join(UserWorkGroup,
            User.user_uid == UserWorkGroup.user_uid).filter(
            UserWorkGroup.work_group_uid.in_(my_wg_uids)
        ).join(UserRole, User.user_uid == UserRole.user_uid).filter(
            UserRole.role.in_(['specialist', 'manager'])
        ).all()

    return jsonify([{
        'user_uid': u.user_uid,
        'full_name': u.full_name(),
        'role': u.role
    } for u in users])


# =========================================================================
# RUN
# =========================================================================

if __name__ == '__main__':
    app.run(debug=True)
