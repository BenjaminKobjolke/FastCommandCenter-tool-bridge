from fasttool_palette.mode import palette_mode


def test_palette_mode_true_when_flag_present() -> None:
    assert palette_mode(["--palette"]) is True


def test_palette_mode_true_when_flag_among_other_args() -> None:
    assert palette_mode(["--config", "settings.ini", "--palette"]) is True


def test_palette_mode_false_when_flag_absent() -> None:
    assert palette_mode(["--config", "settings.ini"]) is False


def test_palette_mode_false_for_empty_args() -> None:
    assert palette_mode([]) is False
