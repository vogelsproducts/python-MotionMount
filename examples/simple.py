import asyncio
import motionmount

ip = "MMF8A55F.local." # Can also be "169.254.13.16" or similar
port = 23 # The best way to get the port number is using zeroconf, but it's likely '23'

async def main():
    mm = motionmount.MotionMount(ip, port)

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
        await asyncio.sleep(1)
        await mm.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
