from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def enum_col(enum_class, **kwargs) -> Enum:
    """
    SQLAlchemy Enum that stores the Python enum's .value (not .name).
    """
    return Enum(
        enum_class,
        values_callable=lambda obj: [e.value for e in obj],
        **kwargs,
    )
