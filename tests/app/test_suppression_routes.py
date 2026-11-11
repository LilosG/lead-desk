import pytest
from fastapi import HTTPException

from app.api.routes.suppression import _clean


def test_clean_lowercases_and_trims():
    assert _clean('  Sean@TeslaElectricDFW.com ') == 'sean@teslaelectricdfw.com'


@pytest.mark.parametrize('bad', ['nope', 'a@b', '@x.com', 'a b@x.com'])
def test_clean_rejects_invalid(bad):
    with pytest.raises(HTTPException):
        _clean(bad)
