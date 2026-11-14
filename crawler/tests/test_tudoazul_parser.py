import json
import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker.tudoazul_parser import parse_tudoazul_flights  # noqa: E402
from worker.utils import flight_to_snapshot  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "azul_availability_v6_GIG_MAD.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_one_entry_per_available_journey_and_cabin():
    flights = parse_tudoazul_flights(load())
    # jornada 1: economy + business; jornada 2: economy; jornada 3 indisponível
    assert [(f["flight_number"], f["cabin"]) for f in flights] == [
        ("2849/8754", "ECONOMIC"),
        ("2849/8754", "BUSINESS"),
        ("4205/4046/8754", "ECONOMIC"),
    ]


def test_fields_of_first_journey():
    f = parse_tudoazul_flights(load())[0]
    assert f["origem"] == "GIG" and f["destino"] == "MAD"
    assert f["carrier_code"] == "AD"
    assert f["miles_price"] == 402000
    assert f["taxes_cents"] == 23098
    assert f["duracao_minutos"] == 22 * 60 + 5
    assert f["escalas"] == 1
    assert f["conexoes"] == ["VCP"]
    assert f["assentos"] == 87
    assert f["pontos_mais_dinheiro"] == [{"nivel": 2, "pontos": 40200, "dinheiro_brl": 4082.98}]


def test_snapshot_matches_fare_snapshots_columns():
    flights = parse_tudoazul_flights(load())
    economy, business = flights[0], flights[1]
    snap = flight_to_snapshot(economy, "2026-12-26", "azul")
    assert snap["class"] == "Economy"
    assert snap["travel_date"] == date(2026, 12, 26)
    assert snap["departure_time"] == time(10, 20)
    assert snap["arrival_time"] == time(12, 25)
    assert snap["taxes_cents"] == 23098
    assert snap["number_of_stops"] == 1
    assert snap["direct_only"] is False
    assert flight_to_snapshot(business, "2026-12-26", "azul")["class"] == "Business"
