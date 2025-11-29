from synthetic_data_crafter import SyntheticDataCrafter
from forex_python.converter import CurrencyRates
from datetime import datetime, timezone, timedelta
from kafka import KafkaProducer
import json
import random
import time
import os
import psycopg2

KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'KAFKA_BOOTSTRAP_SERVERS', 'localhost:19092')
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'remitflow'),
    'user': os.getenv('POSTGRES_USER', 'remitflow_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'remitflow_pass')
}
GENERATION_RATE = int(os.getenv('GENERATION_RATE', '10'))

ORIGIN_COUNTRIES = {
    'Israel': ['Tel Aviv', 'Jerusalem', 'Haifa'],
    'Singapore': ['Singapore'],
    'Hong Kong': ['Hong Kong', 'Kowloon', 'New Territories'],
    'Japan': ['Tokyo', 'Osaka', 'Yokohama', 'Nagoya', 'Sapporo', 'Fukuoka', 'Kobe', 'Hiroshima'],
    'South Korea': ['Seoul', 'Busan', 'Incheon', 'Daegu', 'Daejeon', 'Ulsan'],
    'Malaysia': ['Kuala Lumpur', 'Petaling Jaya', 'Johor Bahru', 'Penang'],
    'USA': ['New York', 'Los Angeles', 'San Francisco', 'Chicago', 'Las Vegas', 'Houston', 'Seattle', 'San Diego', 'Honolulu', 'Miami', 'Phoenix'],
    'Canada': ['Toronto', 'Vancouver', 'Calgary', 'Winnipeg', 'Ottawa', 'Edmonton', 'Montreal', 'Victoria'],
    'United Kingdom': ['London', 'Manchester', 'Liverpool', 'Birmingham', 'Leeds', 'Glasgow', 'Edinburgh'],

    # Countries using EUR
    'Italy': ['Rome', 'Milan', 'Naples', 'Turin', 'Florence', 'Venice', 'Genoa'],
    'Germany': ['Berlin', 'Munich', 'Hamburg', 'Frankfurt', 'Cologne', 'Stuttgart'],
    'Spain': ['Madrid', 'Barcelona', 'Valencia', 'Seville'],
    'France': ['Paris', 'Lyon', 'Marseille', 'Nice', 'Toulouse'],
    'Netherlands': ['Amsterdam', 'Rotterdam', 'The Hague', 'Utrecht'],

    # Scandinavia
    'Norway': ['Oslo', 'Bergen', 'Stavanger'],
    'Sweden': ['Stockholm', 'Gothenburg', 'Malmo'],
    'Denmark': ['Copenhagen', 'Aarhus', 'Odense'],

    'Australia': ['Sydney', 'Melbourne', 'Brisbane', 'Perth', 'Adelaide', 'Canberra', 'Darwin'],
    'New Zealand': ['Auckland', 'Wellington', 'Christchurch', 'Hamilton'],
    'South Africa': ['Johannesburg', 'Cape Town', 'Durban'],
    'Brazil': ['Sao Paulo', 'Rio de Janeiro', 'Brasilia'],

    # NEW supported countries
    'China': ['Beijing', 'Shanghai', 'Shenzhen', 'Guangzhou'],
    'India': ['Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Kolkata', 'Hyderabad'],
    'Mexico': ['Mexico City', 'Guadalajara', 'Monterrey'],
    'Thailand': ['Bangkok', 'Chiang Mai', 'Phuket'],
    'Switzerland': ['Zurich', 'Geneva', 'Basel'],
    'Czech Republic': ['Prague', 'Brno', 'Ostrava'],
    'Hungary': ['Budapest', 'Debrecen', 'Szeged'],
    'Poland': ['Warsaw', 'Krakow', 'Gdansk'],
    'Romania': ['Bucharest', 'Cluj-Napoca', 'Timisoara'],
    'Iceland': ['Reykjavik'],
    'Turkey': ['Istanbul', 'Ankara', 'Izmir'],
    'Indonesia': ['Jakarta', 'Surabaya', 'Bandung', 'Medan']
}

PH_REGIONS = {
    'NCR': ['Manila', 'Quezon City', 'Makati', 'Pasig', 'Taguig', 'Pasay', 'Caloocan', 'Mandaluyong'],
    'Region I': ['Vigan', 'Laoag', 'Urdaneta', 'Dagupan'],
    'Region II': ['Tuguegarao', 'Ilagan', 'Santiago'],
    'Region III': ['Angeles', 'San Fernando', 'Tarlac', 'Olongapo', 'Malolos', 'Mabalacat'],
    'Region IV-A': ['Batangas', 'Cavite', 'Laguna', 'Lucena', 'Tayabas'],
    'MIMAROPA': ['Puerto Princesa', 'Calapan', 'Odiongan'],
    'Region V': ['Legazpi', 'Naga', 'Sorsogon'],
    'Region VI': ['Iloilo City', 'Bacolod', 'Roxas City'],
    'Region VII': ['Cebu City', 'Mandaue', 'Lapu-Lapu', 'Dumaguete'],
    'Region VIII': ['Tacloban', 'Ormoc', 'Catbalogan'],
    'Region IX': ['Zamboanga City', 'Dipolog', 'Pagadian'],
    'Region X': ['Cagayan de Oro', 'Valencia', 'Iligan'],
    'Region XI': ['Davao City', 'Tagum', 'Panabo'],
    'Region XII': ['General Santos', 'Koronadal', 'Tacurong'],
    'CARAGA': ['Butuan', 'Surigao', 'Tandag'],
    'CAR': ['Baguio', 'La Trinidad', 'Tabuk'],
    'BARMM': ['Cotabato City', 'Marawi', 'Jolo', 'Bongao']
}

CHANNELS = [
    {'id': 'CH_001', 'name': 'GCash', 'type': 'ewallet'},
    {'id': 'CH_002', 'name': 'Maya', 'type': 'ewallet'},
    {'id': 'CH_003', 'name': 'BDO', 'type': 'bank'},
    {'id': 'CH_004', 'name': 'BPI', 'type': 'bank'},
    {'id': 'CH_005', 'name': 'Metrobank', 'type': 'bank'},
    {'id': 'CH_006', 'name': 'PNB', 'type': 'bank'},
    {'id': 'CH_007', 'name': 'Landbank', 'type': 'bank'},
    {'id': 'CH_008', 'name': 'Western Union', 'type': 'remittance_center'},
    {'id': 'CH_009', 'name': 'MoneyGram', 'type': 'remittance_center'},
    {'id': 'CH_010', 'name': 'Ria', 'type': 'remittance_center'},
    {'id': 'CH_011', 'name': 'Cebuana Lhuillier', 'type': 'pawnshop'},
    {'id': 'CH_012', 'name': 'Palawan Pawnshop', 'type': 'pawnshop'},
    {'id': 'CH_013', 'name': 'TrueMoney', 'type': 'cash_agent'},
    {'id': 'CH_014', 'name': 'Coins.ph', 'type': 'crypto/ewallet'}
]

AGENTS = [
    {'id': 'AGT_001', 'name': 'Western Union'},
    {'id': 'AGT_002', 'name': 'MoneyGram'},
    {'id': 'AGT_003', 'name': 'Remitly'},
    {'id': 'AGT_004', 'name': 'Wise (TransferWise)'},
    {'id': 'AGT_005', 'name': 'WorldRemit'},
    {'id': 'AGT_006', 'name': 'Xoom (PayPal)'},
    {'id': 'AGT_007', 'name': 'Ria Money Transfer'},
    {'id': 'AGT_008', 'name': 'PayRemit'},
    {'id': 'AGT_009', 'name': 'Cebuana Lhuillier Pera Padala'},
    {'id': 'AGT_010', 'name': 'Palawan Express Pera Padala'},
    {'id': 'AGT_011', 'name': 'Al Ansari Exchange (UAE)'},
    {'id': 'AGT_012', 'name': 'Al Rajhi Bank Remittance (Saudi Arabia)'},
    {'id': 'AGT_013', 'name': 'BDO Remit'},
    {'id': 'AGT_014', 'name': 'BPI Remittance'},
    {'id': 'AGT_015', 'name': 'Metrobank Remit'}
]


CURRENCY_MAP = [
    {'country_name': 'Israel', 'symbol': 'ILS',
        'value': CurrencyRates().get_rates('PHP')['ILS']},
    {'country_name': 'Singapore', 'symbol': 'SGD',
        'value': CurrencyRates().get_rates('PHP')['SGD']},
    {'country_name': 'Hong Kong', 'symbol': 'HKD',
        'value': CurrencyRates().get_rates('PHP')['HKD']},
    {'country_name': 'Japan', 'symbol': 'JPY',
        'value': CurrencyRates().get_rates('PHP')['JPY']},
    {'country_name': 'South Korea', 'symbol': 'KRW',
        'value': CurrencyRates().get_rates('PHP')['KRW']},
    {'country_name': 'Malaysia', 'symbol': 'MYR',
        'value': CurrencyRates().get_rates('PHP')['MYR']},
    {'country_name': 'USA', 'symbol': 'USD',
        'value': CurrencyRates().get_rates('PHP')['USD']},
    {'country_name': 'Canada', 'symbol': 'CAD',
        'value': CurrencyRates().get_rates('PHP')['CAD']},
    {'country_name': 'United Kingdom', 'symbol': 'GBP',
        'value': CurrencyRates().get_rates('PHP')['GBP']},

    # European Union (EUR)
    {'country_name': 'Italy', 'symbol': 'EUR',
        'value': CurrencyRates().get_rates('PHP')['EUR']},
    {'country_name': 'Germany', 'symbol': 'EUR',
        'value': CurrencyRates().get_rates('PHP')['EUR']},
    {'country_name': 'Spain', 'symbol': 'EUR',
        'value': CurrencyRates().get_rates('PHP')['EUR']},
    {'country_name': 'France', 'symbol': 'EUR',
        'value': CurrencyRates().get_rates('PHP')['EUR']},
    {'country_name': 'Netherlands', 'symbol': 'EUR',
        'value': CurrencyRates().get_rates('PHP')['EUR']},

    # Scandinavia
    {'country_name': 'Norway', 'symbol': 'NOK',
        'value': CurrencyRates().get_rates('PHP')['NOK']},
    {'country_name': 'Sweden', 'symbol': 'SEK',
        'value': CurrencyRates().get_rates('PHP')['SEK']},
    {'country_name': 'Denmark', 'symbol': 'DKK',
        'value': CurrencyRates().get_rates('PHP')['DKK']},

    # Others available in ForexPython
    {'country_name': 'Australia', 'symbol': 'AUD',
        'value': CurrencyRates().get_rates('PHP')['AUD']},
    {'country_name': 'New Zealand', 'symbol': 'NZD',
        'value': CurrencyRates().get_rates('PHP')['NZD']},
    {'country_name': 'South Africa', 'symbol': 'ZAR',
        'value': CurrencyRates().get_rates('PHP')['ZAR']},
    {'country_name': 'Brazil', 'symbol': 'BRL',
        'value': CurrencyRates().get_rates('PHP')['BRL']},

    # NEW additions (supported currencies)
    {'country_name': 'China', 'symbol': 'CNY',
        'value': CurrencyRates().get_rates('PHP')['CNY']},
    {'country_name': 'India', 'symbol': 'INR',
        'value': CurrencyRates().get_rates('PHP')['INR']},
    {'country_name': 'Mexico', 'symbol': 'MXN',
        'value': CurrencyRates().get_rates('PHP')['MXN']},
    {'country_name': 'Thailand', 'symbol': 'THB',
        'value': CurrencyRates().get_rates('PHP')['THB']},
    {'country_name': 'Switzerland', 'symbol': 'CHF',
        'value': CurrencyRates().get_rates('PHP')['CHF']},
    {'country_name': 'Czech Republic', 'symbol': 'CZK',
        'value': CurrencyRates().get_rates('PHP')['CZK']},
    {'country_name': 'Hungary', 'symbol': 'HUF',
        'value': CurrencyRates().get_rates('PHP')['HUF']},
    {'country_name': 'Poland', 'symbol': 'PLN',
        'value': CurrencyRates().get_rates('PHP')['PLN']},
    {'country_name': 'Romania', 'symbol': 'RON',
        'value': CurrencyRates().get_rates('PHP')['RON']},
    {'country_name': 'Iceland', 'symbol': 'ISK',
        'value': CurrencyRates().get_rates('PHP')['ISK']},
    {'country_name': 'Turkey', 'symbol': 'TRY',
        'value': CurrencyRates().get_rates('PHP')['TRY']},
    {'country_name': 'Indonesia', 'symbol': 'IDR',
        'value': CurrencyRates().get_rates('PHP')['IDR']},
]


class TransactionGenerator:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        self.conn = None
        self.transaction_counter = 0
        self.SENDER_POOL = []

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**POSTGRES_CONFIG)
        except Exception as e:
            print(f"Failed to connect to PostgreSQL: {e}")

    def initialize_senders(self, count=100):
        country = random.choice(list(ORIGIN_COUNTRIES.keys()))
        sender_schema = [
            {
                "label": 'sender_id',
                "key_label": "character_sequence",
                "group": "advanced",
                "options": {"format": "OFW_#####_#####"}
            },
            {
                "label": 'name',
                "key_label": "full_name",
                "group": "personal",
                "options": {}
            },
            {
                "label": 'email',
                "key_label": "email_address",
                "group": "it",
                "options": {}
            },
            {
                "label": 'phone',
                "key_label": "phone",
                "group": "location",
                "options": {'format': "+639#########"}
            },
            {
                "label": "kyc_level",
                "key_label": "custom_list",
                "group": "basic",
                "options": {"custom_format": "basic,verified,enhanced"}
            },
            {
                "label": "customer_since",
                "key_label": "datetime",
                "group": "basic",
                "options": {"from_date": "01/01/2020"}
            },
            {
                "label": 'country',
                "key_label": "lambda",
                "group": "advanced",
                "options": {'func': lambda: country}
            },
            {
                "label": 'city',
                "key_label": "lambda",
                "group": "advanced",
                "options": {'func': lambda: random.choice(ORIGIN_COUNTRIES[country])}
            },
            {
                "label": 'typical_amount',
                "key_label": "number",
                "group": "basic",
                "options": {'min': 20, 'max': 1000}
            },
            {
                "label": 'frequency_days',
                "key_label": "number",
                "group": "basic",
                "options": {'min': 7, 'max': 30}
            },
        ]

        self.SENDER_POOL.extend(SyntheticDataCrafter(
            sender_schema).many(count).data)

    def generate_transaction(self):
        self.transaction_counter += 1

        sender = random.choice(self.SENDER_POOL)
        origin_country = sender['country']
        origin_city = sender['city']
        base_amount = sender['typical_amount']

        curreny_map = random.choice(CURRENCY_MAP)
        origin_currency = curreny_map['symbol']
        exchange_rate = curreny_map['value']

        dest_region = random.choice(list(PH_REGIONS.keys()))
        dest_city = random.choice(PH_REGIONS[dest_region])

        send_amount = max(
            50, min(5000, round(random.gauss(base_amount, base_amount * 0.3), 2)))
        receive_amount = round(send_amount * exchange_rate, 2)
        fees = round(random.uniform(5, 15), 2)

        fraud_score = random.betavariate(1, 20)
        is_flagged = fraud_score > 0.7
        risk_level = 'high' if fraud_score > 0.7 else 'medium' if fraud_score > 0.4 else 'low'

        status = None
        status_roll = random.random()
        if status_roll < 0.95:
            status = 'completed'
            processing_time = random.randint(1000, 5000)
        elif status_roll < 0.98:
            status = 'processing'
            processing_time = random.randint(5000, 15000)
        else:
            status = 'failed'
            processing_time = random.randint(500, 2000)

        timestamp = datetime.now(timezone.utc)
        country = random.choice(CURRENCY_MAP)
        channel = random.choice(CHANNELS)
        agent = random.choice(AGENTS)

        SCHEMA = {
            'transaction': [
                {
                    "label": 'transaction_id',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: f'TXN_{timestamp.strftime("%Y%m%d")}_{str(random.randint(1, 99999)).zfill(6)}'}
                },
                {
                    "label": 'timestamp',
                    "key_label": "current_timestamp",
                    "group": "basic",
                    "options": {"format": "%Y-%m-%dT%H:%M:%S.%fZ"}
                },
                {
                    "label": 'event_type',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: 'remittance_completed' if status == 'completed' else 'remittance_initiated'}
                },

                {
                    "label": 'completion_timestamp',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: (timestamp + timedelta(milliseconds=processing_time)).isoformat() if status == 'completed' else None}
                },
                {
                    "label": 'status',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: status}
                },
                {
                    "label": 'processing_time_ms',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: processing_time}
                },
                {
                    "label": 'completion_timestamp',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: (timestamp + timedelta(milliseconds=processing_time)).isoformat() if status == 'completed' else None}
                },
                {
                    "label": 'fraud_score',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: round(fraud_score, 4)}
                },
                {
                    "label": 'fraud_flags',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: []}
                },
                {
                    "label": 'risk_level',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: risk_level}
                },
                {
                    "label": 'is_flagged',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: is_flagged}
                },
                {
                    "label": 'verification_required',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: is_flagged}
                },
                {
                    "label": 'session_id',
                    "key_label": "character_sequence",
                    "group": "advanced",
                    "options": {"format": "SESSION_%%%%_%%%%"}
                },
                {
                    "label": 'correlation_id',
                    "key_label": "character_sequence",
                    "group": "advanced",
                    "options": {"format": "CORR_###"}
                },
                {
                    "label": "source_system",
                    "key_label": "custom_list",
                    "group": "basic",
                    "options": {"custom_format": "mobile_app,web_portal,agent_terminal"}
                },

            ],
            'recipient': [
                {
                    "label": 'recipient_id',
                    "key_label": "character_sequence",
                    "group": "advanced",
                    "options": {"format": "RCP_####_####"}
                },
                {
                    "label": 'recipient_name',
                    "key_label": "full_name",
                    "group": "personal",
                    "options": {}
                },
                {
                    "label": 'recipient_phone',
                    "key_label": "phone",
                    "group": "location",
                    "options": {'format': "+639#########"}
                },
                {
                    "label": "relationship",
                    "key_label": "custom_list",
                    "group": "basic",
                    "options": {"custom_format": "spouse,parent,sibling,relative,other"}
                },
                {
                    "label": 'account_number',
                    "key_label": "number",
                    "group": "basic",
                    "options": {'min': 1000000000, 'max': 9999999999}
                },
                {
                    "label": 'account_type',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: channel['type']}
                },
            ],
            'destination': [
                {
                    "label": 'country',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: 'Philippines'}
                },
                {
                    "label": 'province',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: dest_region}
                },
                {
                    "label": 'city',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: dest_city}
                },
                {
                    "label": 'barangay',
                    "key_label": "street_name",
                    "group": "location",
                    "options": {}
                },
                {
                    "label": 'region',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: dest_region}
                },
            ],
            'channel': [
                {
                    "label": 'channel_id',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: channel['id']}
                },
                {
                    "label": 'channel_name',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: channel['name']}
                },
                {
                    "label": 'channel_type',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: channel['type']}
                },
                {
                    "label": 'agent_id',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: agent['id']}
                },
                {
                    "label": 'agent_name',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: agent['name']}
                },
                {
                    "label": 'branch_code',
                    "key_label": "lambda",
                    "group": "advanced",
                    "options": {'func': lambda: f"{origin_city[:3].upper()}_{random.randint(1, 9):03d}"}
                },
            ],
            'device_info': [
                {
                    "label": "device_type",
                    "key_label": "custom_list",
                    "group": "basic",
                    "options": {"custom_format": "mobile,web,kiosk"}
                },
                {
                    "label": "device_id",
                    "key_label": "character_sequence",
                    "group": "advanced",
                    "options": {"format": "DEV_%%%%%%%%"}
                },
                {
                    "label": "ip_address",
                    "key_label": "ip_address_v4",
                    "group": "it",
                    "options": {}
                },
                {
                    "label": "user_agent",
                    "key_label": "user_agent",
                    "group": "it",
                    "options": {}
                },
            ]
        }

        transaction = SyntheticDataCrafter(SCHEMA['transaction']).one()
        recipient = SyntheticDataCrafter(SCHEMA['recipient']).one()
        destination = SyntheticDataCrafter(SCHEMA['destination']).one()
        channel = SyntheticDataCrafter(SCHEMA['channel']).one()
        device_info = SyntheticDataCrafter(SCHEMA['device_info']).one()
        transaction['recipient'] = recipient
        transaction['destination'] = destination
        transaction['channel'] = channel
        transaction['device_info'] = device_info
        transaction['sender'] = {
            'sender_id': sender['sender_id'],
            'sender_name': sender['name'],
            'sender_phone': sender['phone'],
            'sender_email': sender['email'],
            'kyc_level': sender['kyc_level'],
            'customer_since': sender['customer_since']
        }
        transaction['amount'] = {
            'send_amount': send_amount,
            'send_currency': origin_currency,
            'receive_amount': receive_amount,
            'receive_currency': 'PHP',
            'exchange_rate': round(exchange_rate, 4),
            'fees': fees,
            'total_deducted': round(send_amount - fees, 2)
        }
        transaction['origin'] = {
            'country': origin_country,
            'city': origin_city,
            'region': origin_city,
        }

        return transaction

    def send_to_kafka(self, transaction):
        try:
            self.producer.send('remittance-transactions', value=transaction)
            self.producer.flush()
            return True
        except Exception as e:
            print(f"Failed to send to Kafka: {e}")
            return False

    def save_to_postgres(self, transaction):
        try:
            cursor = self.conn.cursor()

            sql = """
                INSERT INTO transactions (
                    transaction_id, timestamp, event_type,
                    sender_id, sender_name, sender_phone, sender_email, sender_kyc_level, sender_customer_since,
                    recipient_id, recipient_name, recipient_phone, recipient_relationship, 
                    recipient_account_number, recipient_account_type,
                    send_amount, send_currency, receive_amount, receive_currency, 
                    exchange_rate, fees, total_deducted,
                    origin_country, origin_city, origin_region,
                    dest_country, dest_province, dest_city, dest_barangay, dest_region,
                    channel_id, channel_name, channel_type, agent_id, agent_name, branch_code,
                    status, processing_time_ms, completion_timestamp, failure_reason,
                    fraud_score, fraud_flags, risk_level, is_flagged, verification_required,
                    device_type, device_id, ip_address, user_agent, session_id, correlation_id, source_system
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
            """

            cursor.execute(sql, (
                transaction['transaction_id'],
                transaction['timestamp'],
                transaction['event_type'],
                transaction['sender']['sender_id'],
                transaction['sender']['sender_name'],
                transaction['sender']['sender_phone'],
                transaction['sender']['sender_email'],
                transaction['sender']['kyc_level'],
                transaction['sender']['customer_since'],
                transaction['recipient']['recipient_id'],
                transaction['recipient']['recipient_name'],
                transaction['recipient']['recipient_phone'],
                transaction['recipient']['relationship'],
                transaction['recipient']['account_number'],
                transaction['recipient']['account_type'],
                transaction['amount']['send_amount'],
                transaction['amount']['send_currency'],
                transaction['amount']['receive_amount'],
                transaction['amount']['receive_currency'],
                transaction['amount']['exchange_rate'],
                transaction['amount']['fees'],
                transaction['amount']['total_deducted'],
                transaction['origin']['country'],
                transaction['origin']['city'],
                transaction['origin']['region'],
                transaction['destination']['country'],
                transaction['destination']['province'],
                transaction['destination']['city'],
                transaction['destination']['barangay'],
                transaction['destination']['region'],
                transaction['channel']['channel_id'],
                transaction['channel']['channel_name'],
                transaction['channel']['channel_type'],
                transaction['channel']['agent_id'],
                transaction['channel']['agent_name'],
                transaction['channel']['branch_code'],
                transaction['status'],
                transaction['processing_time_ms'],
                transaction['completion_timestamp'],
                transaction['failure_reason'],
                transaction['fraud_score'],
                json.dumps(transaction['fraud_flags']),
                transaction['risk_level'],
                transaction['is_flagged'],
                transaction['verification_required'],
                transaction['device_info']['device_type'],
                transaction['device_info']['device_id'],
                transaction['device_info']['ip_address'],
                transaction['device_info']['user_agent'],
                transaction['session_id'],
                transaction['correlation_id'],
                transaction['source_system']
            ))

            self.conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Failed to save to PostgreSQL: {e}")
            self.conn.rollback()
            return False

    def run(self):
        """Main generation loop"""
        print(
            f"Starting transaction generator at {GENERATION_RATE} txn/min")

        self.connect_db()

        senders_count = random.randint(100, 1000)
        self.initialize_senders(count=senders_count)

        interval = 60.0 / GENERATION_RATE  # seconds between transactions

        try:
            while True:
                transaction = self.generate_transaction()

                # Kafka
                print("[DEBUG] Sending to Kafka...")
                try:
                    kafka_success = self.send_to_kafka(transaction)
                    print(f"[DEBUG] Kafka result: {kafka_success}")
                except Exception as e:
                    print(f"[ERROR] Failed to send to Kafka: {e}")
                    kafka_success = False

                # Database
                print("[DEBUG] Saving to PostgreSQL...")
                try:
                    db_success = self.save_to_postgres(transaction)
                    print(f"[DEBUG] DB result: {db_success}")
                except Exception as e:
                    print(f"[ERROR] Failed to save to database: {e}")
                    db_success = False

                if kafka_success and db_success:
                    print(
                        f"[INFO] Generated transaction {transaction['transaction_id']}")
                else:
                    print(
                        "[WARN] Transaction failed to send to one or both destinations.")

                time.sleep(interval)

        except KeyboardInterrupt:
            print("Shutting down generator...")
        finally:
            if self.producer:
                self.producer.close()
            if self.conn:
                self.conn.close()


if __name__ == '__main__':
    # Wait for services to be ready
    time.sleep(10)

    generator = TransactionGenerator()
    generator.run()
