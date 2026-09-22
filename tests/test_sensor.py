"""Tests for the Sensor model."""

import pytest

from wsn_sim.models import Sensor


def make_sensor(x: float = 0, y: float = 0) -> Sensor:
    return Sensor("sensor_test", x, y, initial_energy_j=5.0)


def test_euclidean_distance_is_five() -> None:
    left = make_sensor(0, 0)
    right = Sensor("sensor_other", 3, 4, initial_energy_j=5.0)

    assert left.distance_to(right) == pytest.approx(5.0)


def test_energy_is_clamped_and_sensor_dies_at_zero() -> None:
    sensor = make_sensor()

    remaining = sensor.consume_energy(10.0)

    assert remaining == 0.0
    assert sensor.energy_j == 0.0
    assert sensor.is_alive is False
    assert sensor.can_forward(0) is False


def test_energy_consumption_and_forward_threshold() -> None:
    sensor = make_sensor()

    sensor.consume_energy(1.5)

    assert sensor.energy_j == pytest.approx(3.5)
    assert sensor.can_forward(3.5)
    assert not sensor.can_forward(3.6)


def test_reject_negative_energy_consumption() -> None:
    with pytest.raises(ValueError, match="negative"):
        make_sensor().consume_energy(-0.1)
