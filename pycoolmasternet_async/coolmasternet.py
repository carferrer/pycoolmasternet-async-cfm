import asyncio
import re

_MODES = ["auto", "cool", "dry", "fan", "heat"]


class CoolMasterNet():
    """A connection to a coolmasternet bridge."""
    def __init__(self, host, port=10102, read_timeout=1):
        """Initialize this CoolMasterNet instance to connect to a particular
        host at a particular port."""
        self._host = host
        self._port = port
        self._read_timeout = read_timeout

    async def _make_request(self, request):
        """Send a request to the CoolMasterNet and returns the response."""
        reader, writer = await asyncio.open_connection(self._host, self._port)

        try:
            prompt = await asyncio.wait_for(reader.readuntil(b">"), self._read_timeout)
            if prompt != b">":
                raise Exception("CoolMasterNet prompt not found")

            writer.write((request + "\n").encode("ascii"))
            response = await asyncio.wait_for(reader.readuntil(b"\n>"), self._read_timeout)

            data = response.decode("ascii")
            if data.endswith("\n>"):
                data = data[:-1]

            if data.endswith("OK\r\n"):
                data = data[:-4]

            return data
        finally:
            writer.close()
            await writer.wait_closed()

    async def info(self):
        """Get the general info the this CoolMasterNet."""
        raw = await self._make_request("set")
        lines = raw.strip().split("\r\n")
        key_values = [re.split(r"\s*:\s*", line, 1) for line in lines]
        return dict(key_values)

    async def status(self):
        """Return a list of CoolMasterNetUnit objects with current status."""
        status_lines = (await self._make_request("ls2")).strip().split("\r\n")
        return {
            line[0:6]:CoolMasterNetUnit(self, line[0:6], line)
            for line in status_lines
        }


class CoolMasterNetUnit():
    """An immutable snapshot of a unit."""
    def __init__(self, bridge, unit_id, raw):
        """Initialize a unit snapshot."""
        self._raw = raw
        self._unit_id = unit_id
        self._bridge = bridge
        self._parse()

    def _parse(self):
        fields = re.split(r"\s+", self._raw.strip())
        if len(fields) != 9:
            raise Exception("Unexpected status line format: " + str(fields))

        self._is_on = fields[1] == "ON"
        self._temperature_unit = "imperial" if fields[2][-1] == "F" else "celsius"
        self._thermostat = float(fields[2][:-1])
        self._temperature = float(fields[3][:-1])
        self._fan_speed = fields[4].lower()
        self._mode = fields[5].lower()

    async def _make_unit_request(self, request):
        return await self._bridge._make_request(request.replace("UID", self._unit_id))

    async def refresh(self):
        """Refresh the data from CoolMasterNet and return it as a new instance."""
        status_line = (await self._make_unit_request("ls2 UID")).strip()
        return CoolMasterNetUnit(self._bridge, status_line[0:6], status_line)

    @property
    def unit_id(self):
        """The unit id."""
        return self._unit_id

    @property
    def is_on(self):
        """Is the unit on."""
        return self._is_on
    
    @property
    def thermostat(self):
        """The target temperature."""
        return self._thermostat

    @property
    def temperature(self):
        """The current temperature."""
        return self._temperature

    @property
    def fan_speed(self):
        """The fan spped."""
        return self._fan_speed

    @property
    def mode(self):
        """The current mode (e.g. heat, cool)."""
        return self._mode

    @property
    def temperature_unit(self):
        return self._temperature_unit
    
    async def set_fan_speed(self, value):
        """Set the fan speed."""
        await self._make_unit_request(f"fspeed UID {value}")
        return await self.refresh()

    async def set_mode(self, value):
        """Set the mode."""
        if not value in _MODES:
            raise ValueError(
                f"Unrecognized mode {value}. Valid values: {' '.join(_MODES)}"
            )

        await self._make_unit_request(value + " UID")
        return await self.refresh()

    async def set_thermostat(self, value):
        """Set the target temperature."""
        rounded = round(value, 1)
        await self._make_unit_request(f"temp UID {value}")
        return await self.refresh()

    async def turn_on(self):
        """Turn a unit on."""
        await self._make_unit_request("on UID")
        return await self.refresh()

    async def turn_off(self):
        """Turn a unit off."""
        await self._make_unit_request("off UID")
        return await self.refresh()

    async def feed(self, value):
        """Provides ambient temperature hint to the unit."""
        rounded = round(value, 1)
        await self._make_unit_request(f"feed UID {rounded}")

