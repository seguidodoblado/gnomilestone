from gnomilestone import theme


def test_dark_variant_preserves_mint_accent():
    assert theme.theme_variant("Mint-Y-Orange", True) == "Mint-Y-Dark-Orange"


def test_light_variant_from_mint_dark():
    assert theme.theme_variant("Mint-Y-Dark-Orange", False) == "Mint-Y-Orange"


def test_dark_variant_adwaita_style_suffix():
    assert theme.theme_variant("Adwaita", True) == "Adwaita-dark"


def test_is_dark_theme():
    assert theme.is_dark_theme("Mint-Y-Dark-Orange") is True
    assert theme.is_dark_theme("Mint-Y-Orange") is False
    assert theme.is_dark_theme(None) is False
