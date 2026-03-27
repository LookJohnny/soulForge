"""Battery discharge model for digital twin simulation."""

from __future__ import annotations


class BatteryModel:
    """Simple linear battery model with voltage sag under load."""

    def __init__(self, capacity_mah: float = 2500, voltage_nominal: float = 3.7,
                 voltage_cutoff: float = 3.3, internal_resistance_ohm: float = 0.15):
        self.capacity_mah = capacity_mah
        self.voltage_nominal = voltage_nominal
        self.voltage_cutoff = voltage_cutoff
        self.internal_resistance = internal_resistance_ohm
        self.charge_mah = capacity_mah  # starts full
        self.current_draw_ma = 0.0

    def step(self, current_draw_ma: float, dt: float) -> float:
        """Advance one step. Returns current terminal voltage."""
        self.current_draw_ma = current_draw_ma
        self.charge_mah -= current_draw_ma * (dt / 3600.0)
        self.charge_mah = max(0, self.charge_mah)

        soc = self.charge_mah / max(self.capacity_mah, 1)
        # OCV approximation (linear for simplicity)
        ocv = self.voltage_cutoff + (self.voltage_nominal - self.voltage_cutoff) * soc
        # Voltage sag from internal resistance
        terminal_v = ocv - self.internal_resistance * (current_draw_ma / 1000.0)
        return max(0, terminal_v)

    @property
    def soc_pct(self) -> float:
        return (self.charge_mah / max(self.capacity_mah, 1)) * 100

    def reset(self):
        self.charge_mah = self.capacity_mah
