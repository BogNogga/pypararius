"""Regression tests for search-result badges and the total count."""

from pypararius.parser import _extract_badges, _extract_total_count


SEARCH_HTML = """
<div class="page__results">
  <div class="search-list-header search-list-header--page-title">
    <div class="search-list-header__title">
      <span class="search-list-header__count">756</span>
      <h1 class="search-list-header__heading">Rental Apartments Amsterdam</h1>
    </div>
  </div>

  <section
        class="listing-search-item listing-search-item--with-total-price listing-search-item--list listing-search-item--featured"
                            >
    <div class="listing-search-item__label">
      <span class="listing-label listing-label--featured">
        Highlighted
      </span>
    </div>
    <a href="/apartment-for-rent/amsterdam/bee9acd6/joos-banckersplantsoen">…</a>
  </section>

  <section class="listing-search-item listing-search-item--list">
    <div class="listing-search-item__label">
      <span class="listing-label listing-label--new">
        New
      </span>
    </div>
    <a href="/apartment-for-rent/amsterdam/3d4bb715/reinier-claeszenstraat">…</a>
  </section>

  <section class="listing-search-item listing-search-item--list">
    <a href="/apartment-for-rent/amsterdam/7b8dc27f/eva-besnyoestraat">…</a>
  </section>
</div>
"""


def test_extract_total_count():
    assert _extract_total_count(SEARCH_HTML) == 756


def test_extract_badges_featured_and_new():
    badges = _extract_badges(SEARCH_HTML)
    assert badges["bee9acd6"] == "Highlighted"
    assert badges["3d4bb715"] == "New"
    assert badges["7b8dc27f"] is None


def test_extract_total_count_handles_thousands_separator():
    html = '<span class="search-list-header__count">1.234</span>'
    assert _extract_total_count(html) == 1234
