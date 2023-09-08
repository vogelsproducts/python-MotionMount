import collections

import asyncio
from typing import Optional


class Request:
    def __init__(self, key: str, value: Optional[str]=None):
        self.key = key
        self.value = value

    def encoded(self):
        if self.value is None:
            return f"{self.key}\n".encode()
        else:
            return f"{self.key} = {self.value}\n".encode()


class MotionMount:
    def __init__(self, address: str, port: int):
        self.address = address
        self.port = port

        self.requests = collections.deque()

        self.writer = None
        self.reader_task = None

        print(f"Created MM: {address}: {port}")

    async def connect(self):
        print(f"Connecting to {self.address}")
        reader, writer = await asyncio.open_connection(self.address, self.port)

        self.writer = writer
        self.reader_task = asyncio.create_task(self._reader(reader))

        print("Flushing")
        # We always receive configuration/authentication/requirement on connect
        # Due to a bug the first command will respond with #404
        # So we try to flush the receive buffer first
        await self.request(Request(""))
        print("Done flushing")

        # We're now ready for real commands
        print("Ready for commands")
        await self.request(Request("version/ce/firmware"))

    async def disconnect(self):
        if self.reader_task is not None:
            self.reader_task.cancel()
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()

        self.writer = None
        self.reader_task = None
        self.requests.clear()

    async def request(self, request: Request):
        self.requests.append(request)
        self.writer.write(request.encoded())
        await self.writer.drain()

    async def _reader(self, reader: asyncio.StreamReader):
        while not reader.at_eof():
            data = await reader.readline()
            response = data.decode()

            print(f"Data: {data}")
            if response[0] == "#":
                try:
                    request = self.requests.popleft()
                    print(f"Error: {request.key}: {response}")
                except IndexError:
                    # No request was waiting, only log this error
                    print(f"Error code: {response}")
            else:
                parts = response.split("=", 1)
                key = parts[0].strip()
                value = parts[1].strip()

                if len(self.requests) > 0 and self.requests[0].key == key:
                    # We received the response to this request, we can pop it
                    popped = self.requests.popleft()
                    print(f"Popped: {popped}")
                else:
                    print(f"Data received: {key} = {value}")
        print("Reader done")