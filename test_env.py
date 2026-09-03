# test_env.py
import unittest
import config
from topology import create_wsn_topology

class TestEnvironment(unittest.TestCase):
    def test_config_values(self):
        """Kiểm tra các hằng số môi trường có đúng thiết kế không"""
        self.assertEqual(config.NUM_SENSORS, 450)
        self.assertEqual(config.NUM_SINKS, 7)
        self.assertEqual(config.TX_RADIUS, 300)

    def test_random_seed_reproducibility(self):
        """Kiểm thử tính tái lập của Random Seed"""
        # Sinh mạng lần 1
        config.SEED = 42
        graph1 = create_wsn_topology()
        nodes1 = list(graph1.nodes(data='pos'))
        
        # Sinh mạng lần 2 với cùng Seed
        config.SEED = 42
        graph2 = create_wsn_topology()
        nodes2 = list(graph2.nodes(data='pos'))
        
        # Khẳng định 2 bản đồ hoàn toàn giống hệt nhau
        self.assertEqual(nodes1, nodes2)

if __name__ == '__main__':
    unittest.main()