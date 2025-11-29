import json
from datetime import datetime, timedelta
from typing import Dict, List
import redis
import psycopg2
from kafka import KafkaConsumer, KafkaProducer
import numpy as np
from collections import defaultdict


class AnalyticsProcessor:
    """
    Performs complex analytics on transaction streams:
    - Geographic remittance analytics
    - Trend detection and forecasting
    - Exchange rate analysis
    - Economic impact estimation
    - Pattern recognition for business intelligence
    """

    def __init__(self, kafka_servers, postgres_config, redis_config):
        self.consumer = KafkaConsumer(
            'remittance-transactions',
            bootstrap_servers=kafka_servers,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='analytics-processor',
            auto_offset_reset='latest'
        )

        self.producer = KafkaProducer(
            bootstrap_servers=kafka_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

        self.redis_client = redis.Redis(**redis_config, decode_responses=True)
        self.db_conn = psycopg2.connect(**postgres_config)

        # Analytics windows
        self.geographic_data = defaultdict(list)
        self.hourly_patterns = defaultdict(lambda: defaultdict(int))

    def update_geographic_analytics(self, transaction: Dict):
        # Update geographic remittance analytics
        geo_id = f"GEO_{transaction['destination']['country']}_{transaction['destination']['region']}_{transaction['destination']['city']}"

        try:
            cursor = self.db_conn.cursor()

            # Get or create monthly geographic analytics
            now = datetime.utcnow()
            month_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = (month_start + timedelta(days=32)).replace(day=1)

            cursor.execute("""
                SELECT geo_id, total_received_php, transaction_count,
                       unique_recipients, top_origin_countries
                FROM geo_analytics
                WHERE geo_id = %s
                AND window_start = %s
                AND window_type = 'monthly'
            """, (geo_id, month_start))

            existing = cursor.fetchone()

            # Convert to PHP
            amount_php = transaction['amount']['receive_amount']

            # Get origin country data
            origin_country = transaction['origin']['country']

            if existing:
                # Update existing
                new_count = existing[2] + 1
                new_total = float(existing[1]) + amount_php
                new_avg = new_total / new_count

                # Update top origin countries
                top_origins = json.loads(existing[4]) if existing[4] else []
                origin_found = False

                for origin in top_origins:
                    if origin['country'] == origin_country:
                        origin['volume_php'] += amount_php
                        origin['share'] = origin['volume_php'] / new_total
                        origin_found = True
                        break

                if not origin_found:
                    top_origins.append({
                        'country': origin_country,
                        'volume_php': amount_php,
                        'share': amount_php / new_total
                    })

                # Sort by volume and keep top 10
                top_origins.sort(key=lambda x: x['volume_php'], reverse=True)
                top_origins = top_origins[:10]

                cursor.execute("""
                    UPDATE geo_analytics
                    SET total_received_php = %s,
                        transaction_count = %s,
                        average_transaction_php = %s,
                        top_origin_countries = %s,
                        last_updated = NOW()
                    WHERE geo_id = %s
                    AND window_start = %s
                    AND window_type = 'monthly'
                """, (
                    new_total, new_count, new_avg,
                    json.dumps(top_origins),
                    geo_id, month_start
                ))

            else:
                # Create new
                top_origins = [{
                    'country': origin_country,
                    'volume_php': amount_php,
                    'share': 1.0
                }]

                cursor.execute("""
                    INSERT INTO geo_analytics (
                        geo_id, country, region, province, city,
                        window_start, window_end, window_type,
                        total_received_php, transaction_count,
                        average_transaction_php, unique_recipients,
                        top_origin_countries
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    geo_id,
                    transaction['destination']['country'],
                    transaction['destination']['region'],
                    transaction['destination']['province'],
                    transaction['destination']['city'],
                    month_start, next_month, 'monthly',
                    amount_php, 1, amount_php, 1,
                    json.dumps(top_origins)
                ))

            self.db_conn.commit()
            cursor.close()

            # Publish update
            self.producer.send('geo-analytics', value={
                'geo_id': geo_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'event': 'geo_updated'
            })

            print(f"Updated geographic analytics: {geo_id}")

        except Exception as e:
            print(f"Failed to update geographic analytics: {e}")
            self.db_conn.rollback()

    def calculate_growth_trends(self, geo_id: str):
        # Calculate month-over-month and year-over-year growth
        try:
            cursor = self.db_conn.cursor()

            # Get current month and previous month data
            now = datetime.utcnow()
            current_month = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month = (current_month - timedelta(days=1)).replace(day=1)
            last_year = current_month.replace(year=current_month.year - 1)

            # Get volumes
            cursor.execute("""
                SELECT window_start, total_received_php
                FROM geo_analytics
                WHERE geo_id = %s
                AND window_start IN (%s, %s, %s)
                AND window_type = 'monthly'
            """, (geo_id, current_month, last_month, last_year))

            data = {row[0]: float(row[1]) for row in cursor.fetchall()}

            # Calculate growth rates
            mom_growth = None
            yoy_growth = None

            if current_month in data and last_month in data and data[last_month] > 0:
                mom_growth = (data[current_month] -
                              data[last_month]) / data[last_month]

            if current_month in data and last_year in data and data[last_year] > 0:
                yoy_growth = (data[current_month] -
                              data[last_year]) / data[last_year]

            # Update the record
            if mom_growth is not None or yoy_growth is not None:
                cursor.execute("""
                    UPDATE geo_analytics
                    SET mom_growth = %s,
                        yoy_growth = %s
                    WHERE geo_id = %s
                    AND window_start = %s
                    AND window_type = 'monthly'
                """, (mom_growth, yoy_growth, geo_id, current_month))

                self.db_conn.commit()

            cursor.close()

        except Exception as e:
            print(f"Failed to calculate growth trends: {e}")
            self.db_conn.rollback()

    def analyze_hourly_patterns(self, transaction: Dict):
        # Analyze transaction patterns by hour of day
        try:
            timestamp = datetime.fromisoformat(
                transaction['timestamp'].replace('Z', '+00:00'))
            hour = timestamp.hour
            sender_id = transaction['sender']['sender_id']

            # Store in Redis for quick pattern lookup
            key = f"hourly_pattern:{sender_id}"

            # Get existing pattern
            pattern = self.redis_client.get(key)
            if pattern:
                pattern = json.loads(pattern)
            else:
                pattern = {str(h): 0 for h in range(24)}

            # Increment hour counter
            pattern[str(hour)] = pattern.get(str(hour), 0) + 1

            # Store back with 7 day expiry
            self.redis_client.setex(key, 604800, json.dumps(pattern))

            # Update sender profile with peak hours
            peak_hours = sorted(
                pattern.items(), key=lambda x: x[1], reverse=True)[:3]
            peak_hour_list = [int(h) for h, _ in peak_hours if int(h) > 0]

            if peak_hour_list:
                cursor = self.db_conn.cursor()
                cursor.execute("""
                    UPDATE sender_profiles
                    SET peak_sending_hours = %s
                    WHERE sender_id = %s
                """, (json.dumps(peak_hour_list), sender_id))
                self.db_conn.commit()
                cursor.close()

        except Exception as e:
            print(f"Failed to analyze hourly patterns: {e}")

    def detect_anomalies(self, transaction: Dict):
        # Detect statistical anomalies in transaction patterns
        try:
            cursor = self.db_conn.cursor()

            # Get historical data for this corridor
            corridor = f"{transaction['origin']['country']}_{transaction['destination']['region']}"

            cursor.execute("""
                SELECT average_transaction_usd, total_volume_usd, transaction_count
                FROM corridor_analytics
                WHERE corridor_id = %s
                AND window_type = 'daily'
                AND window_start > NOW() - INTERVAL '30 days'
                ORDER BY window_start DESC
                LIMIT 30
            """, (corridor,))

            historical = cursor.fetchall()

            if len(historical) > 7:
                # Calculate statistics
                amounts = [float(row[0]) for row in historical if row[0]]
                volumes = [float(row[1]) for row in historical if row[1]]

                if amounts:
                    mean_amount = np.mean(amounts)
                    std_amount = np.std(amounts)

                    # Convert current transaction to USD
                    amount_usd = transaction['amount']['send_amount']
                    if transaction['amount']['send_currency'] != 'USD':
                        currency_rates = {
                            'AED': 0.27, 'SAR': 0.27, 'PHP': 0.018, 'SGD': 0.74}
                        amount_usd = amount_usd * \
                            currency_rates.get(
                                transaction['amount']['send_currency'], 0.27)

                    # Check if current amount is anomalous (>3 standard deviations)
                    z_score = (amount_usd - mean_amount) / \
                        std_amount if std_amount > 0 else 0

                    if abs(z_score) > 3:
                        print(
                            f"Anomaly detected in corridor {corridor}: z-score = {z_score:.2f}")

                        # Could publish to an anomaly topic for further investigation
                        anomaly_data = {
                            'transaction_id': transaction['transaction_id'],
                            'corridor': corridor,
                            'amount_usd': amount_usd,
                            'mean_amount': mean_amount,
                            'z_score': z_score,
                            'timestamp': datetime.utcnow().isoformat() + 'Z'
                        }

                        # Cache anomaly in Redis
                        self.redis_client.setex(
                            f"anomaly:{transaction['transaction_id']}",
                            3600,
                            json.dumps(anomaly_data)
                        )

            cursor.close()

        except Exception as e:
            print(f"Failed to detect anomalies: {e}")

    def calculate_economic_impact(self, geo_id: str, region: str):
        # Estimate economic impact of remittances on region
        try:
            cursor = self.db_conn.cursor()

            # Get current month data
            now = datetime.utcnow()
            month_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)

            cursor.execute("""
                SELECT total_received_php, transaction_count, unique_recipients
                FROM geo_analytics
                WHERE geo_id = %s
                AND window_start = %s
                AND window_type = 'monthly'
            """, (geo_id, month_start))

            data = cursor.fetchone()

            if data:
                total_php = float(data[0])
                txn_count = data[1]
                unique_recipients = data[2] or 1

                # Rough economic impact calculations
                # These are simplified - in production would use real economic data

                # Average household size in Philippines
                avg_household_size = 4.5
                estimated_beneficiaries = unique_recipients * avg_household_size

                # Per capita calculation
                per_capita_remittance = total_php / \
                    estimated_beneficiaries if estimated_beneficiaries > 0 else 0

                # Rough GDP contribution (remittances ~10% of PH GDP)
                # This would need actual regional GDP data
                gdp_contribution = total_php * 0.0001  # Placeholder

                # Dependency index (0-1, higher means more dependent on remittances)
                # Simplified calculation
                remittance_dependency = min(
                    per_capita_remittance / 15000, 1.0)  # 15000 PHP as baseline

                # Update database
                cursor.execute("""
                    UPDATE geo_analytics
                    SET gdp_contribution_estimate = %s,
                        per_capita_remittance = %s,
                        remittance_dependency_index = %s
                    WHERE geo_id = %s
                    AND window_start = %s
                    AND window_type = 'monthly'
                """, (
                    gdp_contribution,
                    per_capita_remittance,
                    remittance_dependency,
                    geo_id, month_start
                ))

                self.db_conn.commit()

            cursor.close()

        except Exception as e:
            print(f"Failed to calculate economic impact: {e}")
            self.db_conn.rollback()

    def generate_insights(self):
        # Generate business insights from patterns
        try:
            # This could include:
            # - Identifying high-growth corridors
            # - Detecting seasonal patterns
            # - Recommending optimal send times
            # - Identifying underperforming channels

            insights = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'insights': []
            }

            cursor = self.db_conn.cursor()

            # Find fastest growing corridors (last 7 days vs previous 7 days)
            cursor.execute("""
                WITH current_week AS (
                    SELECT corridor_id, SUM(total_volume_usd) as volume
                    FROM corridor_analytics
                    WHERE window_start > NOW() - INTERVAL '7 days'
                    AND window_type = 'daily'
                    GROUP BY corridor_id
                ),
                previous_week AS (
                    SELECT corridor_id, SUM(total_volume_usd) as volume
                    FROM corridor_analytics
                    WHERE window_start > NOW() - INTERVAL '14 days'
                    AND window_start <= NOW() - INTERVAL '7 days'
                    AND window_type = 'daily'
                    GROUP BY corridor_id
                )
                SELECT 
                    c.corridor_id,
                    c.volume as current_volume,
                    p.volume as previous_volume,
                    ((c.volume - p.volume) / p.volume * 100) as growth_pct
                FROM current_week c
                JOIN previous_week p ON c.corridor_id = p.corridor_id
                WHERE p.volume > 0
                ORDER BY growth_pct DESC
                LIMIT 5
            """)

            for row in cursor.fetchall():
                insights['insights'].append({
                    'type': 'high_growth_corridor',
                    'corridor': row[0],
                    'growth_percentage': float(row[3]),
                    'current_volume': float(row[1])
                })

            cursor.close()

            # Cache insights
            self.redis_client.setex(
                'analytics:insights:latest',
                3600,
                json.dumps(insights)
            )

            print(f"Generated {len(insights['insights'])} insights")

        except Exception as e:
            print(f"Failed to generate insights: {e}")

    def process_transaction(self, transaction: Dict):
        # Main analytics pipeline
        try:
            # Run analytics
            self.update_geographic_analytics(transaction)
            self.analyze_hourly_patterns(transaction)
            self.detect_anomalies(transaction)

            # Update geographic stats (every transaction)
            geo_id = f"GEO_{transaction['destination']['country']}_{transaction['destination']['region']}_{transaction['destination']['city']}"

            # Calculate trends and impact less frequently
            if hash(transaction['transaction_id']) % 10 == 0:  # Every ~10th transaction
                self.calculate_growth_trends(geo_id)
                self.calculate_economic_impact(
                    geo_id, transaction['destination']['region'])

            print(
                f"Processed analytics for transaction: {transaction['transaction_id']}")

        except Exception as e:
            print(f"Error processing transaction analytics: {e}")

    def run(self):
        # Main processing loop
        print("Analytics processor started")

        import time
        last_insight_generation = time.time()
        insight_interval = 3600  # Generate insights every hour

        try:
            for message in self.consumer:
                transaction = message.value

                # Only process completed transactions
                if transaction['status'] == 'completed':
                    self.process_transaction(transaction)

                # Periodically generate insights
                if time.time() - last_insight_generation > insight_interval:
                    self.generate_insights()
                    last_insight_generation = time.time()

        except KeyboardInterrupt:
            print("Shutting down analytics processor...")
        finally:
            self.consumer.close()
            self.producer.close()
            self.db_conn.close()
            self.redis_client.close()
