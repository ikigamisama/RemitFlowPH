

import os
import sys
import time


# Wait for services to be ready
print("Waiting for services to initialize...")
time.sleep(15)

# Get processor configuration
PROCESSOR_TYPE = os.getenv('PROCESSOR_TYPE', 'fraud')

# Database configuration
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'remitflow'),
    'user': os.getenv('POSTGRES_USER', 'remitflow_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'remitflow_pass')
}

# Kafka configuration
KAFKA_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:19092')

# Redis configuration
REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', '6379'))
}

print(f"Starting {PROCESSOR_TYPE} processor...")
print(f"Kafka: {KAFKA_SERVERS}")
print(f"PostgreSQL: {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}")
print(f"Redis: {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}")

try:
    if PROCESSOR_TYPE == 'fraud':
        from fraud_detector import FraudDetector

        processor = FraudDetector(
            kafka_servers=KAFKA_SERVERS,
            postgres_config=POSTGRES_CONFIG,
            redis_config=REDIS_CONFIG
        )

        print("Fraud detection processor initialized")
        processor.run()

    elif PROCESSOR_TYPE == 'aggregation':
        from aggregator import AggregationProcessor

        processor = AggregationProcessor(
            kafka_servers=KAFKA_SERVERS,
            postgres_config=POSTGRES_CONFIG,
            redis_config=REDIS_CONFIG
        )

        print("Aggregation processor initialized")
        processor.run()

    elif PROCESSOR_TYPE == 'analytics':
        from analytics import AnalyticsProcessor

        processor = AnalyticsProcessor(
            kafka_servers=KAFKA_SERVERS,
            postgres_config=POSTGRES_CONFIG,
            redis_config=REDIS_CONFIG
        )

        print("Analytics processor initialized")
        processor.run()

    else:
        print(f"Unknown processor type: {PROCESSOR_TYPE}")
        print("Valid types: fraud, aggregation, analytics")
        sys.exit(1)

except ImportError as e:
    print(f"Failed to import processor module: {e}")
    print("Make sure all required Python files are present")
    sys.exit(1)

except Exception as e:
    print(f"Fatal error in {PROCESSOR_TYPE} processor: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
