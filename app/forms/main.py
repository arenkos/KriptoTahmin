from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from config import Config

class TradingSettingsForm(FlaskForm):
    symbol = SelectField('Kripto Para', choices=[(s, s) for s in Config.DEFAULT_SYMBOLS], validators=[DataRequired()])
    timeframe = SelectField('Zaman Dilimi', choices=[(t, t) for t in Config.DEFAULT_TIMEFRAMES], validators=[DataRequired()])
    leverage = FloatField('Kaldıraç', validators=[DataRequired(), NumberRange(min=1, max=Config.MAX_LEVERAGE)])
    stop_loss = FloatField('Stop Loss (%)', validators=[DataRequired(), NumberRange(min=Config.MIN_STOP_LOSS, max=Config.MAX_STOP_LOSS)])
    take_profit = FloatField('Take Profit (%)', validators=[DataRequired(), NumberRange(min=Config.MIN_TAKE_PROFIT, max=Config.MAX_TAKE_PROFIT)])
    submit = SubmitField('Kaydet')

class APISettingsForm(FlaskForm):
    api_key = StringField('API Anahtarı', validators=[DataRequired()])
    api_secret = StringField('API Gizli Anahtarı', validators=[DataRequired()])
    submit = SubmitField('Kaydet') 