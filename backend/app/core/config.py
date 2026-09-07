from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str
    redis_url: str
    supabase_url: str
    supabase_jwt_secret: str
    supabase_service_key: str
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    elevenlabs_api_key: str
    gemini_api_key: str
    openai_api_key: str


settings = Settings()
