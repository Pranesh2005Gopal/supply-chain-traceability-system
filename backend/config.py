"""
Application Configuration
Loads settings from environment variables or .env file using Pydantic.
"""

from typing import List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "Supply Chain Traceability System"
    APP_ENV: str = "development"
    DEBUG: bool = True
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: Union[str, List[str]] = "*"

    # Dataset path
    DATASET_PATH: str = "/home/praneshg/Downloads/dataset/EPCIS-synthetic-food-supply-chain-dataset-main/synthetic-food-supply-chain-dataset.json"

    # MongoDB Settings (Document Store)
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "supply_trace"
    MONGO_TIMEOUT_MS: int = 5000

    # Neo4j Settings (Provenance Graph Store)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "tracepassword"

    # Redis Settings (Cache Layer)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_TTL_SECONDS: int = 900
    REDIS_TIMEOUT_SECONDS: int = 2

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
