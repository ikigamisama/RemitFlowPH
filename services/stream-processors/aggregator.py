import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List
import redis
import psycopg2
from kafka import KafkaConsumer, KafkaProducer
import time


class AggregationProcessor:
    """
    Processes transaction streams to create aggregated views:
    - Sender profiles (statistics and patterns)
    - Corridor analytics (geographic flows)
    - Channel performance metrics
    - Windowed aggregations (5min, 1hr, 1day)
    """

    def __init__(self, kafka_servers, postgres_config, redis_config):
        self.consumer = KafkaConsumer(
            'remittance-transactions',
            bootstrap_servers=kafka_servers,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='aggregation-processor',
            auto_offset_reset='latest'
        )

        self.producer = KafkaProducer(
            bootstrap_servers=kafka_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

        self.redis_client = redis.Redis(**redis_config, decode_responses=True)
        self.db_conn = psycopg2.connect(**postgres_config)

        # In-memory windows for aggregation
        self.sender_windows = defaultdict(list)
        self.corridor_windows = defaultdict(list)
        self.channel_windows = defaultdict(list)

    def update_sender_profile(self, transaction: Dict):
        # Update sender profile with new transaction data
        sender_id = transaction['sender']['sender_id']

        try:
            cursor = self.db_conn.cursor()

            # Check if profile exists
            cursor.execute("""
                SELECT sender_id, total_transactions, total_sent_usd, 
                       first_transaction_date, preferred_channels, common_recipients
                FROM sender_profiles
                WHERE sender_id = %s
            """, (sender_id,))

            existing = cursor.fetchone()

            # Convert amount to USD (simplified - in production use real exchange rates)
            amount_usd = transaction['amount']['send_amount']
            if transaction['amount']['send_currency'] != 'USD':
                # Rough conversion for demo purposes
                currency_rates = {'AED': 0.27,
                                  'SAR': 0.27, 'PHP': 0.018, 'SGD': 0.74}
                amount_usd = amount_usd * \
                    currency_rates.get(
                        transaction['amount']['send_currency'], 0.27)

            if existing:
                # Update existing profile
                total_txns = existing[1] + 1
                total_sent = float(existing[2]) + amount_usd
                avg_txn = total_sent / total_txns
                first_date = existing[3]

                # Update preferred channels
                preferred_channels = json.loads(
                    existing[4]) if existing[4] else []
                channel = transaction['channel']['channel_name']
                if channel not in preferred_channels:
                    preferred_channels.append(channel)
                if len(preferred_channels) > 5:
                    preferred_channels = preferred_channels[-5:]

                # Update common recipients
                common_recipients = json.loads(
                    existing[5]) if existing[5] else []
                recipient = transaction['recipient']['recipient_id']
                if recipient not in common_recipients:
                    common_recipients.append(recipient)
                if len(common_recipients) > 10:
                    common_recipients = common_recipients[-10:]

                cursor.execute("""
                    UPDATE sender_profiles
                    SET total_transactions = %s,
                        total_sent_usd = %s,
                        average_transaction_usd = %s,
                        last_transaction_date = %s,
                        preferred_channels = %s,
                        common_recipients = %s,
                        last_updated = NOW()
                    WHERE sender_id = %s
                """, (
                    total_txns, total_sent, avg_txn,
                    transaction['timestamp'],
                    json.dumps(preferred_channels),
                    json.dumps(common_recipients),
                    sender_id
                ))

            else:
                # Create new profile
                cursor.execute("""
                    INSERT INTO sender_profiles (
                        sender_id, name, email, phone, kyc_level,
                        registration_date, country_of_residence,
                        total_transactions, total_sent_usd, average_transaction_usd,
                        first_transaction_date, last_transaction_date,
                        preferred_channels, common_recipients
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    sender_id,
                    transaction['sender']['sender_name'],
                    transaction['sender']['sender_email'],
                    transaction['sender']['sender_phone'],
                    transaction['sender']['kyc_level'],
                    transaction['sender']['customer_since'],
                    transaction['origin']['country'],
                    1, amount_usd, amount_usd,
                    transaction['timestamp'],
                    transaction['timestamp'],
                    json.dumps([transaction['channel']['channel_name']]),
                    json.dumps([transaction['recipient']['recipient_id']])
                ))

            # Update time-windowed statistics (24h, 7d, 30d)
            self.update_sender_windows(
                sender_id, transaction['timestamp'], amount_usd)

            self.db_conn.commit()
            cursor.close()

            # Publish update
            self.producer.send('sender-profile-updates', value={
                'sender_id': sender_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'event': 'profile_updated'
            })

            print(f"Updated sender profile: {sender_id}")

        except Exception as e:
            print(f"Failed to update sender profile: {e}")
            self.db_conn.rollback()

    def update_sender_windows(self, sender_id: str, timestamp: str, amount_usd: float):
        # Update time-windowed statistics for sender
        try:
            cursor = self.db_conn.cursor()

            # Count transactions in last 24h, 7d, 30d
            for days, column in [(1, 'txn_count_24h'), (7, 'txn_count_7d'), (30, 'txn_count_30d')]:
                cursor.execute(f"""
                    SELECT COUNT(*), COALESCE(SUM(send_amount), 0)
                    FROM transactions
                    WHERE sender_id = %s
                    AND timestamp > NOW() - INTERVAL '{days} days'
                """, (sender_id,))

                count, total = cursor.fetchone()
                amount_col = column.replace('count', 'amount')

                cursor.execute(f"""
                    UPDATE sender_profiles
                    SET {column} = %s,
                        {amount_col} = %s
                    WHERE sender_id = %s
                """, (count, float(total), sender_id))

            self.db_conn.commit()
            cursor.close()

        except Exception as e:
            print(f"Failed to update sender windows: {e}")
            self.db_conn.rollback()

    def update_corridor_analytics(self, transaction: Dict):
        # Update corridor analytics with new transaction
        corridor_id = f"{transaction['origin']['country']}_{transaction['destination']['region']}"

        try:
            cursor = self.db_conn.cursor()

            # Get or create daily corridor analytics
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)

            cursor.execute("""
                SELECT corridor_id, transaction_count, total_volume_usd
                FROM corridor_analytics
                WHERE corridor_id = %s
                AND window_start = %s
                AND window_type = 'daily'
            """, (corridor_id, today_start))

            existing = cursor.fetchone()

            # Convert to USD
            amount_usd = transaction['amount']['send_amount']
            if transaction['amount']['send_currency'] != 'USD':
                currency_rates = {'AED': 0.27,
                                  'SAR': 0.27, 'PHP': 0.018, 'SGD': 0.74}
                amount_usd = amount_usd * \
                    currency_rates.get(
                        transaction['amount']['send_currency'], 0.27)

            if existing:
                # Update existing
                new_count = existing[1] + 1
                new_volume = float(existing[2]) + amount_usd
                new_avg = new_volume / new_count

                cursor.execute("""
                    UPDATE corridor_analytics
                    SET transaction_count = %s,
                        total_volume_usd = %s,
                        average_transaction_usd = %s,
                        last_updated = NOW()
                    WHERE corridor_id = %s
                    AND window_start = %s
                    AND window_type = 'daily'
                """, (new_count, new_volume, new_avg, corridor_id, today_start))

            else:
                # Create new
                cursor.execute("""
                    INSERT INTO corridor_analytics (
                        corridor_id, origin_country, origin_city,
                        destination_country, destination_region,
                        window_start, window_end, window_type,
                        transaction_count, total_volume_usd, average_transaction_usd
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    corridor_id,
                    transaction['origin']['country'],
                    transaction['origin']['city'],
                    transaction['destination']['country'],
                    transaction['destination']['region'],
                    today_start, today_end, 'daily',
                    1, amount_usd, amount_usd
                ))

            self.db_conn.commit()
            cursor.close()

            # Publish update
            self.producer.send('corridor-analytics', value={
                'corridor_id': corridor_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'event': 'corridor_updated'
            })

            print(f"Updated corridor analytics: {corridor_id}")

        except Exception as e:
            print(f"Failed to update corridor analytics: {e}")
            self.db_conn.rollback()

    def update_channel_performance(self, transaction: Dict):
        # Update channel performance metrics
        channel_id = transaction['channel']['channel_id']
        agent_id = transaction['channel']['agent_id']

        try:
            cursor = self.db_conn.cursor()

            # Get or create daily channel performance
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)

            cursor.execute("""
                SELECT transaction_count, transaction_volume_usd, 
                       avg_processing_time_ms
                FROM channel_performance
                WHERE channel_id = %s
                AND agent_id = %s
                AND window_start = %s
            """, (channel_id, agent_id, today_start))

            existing = cursor.fetchone()

            # Convert to USD
            amount_usd = transaction['amount']['send_amount']
            if transaction['amount']['send_currency'] != 'USD':
                currency_rates = {'AED': 0.27,
                                  'SAR': 0.27, 'PHP': 0.018, 'SGD': 0.74}
                amount_usd = amount_usd * \
                    currency_rates.get(
                        transaction['amount']['send_currency'], 0.27)

            processing_time = transaction.get('processing_time_ms', 0)
            is_success = transaction['status'] == 'completed'

            if existing:
                # Calculate new averages
                new_count = existing[0] + 1
                new_volume = float(existing[1]) + amount_usd

                # Weighted average for processing time
                old_avg_time = existing[2] or 0
                new_avg_time = (
                    (old_avg_time * existing[0]) + processing_time) / new_count

                # Calculate success rate
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM transactions
                    WHERE channel_id = %s
                    AND status = 'completed'
                    AND timestamp >= %s
                """, (channel_id, today_start))

                success_count = cursor.fetchone()[0]
                if is_success:
                    success_count += 1

                success_rate = success_count / new_count if new_count > 0 else 0
                failure_rate = 1 - success_rate

                cursor.execute("""
                    UPDATE channel_performance
                    SET transaction_count = %s,
                        transaction_volume_usd = %s,
                        avg_processing_time_ms = %s,
                        success_rate = %s,
                        failure_rate = %s,
                        last_updated = NOW()
                    WHERE channel_id = %s
                    AND agent_id = %s
                    AND window_start = %s
                """, (
                    new_count, new_volume, int(new_avg_time),
                    success_rate, failure_rate,
                    channel_id, agent_id, today_start
                ))

            else:
                # Create new
                success_rate = 1.0 if is_success else 0.0

                cursor.execute("""
                    INSERT INTO channel_performance (
                        channel_id, agent_id, channel_name, agent_name,
                        channel_type, location,
                        window_start, window_end,
                        transaction_count, transaction_volume_usd,
                        success_rate, failure_rate,
                        avg_processing_time_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    channel_id, agent_id,
                    transaction['channel']['channel_name'],
                    transaction['channel']['agent_name'],
                    transaction['channel']['channel_type'],
                    f"{transaction['origin']['city']}, {transaction['origin']['country']}",
                    today_start, today_end,
                    1, amount_usd,
                    success_rate, 1 - success_rate,
                    processing_time
                ))

            self.db_conn.commit()
            cursor.close()

            # Publish update
            self.producer.send('channel-performance', value={
                'channel_id': channel_id,
                'agent_id': agent_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'event': 'performance_updated'
            })

            print(f"Updated channel performance: {channel_id}")

        except Exception as e:
            print(f"Failed to update channel performance: {e}")
            self.db_conn.rollback()

    def refresh_materialized_views(self):
        # Refresh PostgreSQL materialized views periodically
        try:
            cursor = self.db_conn.cursor()

            # Refresh all materialized views
            views = [
                'mv_realtime_summary',
                'mv_top_corridors',
                'mv_channel_summary'
            ]

            for view in views:
                cursor.execute(
                    f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
                print(f"Refreshed materialized view: {view}")

            self.db_conn.commit()
            cursor.close()

        except Exception as e:
            print(f"Failed to refresh materialized views: {e}")
            self.db_conn.rollback()

    def process_transaction(self, transaction: Dict):
        """Main aggregation pipeline"""
        try:
            # Update all aggregations
            self.update_sender_profile(transaction)
            self.update_corridor_analytics(transaction)
            self.update_channel_performance(transaction)

            print(
                f"Processed aggregations for transaction: {transaction['transaction_id']}")

        except Exception as e:
            print(f"Error processing transaction aggregations: {e}")

    def run(self):
        """Main processing loop"""
        print("Aggregation processor started")

        last_refresh = time.time()
        refresh_interval = 300  # Refresh materialized views every 5 minutes

        try:
            for message in self.consumer:
                transaction = message.value

                # Only process completed transactions
                if transaction['status'] in ['completed', 'failed']:
                    self.process_transaction(transaction)

                # Periodically refresh materialized views
                if time.time() - last_refresh > refresh_interval:
                    self.refresh_materialized_views()
                    last_refresh = time.time()

        except KeyboardInterrupt:
            print("Shutting down aggregation processor...")
        finally:
            self.consumer.close()
            self.producer.close()
            self.db_conn.close()
            self.redis_client.close()
