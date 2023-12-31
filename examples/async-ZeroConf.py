#!/usr/bin/env python3

import logging
from typing import cast

from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

from motionmount import *

def async_on_service_state_change(
    zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
) -> None:
    print(f"Service {name} of type {service_type} state changed: {state_change}")
    if state_change is not ServiceStateChange.Added:
        return

    asyncio.ensure_future(async_display_service_info(zeroconf, service_type, name))


async def async_display_service_info(zeroconf: Zeroconf, service_type: str, name: str) -> None:
    info = AsyncServiceInfo(service_type, name)
    await info.async_request(zeroconf, 3000)
    print("Info from zeroconf.get_service_info: %r" % (info))
    if info:
        addresses = ["%s:%d" % (addr, cast(int, info.port)) for addr in info.parsed_scoped_addresses()]
        print("  Name: %s" % name)
        print("  Addresses: %s" % ", ".join(addresses))
        print("  Weight: %d, priority: %d" % (info.weight, info.priority))
        print(f"  Server: {info.server}")
        if info.properties:
            print("  Properties are:")
            for key, value in info.properties.items():
                print(f"    {key}: {value}")
        else:
            print("  No properties")

        mm = MotionMount(info.parsed_addresses()[0], info.port)

        try:
            await mm.connect()
            await mm.go_to_preset(1)
            print(f"Extension: {mm.extension}")
            name = await mm.get_name()
            print(f"The name is: \"{name}\"")
            await mm.go_to_position(50, -50)
        except Exception as e:
            print(f"Something bad happened: {e}")
        finally:
            await mm.disconnect()
    else:
        print("  No info")
    print('\n')


class AsyncRunner:
    def __init__(self) -> None:
        self.aiobrowser: Optional[AsyncServiceBrowser] = None
        self.aiozc: Optional[AsyncZeroconf] = None

    async def async_run(self) -> None:
        self.aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)

        services = ["_tvm._tcp.local."]

        print("\nBrowsing %s service(s), press Ctrl-C to exit...\n" % services)
        self.aiobrowser = AsyncServiceBrowser(
            self.aiozc.zeroconf, services, handlers=[async_on_service_state_change]
        )
        while True:
            await asyncio.sleep(1)

    async def async_close(self) -> None:
        assert self.aiozc is not None
        assert self.aiobrowser is not None
        await self.aiobrowser.async_cancel()
        await self.aiozc.async_close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    runner = AsyncRunner()
    try:
        loop.run_until_complete(runner.async_run())
    except KeyboardInterrupt:
        loop.run_until_complete(runner.async_close())
