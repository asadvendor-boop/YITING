"""Run the Diagnosis agent: python3 -m agents.diagnosis"""
from agents.diagnosis import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
