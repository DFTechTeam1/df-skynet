from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy.dialects.mysql import BIGINT
from enum import StrEnum, auto
from sqlalchemy import (
    BigInteger,
    CHAR,
    Date,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    SmallInteger,
    DECIMAL,
    ForeignKey,
)


class EmployeeReligions(StrEnum):
    katholik = auto()
    islam = auto()
    kristen = auto()
    budha = auto()
    hindu = auto()
    konghucu = auto()


class EmployeeMaritalStatuses(StrEnum):
    married = auto()
    single = auto()


class EmployeeGenders(StrEnum):
    male = auto()
    female = auto()


class EmployeeEducations(StrEnum):
    smp = auto()
    sma = auto()
    smk = auto()
    diploma = auto()
    s1 = auto()
    s2 = auto()
    s3 = auto()


class EmployeeFamilyRelationships(StrEnum):
    father = auto()
    mother = auto()
    sibling = auto()
    child = auto()


class Employees(SQLModel, table=True):
    __tablename__ = "employees"  # type: ignore

    id: int = Field(sa_column=Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True))
    uid: str = Field(sa_column=Column(CHAR(36)))
    name: str = Field(sa_column=Column(String(255)))
    nickname: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    email: str = Field(sa_column=Column(String(255)))
    personal_email: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    avatar: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    phone: str = Field(sa_column=Column(String(15)))
    id_number: str = Field(sa_column=Column(String(16)))
    religion: EmployeeReligions = Field(sa_column=Column(Enum(EmployeeReligions)))
    martial_status: EmployeeMaritalStatuses = Field(sa_column=Column(Enum(EmployeeMaritalStatuses)))
    address: str = Field(sa_column=Column(String(255)))
    postal_code: Optional[str] = Field(default=None, sa_column=Column(String(6), nullable=True))
    current_address: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    blood_type: Optional[str] = Field(default=None, sa_column=Column(String(2), nullable=True))
    date_of_birth: date = Field(sa_column=Column(Date))
    place_of_birth: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    gender: EmployeeGenders = Field(sa_column=Column(Enum(EmployeeGenders)))
    bank_detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    relation_contact: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    education: Optional[EmployeeEducations] = Field(
        default=None, sa_column=Column(Enum(EmployeeEducations), nullable=True)
    )
    education_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    education_major: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    education_year: int = Field(sa_column=Column(SmallInteger))
    position_id: int = Field(sa_column=Column(BIGINT(unsigned=True), ForeignKey("position_backups.id")))
    boss_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    level_staff: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    status: int = Field(sa_column=Column(SmallInteger))
    join_date: date = Field(sa_column=Column(Date))
    start_review_probation_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    probation_status: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    end_probation_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    bpjs_status: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    bpjs_ketenagakerjaan_number: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    bpjs_kesehatan_number: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    npwp_number: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    bpjs_photo: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    npwp_photo: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    id_number_photo: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    kk_photo: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    created_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    updated_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deleted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    employee_id: str = Field(sa_column=Column(String(150)))
    province_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    city_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    district_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    village_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BIGINT(unsigned=True), ForeignKey("users.id"), nullable=True),
    )
    line_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    end_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    resign_reason: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    telegram_chat_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    branch_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    ptkp_status: Optional[str] = Field(default=None, sa_column=Column(String(5), nullable=True))
    basic_salary: float = Field(default=0.00, sa_column=Column(DECIMAL(24, 2)))
    salary_type: int = Field(sa_column=Column(SmallInteger))
    is_residence_same: int = Field(default=0, sa_column=Column(SmallInteger))
    job_level_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    avatar_color: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_emp_id: Optional[str] = Field(default=None, sa_column=Column(String(100), nullable=True))
    greatday_nationality: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_job_grade: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_marital_status: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_cost_center: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_employment_status: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_work_location: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_religion: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_timezone: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_shift_pattern: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_job_status: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    greatday_company: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    employment_status_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    is_phone_verified: Optional[int] = Field(default=None, sa_column=Column(SmallInteger, nullable=True))

    position_backups: Optional["PositionBackups"] = Relationship(back_populates="employees")  # type: ignore
    users: Optional["Users"] = Relationship(back_populates="employees", sa_relationship_kwargs={"uselist": False})  # type: ignore
