import hashlib
import json

def stable_seed(seed: int, *key: object) -> int:
    payload = json.dumps([seed, *key], ensure_ascii=True, separators=(',', ':'))
    return int.from_bytes(hashlib.sha256(payload.encode('utf-8')).digest()[:8], 'big')

def event_occurs(seed: int, probability: float, *key: object) -> bool:
    return probability == 1 or (probability > 0 and stable_seed(seed, *key) / (1 << 64) < probability)

def randomness_metadata() -> dict:
    return {'event_key_schema': 'wsn_event_keys_v2', 'hash_encoding': 'sha256_canonical_json_first_64_bits', 'stream_usage': {'topology': 'seeded_coordinates', 'traffic': 'deterministic_periodic_no_draws', 'routing': 'deterministic_lexicographic_no_draws', 'attacker_selection': 'seeded_sample_for_random_mode', 'attack_decision': 'event_keyed_bernoulli', 'channel_loss': 'event_keyed_bernoulli'}, 'attack_decision_key': ['packet_id', 'relay_id', 'attempt_index'], 'channel_loss_key': ['packet_id', 'sender_id', 'receiver_id', 'attempt_index'], 'simulated_attempt_index': 0, 'retransmission_modeled': False}
