from __future__ import annotations

from django.db import models


class FuelStation(models.Model):
    """A truck stop with its retail diesel price.

    Mirrors the supplied dataset. `opis_id` is the dataset's own identifier and
    is unique here, which is what makes the importer idempotent: re-importing
    updates rows in place instead of duplicating them.

    `latitude`/`longitude` are derived at import time from the city gazetteer
    (the dataset carries no coordinates), so they carry city-centroid accuracy.
    """

    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField()
    retail_price = models.DecimalField(max_digits=10, decimal_places=8)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        indexes = [
            # Serves the bounding-box candidate query, which filters latitude
            # first because a route's latitude span is usually the narrower one.
            models.Index(fields=["latitude", "longitude"], name="fuel_station_lat_lon_idx"),
            models.Index(fields=["state"], name="fuel_station_state_idx"),
            models.Index(fields=["retail_price"], name="fuel_station_price_idx"),
        ]
        ordering = ["opis_id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"
