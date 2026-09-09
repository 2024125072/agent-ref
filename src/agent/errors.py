


class AgentCoreError(RuntimeError):
    """Exception caused by agentCore"""

class ClientInitError(AgentCoreError):
    """Cannot initialize client"""