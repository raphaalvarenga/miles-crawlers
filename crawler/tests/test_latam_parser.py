import json
import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker.latam_parser import build_url, parse_latam_flights  # noqa: E402
from worker.utils import flight_to_snapshot  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "latam_redemption_MAD_GIG.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_build_url_matches_site():
    assert build_url("mad", "gig", "2026-12-25") == (
        "https://www.latamairlines.com/br/pt/oferta-voos?origin=MAD"
        "&outbound=2026-12-25T00%3A00%3A00.000Z&destination=GIG&adt=1&chd=0&inf=0"
        "&trip=OW&cabin=Economy&redemption=true&sort=RECOMMENDED"
    )


def test_cheapest_brand_per_cabin_and_dedup():
    flights = parse_latam_flights(load())
    # item 2 repete o item 1 e é descartado
    assert [(f["voo"], f["cabin"], f["brand"]) for f in flights] == [
        ("LA-8069/3472", "ECONOMIC", "LIGHT"),
        ("LA-8069/3472", "BUSINESS", "PREMIUM BUSINESS FULL"),
        ("IB-269", "ECONOMIC", "FULL"),
        ("LA-1525/3352", "BUSINESS", "PREMIUM BUSINESS FULL"),
    ]


def test_fields_of_first_itinerary():
    f = parse_latam_flights(load())[0]
    assert f["origem"] == "MAD" and f["destino"] == "GIG"
    assert f["carrier_code"] == "LA"
    assert f["miles_price"] == 227564
    assert f["taxes_cents"] == 19380
    assert f["duracao_minutos"] == 935
    assert f["escalas"] == 1
    assert f["conexoes"] == ["GRU"]
    assert f["assentos"] == 9
    assert [t["milhas"] for t in f["tarifas"]] == [227564, 254984, 295790]


def test_snapshot():
    flights = parse_latam_flights(load())
    snap = flight_to_snapshot(flights[0], "2026-12-25", "latam")
    assert snap["class"] == "Economy"
    assert snap["travel_date"] == date(2026, 12, 25)
    assert snap["departure_time"] == time(22, 45)
    assert snap["arrival_time"] == time(10, 20)
    assert snap["taxes_cents"] == 19380
    nonstop = flight_to_snapshot(flights[2], "2026-12-25", "latam")
    assert nonstop["direct_only"] is True and nonstop["taxes_cents"] == 140166
    assert flight_to_snapshot(flights[3], "2026-12-25", "latam")["class"] == "Business"
