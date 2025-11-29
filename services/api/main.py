import psycopg2
import redis
import json
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import datetime
from psycopg2.extras import RealDictCursor
from config.model import Transaction, DashboardMetrics, CorridorData, ChannelPerformance

POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'remitflow'),
    'user': os.getenv('POSTGRES_USER', 'remitflow_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'remitflow_pass')
}

REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', '6379')),
    'decode_responses': True
}

# Initialize FastAPI
app = FastAPI(
    title="RemitFlow PH API",
    description="Real-Time OFW Remittance Intelligence Platform",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


redis_client = redis.Redis(**REDIS_CONFIG)


@app.get("/")
def read_root():
    return {
        "message": "RemitFlow PH API",
        "version": "1.0.0",
        "status": "operational"
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        # Check database
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.close()
        db_status = "healthy"
    except:
        db_status = "unhealthy"

    try:
        # Check Redis
        redis_client.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        "database": db_status,
        "redis": redis_status,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/dashboard/metrics", response_model=DashboardMetrics)
def get_dashboard_metrics():
    """Get real-time dashboard metrics"""

    # Try cache first
    cache_key = "dashboard:metrics:24h"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    # Query database
    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get metrics for last 24 hours
    cursor.execute("""
        SELECT 
            COUNT(*) as total_transactions,
            SUM(send_amount) as total_volume,
            AVG(send_amount) as average_transaction,
            COUNT(DISTINCT sender_id) as active_senders,
            COUNT(CASE WHEN status = 'completed' THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) AS success_rate
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)

    metrics_row = cursor.fetchone()

    # Get fraud alerts
    cursor.execute("""
        SELECT COUNT(*) as fraud_count
        FROM fraud_alerts
        WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)

    fraud_row = cursor.fetchone()

    cursor.close()
    conn.close()

    metrics = {
        "total_transactions_24h": metrics_row['total_transactions'] or 0,
        "total_volume_24h": float(metrics_row['total_volume'] or 0),
        "average_transaction": float(metrics_row['average_transaction'] or 0),
        "fraud_alerts_24h": fraud_row['fraud_count'] or 0,
        "active_senders": metrics_row['active_senders'] or 0,
        "success_rate": float(metrics_row['success_rate'] or 0)
    }

    # Cache for 30 seconds
    redis_client.setex(cache_key, 30, json.dumps(metrics))

    return metrics


@app.get("/api/v1/transactions/latest", response_model=List[Transaction])
def get_recent_transactions(limit: int = Query(50, le=100)):
    """Get recent transactions"""

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            transaction_id,
            timestamp,
            sender_name,
            recipient_name,
            send_amount,
            send_currency,
            receive_amount,
            status,
            fraud_score,
            risk_level
        FROM transactions
        ORDER BY timestamp DESC
        LIMIT %s
    """, (limit,))

    transactions = cursor.fetchall()

    cursor.close()
    conn.close()

    return [Transaction(**txn) for txn in transactions]


@app.get("/api/v1/transactions/{transaction_id}")
def get_transaction_detail(transaction_id: str):
    """Get detailed information about a specific transaction"""

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM transactions
        WHERE transaction_id = %s
    """, (transaction_id,))

    transaction = cursor.fetchone()

    if not transaction:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Get related fraud alerts if any
    cursor.execute("""
        SELECT *
        FROM fraud_alerts
        WHERE transaction_id = %s
    """, (transaction_id,))

    fraud_alerts = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        "transaction": transaction,
        "fraud_alerts": fraud_alerts
    }


@app.get("/api/v1/transactions/stats/hourly")
def get_hourly_transactions(hours: int = Query(24, le=168)):
    """Get transaction counts by hour"""

    cache_key = f"transactions:hourly:{hours}"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            DATE_TRUNC('hour', timestamp) as hour,
            COUNT(*) as count,
            SUM(send_amount) as volume,
            AVG(fraud_score) as avg_fraud_score
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL '1 hour' * %s
        GROUP BY hour
        ORDER BY hour
    """, (hours,))

    hourly_data = cursor.fetchall()

    cursor.close()
    conn.close()

    result = {"hourly_data": hourly_data or []}

    # Cache for 1 minute
    redis_client.setex(cache_key, 60, json.dumps(result, default=str))

    return result


@app.get("/api/v1/fraud/alerts")
def get_fraud_alerts(
    limit: int = Query(50, le=200),
    severity: Optional[str] = None,
    status: Optional[str] = None
):
    """Get fraud alerts with optional filters"""

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    query = """
        SELECT 
            alert_id,
            timestamp,
            transaction_id,
            alert_type,
            severity,
            description,
            sender_id,
            fraud_score,
            recommended_action,
            status
        FROM fraud_alerts
        WHERE 1=1
    """

    params = []

    if severity:
        query += " AND severity = %s"
        params.append(severity)

    if status:
        query += " AND status = %s"
        params.append(status)

    query += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

    cursor.execute(query, params)

    alerts = cursor.fetchall()

    cursor.close()
    conn.close()

    return {"alerts": alerts}


@app.get("/api/v1/fraud/stats")
def get_fraud_stats():
    """Get fraud detection statistics"""

    cache_key = "fraud:stats:24h"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total_alerts,
            COUNT(CASE WHEN severity = 'high' THEN 1 END) as high_severity,
            COUNT(CASE WHEN severity = 'medium' THEN 1 END) as medium_severity,
            COUNT(CASE WHEN severity = 'low' THEN 1 END) as low_severity,
            COUNT(CASE WHEN status = 'open' THEN 1 END) as open_alerts,
            AVG(fraud_score) as avg_fraud_score
        FROM fraud_alerts
        WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)

    stats = cursor.fetchone()

    # Get flagged transaction rate
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN is_flagged = TRUE THEN 1 END)::FLOAT / COUNT(*) as flagged_rate
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)

    rate_row = cursor.fetchone()

    cursor.close()
    conn.close()

    result = {
        **stats,
        "flagged_transaction_rate": float(rate_row['flagged_rate'] or 0)
    }

    # Cache for 1 minute
    redis_client.setex(cache_key, 60, json.dumps(result, default=str))

    return result


@app.get("/api/v1/corridors", response_model=List[CorridorData])
def get_corridors(
    limit: int = Query(20, le=50),
    time_range: str = Query("7d", regex="^(24h|7d|30d)$")
):
    """Get top remittance corridors"""

    interval_map = {
        "24h": "24 hours",
        "7d": "7 days",
        "30d": "30 days"
    }

    cache_key = f"corridors:top:{time_range}"
    cached = redis_client.get(cache_key)

    if cached:
        data = json.loads(cached)
        return [CorridorData(**corridor) for corridor in data]

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            origin_country || ' -> ' || dest_region as corridor_id,
            origin_country,
            dest_region as destination_region,
            COUNT(*) as transaction_count,
            SUM(send_amount) as total_volume,
            AVG(send_amount) as average_transaction
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL %s
        GROUP BY origin_country, dest_region
        ORDER BY total_volume DESC
        LIMIT %s
    """, (interval_map[time_range], limit))

    corridors = cursor.fetchall()

    cursor.close()
    conn.close()

    corridor_list = [dict(row) for row in corridors]

    # Cache for 5 minutes
    redis_client.setex(cache_key, 300, json.dumps(corridor_list, default=str))

    return [CorridorData(**corridor) for corridor in corridor_list]


@app.get("/api/v1/channels/performance", response_model=List[ChannelPerformance])
def get_channel_performance(time_range: str = Query("7d", regex="^(24h|7d|30d)$")):
    """Get channel performance metrics"""

    interval_map = {
        "24h": "24 hours",
        "7d": "7 days",
        "30d": "30 days"
    }

    cache_key = f"channels:performance:{time_range}"
    cached = redis_client.get(cache_key)

    if cached:
        data = json.loads(cached)
        return [ChannelPerformance(**channel) for channel in data]

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            channel_name,
            COUNT(*) as transaction_count,
            COUNT(CASE WHEN status = 'completed' THEN 1 END)::FLOAT / COUNT(*) as success_rate,
            AVG(processing_time_ms)::INTEGER as avg_processing_time,
            4.5 as average_rating
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL %s
        GROUP BY channel_name
        ORDER BY transaction_count DESC
    """, (interval_map[time_range],))

    channels = cursor.fetchall()

    cursor.close()
    conn.close()

    channel_list = [dict(row) for row in channels]

    # Cache for 5 minutes
    redis_client.setex(cache_key, 300, json.dumps(channel_list, default=str))

    return [ChannelPerformance(**channel) for channel in channel_list]


@app.get("/api/v1/senders/{sender_id}/profile")
def get_sender_profile(sender_id: str):
    """Get sender profile and statistics"""

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get profile
    cursor.execute("""
        SELECT *
        FROM sender_profiles
        WHERE sender_id = %s
    """, (sender_id,))

    profile = cursor.fetchone()

    if not profile:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Sender not found")

    # Get recent transactions
    cursor.execute("""
        SELECT 
            transaction_id,
            timestamp,
            send_amount,
            send_currency,
            dest_region,
            channel_name,
            status
        FROM transactions
        WHERE sender_id = %s
        ORDER BY timestamp DESC
        LIMIT 10
    """, (sender_id,))

    recent_transactions = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        "profile": profile,
        "recent_transactions": recent_transactions
    }


@app.get("/api/v1/analytics/geographic")
def get_geographic_analytics(region: Optional[str] = None):
    """Get geographic remittance analytics"""

    cache_key = f"analytics:geo:{region or 'all'}"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    conn = psycopg2.connect(**POSTGRES_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    query = """
        SELECT 
            dest_region,
            dest_city,
            COUNT(*) as transaction_count,
            SUM(receive_amount) as total_received,
            AVG(receive_amount) as avg_transaction,
            COUNT(DISTINCT sender_id) as unique_senders
        FROM transactions
        WHERE timestamp > NOW() - INTERVAL '30 days'
    """

    params = []

    if region:
        query += " AND dest_region = %s"
        params.append(region)

    query += """
        GROUP BY dest_region, dest_city
        ORDER BY total_received DESC
        LIMIT 50
    """

    cursor.execute(query, params)

    geographic_data = cursor.fetchall()

    cursor.close()
    conn.close()

    result = {"geographic_data": geographic_data}

    # Cache for 10 minutes
    redis_client.setex(cache_key, 600, json.dumps(result, default=str))

    return result
