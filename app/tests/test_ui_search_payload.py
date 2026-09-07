from pathlib import Path


def test_search_ui_sends_tab_content_type_and_default_all_sources():
    html = Path(__file__).resolve().parents[1].joinpath("templates/index.html").read_text()
    assert "content_type: this.contentType()" in html
    assert "defaultAllSources" in html
    assert "webSourceValues = ['rss', 'news', 'google', 'bing']" in html
    assert "[...webSourceValues, 'telegram', ...agencySourceValues]" in html
    assert "content_type: 'all'" not in html.split("async search()")[1].split("async pollResults")[0]
