from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from core.models import db, User, OAuthConfig, Group
from functools import wraps
from authlib.integrations.flask_client import OAuth

bp = Blueprint('auth', __name__, template_folder='templates')

# Initialize OAuth
oauth = OAuth()

def get_google_oauth_config():
    """Fetch Google OAuth config from database."""
    config = OAuthConfig.query.filter_by(provider='google').first()
    if config and config.enabled and config.client_id and config.client_secret:
        return {
            'client_id': config.client_id,
            'client_secret': config.client_secret,
            'hd': config.hd
        }
    return None

def init_oauth(app):
    """Initialize OAuth with app context and dynamic config."""
    oauth.init_app(app)
    
    def register_google():
        config = get_google_oauth_config()
        if config:
            if not hasattr(oauth, 'google') or oauth.google is None:
                oauth.register(
                    name='google',
                    client_id=config['client_id'],
                    client_secret=config['client_secret'],
                    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                    client_kwargs={
                        'scope': 'openid email profile',
                        'hd': config.get('hd')
                    }
                )
    
    app.before_request(register_google)

def superuser_required(f):
    """Decorator for superuser-only routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superuser():
            flash("Superuser access required.", "danger")
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator for admin or superuser routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Admin access required.", "danger")
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def engineer_required(f):
    """Decorator for engineer, admin, or superuser routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_engineer():
            flash("Engineer access required.", "danger")
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard.index'))
        flash("Invalid email or password.", "danger")
    return render_template('auth/login.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@bp.route('/google-setup')
@superuser_required
def google_setup():
    config = OAuthConfig.query.filter_by(provider='google').first()
    return render_template('auth/google_setup.html', config=config)

@bp.route('/save-google-config', methods=['POST'])
@superuser_required
def save_google_config():
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()
    hd = request.form.get('hd', '').strip() or None
    
    config = OAuthConfig.query.filter_by(provider='google').first()
    is_new = config is None
    
    if is_new:
        if not client_id or not client_secret:
            flash("Client ID and Client Secret are required.", "danger")
            return redirect(url_for('auth.google_setup'))
        config = OAuthConfig(provider='google')
        db.session.add(config)
    else:
        if not client_id:
            flash("Client ID is required.", "danger")
            return redirect(url_for('auth.google_setup'))
    
    config.client_id = client_id
    if client_secret:
        config.client_secret = client_secret
    config.hd = hd
    config.enabled = True
    
    try:
        db.session.commit()
        flash("Google OAuth configuration saved successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error saving configuration: {str(e)}", "danger")
    
    return redirect(url_for('auth.google_setup'))

@bp.route('/login/google')
def google_login():
    """Initiate Google OAuth login."""
    config = get_google_oauth_config()
    if not config:
        flash("Google authentication is not configured. Please contact your administrator.", "danger")
        return redirect(url_for('auth.login'))
    
    redirect_uri = url_for('auth.google_callback', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri)

@bp.route('/auth/callback')
def google_callback():
    """Handle Google OAuth callback."""
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if not user_info:
            flash("Failed to get user information from Google.", "danger")
            return redirect(url_for('auth.login'))
        
        email = user_info.get('email')
        google_id = user_info.get('sub')
        
        if not email or not google_id:
            flash("Invalid user information received from Google.", "danger")
            return redirect(url_for('auth.login'))
        
        config = OAuthConfig.query.filter_by(provider='google').first()
        if config and config.hd:
            email_domain = email.split('@')[1] if '@' in email else ''
            if email_domain != config.hd:
                flash(f"Access denied. Only {config.hd} users can log in.", "danger")
                return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                existing_user.google_id = google_id
                db.session.commit()
                user = existing_user
            else:
                user = User(
                    email=email,
                    google_id=google_id,
                    role='user'
                )
                db.session.add(user)
                db.session.commit()
                
                # Assign new Google users to engineer group by default
                engineer_group = Group.query.filter_by(name='engineer').first()
                if engineer_group and engineer_group not in user.groups:
                    user.groups.append(engineer_group)
                    db.session.commit()
        
        login_user(user)
        flash("Successfully logged in with Google!", "success")
        return redirect(url_for('dashboard.index'))
        
    except Exception as e:
        flash(f"Authentication failed: {str(e)}", "danger")
        return redirect(url_for('auth.login'))

@bp.route('/users-groups')
@superuser_required
def manage_users_groups():
    """View and manage users and groups."""
    users = User.query.all()
    groups = Group.query.all()
    return render_template('auth/users_groups.html', users=users, groups=groups)

@bp.route('/create-group', methods=['POST'])
@superuser_required
def create_group():
    """Create a new group."""
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    
    if not name:
        flash("Group name is required.", "danger")
        return redirect(url_for('auth.manage_users_groups'))
    
    # Prevent creating reserved group names
    if name.lower() in ['superuser', 'admin', 'engineer']:
        flash("Cannot create group with reserved name.", "danger")
        return redirect(url_for('auth.manage_users_groups'))
    
    existing = Group.query.filter_by(name=name).first()
    if existing:
        flash("Group already exists.", "danger")
        return redirect(url_for('auth.manage_users_groups'))
    
    group = Group(name=name, description=description)
    db.session.add(group)
    try:
        db.session.commit()
        flash(f"Group '{name}' created successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error creating group: {str(e)}", "danger")
    
    return redirect(url_for('auth.manage_users_groups'))

@bp.route('/add-user-to-group', methods=['POST'])
@superuser_required
def add_user_to_group():
    """Add a user to a group."""
    user_id = request.form.get('user_id', type=int)
    group_id = request.form.get('group_id', type=int)
    
    user = User.query.get_or_404(user_id)
    group = Group.query.get_or_404(group_id)
    
    if group in user.groups:
        flash(f"User already in group '{group.name}'.", "warning")
    else:
        user.groups.append(group)
        db.session.commit()
        flash(f"User '{user.email}' added to group '{group.name}'.", "success")
    
    return redirect(url_for('auth.manage_users_groups'))

@bp.route('/remove-user-from-group', methods=['POST'])
@superuser_required
def remove_user_from_group():
    """Remove a user from a group."""
    user_id = request.form.get('user_id', type=int)
    group_id = request.form.get('group_id', type=int)
    
    user = User.query.get_or_404(user_id)
    group = Group.query.get_or_404(group_id)
    
    if group not in user.groups:
        flash(f"User not in group '{group.name}'.", "warning")
    else:
        user.groups.remove(group)
        db.session.commit()
        flash(f"User '{user.email}' removed from group '{group.name}'.", "success")
    
    return redirect(url_for('auth.manage_users_groups'))

@bp.route('/users/toggle-role/<int:user_id>', methods=['POST'])
@admin_required
def toggle_role(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return "Cannot change your own role", 400
        
    user.role = 'admin' if user.role == 'user' else 'user'
    db.session.commit()
    
    color = "pf-m-purple" if user.role == 'admin' else "pf-m-blue"
    return f'<span class="pf-v5-c-label {color}">{user.role}</span>'
