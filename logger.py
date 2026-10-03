"""Root entry point and alias for wsn_sim.logger."""

from wsn_sim.logger import get_logger, save_to_csv, setup_logger

log = get_logger("WSN_Logger")

__all__ = ["get_logger", "log", "save_to_csv", "setup_logger"]
