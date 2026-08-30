"""Validated request models shared by API boundaries and tests."""

from pydantic import BaseModel, Field, field_validator


class SettingsUpdate(BaseModel):
    trade_amount: float | None = Field(default=None, ge=0)
    step_pct: float | None = Field(default=None, ge=0)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class WithdrawRequest(BaseModel):
    amount: float = Field(gt=0)
    address: str = Field(min_length=1)

    @field_validator("address")
    @classmethod
    def address_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("address must not be blank")
        return value
