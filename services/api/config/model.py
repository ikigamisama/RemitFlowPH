from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class Transaction(BaseModel):
    transaction_id: str
    timestamp: datetime
    sender_name: str
    recipient_name: str
    send_amount: float
    send_currency: str
    receive_amount: float
    status: str
    fraud_score: float
    risk_level: str


class DashboardMetrics(BaseModel):
    total_transactions_24h: int
    total_volume_24h: float
    average_transaction: float
    fraud_alerts_24h: int
    active_senders: int
    success_rate: float


class CorridorData(BaseModel):
    corridor_id: str
    origin_country: str
    destination_region: str
    transaction_count: int
    total_volume: float
    average_transaction: float


class ChannelPerformance(BaseModel):
    channel_name: str
    transaction_count: int
    success_rate: float
    avg_processing_time: int
    average_rating: Optional[float]
