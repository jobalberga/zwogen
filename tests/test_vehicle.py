import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from carconnectivity.charging import Charging
from carconnectivity.charging_connector import ChargingConnector
from carconnectivity.command_impl import ChargingStartStopCommand
from carconnectivity.drive import CombustionDrive, ElectricDrive
from carconnectivity.garage import Garage
from carconnectivity_connectors.volkswagen.vehicle import VolkswagenHybridVehicle

from passat_charge.vehicle import VehicleError, Volkswagen


class VolkswagenAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vin = "TESTVIN00000000000"
        self.garage = Garage(None)
        self.car = VolkswagenHybridVehicle(vin=self.vin, garage=self.garage)
        self.garage.add_vehicle(self.vin, self.car)
        # Petrol level must not accidentally become the displayed battery level.
        petrol = CombustionDrive("petrol", self.car.drives)
        petrol.level._set_value(92)
        self.car.drives.add_drive(petrol)
        electric = ElectricDrive("electric", self.car.drives)
        electric.level._set_value(43)
        self.car.drives.add_drive(electric)
        self.commands = []
        command = ChargingStartStopCommand(parent=self.car.charging.commands)
        command._add_on_set_hook(lambda _, value: self.commands.append(value["command"]) or value)
        command.enabled = True
        self.car.charging.commands.add_command(command)
        self.car.charging.state._set_value(Charging.ChargingState.CHARGING, measured=datetime.now(timezone.utc))
        self.car.charging.connector.connection_state._set_value(ChargingConnector.ChargingConnectorConnectionState.CONNECTED)
        self.persistence = []
        connector = SimpleNamespace(persist=lambda: self.persistence.append("connector"))
        self.client = SimpleNamespace(garage=self.garage, fetch_all=lambda: None,
                                      connectors=SimpleNamespace(connectors={"vw": connector}),
                                      persist=lambda: self.persistence.append("store"))
        self.adapter = Volkswagen("test-only@example.invalid", "test-only-password", self.vin, self.temp.name)
        self.adapter.client = self.client

    def test_reads_real_library_hybrid_state_and_electric_battery(self):
        snapshot = self.adapter.refresh()
        self.assertTrue(snapshot.available)
        self.assertTrue(snapshot.plugged)
        self.assertTrue(snapshot.charging)
        self.assertEqual(snapshot.battery, 43)
        self.assertIsNotNone(snapshot.measured_at)

    def test_sends_start_and_stop_using_real_library_command_parser(self):
        self.adapter.refresh()
        self.adapter.command("stop")
        self.adapter.command("start")
        self.assertEqual(self.commands, [ChargingStartStopCommand.Command.STOP, ChargingStartStopCommand.Command.START])

    def test_refresh_and_commands_save_session_tokens_before_store(self):
        self.adapter.refresh()
        self.adapter.command("stop")
        self.assertEqual(self.persistence, ["connector", "store", "connector", "store"])

    def test_unknown_states_are_not_reported_as_stopped_or_connected(self):
        self.car.charging.state._set_value(Charging.ChargingState.UNKNOWN)
        self.car.charging.connector.connection_state._set_value(ChargingConnector.ChargingConnectorConnectionState.UNKNOWN)
        snapshot = self.adapter.refresh()
        self.assertIsNone(snapshot.charging)
        self.assertIsNone(snapshot.plugged)

    def test_no_fallback_to_another_vin(self):
        self.adapter.vin = "ANOTHERVIN0000000"
        with self.assertRaises(VehicleError):
            self.adapter.refresh()
        self.assertEqual(self.commands, [])

    def test_library_failures_never_expose_auth_response(self):
        def fail():
            raise RuntimeError("private-token-and-password-must-not-escape")
        self.client.fetch_all = fail
        with self.assertRaises(VehicleError) as context:
            self.adapter.refresh()
        self.assertNotIn("private-token", str(context.exception))

    def test_missing_remote_command_blocks_readiness(self):
        self.car.charging.commands.commands.clear()
        with self.assertRaises(VehicleError):
            self.adapter.refresh()

    def test_missing_credentials_never_attempt_authentication(self):
        adapter = Volkswagen("", "", "", self.temp.name)
        with patch("carconnectivity.carconnectivity.CarConnectivity") as constructor:
            with self.assertRaises(VehicleError):
                adapter.refresh()
            constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
