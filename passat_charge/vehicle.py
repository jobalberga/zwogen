"""Small, replaceable adapter around the unofficial Volkswagen connector."""

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


class VehicleError(Exception):
    """A deliberately credential-free error suitable for the UI."""


@dataclass(frozen=True)
class Snapshot:
    available: bool = False
    plugged: bool | None = None
    charging: bool | None = None
    battery: float | None = None
    measured_at: float | None = None
    message: str = "Volkswagen-account niet gekoppeld."

    def to_dict(self):
        return asdict(self)


class Volkswagen:
    def __init__(self, username, password, vin, data_dir):
        self.username = username
        self.password = password
        self.vin = vin.upper()
        self.data_dir = Path(data_dir)
        self.configured = bool(username and password and vin)
        self.client = None
        self.vehicle = None

    def _connect(self):
        if not self.configured:
            raise VehicleError("Volkswagen-account niet gekoppeld.")
        if self.client is None:
            from carconnectivity.carconnectivity import CarConnectivity

            # Do not start the library's background poller: our single worker
            # owns refreshes and commands, avoiding concurrent vehicle actions.
            self.client = CarConnectivity(
                {"carConnectivity": {
                    "log_level": "CRITICAL",
                    "connectors": [{"type": "volkswagen", "config": {
                        "username": self.username,
                        "password": self.password,
                        "interval": 180,
                        "max_age": 0,
                        "log_level": "CRITICAL",
                    }}],
                }},
                tokenstore_file=str(self.data_dir / "vw-tokens.json"),
            )
            for connector in self.client.connectors.connectors.values():
                connector.session.timeout = 30
            self._persist()

    def _persist(self):
        # The manager first copies refreshed session tokens into the tokenstore;
        # CarConnectivity.persist() alone only writes that store to disk.
        for connector in self.client.connectors.connectors.values():
            connector.persist()
        self.client.persist()

    @staticmethod
    def _value(attribute):
        return getattr(attribute, "value", None)

    def refresh(self):
        try:
            self._connect()
            self.client.fetch_all()
            self.vehicle = self.client.garage.get_vehicle(self.vin)
            if self.vehicle is None:
                raise VehicleError("Deze auto staat niet in je Volkswagen-account. Controleer de koppeling.")
            charging = getattr(self.vehicle, "charging", None)
            if charging is None:
                raise VehicleError("Volkswagen geeft geen laadbediening voor deze auto vrij.")
            command = charging.commands.commands.get("start-stop")
            if command is None or not command.enabled or not command.is_changeable:
                raise VehicleError("Laden op afstand is voor deze auto niet beschikbaar.")
            state = self._value(charging.state)
            state = getattr(state, "value", None)
            plug = self._value(charging.connector.connection_state)
            plug = getattr(plug, "value", None)
            battery = None
            from carconnectivity.drive import ElectricDrive

            for drive in self.vehicle.drives.drives.values():
                if isinstance(drive, ElectricDrive):
                    battery = self._value(drive.level)
                    break
            measured = charging.state.last_updated
            self._persist()
            return Snapshot(
                available=True,
                plugged={"connected": True, "disconnected": False}.get(plug),
                charging={"charging": True, "off": False, "ready_for_charging": False,
                          "conservation": False}.get(state),
                battery=battery,
                measured_at=measured.timestamp() if isinstance(measured, datetime) else None,
                message="Verbonden met Volkswagen",
            )
        except VehicleError:
            raise
        except Exception as error:
            # Never expose provider responses, usernames, VINs, or auth tokens.
            from carconnectivity.errors import AuthenticationError

            if isinstance(error, AuthenticationError):
                self.client = None
                raise VehicleError("Volkswagen-inloggen lukt niet. Controleer je koppeling en eventuele tweestapscontrole.") from None
            raise VehicleError("Volkswagen is nu niet bereikbaar. We proberen het later opnieuw.") from None

    def command(self, action):
        if action not in ("start", "stop"):
            raise ValueError("Unsupported vehicle action")
        if self.vehicle is None:
            raise VehicleError("De laadstatus van de auto is nog niet beschikbaar.")
        try:
            command = self.vehicle.charging.commands.commands.get("start-stop")
            if command is None or not command.enabled or not command.is_changeable:
                raise VehicleError("Laden op afstand is niet beschikbaar.")
            command.value = action
            self._persist()
        except VehicleError:
            raise
        except Exception:
            raise VehicleError("Volkswagen heeft de laadopdracht niet bevestigd. Controleer de auto in de VW-app.") from None
