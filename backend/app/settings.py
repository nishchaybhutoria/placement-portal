"""Typed environment settings for identity and server-side sessions."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    """Runtime identity settings sourced from the documented uppercase variables."""

    session_secret: str = Field(min_length=32)
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_domain: str = Field(default="example.edu", min_length=1)
    dev_login: bool = False
    base_url: str = Field(default="http://localhost:8000", min_length=1)
    session_cookie_secure: bool = True

    @model_validator(mode="after")
    def validate_cookie_security(self) -> Settings:
        if not self.session_cookie_secure and not self.dev_login:
            raise ValueError("SESSION_COOKIE_SECURE=false requires DEV_LOGIN=true")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        environment_fields = {
            "SESSION_SECRET": "session_secret",
            "GOOGLE_CLIENT_ID": "google_client_id",
            "GOOGLE_CLIENT_SECRET": "google_client_secret",
            "ALLOWED_DOMAIN": "allowed_domain",
            "DEV_LOGIN": "dev_login",
            "BASE_URL": "base_url",
            "SESSION_COOKIE_SECURE": "session_cookie_secure",
        }
        values = {
            field_name: os.environ[environment_name]
            for environment_name, field_name in environment_fields.items()
            if environment_name in os.environ
        }
        return cls.model_validate(values)
