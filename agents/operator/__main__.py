"""Entrypoint for: python3 -m agents.operator"""
import asyncio
from agents.operator import main

if __name__ == "__main__":
    asyncio.run(main())
