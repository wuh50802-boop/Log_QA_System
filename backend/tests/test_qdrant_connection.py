import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qdrant_client import get_qdrant_client

def main():
    client = get_qdrant_client()
    print("Health check:", client.health_check())
    print("Creating collection...", client.create_collection(recreate=False))
    print("Vector count:", client.count())

if __name__ == "__main__":
    main()