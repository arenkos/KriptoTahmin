from flask import Flask
from config import Config
from app.extensions import db, login_manager

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Lütfen giriş yapın.'
    login_manager.login_message_category = 'info'

    from app.models.database import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes import auth, main, trading
    from app.routes.analysis import analysis_bp
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(trading.bp)
    app.register_blueprint(analysis_bp)

    with app.app_context():
        db.create_all()

    return app 