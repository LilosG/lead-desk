"""The homepage detail used to open website emails, and site-builder detection."""
from __future__ import annotations

import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))



def test_site_hook_finds_one_self_stated_detail():
    from site_signals import site_hook
    assert site_hook("Proudly serving Phoenix since 1996.", 2026) == {"kind": "since", "value": "1996"}
    assert site_hook("Over 20 years of experience", 2026) == {"kind": "experience", "value": "20"}
    assert site_hook("25 years in business", 2026) == {"kind": "years", "value": "25"}
    assert site_hook("We are a licensed CR-11 electrical contractor", 2026) == {"kind": "license", "value": "CR-11"}
    assert site_hook("Licensed C10 #123456", 2026) == {"kind": "license", "value": "C-10"}
    assert site_hook("2-hour emergency response", 2026) == {"kind": "response", "value": "2"}
    assert site_hook("Family owned and operated", 2026) == {"kind": "family", "value": "family-owned"}
    assert site_hook("Call us today for a quote.", 2026) is None
    assert site_hook("Copyright 2025. Since 2025 we", 2026) is None  # too recent to be worth leading with
    assert site_hook("", 2026) is None


def test_site_builder_by_host_or_generator():
    from bs4 import BeautifulSoup
    from site_signals import site_builder
    blank = BeautifulSoup("<html></html>", "html.parser")
    assert site_builder("https://order.toasttab.com/online/x", blank) == "toast"
    assert site_builder("https://joes.square.site/", blank) == "square"
    assert site_builder("https://joes.com/", blank) is None
    toast = BeautifulSoup('<meta name="generator" content="Toast Websites">', "html.parser")
    assert site_builder("https://joes.com/", toast) == "toast"
    # A site that only links to Toast ordering is not built on Toast.
    links = BeautifulSoup('<a href="https://order.toasttab.com/x">Order</a>', "html.parser")
    assert site_builder("https://joes.com/", links) is None
