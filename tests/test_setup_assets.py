from shorts.setup_assets import font_css_url, parse_font_css

CSS = """@font-face {
  font-family: 'Montserrat';
  font-style: normal;
  font-weight: 800;
  src: url(https://fonts.gstatic.com/s/montserrat/v29/abc.ttf) format('truetype');
}
@font-face {
  font-family: 'Montserrat';
  font-style: normal;
  font-weight: 900;
  src: url(https://fonts.gstatic.com/s/montserrat/v29/def.ttf) format('truetype');
}"""


def test_parse_font_css():
    assert parse_font_css(CSS) == [
        (800, "https://fonts.gstatic.com/s/montserrat/v29/abc.ttf"),
        (900, "https://fonts.gstatic.com/s/montserrat/v29/def.ttf"),
    ]


def test_font_css_url():
    assert font_css_url("DM Sans", [700]) == "https://fonts.googleapis.com/css2?family=DM+Sans:wght@700&display=swap"
