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
from typing import Optional, Callable, Deque, Any, Union, List
from enum import Enum, IntEnum


class MotionMountResponse(IntEnum):
    """
    Enum representing possible response codes from MotionMount.
    These are derived from HTTP response code and have a corresponding meaning.
    """
    Unknown = 0,
    Accepted = 202,
    BadRequest = 400,
    Unauthorised = 401,
    Forbidden = 403,
    NotFound = 404,
    MethodNotAllowed = 405,
    URITooLong = 414,


class MotionMountValueType(Enum):
    """
    Enum representing possible value types for MotionMount requests.
    """
    Integer = 0,
    String = 1,
    Bytes = 2,
    Bool = 3,
    IPv4 = 4,
    Void = 5,


class MotionMountError(Exception):
    """
    Base exception class for MotionMount errors.
    """
    pass


class NotConnectedError(MotionMountError):
    """
    Exception raised when not connected to MotionMount.
    """
    def __str__(self):
        return "Not connected to MotionMount"


class MotionMountResponseError(MotionMountError):
    """
    Exception raised for MotionMount response errors.

    Attributes:
        response_value (MotionMountResponse): The response code received.
    """
    def __init__(self, value: MotionMountResponse):
        self.response_value = value


class Request:
    """
    Represents a request to be sent to the MotionMount.

    Args:
        key (str): The key for the request.
        value_type (MotionMountValueType): The value type for the request.
        value (Optional[str]): The optional value for the request.

    Attributes:
        key (str): The key for the request.
        value_type (MotionMountValueType): The value type for the request.
        value (Optional[str]): The optional value for the request.
        future (asyncio.Future): The asyncio Future associated with the request.
    """
    def __init__(self, key: str, value_type: MotionMountValueType, value: Optional[str] = None):
        self.key = key
        self.value = value
        self.value_type = value_type

        event_loop = asyncio.get_event_loop()
        self.future = event_loop.create_future()

    def encoded(self) -> bytes:
        """
        Encodes this request for sending over the network.

        Returns:
            bytes: The encoded request.
        """
        if self.value is None:
            return f"{self.key}\n".encode()
        else:
            return f"{self.key} = {self.value}\n".encode()


def _convert_value(value, value_type: MotionMountValueType):
    """
    Convert a value to the specified MotionMount value type.

    Args:
        value: The value to convert.
        value_type (MotionMountValueType): The target value type.

    Returns:
        Any: The converted value.
    """
    if value_type == MotionMountValueType.Integer:
        return int(value)
    elif value_type == MotionMountValueType.String:
        return value.strip("\"")
    elif value_type == MotionMountValueType.Bytes:
        return bytes.fromhex(value.strip("[]"))
    elif value_type == MotionMountValueType.Bool:
        return bool(int(value))
    elif value_type == MotionMountValueType.Void:
        return value
    else:
        raise ValueError("Unknown value type")

class Preset:
    """Class for storing preset related data"""
    index: int
    name: str
    extension: int
    turn: int

    def __init__(self, index, name, extension, turn):
        self.index = index
        self.name = name
        self.extension = extension
        self.turn = turn

class MotionMount:
    """
    Class to represent a MotionMount.

    You can create one with the IP address and port number which should be used to connect.

    After creation, you should call `connect` first, before accessing other properties.

    When you're done, call `disconnect` to clean up resources.

    Args:
        address (str): The IP address of the MotionMount.
        port (int): The port number to use for the connection.
        notification_callback: Will be called when a notification has been received.
    """
    def __init__(self, address: str, port: int):
        self.address = address
        self.port = port
        
        self._callbacks: list[Callable[[], None]] = []

        self._requests: Deque['Request'] = collections.deque()

        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task[Any]] = None

        self._mac = b'\x00\x00\x00\x00\x00\x00'
        self._name = None

        self._extension = None
        self._turn = None
        self._is_moving = False
        self._target_extension = None
        self._target_turn = None
        self._error_status = None
        self._authentication_status = 0x0

    @property
    def mac(self) -> bytes:
        """Returns the (primary) mac address"""
        return self._mac
        
    @property
    def name(self) -> Optional[str]:
        """Returns the name"""
        return self._name

    @property
    def extension(self) -> Optional[int]:
        """The current extension of the MotionMount, normally between 0 - 100
        but slight excursions can occur due to calibration errors, mechanical play and round-off errors"""
        return self._extension

    @property
    def turn(self) -> Optional[int]:
        """The current rotation of the MotionMount, normally between -100 - 100
        but slight excursions can occur due to calibration errors, mechanical play and round-off errors"""
        return self._turn

    @property
    def is_moving(self) -> Optional[bool]:
        """When true the MotionMount is (electrically) moving to another position"""
        return self._is_moving

    @property
    def target_extension(self) -> Optional[int]:
        """The most recent extension the MotionMount tried to move to"""
        return self._target_extension

    @property
    def target_turn(self) -> Optional[int]:
        """The most recent turn the MotionMount tried to move to"""
        return self._target_turn

    @property
    def error_status(self) -> Optional[int]:
        """The error status of the MotionMount.
        See the protocol documentation for details."""
        return self._error_status

    @property
    def is_authenticated(self) -> bool:
        """Indicates whether we're authenticated to the MotionMount (or no
        authentication is needed)."""
        return self._authentication_status & 0x80 == 0x80

    @property
    def can_authenticate(self) -> Union[bool, int]:
        """Indicates whether we can authenticate.
        When there are too many failed authentication attempts the MotionMount enforces
        a backoff time.
        This propperty either returns `True` if authentication is possible or the (last
        known) backoff time."""
        if self.is_authenticated or self._authentication_status <= 3:
            return True
        else:
            return (self._authentication_status-3) * 3

    async def connect(self) -> None:
        """
        Connect to the MotionMount.

        Properties that are updated by notifications are pre-fetched
        """
        connection_future = asyncio.open_connection(self.address, self.port)
        reader, writer = await asyncio.wait_for(connection_future, timeout=15)

        self._writer = writer
        self._reader_task = asyncio.create_task(self._reader(reader))

        try:
            await self._update_mac()
        except MotionMountResponseError as e:
            # We're fine with a #404, as older firmware doesn't support the mac property
            if e.response_value != MotionMountResponse.NotFound:
                raise
        await self.update_name()
        await self.update_position()
        await self.update_error_status()
        await self.update_authentication_status()

    async def disconnect(self) -> None:
        """
        Disconnect from the MotionMount.
        """
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

        # Let listeners know that we've a changed state (disconnected)
        for callback in self._callbacks:
            callback()

        # Wait for the stream to really close
        if writer is not None:
            try:
                await writer.wait_closed()
            except:
                pass # We're not interested in exceptions

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register callback as a listener for updates."""
        self._callbacks.append(callback)
        
    def remove_listener(self, callback: Callable[[], None]) -> None:
        self._callbacks.remove(callback)
        
    @property
    def is_connected(self) -> bool:
        return self._writer is not None

    async def _update_mac(self):
        """Update the mac address"""
        await self._request(Request("mac", MotionMountValueType.Void))

    async def update_name(self):
        """Update the name of the MotionMount."""
        await self._request(Request("configuration/name", MotionMountValueType.Void))

    async def update_position(self):
        """
        Fetch the current position of the MotionMount.
        """
        # We mark the value types as Void, as we've no further interest in the actual value
        # We just want to trigger the notification logic
        await self._request(Request("mount/extension/current", MotionMountValueType.Void))
        await self._request(Request("mount/turn/current", MotionMountValueType.Void))

    async def update_error_status(self):
        """Fetch the error status from the MotionMount"""
        # We mark the value types as Void, as we've no further interest in the actual value
        # We just want to trigger the notification logic
        await self._request(Request("mount/errorStatus", MotionMountValueType.Void))

    async def update_authentication_status(self):
        """Fetch authentication status from the MotionMount."""
        # We mark the value types as Void, as we've no further interest in the actual value
        # We just want to trigger the notification logic
        await self._request(Request("configuration/authentication/status", MotionMountValueType.Void))

    async def get_presets(self) -> List[Preset]:
        """Gets the valid user presets from the device."""
        presets = []

        for i in range(1,8):
            valid = await self._request(Request(f"mount/preset/{i}/active", MotionMountValueType.Bool))

            if valid:
                name = await self._request(Request(f"mount/preset/{i}/name", MotionMountValueType.String))
                extension = await self._request(Request(f"mount/preset/{i}/extension", MotionMountValueType.Integer))
                turn = await self._request(Request(f"mount/preset/{i}/turn", MotionMountValueType.Integer))

                preset = Preset(i, name, extension, turn)

                presets.append(preset)

        return presets
        
    async def go_to_preset(self, position: int):
        """
        Go to a preset position.
        Preset 0 is the (fixed) Wall position.

        Args:
            position (int): The preset position to go to (0 - 7).

        Raises:
            ValueError: If the position is out of range.
        """
        if position < 0 or position > 7:
            raise ValueError("position must be in the range [0...7]")

        await self._request(Request(f"mount/preset/index = {position}", MotionMountValueType.Void))

    async def go_to_position(self, extension: int, turn: int):
        """
        Go to a specific position.

        Args:
            extension (int): The extension value (0 - 100)
            turn (int): The turn value. (-100 - 100)

        Raises:
            ValueError: If the extension or turn values are out of range.
        """
        if extension < 0 or extension > 100:
            raise ValueError("extension must be in the range [0...100]")
        if turn < -100 or turn > 100:
            raise ValueError("turn must be in the range [-100...100]")

        value_bytes = struct.pack('>Hh', extension, turn)
        await self._request(Request(f"mount/preset/position = [{value_bytes.hex()}]", MotionMountValueType.Void))

    async def set_extension(self, extension: int):
        """
        Set the extension value.

        Args:
            extension (int): The extension value (0 - 100).

        Raises:
            ValueError: If the extension value is out of range.
        """
        if extension < 0 or extension > 100:
            raise ValueError("extension must be in the range [0...100]")
        await self._request(Request(f"mount/extension/target = {extension}", MotionMountValueType.Void))

    async def set_turn(self, turn: int):
        """
        Set the turn value.

        Args:
            turn (int): The turn value (-100 - 100).

        Raises:
            ValueError: If the turn value is out of range.
        """
        if turn < -100 or turn > 100:
            raise ValueError("turn must be in the range [-100...100]")
        await self._request(Request(f"mount/turn/target = {turn}", MotionMountValueType.Void))

    async def authenticate(self, pin: int):
        """
        Provide a pin to authenticate.

        Args:
            pin (int): The pin code for the 'User' level to authenticate with (1-9999)

        Raises:
            ValueError: If the pin code is outside the range.
        """
        if pin < 1 or pin > 9999:
            raise ValueError("pin must be in the range [1...9999]")
        await self._request(Request(f"configuration/authentication/pin = {pin}", MotionMountValueType.Void))
        await self.update_authentication_status()

    async def _request(self, request: Request):
        """
        Enqueues a request, waits for possible earlier requests, and then waits for the request to finish.

        Args:
            request (Request): The request to send.

        Returns:
            Any: The response value.
        """
        # Ignore requests when we're not connected
        if self._writer is None:
            raise NotConnectedError

        try:
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
            value_any = await asyncio.wait_for(request.future, timeout=5.0)
            value = _convert_value(value_any, request.value_type)
            return value
        except MotionMountResponseError:
            pass
        except:
            # Make sure we disconnect when there was a failure
            await self.disconnect()
            raise

    def _update_properties(self, key: str, value: str):
        """
        Update internal properties based on key-value pairs received from MotionMount.

        Args:
            key (str): The key from MotionMount.
            value (str): The corresponding value.
        """
        if key == "mount/extension/current":
            self._extension = _convert_value(value, MotionMountValueType.Integer)
        elif key == "mount/turn/current":
            self._turn = _convert_value(value, MotionMountValueType.Integer)
        elif key == "mount/isMoving":
            self._is_moving = _convert_value(value, MotionMountValueType.Bool)
        elif key == "mount/extension/target":
            self._target_extension = _convert_value(value, MotionMountValueType.Integer)
        elif key == "mount/turn/target":
            self._target_turn = _convert_value(value, MotionMountValueType.Integer)
        elif key == "mount/errorStatus":
            self._error_status = _convert_value(value, MotionMountValueType.Integer)
        elif key == "configuration/authentication/status":
            self._authentication_status = _convert_value(value, MotionMountValueType.Bytes)[0]
        elif key == "mac":
            self._mac = _convert_value(value, MotionMountValueType.Bytes)
        elif key == "configuration/name":
            self._name = _convert_value(value, MotionMountValueType.String)

    async def _reader(self, reader: asyncio.StreamReader) -> None:
        """
        Infinite loop to receive data from the MotionMount and dispatch it to waiting requests.

        Args:
            reader (asyncio.StreamReader): The stream reader for receiving data.
        """
        while not reader.at_eof():
            data = await reader.readline()

            if len(data) == 0:
                # Connection was closed
                if len(self._requests) > 0:
                    # There is a request waiting, we will let that request know about the error
                    popped = self._requests.popleft()
                    popped.future.set_exception(NotConnectedError)

                await self.disconnect()
                break

            # Check to see what kind of response this is
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
                    for callback in self._callbacks:
                        try:
                            callback()
                        except Exception as e:
                            # TODO: How to properly let the caller know something went wrong?
                            print(f"Exception during notification: {e}")
