# Data validation
from typing import Annotated, Literal

from pydantic import BaseModel, Field

RatingField = Annotated[
    int | None,
    Field(None, ge=0, le=100_000, description="Rating points", examples=[1250]),
]
SlugField = Annotated[
    str | None,
    Field(None, max_length=64, description="URL-friendly identifier"),
]
CountryField = Annotated[
    str | None,
    Field(
        None,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code",
        examples=["US"],
    ),
]


class SearchResultItem(BaseModel):
    id: str = Field(
        ..., description="GeoGuessr user ID", examples=["abc123xyz456abc123xy"]
    )
    nick: str = Field(
        ..., min_length=1, max_length=64, description="Player nickname", examples=["ProGeo"]
    )
    slug: SlugField = None
    country_code: CountryField = None
    rating: RatingField = None
    rating_moving: RatingField = None
    rating_nomove: RatingField = None
    rating_nmpz: RatingField = None
    position_overall: Annotated[int | None, Field(None, ge=1, description="Global rank")] = None
    position_moving: Annotated[int | None, Field(None, ge=1)] = None
    position_nomove: Annotated[int | None, Field(None, ge=1)] = None
    position_nmpz: Annotated[int | None, Field(None, ge=1)] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "abc123xyz456abc123xy",
                "nick": "ProGeo",
                "slug": "progeo",
                "country_code": "FI",
                "rating": 1250,
                "position_overall": 42,
            }]
        }
    }


class SeriesPoint(BaseModel):
    date: str = Field(..., description="ISO date (YYYY-MM-DD)", examples=["2024-06-01"])
    value: Annotated[
        int,
        Field(..., ge=0, le=100_000, description="Rating on that date", examples=[1200]),
    ]


class SeriesResponse(BaseModel):
    mode: Literal["overall", "moving", "nomove", "nmpz"] = Field(
        ..., description="Game mode"
    )
    range: Literal["7d", "30d", "90d", "all"] = Field(..., description="Time range")
    points: list[SeriesPoint] = Field(
        ..., description="Rating data points sorted by date"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "mode": "overall",
                "range": "30d",
                "points": [{"date": "2024-06-01", "value": 1200}],
            }]
        }
    }


class ForecastResponse(BaseModel):
    horizon: Annotated[
        int,
        Field(..., ge=1, le=365, description="Forecast horizon in days", examples=[30]),
    ]
    mode: Literal["overall", "moving", "nomove", "nmpz"] = Field(
        ..., description="Game mode"
    )
    predicted_delta: int | None = Field(
        None, description="Predicted rating change", examples=[50]
    )
    predicted_rating: Annotated[
        int | None,
        Field(None, ge=0, le=100_000, description="Predicted absolute rating", examples=[1300]),
    ] = None
    confidence: Annotated[
        int | None,
        Field(None, ge=0, description="Uncertainty interval (±points)", examples=[80]),
    ] = None
    n_points: Annotated[
        int,
        Field(..., ge=0, description="Data points used for forecast", examples=[15]),
    ]

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "horizon": 30,
                "mode": "overall",
                "predicted_delta": 50,
                "predicted_rating": 1300,
                "confidence": 80,
                "n_points": 15,
            }]
        }
    }


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        ..., description="Overall service status"
    )
    db: Literal["ok", "error"] = Field(..., description="Database connectivity")

    model_config = {
        "json_schema_extra": {"examples": [{"status": "ok", "db": "ok"}]}
    }


class ErrorResponse(BaseModel):
    error: str = Field(
        ..., description="Human-readable error message", examples=["Not found"]
    )
    status: int = Field(..., ge=100, le=599, description="HTTP status code", examples=[404])
