"""Bluetooth Low Energy client for the Dymo LetraTag LT200B."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner

# the print service/characteristic UUIDs are not advertised uniformly by
# every unit, so the service is located by its fixed prefix
_SERVICE_PREFIX = "be3dd650"
_CHARACTERISTIC_TEMPLATE = "be3dd651-{0}-42f1-99c1-f0f749dd0678"


@dataclass(frozen=True)
class DiscoveredPrinter:
    """A BLE device found while scanning."""

    name: str | None
    address: str


class PrinterClient:
    """Sends print jobs to and scans for LT200B printers over BLE."""

    async def print_job(self, address: str, job: list[list[int]]) -> None:
        """Connect to the printer and write all chunks of a job."""
        async with BleakClient(address) as client:
            uuid_suffix = self._find_print_service(client)
            characteristic = _CHARACTERISTIC_TEMPLATE.format(uuid_suffix)
            for chunk in job:
                await client.write_gatt_char(characteristic, bytearray(chunk))

    async def scan(self, timeout: float = 5.0) -> list[DiscoveredPrinter]:
        """Discover nearby BLE devices that advertise a name."""
        devices = await BleakScanner.discover(timeout=timeout)
        return [
            DiscoveredPrinter(name=device.name, address=device.address)
            for device in devices
            if device.name
        ]

    @staticmethod
    def _find_print_service(client: BleakClient) -> str:
        for service in client.services:
            first, second, _, _, _ = service.uuid.split("-")
            if first == _SERVICE_PREFIX:
                return second
        raise RuntimeError("Printer service not found; unsupported device?")
