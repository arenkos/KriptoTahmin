from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, IntegerField, FloatField
from wtforms.validators import DataRequired, NumberRange

class TradingSettingsForm(FlaskForm):
    symbol = StringField('Kripto Para Çifti', validators=[DataRequired()])
    timeframe = SelectField('Zaman Dilimi', 
        choices=[
            ('1m', '1 Dakika'),
            ('3m', '3 Dakika'),
            ('5m', '5 Dakika'),
            ('15m', '15 Dakika'),
            ('30m', '30 Dakika'),
            ('1h', '1 Saat'),
            ('2h', '2 Saat'),
            ('4h', '4 Saat'),
            ('1d', '1 Gün'),
            ('1w', '1 Hafta')
        ],
        validators=[DataRequired()]
    )
    leverage = IntegerField('Kaldıraç', 
        validators=[DataRequired(), NumberRange(min=1, max=125)],
        default=1
    )
    stop_loss = FloatField('Stop Loss (%)', 
        validators=[DataRequired(), NumberRange(min=0.1, max=100)],
        default=1.0
    )
    take_profit = FloatField('Take Profit (%)', 
        validators=[DataRequired(), NumberRange(min=0.1, max=1000)],
        default=2.0
    ) 