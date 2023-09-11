#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2023 Vogel's Products
#
# This file is part of python-MotionMount
#
# SPDX-License-Identifier:    MIT
#

import collections

import asyncio
import struct
from typing import Optional
from enum import Enum, IntEnum


class MotionMountResponse(IntEnum):
    Unknown = 0,
    Accepted = 202,
    BadRequest = 400,
    Unauthorised = 401,
    Forbidden = 403,
    NotFound = 404,
    MethodNotAllowed = 405,
    URITooLong = 414,


class MotionMountValueType(Enum):
    Integer = 0,
    String = 1,
    ByteArray = 2,
    Bool = 3,
    IPv4 = 4,
    Void = 5,


class MotionMountError(Exception):
    """
    """


class NotConnectedError(MotionMountError):
    """
    """

    def __str__(self):
        return "Not connected to MotionMount"


class MotionMountResponseError(MotionMountError):
    """
    """

    def __init__(self, value: MotionMountResponse):
        self.response_value = value


class Request:
    """Internal class that represents a request that's sent to the MotionMount."""

    def __init__(self, key: str, value_type: MotionMountValueType, value: Optional[str] = None):
        self.key = key
        self.value = value
        self.value_type = value_type

        event_loop = asyncio.get_event_loop()
        self.future = event_loop.create_future()

    def encoded(self) -> bytes:
        """Encodes this request such that it can be sent over the network."""

        if self.value is None:
            return f"{self.key}\n".encode()
        else:
            return f"{self.key} = {self.value}\n".encode()


def _convert_value(value, value_type: MotionMountValueType):
    if value_type == MotionMountValueType.Integer:
        return int(value)
    elif value_type == MotionMountValueType.String:
        return value.strip("\"")
    elif value_type == MotionMountValueType.ByteArray:
        return ValueError("Byte array not supported")
    elif value_type == MotionMountValueType.Bool:
        return bool(value)
    elif value_type == MotionMountValueType.Void:
        return value
    else:
        raise ValueError("Unknown value type")


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

        self.extension = None
        self.turn = None

    async def connect(self):
        reader, writer = await asyncio.open_connection(self.address, self.port)

        self._writer = writer
        self._reader_task = asyncio.create_task(self._reader(reader))

        await self.update_position()

    async def disconnect(self):
        writer = self._writer

        # Close the stream
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._writer is not None:
            self._writer.close()

        # Cancel all waiting requests
        for request in self._requests:
            request.future.cancel()

        # Clean up our state
        self._writer = None
        self._reader_task = None
        self._requests.clear()

        # Wait for the stream to really close
        if writer is not None:
            await writer.wait_closed()

    async def get_name(self) -> str:
        return await self._request(Request("configuration/name", MotionMountValueType.String))

    async def update_position(self):
        # We mark the value types as Void, as we've no further interest in the actual value
        # We just want to trigger the notification logic
        await self._request(Request("mount/extension/current", MotionMountValueType.Void))
        await self._request(Request("mount/turn/current", MotionMountValueType.Void))

    async def go_to_preset(self, position: int):
        if position < 0 or position > 9:
            raise ValueError("position must be in the range [0...9]")

        await self._request(Request(f"mount/preset/index = {position}", MotionMountValueType.Void))

    async def go_to_position(self, extension: int, turn: int):
        if extension < 0 or extension > 100: raise ValueError("extension must be in the range [0...100]")
        if turn < -100 or turn > 100: raise  ValueError("turn must be in the range [-100...100]")

        value_bytes = struct.pack('>Hh', extension, turn)
        await self._request(Request(f"mount/preset/position = [{value_bytes.hex()}]", MotionMountValueType.Void))

    async def set_extension(self, extension: int):
        if extension < 0 or extension > 100: raise ValueError("extension must be in the range [0...100]")
        await self._request(Request(f"mount/extension/target = {extension}", MotionMountValueType.Void))

    async def set_turn(self, turn: int):
        if turn < -100 or turn > 100: raise  ValueError("turn must be in the range [-100...100]")
        await self._request(Request(f"mount/turn/target = {turn}", MotionMountValueType.Void))

    async def _request(self, request: Request):
        """ Enqueues `request`, waits for possible earlier requests and then waits for `request` to finish"""

        # Ignore requests when we're not connected
        if self._writer is None:
            raise NotConnectedError

        # Check a possible previous request and wait for it to finish
        previous_request = None
        if len(self._requests) > 0:
            previous_request = self._requests[len(self._requests) - 1]

        # Add ourselves to the queue
        self._requests.append(request)

        # Wait for the previous request
        if previous_request is not None:
            await previous_request.future

        # We're ready to go!
        self._writer.write(request.encoded())
        await self._writer.drain()

        # Wait for our request to finish
        value_any = await request.future
        value = _convert_value(value_any, request.value_type)
        return value

    def _update_properties(self, key: str, value: str):
        if key == "mount/extension/current":
            self.extension = _convert_value(value, MotionMountValueType.Integer)
        elif key == "mount/turn/current":
            self.turn = _convert_value(value, MotionMountValueType.Integer)
        # TODO: How to let the world now that a property changed????

    async def _reader(self, reader: asyncio.StreamReader):
        """ Infinite loop to receive data from the MotionMount and dispatch it to the waiting requests"""

        while not reader.at_eof():
            data = await reader.readline()
            response = data.decode().strip()

            if response[0] == "#":
                try:
                    response_value = MotionMountResponse(int(response[1:]))
                except ValueError:
                    response_value = MotionMountResponse.Unknown

                try:
                    request = self._requests.popleft()

                    if response_value == MotionMountResponse.Accepted:
                        request.future.set_result(True)
                    else:
                        request.future.set_exception(MotionMountResponseError(response_value))
                except IndexError:
                    # No request was waiting, only log this error
                    print(f"Error code: {response}")
            else:
                parts = response.split("=", 1)
                key = parts[0].strip()
                value = parts[1].strip()

                self._update_properties(key, value)

                if len(self._requests) > 0 and self._requests[0].key == key:
                    # We received the response to this request, we can pop it
                    popped = self._requests.popleft()
                    popped.future.set_result(value)
                else:
                    print(f"Notification received: {key} = {value}")
