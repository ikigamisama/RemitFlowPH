import json
from datetime import datetime, timedelta
from typing import Dict, List
import redis
import psycopg2
from kafka import KafkaConsumer, KafkaProducer


class FraudDetector:
    def __init__(self, kafka_servers, postgres_config, redis_config):
        self.consumer = KafkaConsumer(
            'remittance-transactions',
            bootstrap_servers=kafka_servers,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='fraud-detection-processor',
            auto_offset_reset='latest'
        )

        self.producer = KafkaProducer(
            bootstrap_servers=kafka_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

        self.redis_client = redis.Redis(**redis_config, decode_responses=True)
        self.db_conn = psycopg2.connect(**postgres_config)

        # Fraud detection rules
        self.rules = {
            # 5 txns in 24h
            'velocity_check_24h': {'threshold': 5, 'window': 86400},
            # 3 txns in 1h
            'velocity_check_1h': {'threshold': 3, 'window': 3600},
            # 3x typical amount
            'amount_anomaly': {'multiplier': 3.0},
            'large_transaction': {'threshold': 50000},
            # 5 min between txns
            'rapid_succession': {'threshold': 300},
        }

    def get_sender_history(self, sender_id: str, window_seconds: int) -> List[Dict]:
        # Get recent transactions for sender from Redis cache
        key = f"sender_history:{sender_id}"

        cached = self.redis_client.get(key)
        if cached:
            history = json.loads(cached)
            cutoff = datetime.utcnow().timestamp() - window_seconds
            return [t for t in history if t['timestamp'] > cutoff]

        cursor = self.db_conn.cursor()
        cursor.execute("""
            SELECT transaction_id, timestamp, send_amount, send_currency
            FROM transactions
            WHERE sender_id = %s 
            AND timestamp > NOW() - INTERVAL '%s seconds'
            ORDER BY timestamp DESC
        """, (sender_id, window_seconds))

        history = []
        for row in cursor.fetchall():
            history.append({
                'transaction_id': row[0],
                'timestamp': row[1].timestamp(),
                'amount': float(row[2]),
                'currency': row[3]
            })

        cursor.close()

        # Cache for future use (expire after 1 hour)
        self.redis_client.setex(key, 3600, json.dumps(history))

        return history

    def get_sender_profile(self, sender_id: str) -> Dict:
        # Get sender profile from database
        cursor = self.db_conn.cursor()
        cursor.execute("""
            SELECT average_transaction_usd, transaction_frequency_days, 
                   risk_score, txn_count_24h
            FROM sender_profiles
            WHERE sender_id = %s
        """, (sender_id,))

        row = cursor.fetchone()
        cursor.close()

        if row:
            return {
                'average_transaction': float(row[0]) if row[0] else 500,
                'frequency_days': float(row[1]) if row[1] else 14,
                'risk_score': float(row[2]) if row[2] else 0.1,
                'txn_count_24h': int(row[3]) if row[3] else 0
            }

        return {
            'average_transaction': 500,
            'frequency_days': 14,
            'risk_score': 0.1,
            'txn_count_24h': 0
        }

    def check_velocity(self, transaction: Dict) -> Dict:
        # Check transaction velocity rules
        sender_id = transaction['sender']['sender_id']
        alerts = []

        # 24-hour velocity check
        history_24h = self.get_sender_history(
            sender_id, self.rules['velocity_check_24h']['window'])
        if len(history_24h) >= self.rules['velocity_check_24h']['threshold']:
            alerts.append({
                'rule': 'velocity_check_24h',
                'severity': 'medium',
                'description': f"Sender has {len(history_24h)} transactions in 24h (threshold: {self.rules['velocity_check_24h']['threshold']})",
                'threshold': self.rules['velocity_check_24h']['threshold'],
                'actual_value': len(history_24h)
            })

        # 1-hour velocity check
        history_1h = self.get_sender_history(
            sender_id, self.rules['velocity_check_1h']['window'])
        if len(history_1h) >= self.rules['velocity_check_1h']['threshold']:
            alerts.append({
                'rule': 'velocity_check_1h',
                'severity': 'high',
                'description': f"Sender has {len(history_1h)} transactions in 1h (threshold: {self.rules['velocity_check_1h']['threshold']})",
                'threshold': self.rules['velocity_check_1h']['threshold'],
                'actual_value': len(history_1h)
            })

        # Rapid succession check
        if len(history_1h) > 0:
            last_txn_time = max([t['timestamp'] for t in history_1h])
            current_time = datetime.utcnow().timestamp()
            time_diff = current_time - last_txn_time

            if time_diff < self.rules['rapid_succession']['threshold']:
                alerts.append({
                    'rule': 'rapid_succession',
                    'severity': 'medium',
                    'description': f"Transaction within {int(time_diff)}s of previous (threshold: {self.rules['rapid_succession']['threshold']}s)",
                    'threshold': self.rules['rapid_succession']['threshold'],
                    'actual_value': int(time_diff)
                })

        return alerts

    def check_amount_anomaly(self, transaction: Dict) -> Dict:
        # Check for unusual transaction amounts
        sender_id = transaction['sender']['sender_id']
        amount = transaction['amount']['send_amount']

        profile = self.get_sender_profile(sender_id)
        typical_amount = profile['average_transaction']

        alerts = []

        # Amount anomaly check
        if amount > typical_amount * self.rules['amount_anomaly']['multiplier']:
            alerts.append({
                'rule': 'amount_anomaly',
                'severity': 'high',
                'description': f"Amount ${amount:.2f} is {amount/typical_amount:.1f}x typical ${typical_amount:.2f}",
                'threshold': typical_amount * self.rules['amount_anomaly']['multiplier'],
                'actual_value': amount
            })

        # Large transaction check
        if amount >= self.rules['large_transaction']['threshold']:
            alerts.append({
                'rule': 'large_transaction',
                'severity': 'medium',
                'description': f"Large transaction: ${amount:.2f} (threshold: ${self.rules['large_transaction']['threshold']})",
                'threshold': self.rules['large_transaction']['threshold'],
                'actual_value': amount
            })

        return alerts

    def check_geographic_anomaly(self, transaction: Dict) -> Dict:
        # Check for unusual geographic patterns
        alerts = []

        sender_id = transaction['sender']['sender_id']
        origin_country = transaction['origin']['country']

        return alerts

    def calculate_fraud_score(self, alerts: List[Dict]) -> float:
        # Calculate overall fraud score based on alerts
        if not alerts:
            return 0.0

        severity_weights = {
            'low': 0.1,
            'medium': 0.3,
            'high': 0.6,
            'critical': 1.0
        }

        total_score = sum(severity_weights.get(
            alert['severity'], 0.1) for alert in alerts)
        normalized_score = min(total_score / 2.0, 1.0)  # Normalize to 0-1

        return round(normalized_score, 4)

    def determine_action(self, fraud_score: float, alerts: List[Dict]) -> Dict:
        # Determine what action to take based on fraud score
        if fraud_score >= 0.8:
            return {
                'recommended_action': 'auto_block',
                'auto_action_taken': 'blocked',
                'verification_required': True
            }
        elif fraud_score >= 0.5:
            return {
                'recommended_action': 'manual_review',
                'auto_action_taken': 'flagged_for_review',
                'verification_required': True
            }
        elif fraud_score >= 0.3:
            return {
                'recommended_action': 'enhanced_monitoring',
                'auto_action_taken': 'monitored',
                'verification_required': False
            }
        else:
            return {
                'recommended_action': 'none',
                'auto_action_taken': 'approved',
                'verification_required': False
            }

    def create_fraud_alert(self, transaction: Dict, alerts: List[Dict], fraud_score: float) -> Dict:
        # Create a fraud alert
        action = self.determine_action(fraud_score, alerts)

        alert = {
            'alert_id': f"ALERT_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{transaction['transaction_id'][-6:]}",
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'transaction_id': transaction['transaction_id'],
            'alert_type': alerts[0]['rule'] if alerts else 'unknown',
            'severity': max([a['severity'] for a in alerts], key=lambda s: ['low', 'medium', 'high', 'critical'].index(s)) if alerts else 'low',
            'details': {
                'rules_triggered': [a['rule'] for a in alerts],
                'alerts': alerts,
                'description': f"{len(alerts)} fraud rules triggered"
            },
            'sender_id': transaction['sender']['sender_id'],
            'fraud_score': fraud_score,
            'recommended_action': action['recommended_action'],
            'auto_action_taken': action['auto_action_taken'],
            'context': {
                'sender_history': self.get_sender_profile(transaction['sender']['sender_id'])
            },
            'status': 'open',
            'assigned_to': None,
            'resolution_notes': None
        }

        return alert

    def save_fraud_alert(self, alert: Dict):
        # Save fraud alert to database
        try:
            cursor = self.db_conn.cursor()

            sql = """
                INSERT INTO fraud_alerts (
                    alert_id, timestamp, transaction_id, alert_type, severity,
                    rule_triggered, threshold, actual_value, description,
                    sender_id, fraud_score, recommended_action, auto_action_taken,
                    context, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            first_alert = alert['details']['alerts'][0] if alert['details']['alerts'] else {
            }

            cursor.execute(sql, (
                alert['alert_id'],
                alert['timestamp'],
                alert['transaction_id'],
                alert['alert_type'],
                alert['severity'],
                first_alert.get('rule', 'unknown'),
                first_alert.get('threshold', 0),
                first_alert.get('actual_value', 0),
                alert['details']['description'],
                alert['sender_id'],
                alert['fraud_score'],
                alert['recommended_action'],
                alert['auto_action_taken'],
                json.dumps(alert['context']),
                alert['status']
            ))

            self.db_conn.commit()
            cursor.close()

            print(f"Saved fraud alert: {alert['alert_id']}")
        except Exception as e:
            print(f"Failed to save fraud alert: {e}")
            self.db_conn.rollback()

    def update_transaction_fraud_info(self, transaction_id: str, fraud_score: float,
                                      is_flagged: bool, verification_required: bool):
        # Update transaction with fraud detection results
        try:
            cursor = self.db_conn.cursor()

            sql = """
                UPDATE transactions
                SET fraud_score = %s,
                    is_flagged = %s,
                    verification_required = %s,
                    risk_level = CASE
                        WHEN %s >= 0.7 THEN 'high'
                        WHEN %s >= 0.4 THEN 'medium'
                        ELSE 'low'
                    END
                WHERE transaction_id = %s
            """

            cursor.execute(sql, (
                fraud_score, is_flagged, verification_required,
                fraud_score, fraud_score, transaction_id
            ))

            self.db_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Failed to update transaction: {e}")
            self.db_conn.rollback()

    def process_transaction(self, transaction: Dict):
        # Main fraud detection pipeline
        try:
            velocity_alerts = self.check_velocity(transaction)
            amount_alerts = self.check_amount_anomaly(transaction)
            geo_alerts = self.check_geographic_anomaly(transaction)

            all_alerts = velocity_alerts + amount_alerts + geo_alerts
            fraud_score = self.calculate_fraud_score(all_alerts)

            is_flagged = fraud_score >= 0.5
            verification_required = fraud_score >= 0.5

            self.update_transaction_fraud_info(
                transaction['transaction_id'],
                fraud_score,
                is_flagged,
                verification_required
            )

            if is_flagged:
                alert = self.create_fraud_alert(
                    transaction, all_alerts, fraud_score)

                self.save_fraud_alert(alert)

                self.producer.send('fraud-alerts', value=alert)
                self.producer.flush()

                print(
                    f"Fraud alert created: {alert['alert_id']} (score: {fraud_score:.4f})")
            else:
                print(
                    f"Transaction {transaction['transaction_id']} passed fraud checks (score: {fraud_score:.4f})")

            sender_id = transaction['sender']['sender_id']
            key = f"sender_history:{sender_id}"
            history = self.get_sender_history(sender_id, 86400)
            history.append({
                'transaction_id': transaction['transaction_id'],
                'timestamp': datetime.utcnow().timestamp(),
                'amount': transaction['amount']['send_amount'],
                'currency': transaction['amount']['send_currency']
            })
            self.redis_client.setex(key, 3600, json.dumps(history))

        except Exception as e:
            print(
                f"Error processing transaction {transaction.get('transaction_id')}: {e}")

    def run(self):
        # Main processing loop
        print("Fraud detection processor started")

        try:
            for message in self.consumer:
                transaction = message.value
                self.process_transaction(transaction)
        except KeyboardInterrupt:
            print("Shutting down fraud processor...")
        finally:
            self.consumer.close()
            self.producer.close()
            self.db_conn.close()
            self.redis_client.close()
