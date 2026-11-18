from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class DailyBar(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=15)
    trade_date: date
    open_price: float = Field(..., gt=0)
    high_price: float = Field(..., gt=0)
    low_price: float = Field(..., gt=0)
    close_price: float = Field(..., gt=0)
    volume: int = Field(..., ge=0)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_ohlc_integrity(self) -> "DailyBar":
        if self.high_price < self.low_price:
            raise ValueError(f"high_price ({self.high_price}) cannot be less than low_price ({self.low_price})")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("high_price cannot be less than open or close price")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("low_price cannot be greater than open or close price")
        return self


class TradeSignal(BaseModel):
    ticker: str
    signal_date: date
    side: Literal["BUY", "SHORT"]
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    target_price: float = Field(..., gt=0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    poc: Optional[float] = None  # volume point of control behind the setup
    weekly_bias: Optional[str] = None  # higher-timeframe regime: UP / DOWN / FLAT