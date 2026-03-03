from pydantic import BaseModel


class ServiceStatus(BaseModel):
    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    services: dict[str, ServiceStatus]
