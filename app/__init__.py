from flask import Flask
from config import Config
from app.extensions import db, login_manager
from flask_migrate import Migrate

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Lütfen giriş yapın.'
    login_manager.login_message_category = 'info'

    migrate = Migrate(app, db)

    from app.models.database import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes import auth, main, trading
    from app.routes.analysis import analysis_bp
    from app.routes.backtest import backtest_bp
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(trading.bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(backtest_bp)

    with app.app_context():
        db.create_all()

    return app 