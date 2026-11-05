from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_VA = 60000


class HomeLoadsRequest(BaseModel):
    square_feet: int = Field(gt=0, le=30000)
    small_appliance_circuits: int = Field(default=2, ge=2, le=12)
    laundry_circuits: int = Field(default=1, ge=0, le=3)
    range_va: int = Field(default=0, ge=0, le=MAX_VA)
    cooktop_va: int = Field(default=0, ge=0, le=MAX_VA)
    oven_va: int = Field(default=0, ge=0, le=MAX_VA)
    dryer_va: int = Field(default=0, ge=0, le=MAX_VA)
    water_heater_va: int = Field(default=0, ge=0, le=MAX_VA)
    dishwasher_va: int = Field(default=0, ge=0, le=MAX_VA)
    disposal_va: int = Field(default=0, ge=0, le=MAX_VA)
    microwave_va: int = Field(default=0, ge=0, le=MAX_VA)
    hot_tub_or_pool_va: int = Field(default=0, ge=0, le=MAX_VA)
    other_va: int = Field(default=0, ge=0, le=MAX_VA)
    heating_va: int = Field(default=0, ge=0, le=MAX_VA)
    cooling_va: int = Field(default=0, ge=0, le=MAX_VA)


class EvJobRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=200)
    contractor: str = Field(min_length=1, max_length=120)
    license_number: str = Field(min_length=1, max_length=60)
    home: HomeLoadsRequest
    service_amps: int = Field(ge=60, le=800)
    open_breaker_spaces: int = Field(ge=0, le=60)
    charger_amps: int = Field(ge=16, le=80)
    location: Literal["attached_garage", "detached_garage", "exterior_wall"]
    run_ft: int = Field(gt=0, le=500)
    trench_ft: int = Field(default=0, ge=0, le=500)

    @model_validator(mode="after")
    def trench_fits_the_run(self) -> "EvJobRequest":
        if self.trench_ft > self.run_ft:
            raise ValueError("the trench can't be longer than the whole circuit run")
        return self
