import asyncio
from openai import AsyncOpenAI

from .errors import (
    AgentCoreError,
    ClientInitError
)


class AgentCore:
    def __init__(self, name, goal, depth, max_depth = 1, client = None, api_key = None, base_url = None):
        self.name = name
        self.goal = goal

        # set client
        if client == None:
            if api_key != None and base_url != None:
                try:
                    self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                except:
                    ClientInitError()
            else:
                ClientInitError()
        else:
            self.client = client

    async def run(self, max_step = 5):
        pass




def test():
    name = "test"
    url = ""
    api = ""
    ac = AgentCore()

if __name__ == "__main__":
    test()
