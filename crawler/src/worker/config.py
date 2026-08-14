import os

RABBIT_URL = os.getenv("RABBIT_URL", "amqp://admin:12345678a@192.168.1.40")
QUEUE_NAME = os.getenv("QUEUE_NAME", "crawl.smiles")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:12345678@192.168.1.40:5432/milesdb")
PREFETCH_COUNT = int(os.getenv("PREFETCH_COUNT", "1"))
