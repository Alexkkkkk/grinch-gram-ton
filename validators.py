"""Input validation schemas using Pydantic."""

from typing import Optional

from pydantic import BaseModel, Field, validator


class SettingsUpdate(BaseModel):
    trade_amount: Optional[float] = Field(None, ge=0.01, le=10000)
    step_pct: Optional[float] = Field(None, ge=0.1, le=50)
    grid_levels: Optional[int] = Field(None, ge=2, le=100)
    slippage_pct: Optional[float] = Field(None, ge=0.01, le=20)
    ai_enabled: Optional[bool] = None
    ai_min_conf: Optional[float] = Field(None, ge=0, le=100)

    @validator("trade_amount", "step_pct", "slippage_pct")
    def must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("must be positive")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class WithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0)
    address: str = Field(..., min_length=10, max_length=120)
