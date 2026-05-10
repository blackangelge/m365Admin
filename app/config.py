from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_secret_key: str
    app_session_cookie_name: str = "m365admin_session"
    app_debug: bool = False

    database_url: str = "sqlite+aiosqlite:////data/m365admin.db"

    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str = ""
    azure_redirect_uri: str
    azure_scopes: str = "openid profile email User.Read"

    admin_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.azure_tenant_id}"

    @property
    def scopes_list(self) -> list[str]:
        return self.azure_scopes.split()


settings = Settings()
