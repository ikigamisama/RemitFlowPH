import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import os


API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')

# Page config
st.set_page_config(
    page_title="RemitFlow PH - Dashboard",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .alert-high {
        background-color: #ffebee;
        border-left: 4px solid #f44336;
        padding: 10px;
        margin: 5px 0;
    }
    .alert-medium {
        background-color: #fff3e0;
        border-left: 4px solid #ff9800;
        padding: 10px;
        margin: 5px 0;
    }
</style>
""", unsafe_allow_html=True)

# Helper functions


def fetch_api(endpoint, params=None):
    """Fetch data from API"""
    try:
        response = requests.get(
            f"{API_BASE_URL}{endpoint}", params=params, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        return None


def format_currency(amount, currency="USD"):
    """Format currency values"""
    if currency == "PHP":
        return f"₱{amount:,.2f}"
    return f"${amount:,.2f}"


# Sidebar
with st.sidebar:
    st.title("💸 RemitFlow PH")
    st.markdown("### Real-Time OFW Remittance Intelligence")

    # Auto-refresh toggle
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)

    # Time range selector
    time_range = st.selectbox(
        "Time Range",
        options=["24h", "7d", "30d"],
        index=0
    )

    # Navigation
    st.markdown("---")
    st.markdown("### 📊 Dashboard")

    # System status
    st.markdown("---")
    st.markdown("### System Status")

    health_data = fetch_api("/health")
    if health_data:
        if health_data['status'] == 'healthy':
            st.success("✅ All systems operational")
        else:
            st.warning("⚠️ System degraded")

        st.caption(f"Database: {health_data.get('database', 'unknown')}")
        st.caption(f"Redis: {health_data.get('redis', 'unknown')}")

# Main content
st.title("📊 Real-Time Remittance Dashboard")

# Auto-refresh logic
if auto_refresh:
    st_autorefresh = st.empty()
    with st_autorefresh:
        st.info("Auto-refreshing every 30 seconds...")
    time.sleep(0.1)  # Small delay for display
    placeholder = st.empty()
else:
    placeholder = st.container()

with placeholder.container():

    # Fetch dashboard metrics
    metrics_data = fetch_api("/api/v1/dashboard/metrics")

    if metrics_data:
        # Top metrics row
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                "Total Transactions (24h)",
                f"{metrics_data['total_transactions_24h']:,}",
                delta=None
            )

        with col2:
            st.metric(
                "Total Volume (24h)",
                format_currency(metrics_data['total_volume_24h']),
                delta=None
            )

        with col3:
            st.metric(
                "Avg Transaction",
                format_currency(metrics_data['average_transaction']),
                delta=None
            )

        with col4:
            st.metric(
                "Success Rate",
                f"{metrics_data['success_rate']*100:.1f}%",
                delta=None
            )

        with col5:
            alert_delta = - \
                metrics_data['fraud_alerts_24h'] if metrics_data['fraud_alerts_24h'] > 0 else 0
            st.metric(
                "Fraud Alerts (24h)",
                metrics_data['fraud_alerts_24h'],
                delta=alert_delta,
                delta_color="inverse"
            )

    st.markdown("---")

    # Two column layout
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("📈 Transaction Volume Trend")

        # Fetch hourly data
        hourly_data = fetch_api(
            "/api/v1/transactions/hourly", params={"hours": 24})

        if hourly_data and hourly_data.get('hourly_data'):
            df_hourly = pd.DataFrame(hourly_data['hourly_data'])
            df_hourly['hour'] = pd.to_datetime(df_hourly['hour'])

            # Create dual-axis chart
            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=df_hourly['hour'],
                y=df_hourly['count'],
                name='Transaction Count',
                marker_color='lightblue',
                yaxis='y'
            ))

            fig.add_trace(go.Scatter(
                x=df_hourly['hour'],
                y=df_hourly['volume'],
                name='Volume ($)',
                mode='lines+markers',
                marker_color='darkblue',
                yaxis='y2'
            ))

            fig.update_layout(
                yaxis=dict(title='Transaction Count'),
                yaxis2=dict(title='Volume ($)', overlaying='y', side='right'),
                hovermode='x unified',
                height=400,
                showlegend=True
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hourly data available")

    with col_right:
        st.subheader("⚠️ Recent Fraud Alerts")

        # Fetch fraud alerts
        fraud_data = fetch_api("/api/v1/fraud/alerts", params={"limit": 5})

        if fraud_data and fraud_data.get('alerts'):
            for alert in fraud_data['alerts']:
                severity = alert['severity']
                alert_class = f"alert-{severity}" if severity in [
                    'high', 'medium'] else ""

                st.markdown(f"""
                <div class="{alert_class}">
                    <strong>{alert['alert_type'].replace('_', ' ').title()}</strong><br>
                    Fraud Score: {alert['fraud_score']:.2f}<br>
                    <small>{alert['timestamp'][:19]}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ No recent fraud alerts")

    st.markdown("---")

    # Three column layout for analytics
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("🌍 Top Corridors")

        corridors_data = fetch_api(
            "/api/v1/corridors", params={"time_range": time_range, "limit": 10})

        if corridors_data and isinstance(corridors_data, list):
            df_corridors = pd.DataFrame(corridors_data)

            fig = px.bar(
                df_corridors.head(10),
                x='total_volume',
                y='corridor_id',
                orientation='h',
                title=f"Top 10 Corridors ({time_range})",
                labels={
                    'total_volume': 'Volume ($)', 'corridor_id': 'Corridor'},
                color='total_volume',
                color_continuous_scale='Blues'
            )

            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No corridor data available")

    with col2:
        st.subheader("📱 Channel Performance")

        channels_data = fetch_api(
            "/api/v1/channels/performance", params={"time_range": time_range})

        if channels_data and isinstance(channels_data, list):
            df_channels = pd.DataFrame(channels_data)

            fig = px.pie(
                df_channels,
                values='transaction_count',
                names='channel_name',
                title=f"Transaction Distribution ({time_range})",
                hole=0.4
            )

            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No channel data available")

    with col3:
        st.subheader("🎯 Success Rates")

        if channels_data and isinstance(channels_data, list):
            df_channels = pd.DataFrame(channels_data)
            df_channels['success_rate_pct'] = df_channels['success_rate'] * 100

            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=df_channels['channel_name'],
                y=df_channels['success_rate_pct'],
                marker_color=df_channels['success_rate_pct'].apply(
                    lambda x: 'green' if x >= 95 else 'orange' if x >= 90 else 'red'
                ),
                text=df_channels['success_rate_pct'].apply(
                    lambda x: f"{x:.1f}%"),
                textposition='auto'
            ))

            fig.update_layout(
                title=f"Channel Success Rates ({time_range})",
                yaxis_title="Success Rate (%)",
                xaxis_title="Channel",
                height=400,
                showlegend=False
            )

            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Recent transactions table
    st.subheader("📋 Recent Transactions")

    transactions_data = fetch_api(
        "/api/v1/transactions/recent", params={"limit": 20})

    if transactions_data and isinstance(transactions_data, list):
        df_transactions = pd.DataFrame(transactions_data)

        # Format display columns
        display_df = df_transactions[[
            'transaction_id', 'timestamp', 'sender_name', 'recipient_name',
            'send_amount', 'send_currency', 'status', 'fraud_score', 'risk_level'
        ]].copy()

        # Add visual indicators
        display_df['status_icon'] = display_df['status'].apply(
            lambda x: '✅' if x == 'completed' else '⏳' if x == 'processing' else '❌'
        )

        display_df['risk_icon'] = display_df['risk_level'].apply(
            lambda x: '🔴' if x == 'high' else '🟡' if x == 'medium' else '🟢'
        )

        # Style the dataframe
        st.dataframe(
            display_df,
            use_container_width=True,
            height=400,
            hide_index=True
        )
    else:
        st.info("No recent transactions available")

    # Footer
    st.markdown("---")
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Auto-refresh
if auto_refresh:
    time.sleep(30)
    st.rerun()
