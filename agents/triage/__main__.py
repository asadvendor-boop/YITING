"""Run the Triage agent: python3 -m agents.triage"""
from agents.triage import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
