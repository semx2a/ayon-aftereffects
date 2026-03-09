from ayon_server.settings import (
    BaseSettingsModel,
    MultiplatformPathModel,
    SettingsField,
    normalize_name,
)
from pydantic import validator


class ScriptConfigModel(BaseSettingsModel):
    """Provide list of scripts to run at workfile_opened."""

    _layout = "expanded"
    active: bool = SettingsField(True)
    name: str = SettingsField(default_factory=str, title="Script name")
    path: MultiplatformPathModel = SettingsField(
        default_factory=MultiplatformPathModel
    )

    @validator("name")
    def normalize_value(cls, value: str) -> str:
        return normalize_name(value)


class ScriptList(BaseSettingsModel):
    """Workfile template builder with dynamic items via Placeholders"""

    paths: list[ScriptConfigModel] = SettingsField(
        default_factory=list, title="Scripts"
    )
