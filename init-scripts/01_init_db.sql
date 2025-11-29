-- RemitFlow PH Database Initialization Script
-- Creates all necessary tables, indexes, and extensions

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- TRANSACTIONS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    
    -- Sender
    sender_id VARCHAR(50) NOT NULL,
    sender_name VARCHAR(255),
    sender_phone VARCHAR(20),
    sender_email VARCHAR(255),
    sender_kyc_level VARCHAR(20),
    sender_customer_since DATE,
    
    -- Recipient
    recipient_id VARCHAR(50) NOT NULL,
    recipient_name VARCHAR(255),
    recipient_phone VARCHAR(20),
    recipient_relationship VARCHAR(50),
    recipient_account_number VARCHAR(100),
    recipient_account_type VARCHAR(50),
    
    -- Amounts
    send_amount DECIMAL(15,2),
    send_currency VARCHAR(3),
    receive_amount DECIMAL(15,2),
    receive_currency VARCHAR(3),
    exchange_rate DECIMAL(10,4),
    fees DECIMAL(10,2),
    total_deducted DECIMAL(15,2),
    
    -- Origin
    origin_country VARCHAR(100),
    origin_city VARCHAR(100),
    origin_region VARCHAR(100),
    
    -- Destination
    dest_country VARCHAR(100),
    dest_province VARCHAR(100),
    dest_city VARCHAR(100),
    dest_barangay VARCHAR(100),
    dest_region VARCHAR(100),
    
    -- Channel
    channel_id VARCHAR(50),
    channel_name VARCHAR(100),
    channel_type VARCHAR(50),
    agent_id VARCHAR(50),
    agent_name VARCHAR(255),
    branch_code VARCHAR(50),
    
    -- Status
    status VARCHAR(50),
    processing_time_ms INTEGER,
    completion_timestamp TIMESTAMPTZ,
    failure_reason TEXT,
    
    -- Fraud
    fraud_score DECIMAL(5,4),
    fraud_flags JSONB DEFAULT '[]',
    risk_level VARCHAR(20),
    is_flagged BOOLEAN DEFAULT FALSE,
    verification_required BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    device_type VARCHAR(50),
    device_id VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    session_id VARCHAR(100),
    correlation_id VARCHAR(100),
    source_system VARCHAR(50),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (transaction_id, timestamp)
);

-- Indexes for transactions
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_sender ON transactions(sender_id);
CREATE INDEX IF NOT EXISTS idx_transactions_recipient ON transactions(recipient_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_fraud ON transactions(is_flagged, fraud_score);
CREATE INDEX IF NOT EXISTS idx_transactions_corridor ON transactions(origin_country, dest_region);
CREATE INDEX IF NOT EXISTS idx_transactions_channel ON transactions(channel_id);

-- Convert to hypertable
SELECT create_hypertable('transactions', 'timestamp', if_not_exists => TRUE);

-- ============================================
-- SENDER PROFILES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS sender_profiles (
    sender_id VARCHAR(50) PRIMARY KEY,
    
    -- Profile
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    kyc_level VARCHAR(20),
    registration_date DATE,
    country_of_residence VARCHAR(100),
    occupation VARCHAR(100),
    
    -- Statistics
    total_transactions INTEGER DEFAULT 0,
    total_sent_usd DECIMAL(15,2) DEFAULT 0,
    average_transaction_usd DECIMAL(15,2) DEFAULT 0,
    first_transaction_date DATE,
    last_transaction_date DATE,
    transaction_frequency_days DECIMAL(10,2),
    
    -- Time Windows
    txn_count_24h INTEGER DEFAULT 0,
    txn_amount_24h DECIMAL(15,2) DEFAULT 0,
    txn_count_7d INTEGER DEFAULT 0,
    txn_amount_7d DECIMAL(15,2) DEFAULT 0,
    txn_count_30d INTEGER DEFAULT 0,
    txn_amount_30d DECIMAL(15,2) DEFAULT 0,
    
    -- Patterns (JSONB for flexibility)
    preferred_channels JSONB DEFAULT '[]',
    common_recipients JSONB DEFAULT '[]',
    typical_amount_range JSONB DEFAULT '{}',
    peak_sending_days JSONB DEFAULT '[]',
    peak_sending_hours JSONB DEFAULT '[]',
    
    -- Risk
    risk_score DECIMAL(5,4) DEFAULT 0,
    risk_level VARCHAR(20) DEFAULT 'low',
    fraud_incidents INTEGER DEFAULT 0,
    chargebacks INTEGER DEFAULT 0,
    last_risk_assessment TIMESTAMPTZ,
    
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sender_risk ON sender_profiles(risk_level, risk_score);
CREATE INDEX IF NOT EXISTS idx_sender_country ON sender_profiles(country_of_residence);

-- ============================================
-- EXCHANGE RATES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS exchange_rates (
    rate_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    
    -- Currency Pair
    from_currency VARCHAR(3),
    to_currency VARCHAR(3),
    
    -- Rates
    mid_market_rate DECIMAL(10,4),
    buy_rate DECIMAL(10,4),
    sell_rate DECIMAL(10,4),
    spread_percentage DECIMAL(5,4),
    
    -- Provider Rates (stored as JSONB for flexibility)
    provider_rates JSONB DEFAULT '[]',
    best_provider VARCHAR(50),
    
    -- Analytics
    change_1h DECIMAL(10,4),
    change_24h DECIMAL(10,4),
    change_7d DECIMAL(10,4),
    volatility_24h DECIMAL(5,4),
    is_favorable BOOLEAN DEFAULT FALSE,
    recommendation VARCHAR(50),
    
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (rate_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_rates_timestamp ON exchange_rates(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rates_pair ON exchange_rates(from_currency, to_currency);
CREATE INDEX IF NOT EXISTS idx_rates_favorable ON exchange_rates(is_favorable, timestamp DESC);

SELECT create_hypertable('exchange_rates', 'timestamp', if_not_exists => TRUE);

-- ============================================
-- CORRIDOR ANALYTICS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS corridor_analytics (
    corridor_id VARCHAR(100),
    
    -- Corridor Info
    origin_country VARCHAR(100),
    origin_city VARCHAR(100),
    destination_country VARCHAR(100),
    destination_region VARCHAR(100),
    
    -- Time Window
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    window_type VARCHAR(20),
    
    -- Metrics
    transaction_count INTEGER DEFAULT 0,
    total_volume_usd DECIMAL(15,2) DEFAULT 0,
    average_transaction_usd DECIMAL(15,2) DEFAULT 0,
    median_transaction_usd DECIMAL(15,2) DEFAULT 0,
    
    unique_senders INTEGER DEFAULT 0,
    unique_recipients INTEGER DEFAULT 0,
    new_senders INTEGER DEFAULT 0,
    
    growth_rate_vs_previous DECIMAL(5,4),
    yoy_growth DECIMAL(5,4),
    
    -- Distribution (JSONB)
    distribution_by_amount JSONB DEFAULT '{}',
    distribution_by_channel JSONB DEFAULT '{}',
    distribution_by_hour JSONB DEFAULT '{}',
    
    -- Rate Analytics
    average_rate DECIMAL(10,4),
    best_rate DECIMAL(10,4),
    worst_rate DECIMAL(10,4),
    rate_volatility DECIMAL(5,4),
    
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (corridor_id, window_start, window_type)
);

CREATE INDEX IF NOT EXISTS idx_corridor_window ON corridor_analytics(window_start DESC, window_type);
CREATE INDEX IF NOT EXISTS idx_corridor_origin ON corridor_analytics(origin_country, origin_city);
CREATE INDEX IF NOT EXISTS idx_corridor_destination ON corridor_analytics(destination_country, destination_region);

-- ============================================
-- CHANNEL PERFORMANCE TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS channel_performance (
    channel_id VARCHAR(50),
    agent_id VARCHAR(50),
    
    -- Info
    channel_name VARCHAR(100),
    agent_name VARCHAR(255),
    channel_type VARCHAR(50),
    location VARCHAR(255),
    
    -- Time Window
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    
    -- Performance
    transaction_count INTEGER DEFAULT 0,
    transaction_volume_usd DECIMAL(15,2) DEFAULT 0,
    success_rate DECIMAL(5,4),
    failure_rate DECIMAL(5,4),
    
    avg_processing_time_ms INTEGER,
    median_processing_time_ms INTEGER,
    p95_processing_time_ms INTEGER,
    p99_processing_time_ms INTEGER,
    
    sla_compliance DECIMAL(5,4),
    uptime_percentage DECIMAL(5,2),
    
    -- Customer Metrics
    average_rating DECIMAL(3,2),
    total_ratings INTEGER DEFAULT 0,
    nps_score INTEGER,
    complaint_rate DECIMAL(5,4),
    
    -- Competitive
    market_share DECIMAL(5,4),
    rate_competitiveness VARCHAR(20),
    average_fees_usd DECIMAL(10,2),
    
    -- Issues
    current_issues JSONB DEFAULT '[]',
    resolved_today INTEGER DEFAULT 0,
    avg_resolution_time_minutes INTEGER,
    
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (channel_id, agent_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_channel_perf_window ON channel_performance(window_start DESC);
CREATE INDEX IF NOT EXISTS idx_channel_perf_rating ON channel_performance(average_rating DESC);
CREATE INDEX IF NOT EXISTS idx_channel_perf_success ON channel_performance(success_rate DESC);

-- ============================================
-- FRAUD ALERTS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    transaction_id VARCHAR(50),
    
    alert_type VARCHAR(50),
    severity VARCHAR(20),
    
    -- Details
    rule_triggered VARCHAR(100),
    threshold DECIMAL(15,2),
    actual_value DECIMAL(15,2),
    description TEXT,
    
    sender_id VARCHAR(50),
    fraud_score DECIMAL(5,4),
    
    recommended_action VARCHAR(50),
    auto_action_taken VARCHAR(50),
    
    -- Context (JSONB)
    context JSONB DEFAULT '{}',
    
    status VARCHAR(50) DEFAULT 'open',
    assigned_to VARCHAR(50),
    resolution_notes TEXT,
    resolved_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (alert_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_fraud_timestamp ON fraud_alerts(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_status ON fraud_alerts(status);
CREATE INDEX IF NOT EXISTS idx_fraud_severity ON fraud_alerts(severity, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_sender ON fraud_alerts(sender_id);
CREATE INDEX IF NOT EXISTS idx_fraud_transaction ON fraud_alerts(transaction_id);

SELECT create_hypertable('fraud_alerts', 'timestamp', if_not_exists => TRUE);

-- ============================================
-- GEOGRAPHIC ANALYTICS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS geo_analytics (
    geo_id VARCHAR(100),
    
    -- Location
    country VARCHAR(100),
    region VARCHAR(100),
    province VARCHAR(100),
    city VARCHAR(100),
    
    -- Time Window
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    window_type VARCHAR(20),
    
    -- Inflow Metrics
    total_received_php DECIMAL(15,2) DEFAULT 0,
    transaction_count INTEGER DEFAULT 0,
    unique_recipients INTEGER DEFAULT 0,
    average_transaction_php DECIMAL(15,2) DEFAULT 0,
    
    -- Top Origins (JSONB array)
    top_origin_countries JSONB DEFAULT '[]',
    
    -- Economic Impact
    gdp_contribution_estimate DECIMAL(10,8),
    per_capita_remittance DECIMAL(15,2),
    remittance_dependency_index DECIMAL(5,4),
    
    -- Growth
    mom_growth DECIMAL(5,4),
    yoy_growth DECIMAL(5,4),
    seasonality_index DECIMAL(5,4),
    
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (geo_id, window_start, window_type)
);

CREATE INDEX IF NOT EXISTS idx_geo_window ON geo_analytics(window_start DESC);
CREATE INDEX IF NOT EXISTS idx_geo_location ON geo_analytics(country, region, city);
CREATE INDEX IF NOT EXISTS idx_geo_volume ON geo_analytics(total_received_php DESC);

-- ============================================
-- MATERIALIZED VIEWS FOR DASHBOARD
-- ============================================

-- Real-time summary (last 24 hours)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_realtime_summary AS
SELECT 
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as txn_count,
    SUM(send_amount) as total_volume_usd,
    AVG(send_amount) as avg_transaction_usd,
    AVG(fraud_score) as avg_fraud_score,
    COUNT(CASE WHEN is_flagged = TRUE THEN 1 END) as flagged_count,
    COUNT(DISTINCT sender_id) as unique_senders,
    COUNT(DISTINCT channel_id) as active_channels
FROM transactions
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;

CREATE INDEX IF NOT EXISTS idx_mv_realtime_hour ON mv_realtime_summary(hour DESC);

-- Top corridors
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_corridors AS
SELECT 
    origin_country,
    dest_region,
    COUNT(*) as txn_count,
    SUM(send_amount) as total_volume_usd,
    AVG(send_amount) as avg_transaction_usd,
    COUNT(DISTINCT sender_id) as unique_senders
FROM transactions
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY origin_country, dest_region
ORDER BY total_volume_usd DESC
LIMIT 20;

-- Channel performance summary
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_channel_summary AS
SELECT 
    channel_id,
    channel_name,
    channel_type,
    COUNT(*) as txn_count,
    SUM(send_amount) as total_volume_usd,
    AVG(processing_time_ms) as avg_processing_time,
    COUNT(CASE WHEN status = 'completed' THEN 1 END)::DECIMAL / COUNT(*) as success_rate
FROM transactions
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY channel_id, channel_name, channel_type
ORDER BY total_volume_usd DESC;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO remitflow_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO remitflow_user;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'RemitFlow database initialized successfully!';
END $$;