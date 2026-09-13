from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    app: str
    version: str


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
