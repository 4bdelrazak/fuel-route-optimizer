"""Import the supplied fuel-price CSV into the database.

Idempotent: `opis_id` is the dataset's own key and is unique in the table, so a
repeated import updates prices in place. Rows are written with a single
upserting `bulk_create` per batch rather than row-by-row saves.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel.models import FuelStation
from fuel.services import city_coordinates
from fuel.us_states import US_STATE_CODES

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
}
MAX_PLAUSIBLE_PRICE = 100.0


@dataclass
class ImportStats:
    """Counts reported at the end of a run, one bucket per reason a row failed."""

    rows_read: int = 0
    written: int = 0
    duplicate_ids: int = 0
    non_us: int = 0
    unresolved_city: int = 0
    invalid_price: int = 0
    missing_fields: int = 0
    unresolved_examples: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return (
            self.duplicate_ids
            + self.non_us
            + self.unresolved_city
            + self.invalid_price
            + self.missing_fields
        )


class Command(BaseCommand):
    help = "Import truck-stop fuel prices from the assessment CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_path", type=Path, help="Path to the fuel-price CSV.")
        parser.add_argument("--batch-size", type=int, default=1000, help="Rows per upsert batch.")

    def handle(self, *args, **options) -> None:
        path: Path = options["csv_path"]
        if not path.exists():
            raise CommandError(f"No such file: {path}")

        stats = ImportStats()
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing required columns: {sorted(missing)}")
            stations = self._parse(reader, stats)

        with transaction.atomic():
            FuelStation.objects.bulk_create(
                stations,
                batch_size=options["batch_size"],
                update_conflicts=True,
                unique_fields=["opis_id"],
                update_fields=[
                    "name",
                    "address",
                    "city",
                    "state",
                    "rack_id",
                    "retail_price",
                    "latitude",
                    "longitude",
                ],
            )
        stats.written = len(stations)
        logger.info("Imported %s fuel stations (%s skipped)", stats.written, stats.skipped)
        self._report(stats)

    def _parse(self, reader: csv.DictReader, stats: ImportStats) -> list[FuelStation]:
        """Validate rows and collapse duplicate IDs, keeping the last occurrence.

        The feed lists 678 truck stops twice under name variants ("PILOT #1243"
        and "PILOT TRAVEL CENTER #1243"). They share an OPIS ID, so they must be
        collapsed before the upsert: an `ON CONFLICT DO UPDATE` cannot touch the
        same row twice in one statement.
        """
        by_id: dict[int, FuelStation] = {}
        for row in reader:
            stats.rows_read += 1
            station = self._build(row, stats)
            if station is None:
                continue
            if station.opis_id in by_id:
                stats.duplicate_ids += 1
            by_id[station.opis_id] = station
        return list(by_id.values())

    @staticmethod
    def _build(row: dict[str, str], stats: ImportStats) -> FuelStation | None:
        name = (row.get("Truckstop Name") or "").strip()
        city = (row.get("City") or "").strip()
        state = (row.get("State") or "").strip().upper()
        try:
            opis_id = int((row.get("OPIS Truckstop ID") or "").strip())
            rack_id = int((row.get("Rack ID") or "").strip())
        except ValueError:
            stats.missing_fields += 1
            return None
        if not name or not city or not state:
            stats.missing_fields += 1
            return None
        if state not in US_STATE_CODES:
            stats.non_us += 1
            return None

        try:
            price = float((row.get("Retail Price") or "").strip())
        except ValueError:
            stats.invalid_price += 1
            return None
        if not 0.0 < price < MAX_PLAUSIBLE_PRICE:
            stats.invalid_price += 1
            return None

        coordinate = city_coordinates.lookup(city, state)
        if coordinate is None:
            stats.unresolved_city += 1
            if len(stats.unresolved_examples) < 10:
                stats.unresolved_examples.append(f"{city}, {state}")
            return None

        return FuelStation(
            opis_id=opis_id,
            name=name,
            address=(row.get("Address") or "").strip(),
            city=city,
            state=state,
            rack_id=rack_id,
            retail_price=round(price, 8),
            latitude=coordinate.latitude,
            longitude=coordinate.longitude,
        )

    def _report(self, stats: ImportStats) -> None:
        write = self.stdout.write
        write(f"Rows read:              {stats.rows_read}")
        write(self.style.SUCCESS(f"Stations written:        {stats.written}"))
        write(f"Skipped (total):        {stats.skipped}")
        write(f"  duplicate OPIS IDs:   {stats.duplicate_ids}")
        write(f"  outside the USA:      {stats.non_us}")
        write(f"  city not in gazetteer:{stats.unresolved_city}")
        write(f"  invalid price:        {stats.invalid_price}")
        write(f"  missing fields:       {stats.missing_fields}")
        if stats.unresolved_examples:
            write(f"  unresolved examples:  {', '.join(stats.unresolved_examples)}")
