"""Parse da Smiles usado pela ponte da extensão (smiles_parser.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker.smiles_parser import (  # noqa: E402
    AVAILABILITY_URL_FRAGMENT,
    SmilesRejectedError,
    build_url,
    parse_smiles_flights,
)
from worker.utils import flight_to_snapshot  # noqa: E402

PAYLOAD = {
    "requestedFlightSegmentList": [{
        "flightList": [{
            "uid": "efemero",
            "flightNumber": "6053",
            "cabin": "ECONOMIC",
            "stops": 0,
            "availableSeats": 4,
            "airline": {"code": "G3", "name": "GOL"},
            "departure": {"date": "2026-12-01T09:05:00", "airport": {"code": "SDU"}},
            "arrival": {"date": "2026-12-01T10:10:00", "airport": {"code": "CGH"}},
            "duration": {"hours": 1, "minutes": 5},
            "fareList": [
                {"type": "SMILES", "miles": 17820, "money": 0},
                {"type": "SMILES_CLUB", "miles": 16038, "money": 0},
            ],
        }],
    }],
}


def test_build_url_points_to_search_page():
    url = build_url("SDU", "CGH", "2026-12-01", 1)
    assert url.startswith("https://www.smiles.com.br/mfe/emissao-passagem?")
    assert "originAirport=SDU" in url and "destinationAirport=CGH" in url and "cabin=ALL" in url


def test_capture_fragment_matches_api_url():
    api = ("https://api-air-flightsearch-blue.smiles.com.br/v1/airlines/search?cabin=ALL"
           "&originAirportCode=SDU&destinationAirportCode=CGH&departureDate=2026-12-01")
    assert AVAILABILITY_URL_FRAGMENT in api


def test_parses_flights_into_snapshot():
    flights = parse_smiles_flights(PAYLOAD)
    assert len(flights) == 1
    snapshot = flight_to_snapshot(flights[0], "2026-12-01", "smiles")
    assert snapshot["class"] == "Economy"
    assert snapshot["flight_number"] == "6053"


def test_rejection_raises_instead_of_zero_flights():
    with pytest.raises(SmilesRejectedError, match="Something went wrong"):
        parse_smiles_flights({"message": "Something went wrong", "clientIP": "x", "referenceId": "y"})


def test_empty_flight_list_is_zero_flights():
    assert parse_smiles_flights({"requestedFlightSegmentList": [{"flightList": []}]}) == []


def _with_fares(fares):
    import copy
    payload = copy.deepcopy(PAYLOAD)
    payload["requestedFlightSegmentList"][0]["flightList"][0]["fareList"] = fares
    return payload


def test_tax_comes_from_airline_cost_tax():
    # Formato real da resposta: a taxa vem em "g3": {"costTax": "62.14"} em cada tarifa.
    payload = _with_fares([
        {"type": "SMILES", "miles": 15600, "money": 0, "g3": {"costTax": "62.14", "productClass": "PA"}},
        {"type": "SMILES_CLUB", "miles": 14800, "money": 0, "g3": {"costTax": "62.14", "productClass": "PA"}},
        {"type": "MONEY", "miles": 0, "money": 285.9, "g3": {"costTax": "62.14", "productClass": "SL"}},
    ])
    flight = parse_smiles_flights(payload)[0]
    assert flight["taxes_cents"] == 6214
    assert flight_to_snapshot(flight, "2027-01-28", "smiles")["taxes_cents"] == 6214


def test_missing_tax_stays_zero():
    flight = parse_smiles_flights(PAYLOAD)[0]
    assert flight["taxes_cents"] == 0
    assert flight_to_snapshot(flight, "2026-12-01", "smiles")["taxes_cents"] == 0
