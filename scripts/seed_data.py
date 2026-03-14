#!/usr/bin/env python3
# ============================================================
# PSKC — Seed Data Generator
# Generate dummy data for testing
# ============================================================
import argparse
import sys
import os
import json
import random
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_access_events(
    num_events: int = 10000,
    num_keys: int = 1000,
    num_services: int = 10,
    duration_hours: int = 24,
    hot_key_ratio: float = 0.2,
    cache_hit_ratio: float = 0.7
) -> list:
    """
    Generate synthetic access events.
    
    Args:
        num_events: Number of events to generate
        num_keys: Number of unique keys
        num_services: Number of unique services
        duration_hours: Duration of data in hours
        hot_key_ratio: Ratio of hot (popular) keys
        cache_hit_ratio: Ratio of cache hits
        
    Returns:
        List of access event dictionaries
    """
    
    # Define hot keys
    hot_keys = [f"key_{i}" for i in range(int(num_keys * hot_key_ratio))]
    all_keys = hot_keys + [f"key_{i}" for i in range(int(num_keys * hot_key_ratio), num_keys)]
    
    # Services
    services = [f"service_{i}" for i in range(num_services)]
    
    # Time range
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=duration_hours)
    time_range = duration_hours * 3600  # seconds
    
    events = []
    
    for i in range(num_events):
        # Random timestamp
        offset = random.random() * time_range
        timestamp = (start_time + timedelta(seconds=offset)).timestamp()
        
        # Select key (with bias towards hot keys)
        if random.random() < 0.7:
            key_id = random.choice(hot_keys)
        else:
            key_id = random.choice(all_keys)
        
        # Select service
        service_id = random.choice(services)
        
        # Determine cache hit based on key
        is_hot = key_id in hot_keys
        cache_hit = random.random() < (cache_hit_ratio if is_hot else 0.3)
        
        # Latency based on cache hit
        if cache_hit:
            latency_ms = random.uniform(1, 10)
        else:
            latency_ms = random.uniform(50, 300)
        
        event = {
            "key_id": key_id,
            "service_id": service_id,
            "timestamp": timestamp,
            "hour": datetime.fromtimestamp(timestamp).hour,
            "day_of_week": datetime.fromtimestamp(timestamp).weekday(),
            "cache_hit": cache_hit,
            "latency_ms": latency_ms
        }
        
        events.append(event)
    
    # Sort by timestamp
    events.sort(key=lambda x: x['timestamp'])
    
    return events


def generate_key_metadata(
    num_keys: int = 1000,
    hot_key_ratio: float = 0.2
) -> list:
    """Generate key metadata"""
    
    hot_count = int(num_keys * hot_key_ratio)
    
    keys = []
    
    for i in range(num_keys):
        key = {
            "key_id": f"key_{i}",
            "key_type": "symmetric",
            "algorithm": "AES-256",
            "created_at": datetime.now().timestamp() - random.randint(86400, 8640000),
            "enabled": True,
            "hot": i < hot_count
        }
        
        keys.append(key)
    
    return keys


def generate_service_config(num_services: int = 10) -> list:
    """Generate service configurations"""
    
    services = []
    
    for i in range(num_services):
        service = {
            "service_id": f"service_{i}",
            "name": f"Service {i}",
            "tier": random.choice(["gold", "silver", "bronze"]),
            "qps_limit": random.randint(100, 10000),
            "enabled": True
        }
        
        services.append(service)
    
    return services


def seed_data(
    output_dir: str = "data/raw",
    num_events: int = 10000,
    num_keys: int = 1000,
    num_services: int = 10
):
    """Generate and save seed data"""
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate data
    logger.info("Generating access events...")
    events = generate_access_events(
        num_events=num_events,
        num_keys=num_keys,
        num_services=num_services
    )
    
    logger.info("Generating key metadata...")
    keys = generate_key_metadata(num_keys=num_keys)
    
    logger.info("Generating service config...")
    services = generate_service_config(num_services=num_services)
    
    # Save to files
    events_file = os.path.join(output_dir, "access_events.json")
    keys_file = os.path.join(output_dir, "keys.json")
    services_file = os.path.join(output_dir, "services.json")
    
    with open(events_file, 'w') as f:
        json.dump(events, f, indent=2)
    logger.info(f"Saved {len(events)} events to {events_file}")
    
    with open(keys_file, 'w') as f:
        json.dump(keys, f, indent=2)
    logger.info(f"Saved {len(keys)} keys to {keys_file}")
    
    with open(services_file, 'w') as f:
        json.dump(services, f, indent=2)
    logger.info(f"Saved {len(services)} services to {services_file}")
    
    # Print summary
    print("\n" + "=" * 50)
    print("SEED DATA GENERATED")
    print("=" * 50)
    print(f"Output directory: {output_dir}")
    print(f"Access events:     {len(events)}")
    print(f"Keys:             {len(keys)}")
    print(f"Services:         {len(services)}")
    print("=" * 50 + "\n")
    
    return {
        "events_file": events_file,
        "keys_file": keys_file,
        "services_file": services_file
    }


def load_seed_data(data_dir: str = "data/raw") -> dict:
    """Load seed data from files"""
    
    data = {}
    
    files = {
        "events": "access_events.json",
        "keys": "keys.json",
        "services": "services.json"
    }
    
    for key, filename in files.items():
        filepath = os.path.join(data_dir, filename)
        
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data[key] = json.load(f)
            logger.info(f"Loaded {len(data[key])} {key}")
        else:
            logger.warning(f"File not found: {filepath}")
            data[key] = []
    
    return data


def main():
    parser = argparse.ArgumentParser(description="Generate seed data for PSKC")
    
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="data/raw",
        help="Output directory"
    )
    
    parser.add_argument(
        "--events", "-n",
        type=int,
        default=10000,
        help="Number of events to generate"
    )
    
    parser.add_argument(
        "--keys",
        type=int,
        default=1000,
        help="Number of keys"
    )
    
    parser.add_argument(
        "--services",
        type=int,
        default=10,
        help="Number of services"
    )
    
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load existing seed data instead of generating"
    )
    
    args = parser.parse_args()
    
    if args.load:
        data = load_seed_data(args.output)
        print(f"Loaded data: {len(data.get('events', []))} events")
    else:
        seed_data(
            output_dir=args.output,
            num_events=args.events,
            num_keys=args.keys,
            num_services=args.services
        )


if __name__ == "__main__":
    main()
