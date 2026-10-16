"""Day-by-day numbers shared by sources that publish one value per series per day."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class SeriesObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    day: date
    value: float
