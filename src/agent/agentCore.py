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
        self.context = None

        # set client
        if client is None:
            if api_key != None and base_url != None:
                try:
                    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                except Exception as e:
                    raise ClientInitError("api key or url is not correct") from e
            else:
                raise ClientInitError("cannot initialize client")
            
        self.client = client

    def _get_tools():
        pass

    async def run(self, max_step = 5):
        pass




def test():
    name = "test"
    url = ""
    api = ""
    ac = AgentCore()

if __name__ == "__main__":
    test()
