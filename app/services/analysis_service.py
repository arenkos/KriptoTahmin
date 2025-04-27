from app.extensions import db
from app.models.analysis import AnalysisResult
from sqlalchemy import desc
import numpy as np
from datetime import datetime, timedelta

class AnalysisService:
    @staticmethod
    def get_active_analysis(symbol, timeframe):
        """Belirli bir sembol ve zaman dilimi için aktif analiz sonucunu getirir."""
        return AnalysisResult.query.filter_by(
            symbol=symbol,
            timeframe=timeframe,
            is_active=True
        ).first()

    @staticmethod
    def save_analysis_result(symbol, timeframe, results):
        """Yeni analiz sonucunu kaydeder ve eski sonucu deaktif eder."""
        # Eski sonucu deaktif et
        old_result = AnalysisResult.query.filter_by(
            symbol=symbol,
            timeframe=timeframe,
            is_active=True
        ).first()
        
        if old_result:
            old_result.is_active = False
            db.session.add(old_result)

        # Yeni sonucu kaydet
        new_result = AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            leverage=results['leverage'],
            stop_percentage=results['stop_percentage'],
            success_rate=results['success_rate'],
            profit_rate=results['profit_rate'],
            successful_trades=results['successful_trades'],
            unsuccessful_trades=results['unsuccessful_trades'],
            final_balance=results['final_balance'],
            atr_period=results['atr_period'],
            atr_multiplier=results['atr_multiplier'],
            total_trades=results['total_trades'],
            win_rate=results['win_rate'],
            average_win=results['average_win'],
            average_loss=results['average_loss'],
            max_drawdown=results['max_drawdown'],
            risk_reward_ratio=results['risk_reward_ratio'],
            sharpe_ratio=results['sharpe_ratio'],
            is_active=True
        )
        
        db.session.add(new_result)
        db.session.commit()
        return new_result

    @staticmethod
    def get_all_active_analyses():
        """Tüm aktif analiz sonuçlarını getirir."""
        return AnalysisResult.query.filter_by(is_active=True).all()

    @staticmethod
    def should_update_analysis(symbol, timeframe):
        """Analizin güncellenmesi gerekip gerekmediğini kontrol eder."""
        last_analysis = AnalysisService.get_active_analysis(symbol, timeframe)
        if not last_analysis:
            return True
        
        # Son 24 saat içinde güncellenmişse False döner
        return datetime.utcnow() - last_analysis.analysis_date > timedelta(hours=24)

    @staticmethod
    def calculate_performance_metrics(trades):
        """İşlem performans metriklerini hesaplar."""
        if not trades:
            return {
                'win_rate': 0,
                'average_win': 0,
                'average_loss': 0,
                'max_drawdown': 0,
                'risk_reward_ratio': 0,
                'sharpe_ratio': 0
            }

        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]
        
        win_rate = len(wins) / len(trades) if trades else 0
        average_win = np.mean(wins) if wins else 0
        average_loss = abs(np.mean(losses)) if losses else 0
        
        # Maximum Drawdown hesaplama
        cumulative = np.cumsum(trades)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_drawdown = np.max(drawdowns)
        
        # Risk/Reward Ratio
        risk_reward_ratio = average_win / average_loss if average_loss != 0 else 0
        
        # Sharpe Ratio (basitleştirilmiş)
        returns = np.array(trades)
        sharpe_ratio = np.mean(returns) / np.std(returns) if len(returns) > 1 else 0
        
        return {
            'win_rate': win_rate * 100,
            'average_win': average_win,
            'average_loss': average_loss,
            'max_drawdown': max_drawdown,
            'risk_reward_ratio': risk_reward_ratio,
            'sharpe_ratio': sharpe_ratio
        }

    @staticmethod
    def get_best_parameters(symbol, timeframe):
        """En iyi parametre kombinasyonunu döndürür."""
        result = AnalysisService.get_active_analysis(symbol, timeframe)
        if result:
            return {
                'leverage': result.leverage,
                'stop_percentage': result.stop_percentage,
                'atr_period': result.atr_period,
                'atr_multiplier': result.atr_multiplier
            }
        return None

    @staticmethod
    def get_results_by_timeframe(timeframe):
        """Belirli bir zaman dilimi için analiz sonuçlarını getirir."""
        return AnalysisResult.query.filter_by(
            timeframe=timeframe
        ).order_by(desc(AnalysisResult.created_at)).first()

    @staticmethod
    def save_result(symbol, timeframe, leverage, stop_percentage, 
                   success_rate, profit_rate, successful_trades, 
                   unsuccessful_trades, final_balance):
        """Analiz sonucunu veritabanına kaydeder."""
        result = AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            leverage=leverage,
            stop_percentage=stop_percentage,
            success_rate=success_rate,
            profit_rate=profit_rate,
            successful_trades=successful_trades,
            unsuccessful_trades=unsuccessful_trades,
            final_balance=final_balance
        )
        db.session.add(result)
        db.session.commit()
        return result

    @staticmethod
    def get_top_results(limit=10):
        """En karlı sonuçları getirir."""
        return AnalysisResult.query.order_by(
            desc(AnalysisResult.profit_rate)
        ).limit(limit).all()

    @staticmethod
    def get_results_by_symbol(symbol):
        """Belirli bir sembol için sonuçları getirir."""
        return AnalysisResult.query.filter_by(
            symbol=symbol
        ).order_by(desc(AnalysisResult.profit_rate)).all()

    @staticmethod
    def get_supported_symbols():
        """Desteklenen sembollerin listesini getirir."""
        return db.session.query(AnalysisResult.symbol).distinct().all()

    @staticmethod
    def delete_result(result_id):
        """Belirli bir analiz sonucunu siler."""
        result = AnalysisResult.query.get(result_id)
        if result:
            db.session.delete(result)
            db.session.commit()
            return True
        return False 