import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from fuel.models import FuelStation

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def write_csv(tmp_path, rows: str, header: str = HEADER, name: str = "prices.csv"):
    path = tmp_path / name
    path.write_text(header + rows, encoding="utf-8")
    return path


def run_import(path, **kwargs) -> str:
    from io import StringIO

    out = StringIO()
    call_command("import_fuel_prices", str(path), stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
def test_imports_a_valid_row_with_coordinates_from_the_gazetteer(tmp_path):
    path = write_csv(tmp_path, '7,WOODSHED,"I-44, EXIT 283",Big Cabin,OK,307,3.00733333\n')

    run_import(path)

    station = FuelStation.objects.get(opis_id=7)
    assert station.name == "WOODSHED"
    assert station.city == "Big Cabin"
    assert float(station.retail_price) == pytest.approx(3.00733333)
    # Big Cabin, OK sits in north-east Oklahoma.
    assert station.latitude == pytest.approx(36.5, abs=1.0)
    assert station.longitude == pytest.approx(-95.2, abs=1.0)


@pytest.mark.django_db
def test_rejects_rows_outside_the_usa_and_counts_them(tmp_path):
    path = write_csv(
        tmp_path,
        "1,US STOP,Addr,Big Cabin,OK,1,3.10\n"
        "2,CANADA STOP,Addr,Calgary,AB,1,3.20\n"
        "3,ALSO CANADA,Addr,Toronto,ON,1,3.30\n",
    )

    output = run_import(path)

    assert set(FuelStation.objects.values_list("opis_id", flat=True)) == {1}
    assert "outside the USA:      2" in output


@pytest.mark.django_db
def test_collapses_duplicate_opis_ids_and_reports_the_count(tmp_path):
    """The real feed lists the same truck stop twice under name variants."""
    path = write_csv(
        tmp_path,
        "20,PILOT TRAVEL CENTER #1243,Addr,Gila Bend,AZ,930,3.899\n"
        "20,PILOT #1243,Addr,Gila Bend,AZ,930,3.899\n",
    )

    output = run_import(path)

    assert FuelStation.objects.count() == 1
    assert FuelStation.objects.get().name == "PILOT #1243", "the last occurrence wins"
    assert "duplicate OPIS IDs:   1" in output


@pytest.mark.django_db
@pytest.mark.parametrize("price", ["", "not-a-number", "0", "-1.5", "250.0"])
def test_rejects_unusable_prices(tmp_path, price):
    path = write_csv(tmp_path, f"1,STOP,Addr,Big Cabin,OK,1,{price}\n")

    output = run_import(path)

    assert FuelStation.objects.count() == 0
    assert "invalid price:        1" in output


@pytest.mark.django_db
@pytest.mark.parametrize(
    "row",
    [
        ",STOP,Addr,Big Cabin,OK,1,3.10\n",
        "1,,Addr,Big Cabin,OK,1,3.10\n",
        "1,STOP,Addr,,OK,1,3.10\n",
        "1,STOP,Addr,Big Cabin,,1,3.10\n",
        "1,STOP,Addr,Big Cabin,OK,,3.10\n",
    ],
)
def test_rejects_rows_with_missing_required_fields(tmp_path, row):
    path = write_csv(tmp_path, row)

    output = run_import(path)

    assert FuelStation.objects.count() == 0
    assert "missing fields:       1" in output or "invalid price:        1" in output


@pytest.mark.django_db
def test_reports_cities_the_gazetteer_cannot_place(tmp_path):
    path = write_csv(tmp_path, "1,STOP,Addr,Nowhere At All,TX,1,3.10\n")

    output = run_import(path)

    assert FuelStation.objects.count() == 0
    assert "city not in gazetteer:1" in output
    assert "Nowhere At All, TX" in output


@pytest.mark.django_db
def test_a_bad_row_does_not_stop_the_good_rows(tmp_path):
    path = write_csv(
        tmp_path,
        "1,GOOD,Addr,Big Cabin,OK,1,3.10\n"
        "2,BAD PRICE,Addr,Big Cabin,OK,1,oops\n"
        "3,ALSO GOOD,Addr,Tomah,WI,1,3.28\n",
    )

    output = run_import(path)

    assert set(FuelStation.objects.values_list("opis_id", flat=True)) == {1, 3}
    assert "Rows read:              3" in output
    assert "Stations written:        2" in output


@pytest.mark.django_db
def test_reimporting_updates_in_place_rather_than_duplicating(tmp_path):
    first = write_csv(tmp_path, "1,STOP,Addr,Big Cabin,OK,1,3.10\n", name="first.csv")
    run_import(first)

    second = write_csv(tmp_path, "1,STOP RENAMED,Addr,Big Cabin,OK,1,4.25\n", name="second.csv")
    run_import(second)

    assert FuelStation.objects.count() == 1
    station = FuelStation.objects.get()
    assert station.name == "STOP RENAMED"
    assert float(station.retail_price) == pytest.approx(4.25)


@pytest.mark.django_db
def test_rejects_a_csv_missing_required_columns(tmp_path):
    path = write_csv(tmp_path, "1,STOP\n", header="OPIS Truckstop ID,Truckstop Name\n")

    with pytest.raises(CommandError, match="missing required columns"):
        run_import(path)


@pytest.mark.django_db
def test_rejects_a_missing_file(tmp_path):
    with pytest.raises(CommandError, match="No such file"):
        run_import(tmp_path / "absent.csv")


@pytest.mark.django_db
def test_handles_a_utf8_bom_as_written_by_excel(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(HEADER + "1,STOP,Addr,Big Cabin,OK,1,3.10\n", encoding="utf-8-sig")

    run_import(path)

    assert FuelStation.objects.count() == 1
