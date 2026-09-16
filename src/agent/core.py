import asyncio
from openai import AsyncOpenAI



from .errors import (
    AgentCoreError,
    ClientInitError
)


class AgentCore:
    def __init__(self, name, task, depth, max_depth = 1, max_step = 5,
                  client: AsyncOpenAI = None, api_key: str = None, base_url: str = None):
        self.name = name
        self.task = task
        self.depth = depth
        self.max_depth = max_depth
        self.max_step = max_step

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

    async def run(self):
        pass




def test():
    name = "test"
    url = ""
    api = ""
    ac = AgentCore()

if __name__ == "__main__":
    test()
