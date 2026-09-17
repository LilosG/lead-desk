from pathlib import Path


def test_run_repository_prefers_sweep_city_scope_over_legacy_geo_label():
    source = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "repositories"
        / "runs.py"
    ).read_text()

    assert "from sweep_jobs sj" in source
    assert "where sj.run_id = r.id" in source
    assert "array_to_string(sj.cities, ' • ')" in source
    assert 'row["geo_label"] = " • ".join(sweep["cities"])' in source
