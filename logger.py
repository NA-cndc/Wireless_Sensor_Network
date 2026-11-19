from logging import getLogger
from wsn_sim.storage import append_csv_row as save_to_csv
log = getLogger('wsn_sim')
__all__ = ['log', 'save_to_csv']
