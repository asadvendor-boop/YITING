"""Entrypoint for: python3 -m agents.commander"""
import asyncio
from agents.commander import main

if __name__ == "__main__":
    asyncio.run(main())
