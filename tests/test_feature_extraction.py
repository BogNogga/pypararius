"""Regression tests for the robust feature-table extraction.

Pararius renders the detail-page feature table with several quirks that broke
the original regex parser:

* a stray space before the closing ``>`` of ``<span ..." >`` tags,
* ``<span>`` tags split across multiple lines (tooltip fields),
* facility values rendered as ``<ul><li>`` lists,
* a "More info" tooltip ``<button>`` inside some values.
"""

from pypararius.parser import _extract_features, _strip_html


FEATURE_HTML = """
<div class="listing-features">
  <dl class="listing-features__list">
    <dt class="listing-features__term">Rental price</dt>
    <dd class="listing-features__description">
      <span class="listing-features__main-description">&euro;&nbsp;2.950 per month</span>
    </dd>

    <dt class="listing-features__term">Energy rating</dt>
    <dd class="listing-features__description listing-features__description--energy-label-a ">
      <span class="listing-features__main-description" >A</span>
    </dd>

    <dt class="listing-features__term">Number of bedrooms</dt>
    <dd class="listing-features__description listing-features__description--number_of_bedrooms ">
      <span class="listing-features__main-description" >3</span>
    </dd>

    <dt class="listing-features__term">Deposit</dt>
    <dd class="listing-features__description listing-features__description--with-tooltip">
      <span
        class="listing-features__main-description"
        aria-describedby="tooltip-listing-features-deposit"                    >
        &euro;&nbsp;5.900
      </span>
      <button type="button" class="tooltip__toggle">
        <span class="tooltip__toggle-icon">i</span>
        More info
      </button>
    </dd>

    <dt class="listing-features__term">Income requirement</dt>
    <dd class="listing-features__description listing-features__description--required_income ">
      <span class="listing-features__main-description" >&euro;9,000</span>
    </dd>

    <dt class="listing-features__term">Facilities</dt>
    <dd class="listing-features__description listing-features__description--facilities ">
      <ul class="listing-features__main-description listing-features__main-description--splitted">
        <li>Roof terrace</li>
        <li>Cable TV</li>
        <li>Intercom</li>
      </ul>
    </dd>
  </dl>
</div>
"""


def test_extract_energy_rating_with_space_before_close():
    features = _extract_features(FEATURE_HTML)
    assert features["Energy rating"] == "A"


def test_extract_bedrooms_with_space_before_close():
    features = _extract_features(FEATURE_HTML)
    assert features["Number of bedrooms"] == "3"


def test_extract_deposit_from_multiline_span_and_drops_tooltip():
    features = _extract_features(FEATURE_HTML)
    assert features["Deposit"] == "\u20ac 5.900"


def test_extract_facilities_as_comma_separated_list():
    features = _extract_features(FEATURE_HTML)
    assert features["Facilities"] == "Roof terrace, Cable TV, Intercom"


def test_strip_html_preserves_thousands_separator():
    assert _strip_html("&euro;9,000") == "\u20ac9,000"


def test_extract_income_requirement_preserves_thousands_separator():
    features = _extract_features(FEATURE_HTML)
    assert features["Income requirement"] == "\u20ac9,000"
