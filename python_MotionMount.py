import collections

import asyncio
from typing import Optional


class Request:
    """Internal class that represents a request that's send to the MotionMount."""

    def __init__(self, key: str, value: Optional[str] = None):
        self.key = key
        self.value = value

        event_loop = asyncio.get_event_loop()
        self.future = event_loop.create_future()

    def encoded(self) -> bytes:
        """Encodes this request such that it can be sent over the network."""

        if self.value is None:
            return f"{self.key}\n".encode()
        else:
            return f"{self.key} = {self.value}\n".encode()


class MotionMount:
    """Class to represent a MotionMount

        You can create one with the IP address and port number which should be used to connect.

        After creation, you should call `connect` first, before accessing other properties.

        When you're done, call `disconnect` to clean up resources.
    """
    def __init__(self, address: str, port: int):
        self.address = address
        self.port = port

        self._requests = collections.deque()

        self._writer = None
        self._reader_task = None

        print(f"Created MM: {address}: {port}")

    async def connect(self):
        print(f"Connecting to {self.address}")
        reader, writer = await asyncio.open_connection(self.address, self.port)

        self._writer = writer
        self._reader_task = asyncio.create_task(self._reader(reader))

        # We're now ready for real commands
        print("Ready for commands")
        await self._request(Request("version/ce/firmware"))

    async def disconnect(self):
        writer = self._writer

        # Close the stream
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._writer is not None:
            self._writer.close()
            print("Writer closed")

        # Cancel all waiting requests
        for request in self._requests:
            request.future.cancel()

        # Clean up our state
        self._writer = None
        self._reader_task = None
        self._requests.clear()

        # Wait for the stream to really close
        await writer.wait_closed()

        print("Disconnected")

    async def _request(self, request: Request):
        """ Enqueues `request`, waits for possible earlier requests and then waits for `request` to finish"""

        # Ignore requests when we're not connected
        if self._writer is None:
            return

        # Check a possible previous request and wait for it to finish
        previous_request = None
        if len(self._requests) > 0:
            previous_request = self._requests[len(self._requests) - 1]

        # Add ourselves to the queue
        self._requests.append(request)

        # Wait for the previous request
        if previous_request is not None:
            print("Awaiting previous request")
            await previous_request.future

        # We're ready to go!
        self._writer.write(request.encoded())
        await self._writer.drain()

        # Wait for our request to finish
        result = await request.future
        print(f"Result: {result}")

    async def _reader(self, reader: asyncio.StreamReader):
        """ Infinite loop to receive data from the MotionMount and dispatch it to the waiting requests"""

        while not reader.at_eof():
            data = await reader.readline()
            response = data.decode()

            print(f"Data: {data}")
            if response[0] == "#":
                try:
                    request = self._requests.popleft()
                    print(f"Error: {request.key}: {response}")
                    request.future.set_result(response)
                except IndexError:
                    # No request was waiting, only log this error
                    print(f"Error code: {response}")
            else:
                parts = response.split("=", 1)
                key = parts[0].strip()
                value = parts[1].strip()

                if len(self._requests) > 0 and self._requests[0].key == key:
                    # We received the response to this request, we can pop it
                    popped = self._requests.popleft()
                    print(f"Popped: {popped}")
                    popped.future.set_result(value)
                else:
                    print(f"Notification received: {key} = {value}")
        print("Reader done")
