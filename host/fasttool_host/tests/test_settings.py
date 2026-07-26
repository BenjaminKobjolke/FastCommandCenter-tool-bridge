import pytest

from fasttool_host.settings import SettingsError, ToolSetting, ToolSettings

SNAPSHOT_BODY = {
    "tool_id": "fastkeyboardmouse",
    "settings": [
        {"id": "ToggleKey", "label": "Toggle mouse mode", "type": "shortcut", "value": "alt+q"},
        {
            "id": "BaseSpeed",
            "label": "Cursor speed",
            "type": "int",
            "value": 20,
            "min": 1,
            "max": 100,
            "step": 1,
        },
        {"id": "DarkMode", "label": "Dark mode", "type": "bool", "value": True},
        {
            "id": "SpeedModifier",
            "label": "Speed boost key",
            "type": "enum",
            "value": "Shift",
            "choices": ["Shift", "Ctrl", "Alt"],
        },
        {
            "id": "IndicatorColor",
            "label": "Cursor indicator color",
            "type": "color",
            "value": "#00ff00",
        },
    ],
}


def test_tool_settings_from_dict_parses_every_field() -> None:
    settings = ToolSettings.from_dict(SNAPSHOT_BODY)

    assert settings.tool_id == "fastkeyboardmouse"
    assert len(settings.settings) == 5

    toggle = settings.settings[0]
    assert toggle.id == "ToggleKey"
    assert toggle.type == "shortcut"
    assert toggle.value == "alt+q"

    speed = settings.settings[1]
    assert speed.type == "int"
    assert speed.value == 20
    assert speed.min == 1
    assert speed.max == 100
    assert speed.step == 1

    dark_mode = settings.settings[2]
    assert dark_mode.type == "bool"
    assert dark_mode.value is True

    modifier = settings.settings[3]
    assert modifier.type == "enum"
    assert modifier.choices == ("Shift", "Ctrl", "Alt")

    color = settings.settings[4]
    assert color.type == "color"
    assert color.value == "#00ff00"


def test_tool_setting_omits_type_specific_fields_by_default() -> None:
    setting = ToolSetting.from_dict({"id": "x", "label": "X", "type": "bool", "value": True})

    assert setting.min is None
    assert setting.max is None
    assert setting.step is None
    assert setting.choices is None


def test_tool_settings_from_dict_rejects_missing_tool_id() -> None:
    with pytest.raises(SettingsError, match="missing required field"):
        ToolSettings.from_dict({"settings": []})


def test_tool_settings_from_dict_rejects_missing_settings() -> None:
    with pytest.raises(SettingsError, match="missing required field"):
        ToolSettings.from_dict({"tool_id": "x"})


def test_tool_setting_from_dict_rejects_missing_required_field() -> None:
    with pytest.raises(SettingsError, match="missing required field"):
        ToolSetting.from_dict({"id": "x", "type": "bool", "value": True})


def test_tool_settings_from_dict_rejects_non_list_settings() -> None:
    with pytest.raises(SettingsError, match="must be a list"):
        ToolSettings.from_dict({"tool_id": "x", "settings": "not-a-list"})


def test_tool_settings_from_dict_empty_settings_list_is_valid() -> None:
    settings = ToolSettings.from_dict({"tool_id": "x", "settings": []})

    assert settings.settings == ()
