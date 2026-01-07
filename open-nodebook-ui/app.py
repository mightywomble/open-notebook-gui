import os
import sys
import importlib
from flask import Flask
from flask_login import LoginManager

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.models import db, User, OAuthConfig, Group, CompanyConfig
from config import Config

def create_app():
    """Application Factory to initialize the UI and load modular features."""
    app = Flask(__name__, 
                template_folder='core/templates', 
                static_folder='core/static')
    
    app.config.from_object(Config)
    
    db.init_app(app)


    @app.context_processor
    def inject_company_config():
        cfg = CompanyConfig.query.first()
        if not cfg:
            return {'company_name': 'Cudo', 'company_icon_url': None, 'company_config': None}

        icon_url = None
        if cfg.icon_path:
            from flask import url_for
            icon_url = url_for('static', filename=cfg.icon_path)

        return {
            'company_name': cfg.company_name or 'Cudo',
            'company_icon_url': icon_url,
            'company_config': cfg,
        }

    # --- Authentication Setup ---
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    # ---------------------------------------

    with app.app_context():
        try:
            db.create_all()
            print("[*] Database connection successful and tables verified.")
            

            # Seed company config singleton
            company_cfg = CompanyConfig.query.first()
            if not company_cfg:
                company_cfg = CompanyConfig(company_name='Cudo', icon_path=None)
                db.session.add(company_cfg)
                db.session.commit()
                print("[*] Initialized company config.")

            # Seed default groups
            for group_name, desc in [
                ('superuser', 'Full system access including all settings'),
                ('admin', 'Administrative access except Google OAuth setup'),
                ('engineer', 'Limited access to knowledge base features'),
                ('team-manager', 'Can approve/reject KB items and manage internal/customer publishing')
            ]:
                group = Group.query.filter_by(name=group_name).first()
                if not group:
                    group = Group(name=group_name, description=desc)
                    db.session.add(group)
                    print(f"[*] Created group: {group_name}")
            
            db.session.commit()
            
            # Seed the Admin user automatically if it doesn't exist
            admin = User.query.filter_by(email='admin@local.com').first()
            superuser_group = Group.query.filter_by(name='superuser').first()
            
            if not admin:
                admin = User(email='admin@local.com', role='admin')
                admin.set_password('Qw3rty123?')
                db.session.add(admin)
                db.session.commit()
                print("[*] Default admin user initialized.")
            
            # Ensure admin is in superuser group
            if superuser_group and superuser_group not in admin.groups:
                admin.groups.append(superuser_group)
                db.session.commit()
                print("[*] Admin user added to superuser group.")
                
        except Exception as e:
            print(f"[!] Database initialization error: {e}")

    # Automatic Module Discovery
    features_dir = os.path.join(os.path.dirname(__file__), 'features')
    
    if os.path.exists(features_dir):
        for module_name in os.listdir(features_dir):
            module_path = os.path.join(features_dir, module_name)
            
            if os.path.isdir(module_path) and os.path.exists(os.path.join(module_path, 'routes.py')):
                try:
                    feature_module = importlib.import_module(f'features.{module_name}.routes')
                    
                    if hasattr(feature_module, 'bp'):
                        app.register_blueprint(feature_module.bp)
                        print(f"[*] Successfully loaded feature: {module_name}")
                        
                        if module_name == 'auth' and hasattr(feature_module, 'init_oauth'):
                            feature_module.init_oauth(app)
                            print("[*] OAuth initialized for Google authentication")
                            
                except Exception as e:
                    print(f"[!] Failed to load feature '{module_name}': {e}")

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
