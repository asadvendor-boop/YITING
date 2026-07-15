"""Entrypoint for: python3 -m agents.safety_reviewer"""
import asyncio
from agents.safety_reviewer import main

if __name__ == "__main__":
    asyncio.run(main())
