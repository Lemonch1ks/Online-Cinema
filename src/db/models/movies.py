from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import String, Float, Integer, DECIMAL, ForeignKey, Uuid, UniqueConstraint, Text
from db import Base
from uuid import UUID, uuid4
from decimal import Decimal


class Movie(Base):
    __tablename__ = 'movies'
    __table_args__ = (
        UniqueConstraint("name", "year", "time", name="unique_name_time_year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    imdb: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_score: Mapped[float] = mapped_column(Float, nullable=True)
    gross: Mapped[float] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(DECIMAL(10,2), nullable=False)
    certification_id: Mapped[int] = relationship(ForeignKey("certifications.id"), nullable=False)



class Certification(Base):
    __tablename__ = 'certifications'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    movies: Mapped[list["Movie"]] = relationship(back_populates="certification")
