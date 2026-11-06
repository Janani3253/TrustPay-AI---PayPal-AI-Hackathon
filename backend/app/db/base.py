from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA_NAME = "trustpay_ai"


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.x models."""
    metadata = MetaData(schema=SCHEMA_NAME)

