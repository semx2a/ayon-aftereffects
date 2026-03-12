from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
    normalize_name,
)
from pydantic import validator


class ScriptConfigModel(BaseSettingsModel):
    """Provide list of scripts to run at workfile_opened."""

    name: str = SettingsField(default_factory=str, title="Script name.")
    auto: bool = SettingsField(
        True,
        description="Auto/Manual toggle.",
    )
    path: str = SettingsField("", title="Path to script.")

    @validator("name")
    def normalize_value(cls, value: str) -> str:
        return normalize_name(value)


class Scripts(BaseSettingsModel):
    """Workfile template builder with dynamic items via Placeholders"""

    configs: list[ScriptConfigModel] = SettingsField(
        default_factory=list, title="Script config"
    )
