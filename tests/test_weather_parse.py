"""NSRDB parser: wind direction column and the cache-miss rule for files
written before it was fetched."""

import json

from engine.weather import WeatherYear, _cache_read, parse_nsrdb_csv


def _csv(with_direction: bool) -> str:
    head = ["Year", "Month", "Day", "Hour", "Minute", "Temperature",
            "Relative Humidity", "Pressure", "GHI", "DNI", "DHI",
            "Wind Speed", "Cloud Type"]
    if with_direction:
        head.insert(-1, "Wind Direction")
    rows = ["Source,Location ID,Latitude,Longitude,Elevation,Time Zone",
            "NSRDB,123,29.76,-95.37,15,-6",
            ",".join(head)]
    for i in range(8760):
        r = ["2020", "1", "1", str(i % 24), "0", "20.0", "50", "1013",
             "0", "0", "0", "3.0", "0"]
        if with_direction:
            r.insert(-1, str((i * 37) % 360))
        rows.append(",".join(r))
    return "\n".join(rows) + "\n"


def test_wind_direction_parsed():
    y = parse_nsrdb_csv(_csv(True))
    assert len(y.wind_dir_deg) == 8760
    assert y.wind_dir_deg[1] == 37.0
    assert len(y.wind_m_s) == 8760 and y.wind_m_s[0] == 3.0


def test_wind_direction_optional():
    y = parse_nsrdb_csv(_csv(False))
    assert y.wind_dir_deg == []
    assert len(y.t_out_c) == 8760


def test_cache_without_direction_is_a_miss(tmp_path):
    old = WeatherYear(t_out_c=[20.0] * 8760, rh_out=[0.5] * 8760, wind_m_s=[3.0] * 8760)
    p = tmp_path / "tmy_old.json"
    p.write_text(json.dumps(old.__dict__))
    assert _cache_read(p) is None
    new = WeatherYear(t_out_c=[20.0] * 8760, rh_out=[0.5] * 8760,
                      wind_m_s=[3.0] * 8760, wind_dir_deg=[90.0] * 8760)
    p.write_text(json.dumps(new.__dict__))
    assert _cache_read(p) is not None
